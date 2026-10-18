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
    private val folderRequest = 7411
    private val folderPrefs = "xbox360recomp_storage"
    private var pendingFolderKind: String? = null
    private var pendingFolderResult: MethodChannel.Result? = null
    private var importMethodChannel: MethodChannel? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var pendingIsoResult: MethodChannel.Result? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        flutterEngine.platformViewsController.registry.registerViewFactory(
            "xbox360recomp/game_surface", EmulationSurfaceFactory())
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, engineChannel).setMethodCallHandler { call, result ->
            when (call.method) {
                "getSupportedAbis" -> result.success(Build.SUPPORTED_ABIS.toList())
                "getVulkanVersion" -> result.success(getVulkanVersion())
                else -> result.notImplemented()
            }
        }
        importMethodChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, importChannel)
        importMethodChannel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "pickIso" -> openIsoPicker(result)
                "chooseDirectory" -> chooseDirectory(call.argument<String>("kind"), result)
                "getDirectory" -> getDirectory(call.argument<String>("kind"), result)
                "resetDirectory" -> resetDirectory(call.argument<String>("kind"), result)
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
        if (requestCode == folderRequest) {
            handleFolderResult(resultCode, data)
            return
        }
        if (requestCode != isoRequest) return
        val result = pendingIsoResult ?: return
        pendingIsoResult = null
        val uri = if (resultCode == Activity.RESULT_OK) data?.data else null
        if (uri == null) {
            result.success(null)
            return
        }
        sendImportProgress("Reading Android document...", 0L, -1L)
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
            sendImportProgress("Copying ISO into app storage...", 0L, expectedSize)
            val digest = MessageDigest.getInstance("SHA-256")
            var total = 0L
            var lastUpdate = 0L
            var consecutiveZeroReads = 0
            val buffer = ByteArray(1024 * 1024)
            val source = contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("Android could not read the selected document")
            source.use { input ->
                FileOutputStream(staged).use { target ->
                    while (true) {
                        val length = input.read(buffer)
                        if (length < 0) break
                        if (length == 0) {
                            consecutiveZeroReads++
                            if (consecutiveZeroReads > 1000) {
                                throw IllegalStateException("Android document stopped providing data")
                            }
                            continue
                        }
                        consecutiveZeroReads = 0
                        if (staging.usableSpace < length + 32L * 1024 * 1024) {
                            throw IllegalStateException("Storage filled while importing ISO")
                        }
                        target.write(buffer, 0, length)
                        digest.update(buffer, 0, length)
                        total += length
                        val now = android.os.SystemClock.elapsedRealtime()
                        if (now - lastUpdate > 300L) {
                            sendImportProgress("Copying ISO into app storage...", total, expectedSize)
                            lastUpdate = now
                        }
                    }
                }
            }
            if (total == 0L || (expectedSize >= 0 && total != expectedSize)) {
                throw IllegalStateException("Incomplete or empty ISO received from Android storage")
            }
            sendImportProgress("ISO copied; checking integrity...", total, expectedSize)
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

    private fun sendImportProgress(stage: String, bytes: Long, total: Long) {
        mainHandler.post {
            importMethodChannel?.invokeMethod(
                "importProgress",
                mapOf("stage" to stage, "bytes" to bytes, "total" to total)
            )
        }
    }

    // SAF folder grants are persisted. The app's native JIT still requires
    // real private filesystem paths, so these are user-selected import/export
    // locations and are NOT silently advertised as a JIT data directory.
    private fun folderKey(kind: String?) =
        if (kind == "games" || kind == "saves") "saf_" + kind else null

    private fun getDirectory(kind: String?, result: MethodChannel.Result) {
        val key = folderKey(kind)
        if (key == null) {
            result.error("INVALID_FOLDER", "Choose games or saves", null)
            return
        }
        val prefs = getSharedPreferences(folderPrefs, MODE_PRIVATE)
        result.success(mapOf("uri" to prefs.getString(key, null),
                            "name" to prefs.getString(key + "_name", null)))
    }

    private fun resetDirectory(kind: String?, result: MethodChannel.Result) {
        val key = folderKey(kind)
        if (key == null) {
            result.error("INVALID_FOLDER", "Choose games or saves", null)
            return
        }
        val prefs = getSharedPreferences(folderPrefs, MODE_PRIVATE)
        prefs.edit().remove(key).remove(key + "_name").apply()
        result.success(null)
    }

    private fun chooseDirectory(kind: String?, result: MethodChannel.Result) {
        if (folderKey(kind) == null) {
            result.error("INVALID_FOLDER", "Choose games or saves", null)
            return
        }
        if (pendingFolderResult != null) {
            result.error("PICKER_BUSY", "Another directory picker is open", null)
            return
        }
        pendingFolderResult = result
        pendingFolderKind = kind
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or
                         Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                         Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            }
            startActivityForResult(intent, folderRequest)
        } catch (e: Exception) {
            pendingFolderKind = null
            pendingFolderResult = null
            result.error("PICKER_UNAVAILABLE", e.message ?: "Cannot choose folder", null)
        }
    }

    private fun handleFolderResult(resultCode: Int, data: Intent?) {
        val result = pendingFolderResult ?: return
        val kind = pendingFolderKind
        pendingFolderResult = null
        pendingFolderKind = null
        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            result.success(null)
            return
        }
        val uri = data.data!!
        try {
            val flags = (data.flags and
                (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION))
            contentResolver.takePersistableUriPermission(uri, flags)
            val key = folderKey(kind)!!
            val label = uri.lastPathSegment ?: "Selected directory"
            getSharedPreferences(folderPrefs, MODE_PRIVATE).edit()
                .putString(key, uri.toString())
                .putString(key + "_name", label)
                .apply()
            result.success(mapOf("uri" to uri.toString(), "name" to label))
        } catch (e: Exception) {
            result.error("FOLDER_PERMISSION_FAILED",
                e.message ?: "Cannot retain access to this directory", null)
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
