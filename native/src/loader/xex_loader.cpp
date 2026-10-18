/**
 * Bounded XEX2 header reader.
 *
 * Xbox 360 XEX2 is big-endian. Optional header types use their exact 32-bit
 * keys; entries whose low byte is 0xFF are variable-sized data offsets.
 * Layout reference: xenia/kernel/util/xex2_info.h (structs and keys).
 *
 * This is NOT yet a full Xbox 360 executable loader. Encryption/LZX import
 * relocation and full PE image mapping need separate implementations.
 * Unsupported formats must NEVER be treated as ready-to-execute machine code.
 */
#include "../../include/loader/xex_loader.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <vector>

#if defined(__ANDROID__)
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,"X360:XEX",__VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"X360:XEX",__VA_ARGS__)
#else
#define LOGI(...) do {} while(0)
#define LOGE(...) do {} while(0)
#endif

namespace x360 {
namespace {
constexpr uint32_t kMagic = 0x58455832; // XEX2
constexpr uint32_t kEntryPoint = 0x00010100;
constexpr uint32_t kExecutionInfo = 0x00040006;
constexpr uint32_t kFileFormat = 0x000003FF;
constexpr uint32_t kImports = 0x000103FF;
constexpr size_t kMaxXexBytes = 512ULL * 1024 * 1024;
constexpr uint64_t kGuestSize = 0x100000000ULL;

// No reinterpret_cast reads of unaligned guest big-endian structures.
uint16_t read16(const uint8_t* p) {
    return (uint16_t(p[0]) << 8) | uint16_t(p[1]);
}
uint32_t read32(const uint8_t* p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) |
           (uint32_t(p[2]) << 8) | uint32_t(p[3]);
}
bool within(size_t total, uint64_t pos, uint64_t len) {
    return pos <= total && len <= total - pos;
}
} // namespace

XexLoader::XexLoader() = default;
XexLoader::~XexLoader() = default;

bool XexLoader::load(const std::string& path, XexImage& image) {
    m_lastError.clear();
    image = XexImage{};

    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        m_lastError = "Cannot open extracted default.xex";
        return false;
    }
    const auto end = file.tellg();
    if (end <= 0 || static_cast<uint64_t>(end) > kMaxXexBytes) {
        m_lastError = "XEX executable is empty or exceeds the 512 MiB safety limit";
        return false;
    }
    const size_t size = static_cast<size_t>(end);
    std::vector<uint8_t> data(size);
    file.seekg(0);
    if (!file.read(reinterpret_cast<char*>(data.data()),
                   static_cast<std::streamsize>(data.size()))) {
        m_lastError = "XEX executable could not be read completely";
        return false;
    }

    if (!parseHeader(data, image)) { LOGE("%s", m_lastError.c_str()); return false; }
    if (!decryptSections(data, image)) { LOGE("%s", m_lastError.c_str()); return false; }
    if (!decompressSections(data, image)) { LOGE("%s", m_lastError.c_str()); return false; }
    if (!resolveImports(image)) { LOGE("%s", m_lastError.c_str()); return false; }
    if (!mapToVirtualMemory(image)) { LOGE("%s", m_lastError.c_str()); return false; }
    LOGI("XEX2 metadata: TitleID=%s, base=0x%08X, entry=0x%08X",
         image.titleId.c_str(), image.baseAddress, image.entryPoint);
    return true;
}

