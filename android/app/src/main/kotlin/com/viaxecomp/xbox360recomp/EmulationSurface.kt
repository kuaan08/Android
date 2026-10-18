package com.viaxecomp.xbox360recomp

import android.content.Context
import android.graphics.PixelFormat
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import io.flutter.plugin.common.StandardMessageCodec
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory

/** Bridges Flutter's AndroidView to the native Xenos/Vulkan surface. */
class EmulationSurfaceFactory : PlatformViewFactory(StandardMessageCodec.INSTANCE) {
    override fun create(context: Context, viewId: Int, args: Any?): PlatformView =
        EmulationSurface(context)
}

class EmulationSurface(context: Context) : PlatformView, SurfaceHolder.Callback {
    private val view = SurfaceView(context)
    private var active = false

    init {
        System.loadLibrary("xbox360recomp")
        view.holder.setFormat(PixelFormat.OPAQUE)
        view.holder.addCallback(this)
    }

    private external fun nativeSurfaceCreated(surface: Surface)
    private external fun nativeSurfaceChanged(surface: Surface, width: Int, height: Int)
    private external fun nativeSurfaceDestroyed()

    override fun getView(): View = view

    override fun dispose() {
        view.holder.removeCallback(this)
        if (active) {
            active = false
            nativeSurfaceDestroyed()
        }
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        active = true
        nativeSurfaceCreated(holder.surface)
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        if (active && width > 0 && height > 0) {
            nativeSurfaceChanged(holder.surface, width, height)
        }
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        if (active) {
            active = false
            nativeSurfaceDestroyed()
        }
    }
}
