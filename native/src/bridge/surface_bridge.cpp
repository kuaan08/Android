/**
 * Surface bridge — ANativeWindow lifecycle management for the GPU layer.
 * Called from Kotlin SurfaceHolder callbacks via JNI.
 */
#include "../../include/gpu/gpu_layer.h"
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <android/log.h>
#include <jni.h>
#include <atomic>

#define LOG_TAG "X360:SURF"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// Globals declared in jni_bridge.cpp
extern x360::gpu::GpuLayer g_gpuLayer;
extern uint8_t*             g_guestMemory;
extern std::atomic<bool>    g_initialized;
static constexpr uint64_t   GUEST_BASE = 0x00000000ULL;

namespace x360 {
namespace bridge {

static ANativeWindow* g_currentWindow = nullptr;

void onSurfaceCreated(ANativeWindow* win) {
    if (!win) return;
    if (g_currentWindow != nullptr && g_currentWindow != win) {
        ANativeWindow_release(g_currentWindow);
    }
    g_currentWindow = win;
    LOGI("SURF: surface created %p (%dx%d)",
         win, ANativeWindow_getWidth(win), ANativeWindow_getHeight(win));

    if (!g_initialized.load() || g_guestMemory == nullptr) {
        LOGE("Surface created before native guest runtime initialization");
        return;
    }
    if (!g_gpuLayer.isInitialized()) {
        if (!g_gpuLayer.init(win, g_guestMemory, GUEST_BASE))
            LOGE("Vulkan surface initialization failed");
    } else {
        g_gpuLayer.setSurface(win);
    }
}

void onSurfaceChanged(ANativeWindow* win, int width, int height) {
    LOGI("SURF: surface changed %dx%d", width, height);
    g_gpuLayer.onSurfaceChanged(width, height);
}

void onSurfaceDestroyed() {
    LOGI("SURF: surface destroyed");
    g_gpuLayer.clearSurface();
    if (g_currentWindow) ANativeWindow_release(g_currentWindow);
    g_currentWindow = nullptr;
}

} // namespace bridge
} // namespace x360

// ─── JNI entry points (Kotlin surface callbacks) ─────────────────────────────
// Package: com.viaxecomp.xbox360recomp
extern "C" {

JNIEXPORT void JNICALL
Java_com_viaxecomp_xbox360recomp_EmulationSurface_nativeSurfaceCreated(
        JNIEnv* env, jobject, jobject surface) {
    ANativeWindow* win = ANativeWindow_fromSurface(env, surface);
    if (win) x360::bridge::onSurfaceCreated(win);
}

JNIEXPORT void JNICALL
Java_com_viaxecomp_xbox360recomp_EmulationSurface_nativeSurfaceChanged(
        JNIEnv* env, jobject, jobject surface, jint width, jint height) {
    ANativeWindow* win = ANativeWindow_fromSurface(env, surface);
    if (win) {
        x360::bridge::onSurfaceChanged(win, width, height);
        ANativeWindow_release(win);
    }
}

JNIEXPORT void JNICALL
Java_com_viaxecomp_xbox360recomp_EmulationSurface_nativeSurfaceDestroyed(
        JNIEnv*, jobject) {
    x360::bridge::onSurfaceDestroyed();
}

} // extern "C"
