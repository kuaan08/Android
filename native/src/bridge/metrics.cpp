/**
 * Metrics bridge — collects and exposes real-time performance counters.
 * CPU temperature, GPU temperature, RAM usage, FPS, frame time.
 * Exposed to Dart/Flutter via dart:ffi.
 */
#include "../../include/jit/jit_engine.h"
#include "../../include/gpu/gpu_layer.h"
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <cstdlib>
#include <android/log.h>
#include <sys/resource.h>

#define LOG_TAG "X360:METRICS"

extern x360::jit::JitEngine g_jitEngine;
extern x360::gpu::GpuLayer  g_gpuLayer;

namespace x360 {
namespace bridge {

// Read a thermal zone temperature from sysfs (Android exposes these under /sys/class/thermal)
static float readThermalZone(int zone) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/thermal/thermal_zone%d/temp", zone);
    FILE* f = fopen(path, "r");
    if (!f) return 0.0f;
    int milliC = 0;
    fscanf(f, "%d", &milliC);
    fclose(f);
    return milliC / 1000.0f;
}

// Find the "best" CPU temperature zone (highest reading = hottest core)
float getCpuTemperature() {
    float maxTemp = 0.0f;
    for (int z = 0; z < 20; z++) {
        float t = readThermalZone(z);
        if (t > maxTemp && t < 150.0f) maxTemp = t; // sanity check < 150°C
    }
    return maxTemp;
}

// GPU temperature — on Adreno it's typically zone 12 or similar
float getGpuTemperature() {
    // Try common Adreno/Mali thermal zones
    float best = 0.0f;
    for (int z = 10; z < 20; z++) {
        float t = readThermalZone(z);
        if (t > best && t < 120.0f) best = t;
    }
    return best;
}

// RSS in bytes
int64_t getRamUsage() {
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    return (int64_t)ru.ru_maxrss * 1024LL;
}

// Blocks compiled so far
int64_t getBlocksCompiled() {
    return (int64_t)g_jitEngine.blocksCompiled();
}

// Total PPC instructions executed
int64_t getInstructionsExecuted() {
    return (int64_t)g_jitEngine.instructionsExecuted();
}

} // namespace bridge
} // namespace x360

// dart:ffi entry points
extern "C" {

float x360_metrics_cpu_temp() {
    return x360::bridge::getCpuTemperature();
}

float x360_metrics_gpu_temp() {
    return x360::bridge::getGpuTemperature();
}

int64_t x360_metrics_blocks_compiled() {
    return x360::bridge::getBlocksCompiled();
}

int64_t x360_metrics_instructions_executed() {
    return x360::bridge::getInstructionsExecuted();
}

// FPS is actual Vulkan present rate, not arbitrary JIT loop iteration count.
float x360_metrics_fps() {
    return g_gpuLayer.framesPresented() ? g_gpuLayer.currentFps() : 0.0f;
}

float x360_metrics_frame_time() {
    const float fps = x360_metrics_fps();
    return fps > 0.0f ? 1000.0f / fps : 0.0f;
}

int64_t x360_metrics_ram() {
    return x360::bridge::getRamUsage();
}

int32_t x360_metrics_gpu_state() { return g_gpuLayer.rendererStatus(); }
int32_t x360_metrics_jit_state() { return static_cast<int32_t>(g_jitEngine.state()); }
int64_t x360_metrics_gpu_frames() { return static_cast<int64_t>(g_gpuLayer.framesPresented()); }
int64_t x360_metrics_pm4_packets() { return static_cast<int64_t>(g_gpuLayer.pm4PacketsSeen()); }
int64_t x360_metrics_pm4_draw_attempts() { return static_cast<int64_t>(g_gpuLayer.pm4DrawCallsSeen()); }
int64_t x360_metrics_shader_attempts() { return static_cast<int64_t>(g_gpuLayer.shadersRequested()); }
int64_t x360_metrics_shader_compiled() { return static_cast<int64_t>(g_gpuLayer.shadersCompiled()); }
int64_t x360_metrics_shader_failed() { return static_cast<int64_t>(g_gpuLayer.shadersFailed()); }
int32_t x360_metrics_shader_busy() { return g_gpuLayer.shaderCompiling() ? 1 : 0; }

int32_t x360_metrics_gpu_name(char* out, int32_t capacity) {
    if (!out || capacity <= 0) return -1;
    auto name = g_gpuLayer.gpuName();
    if (name.empty()) name = "Vulkan GPU not initialized";
    const size_t count = std::min(name.size(), static_cast<size_t>(capacity-1));
    std::memcpy(out, name.data(), count);
    out[count] = '\0';
    return static_cast<int32_t>(count);
}

} // extern "C"
