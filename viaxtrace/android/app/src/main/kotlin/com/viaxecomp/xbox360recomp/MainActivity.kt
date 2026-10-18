package com.viaxecomp.xbox360recomp

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Build
import android.provider.OpenableColumns
import android.util.Log
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID

class MainActivity : FlutterActivity() {
    private val engineChannel = "com.viaxecomp.xbox360recomp/engine"
    private val importChannel = "com.viaxecomp.xbox360recomp/import"
    private val isoRequest = 7410
    private val mainHandler = Handler(Looper.getMainLooper())
    private var pendingIsoResult: MethodChannel.Result? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, engineChannel).setMethodCallHandler { call, result ->
            when (call.method) {
                "getSupportedAbis" -> result.success(Build.SUPPORTED_ABIS.toList())
                "getVulkanVersion" -> result.success(getVulkanVersion())
                else -> result.notImplemented()
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, importChannel).setMethodCallHandler { call, result ->
            when (call.method) {
                "pickIso" -> openIsoPicker(result)
                else -> result.notImplemented()
            }
        }
    }

    private fun openIsoPicker(result: MethodChannel.Result) {
        if (pendingIsoResult != null) {
            result.error("IMPORT_BUSY", "Another ISO selection is in progress", null)
            return
        }
        pendingIsoResult = result
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                type = "*/*"
                addCategory(Intent.CATEGORY_OPENABLE)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivityForResult(intent, isoRequest)
        } catch (e: Exception) {
            pendingIsoResult = null
            result.error("PICKER_UNAVAILABLE", "Cannot open Android document picker: " + e.message, null)
        }
    }

    @Deprecated("Activity result callback is needed for the standalone Android SAF picker.")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != isoRequest) return
        val result = pendingIsoResult ?: return
        pendingIsoResult = null
        val uri = if (resultCode == Activity.RESULT_OK) data?.data else null
        if (uri == null) {
            result.success(null)
            return
        }
        Thread({ copyUriToPrivateStaging(uri, result) }, "x360-saf-iso-import").start()
    }

    private fun copyUriToPrivateStaging(uri: Uri, result: MethodChannel.Result) {
        val staging = File(filesDir, "import-staging")
        var output: File? = null
        try {
            if (!staging.isDirectory && !staging.mkdirs()) {
                throw IllegalStateException("Cannot create private import directory")
            }
            var displayName = "game.iso"
            var expectedSize = -1L
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
                null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                    if (nameIndex >= 0) displayName = cursor.getString(nameIndex) ?: displayName
                    if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) expectedSize = cursor.getLong(sizeIndex)
                }
            }
            if (!displayName.lowercase().endsWith(".iso") &&
                !displayName.lowercase().endsWith(".xiso")) {
                throw IllegalArgumentException("Choose an .iso or .xiso disc image")
            }
            if (expectedSize > 0 && expectedSize + 64L * 1024 * 1024 > staging.usableSpace) {
                throw IllegalStateException("Not enough free space to import this ISO")
            }
            val staged = File(staging, UUID.randomUUID().toString() + ".iso")
            output = staged
            val digest = MessageDigest.getInstance("SHA-256")
            var total = 0L
            val buffer = ByteArray(1024 * 1024)
            val source = contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("Android could not read the selected document")
            source.use { input ->
                FileOutputStream(staged).use { target ->
                    while (true) {
                        val length = input.read(buffer)
                        if (length < 0) break
                        if (length == 0) continue
                        if (staging.usableSpace < length + 32L * 1024 * 1024) {
                            throw IllegalStateException("Storage filled while importing ISO")
                        }
                        target.write(buffer, 0, length)
                        digest.update(buffer, 0, length)
                        total += length
                    }
                }
            }
            if (total == 0L || (expectedSize >= 0 && total != expectedSize)) {
                throw IllegalStateException("Incomplete or empty ISO received from Android storage")
            }
            val sha = digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
            val payload = mapOf("path" to staged.absolutePath, "name" to displayName,
                "size" to total, "sha256" to sha)
            mainHandler.post { result.success(payload) }
        } catch (e: Exception) {
            output?.delete()
            Log.e("Xbox360RecompImport", "SAF ISO copy failed", e)
            mainHandler.post { result.error("ISO_COPY_FAILED", e.message ?: "Cannot import ISO", null) }
        }
    }

    private fun getVulkanVersion(): String {
        return try {
            val feature = packageManager.systemAvailableFeatures.firstOrNull {
                it.name == android.content.pm.PackageManager.FEATURE_VULKAN_HARDWARE_VERSION
            }
            if (feature == null) "Unavailable" else {
                val major = (feature.version shr 22) and 0x3ff
                val minor = (feature.version shr 12) and 0x3ff
                major.toString() + "." + minor
            }
        } catch (_: Exception) { "unknown" }
    }
}