bool XexLoader::parseHeader(const std::vector<uint8_t>& raw, XexImage& img) {
    if (!within(raw.size(), 0, 24) || read32(raw.data()) != kMagic) {
        m_lastError = "Not an XEX2 executable (missing XEX2 magic)";
        return false;
    }
    const uint32_t flags = read32(raw.data() + 4);
    const uint32_t headerSize = read32(raw.data() + 8);
    const uint32_t securityOffset = read32(raw.data() + 16);
    const uint32_t count = read32(raw.data() + 20);
    if (count > 4096 || !within(raw.size(), 24, uint64_t(count) * 8) ||
        headerSize < 24 + uint64_t(count) * 8 || headerSize >= raw.size() ||
        !within(raw.size(), securityOffset, 0x184)) {
        m_lastError = "XEX2 header directory or security information is truncated";
        return false;
    }

    // XEX2 security information, NOT XEX1 (load address at 0x110).
    const uint32_t imageSize = read32(raw.data() + securityOffset + 4);
    const uint32_t loadAddress = read32(raw.data() + securityOffset + 0x110);
    if (imageSize == 0 || imageSize > kMaxXexBytes ||
        uint64_t(loadAddress) + imageSize > kGuestSize) {
        m_lastError = "XEX2 security info has invalid image size or guest load address";
        return false;
    }
    img.header.magic = kMagic;
    img.header.moduleFlags = flags;
    img.header.sizeOfHeaders = headerSize;
    img.header.securityOffset = securityOffset;
    img.header.headerDirectoryEntryCount = count;
    img.header.baseAddress = loadAddress;
    img.baseAddress = loadAddress;
    img.header.compressionType = XexCompressionType::None;
    img.header.encryptionType = XexEncryptionType::None;

    bool foundEntry = false;
    bool foundFormat = false;
    for (uint32_t i = 0; i < count; ++i) {
        const uint8_t* item = raw.data() + 24 + size_t(i) * 8;
        const uint32_t key = read32(item);
        const uint32_t value = read32(item + 4);
        if (key == kEntryPoint) {
            img.entryPoint = value;
            img.header.entryPoint = value;
            foundEntry = true;
        } else if (key == kExecutionInfo) {
            if (!within(raw.size(), value, 24) || uint64_t(value) + 24 > headerSize) {
                m_lastError = "XEX2 execution info offset is out of bounds";
                return false;
            }
            char title[9]{};
            std::snprintf(title, sizeof(title), "%08X", read32(raw.data() + value + 12));
            img.titleId = title;
        } else if (key == kFileFormat) {
            if (!within(raw.size(), value, 8) || uint64_t(value) + 8 > headerSize) {
                m_lastError = "XEX2 file-format header is out of bounds";
                return false;
            }
            const uint32_t infoSize = read32(raw.data() + value);
            if (infoSize < 8 || !within(raw.size(), value, infoSize) ||
                uint64_t(value) + infoSize > headerSize) {
                m_lastError = "XEX2 compression header has invalid length";
                return false;
            }
            const uint16_t encryption = read16(raw.data() + value + 4);
            const uint16_t compression = read16(raw.data() + value + 6);
            if (encryption > 1 || compression > 3) {
                m_lastError = "XEX2 encryption or compression uses an unknown format";
                return false;
            }
            img.header.encryptionType = static_cast<XexEncryptionType>(encryption);
            img.header.compressionType = static_cast<XexCompressionType>(compression);
            // Keep offsets for BASIC compression block descriptors.
            img.header.fileFormatInfoOffset = value;
            img.header.fileFormatInfoSize = infoSize;
            foundFormat = true;
        } else if (key == kImports) {
            img.header.importTableOffset = value;
        }
    }

    if (!foundEntry || img.entryPoint < img.baseAddress ||
        uint64_t(img.entryPoint) >= uint64_t(img.baseAddress) + imageSize) {
        m_lastError = "XEX2 entry point missing or outside the executable image";
        return false;
    }
    if (!foundFormat) {
        m_lastError = "XEX2 required file-format header (0x000003FF) is missing";
        return false;
    }
    LOGI("XEX2 parsed: title=%s, encryption=%u, compression=%u, base=%08X, entry=%08X",
         img.titleId.c_str(),
         static_cast<unsigned>(img.header.encryptionType),
         static_cast<unsigned>(img.header.compressionType),
         img.baseAddress, img.entryPoint);
    return true;
}

bool XexLoader::decryptSections(std::vector<uint8_t>&, XexImage& image) {
    if (image.header.encryptionType == XexEncryptionType::None) return true;
    // Never pass encrypted code through as valid PPC instructions.
    m_lastError = "XEX2 uses encrypted executable data (AES); decryption is not implemented";
    return false;
}

bool XexLoader::decompressSections(std::vector<uint8_t>& data, XexImage& image) {
    const size_t payloadStart = image.header.sizeOfHeaders;
    const size_t maxOutput = kMaxXexBytes;
    const auto compression = image.header.compressionType;
    if (compression == XexCompressionType::None) {
        image.rawMemory.assign(data.begin() + payloadStart, data.end());
        return !image.rawMemory.empty();
    }

    if (compression == XexCompressionType::Basic) {
        const size_t descriptor = image.header.fileFormatInfoOffset;
        const size_t infoSize = image.header.fileFormatInfoSize;
        if (infoSize <= 8 || (infoSize - 8) % 8 != 0) {
            m_lastError = "Invalid XEX2 BASIC compression block table";
            return false;
        }
        size_t input = payloadStart;
        for (size_t pos = descriptor + 8; pos < descriptor + infoSize; pos += 8) {
            const size_t dataSize = read32(data.data() + pos);
            const size_t zeros = read32(data.data() + pos + 4);
            if (!within(data.size(), input, dataSize) ||
                dataSize > maxOutput - image.rawMemory.size() ||
                zeros > maxOutput - image.rawMemory.size() - dataSize) {
                m_lastError = "Invalid XEX2 BASIC block lengths (truncated or oversized)";
                image.rawMemory.clear();
                return false;
            }
            image.rawMemory.insert(image.rawMemory.end(),
                                   data.begin() + input, data.begin() + input + dataSize);
            image.rawMemory.insert(image.rawMemory.end(), zeros, uint8_t(0));
            input += dataSize;
        }
        if (image.rawMemory.empty()) {
            m_lastError = "XEX2 BASIC decompression produced an empty image";
            return false;
        }
        return true;
    }

    // LZX may require block chaining, window restoration and AES first.
    // A fake successful decompression is more harmful than a precise error.
    m_lastError = (compression == XexCompressionType::Normal)
        ? "XEX2 uses LZX (normal) compression; full decompression is not implemented"
        : "XEX2 uses DELTA compression; delta patching is not implemented";
    return false;
}

bool XexLoader::resolveImports(XexImage&) {
    // TODO: enumerate imported Xbox kernel/XAM APIs and patch HLE thunks.
    return true;
}

bool XexLoader::mapToVirtualMemory(XexImage& img) {
    if (img.rawMemory.empty()) {
        m_lastError = "XEX2 image payload is empty";
        return false;
    }
    if (uint64_t(img.baseAddress) + img.rawMemory.size() > kGuestSize) {
        m_lastError = "XEX2 image exceeds the guest address space";
        return false;
    }
    // PE section alignment and relocations are still experimental. A valid
    // XEX2 parser result alone does not demonstrate playable execution.
    return true;
}
} // namespace x360
