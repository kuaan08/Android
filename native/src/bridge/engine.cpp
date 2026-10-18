/**
 * Engine state machine — top-level game lifecycle management.
 * Coordinates XEX/STFS/ISO loading, JIT startup, GPU init, and teardown.
 */
#include "../../include/loader/xex_loader.h"
#include "../../include/loader/stfs_parser.h"
#include "../../include/loader/iso_parser.h"
#include "../../include/loader/title_disc.h"
#include "../../include/jit/jit_engine.h"
#include "../../include/hle/hle_kernel.h"
#include "../../include/gpu/gpu_layer.h"
#include <android/log.h>
#include <string>
#include <filesystem>
#include <optional>
#include <fstream>
#include <cstring>
#include <algorithm>
#include <sys/mman.h>

#define LOG_TAG "X360:ENGINE"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// ─── Globals defined in jni_bridge.cpp (global scope, not namespaced) ────────
// engine.cpp uses extern declarations at global scope to match the definitions.
extern x360::XexLoader          g_xexLoader;
extern x360::jit::JitEngine     g_jitEngine;
extern x360::hle::HleKernel     g_hleKernel;
extern x360::gpu::GpuLayer      g_gpuLayer;
extern uint8_t*                  g_guestMemory;
extern std::string               g_gameDir;
extern std::string               g_saveDir;
extern std::string               g_lastLoadError;

static constexpr uint64_t GUEST_BASE     = 0x00000000ULL;
static constexpr size_t   GUEST_MEM_SIZE = 0x100000000ULL;

namespace x360 {
namespace bridge {

namespace fs = std::filesystem;

// ─── STFS game loader (delegates to StfsParser + XexLoader) ─────────────────

int32_t loadStfsGame(const char* path, char* outTitleId, int32_t outLen) {
    LOGI("ENGINE: loading STFS container: %s", path);

    x360::StfsParser parser;
    x360::StfsPackage pkg;

    if (!parser.open(path, pkg)) {
        g_lastLoadError = parser.lastError();
        LOGE("ENGINE: STFS open failed: %s", g_lastLoadError.c_str());
        return -1;
    }

    LOGI("ENGINE: STFS package '%s' (titleId=%s, %zu files)",
         pkg.displayName.c_str(), pkg.titleId.c_str(), pkg.files.size());

    // Extract to temp directory
    std::string extractDir = g_gameDir + "/.stfs_extract/" + pkg.titleId;
    int extracted = parser.extractAll(path, extractDir, pkg);
    if (extracted < 0) {
        g_lastLoadError = "STFS package extraction failed";
        LOGE("ENGINE: STFS extract failed");
        return -2;
    }

    // Find default.xex in extracted files
    std::string xexPath;
    for (const auto& f : pkg.files) {
        std::string lower = f.name;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower.find("default.xex") != std::string::npos) {
            xexPath = extractDir + "/" + f.name;
            break;
        }
    }

    if (xexPath.empty()) {
        g_lastLoadError = "No default.xex was found in STFS package";
        LOGE("ENGINE: default.xex not found in STFS package");
        return -3;
    }

    // Now load the XEX
    x360::XexImage img;
    if (!g_xexLoader.load(xexPath, img)) {
        g_lastLoadError = g_xexLoader.lastError();
        LOGE("ENGINE: XEX load failed: %s", g_lastLoadError.c_str());
        return -4;
    }

    if (outTitleId && outLen > 0) {
        strncpy(outTitleId, img.titleId.c_str(), outLen - 1);
        outTitleId[outLen - 1] = '\0';
    }

    // Map XEX into guest memory
    const uint64_t imageOffset = img.baseAddress - GUEST_BASE;
    if (g_guestMemory && imageOffset + img.rawMemory.size() <= GUEST_MEM_SIZE) {
        memcpy(g_guestMemory + imageOffset, img.rawMemory.data(), img.rawMemory.size());
    }

    return g_jitEngine.init(g_guestMemory, GUEST_MEM_SIZE, GUEST_BASE, img.entryPoint) ? 0 : -5;
}

// ─── ISO game loader ──────────────────────────────────────────────────────────

int32_t loadIsoGame(const char* path, char* outTitleId, int32_t outLen) {
    LOGI("ENGINE: loading ISO: %s", path);

    x360::IsoParser parser;
    if (!parser.open(path)) {
        g_lastLoadError = parser.lastError();
        LOGE("ENGINE: ISO open failed: %s", g_lastLoadError.c_str());
        return -1;
    }

    // listFiles() returns a temporary vector. Keep only an owned entry value,
    // never a pointer into the destroyed temporary.
    const auto xexEntry = x360::selectDefaultXex(parser.listFiles());

    if (!xexEntry) {
        g_lastLoadError = "ISO contains no default.xex executable";
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -2;
    }
    if (xexEntry->size < 24 || xexEntry->size > 512U * 1024U * 1024U) {
        g_lastLoadError = "ISO default.xex entry size is invalid or exceeds the 512 MiB limit";
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -3;
    }

    // Extract into private app storage; do not retain dangling ISO entry data.
    const fs::path directory = fs::path(g_gameDir) / ".iso_extract";
    std::error_code directoryError;
    fs::create_directories(directory, directoryError);
    if (directoryError) {
        g_lastLoadError = "Could not create private XEX extraction directory: " +
                          directoryError.message();
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -3;
    }
    const std::string xexPath = (directory / "default.xex").string();
    if (!parser.extractFile(*xexEntry, xexPath)) {
        g_lastLoadError = "Could not extract default.xex from ISO: " + parser.lastError();
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -3;
    }

    // A supposedly extracted XEX with a different magic indicates bad disc
    // offsets/entry parsing, not unsupported PPC instructions.
    std::ifstream extracted(xexPath, std::ios::binary);
    char magic[4]{};
    if (!extracted.read(magic, sizeof(magic)) ||
        std::memcmp(magic, "XEX2", sizeof(magic)) != 0) {
        g_lastLoadError =
            "Extracted default.xex is not XEX2 (invalid magic). "
            "ISO directory offsets or disc format may be incorrect.";
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -4;
    }
    extracted.close();

    x360::XexImage img{};
    if (!g_xexLoader.load(xexPath, img)) {
        g_lastLoadError = g_xexLoader.lastError();
        if (g_lastLoadError.empty())
            g_lastLoadError = "XEX2 loader failed without an internal reason";
        LOGE("ENGINE: XEX load failed: %s", g_lastLoadError.c_str());
        return -4;
    }

    if (outTitleId && outLen > 0) {
        strncpy(outTitleId, img.titleId.c_str(), outLen - 1);
        outTitleId[outLen - 1] = '\0';
    }

    const uint64_t imageOffset = img.baseAddress - GUEST_BASE;
    if (!g_guestMemory || imageOffset > GUEST_MEM_SIZE ||
        img.rawMemory.size() > GUEST_MEM_SIZE - imageOffset) {
        g_lastLoadError = "XEX2 executable memory mapping exceeds guest 4 GiB address space";
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -5;
    }
    memcpy(g_guestMemory + imageOffset, img.rawMemory.data(), img.rawMemory.size());
    if (!g_jitEngine.init(g_guestMemory, GUEST_MEM_SIZE, GUEST_BASE, img.entryPoint)) {
        g_lastLoadError = "ARM64 JIT initialization failed after XEX2 load";
        LOGE("ENGINE: %s", g_lastLoadError.c_str());
        return -5;
    }
    return 0;
}

} // namespace bridge
} // namespace x360
