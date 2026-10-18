package org.xbo360.app;

import android.content.Context;
import android.os.Handler;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Experimental JNI bridge for ReXGlue project initialization and C++ codegen. */
public final class CodegenBridge {
    private static final ExecutorService CODEGEN_EXECUTOR =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "xbo360-codegen");
                thread.setPriority(Thread.NORM_PRIORITY - 1);
                return thread;
            });

    static {
        System.loadLibrary("xbo360_codegen_jni");
    }

    private CodegenBridge() { }

    /** Call once from the Android main thread, passing an application Context. */
    public static boolean initialize(Context context) {
        if (context == null) {
            return false;
        }
        Context appContext = context.getApplicationContext();
        return nativeInitialize(appContext != null ? appContext : context);
    }

    /**
     * Run native ReXGlue codegen against a manifest in app-private storage.
     * The manifest/XEX/game paths must be readable and writable by this app.
     * `handler` should target the UI thread if callbacks update views.
     * Completion receives null on success, otherwise a diagnostic string.
     */
    public static void runCodegenAsync(String manifestPath, Handler handler,
                                       ProgressListener progress, Completion completion) {
        if (manifestPath == null || manifestPath.isEmpty()) {
            if (handler != null && completion != null) {
                handler.post(() -> completion.onComplete("O caminho do manifest está vazio."));
            }
            return;
        }
        if (handler == null || completion == null) {
            throw new IllegalArgumentException("handler e completion são obrigatórios");
        }

        CODEGEN_EXECUTOR.execute(() -> {
            String error = nativeRunCodegen(manifestPath, message -> {
                if (progress != null) {
                    handler.post(() -> progress.onProgress(message));
                }
            });
            handler.post(() -> completion.onComplete(error));
        });
    }

    /**
     * Create a single-XEX ReXGlue project in app-private storage and generate
     * its C++ sources. This prototype rejects game folders containing guest
     * DLLs and does not compile the generated C++ into a playable APK.
     */
    public static void initAndRunCodegenAsync(String projectName, String xexPath,
                                              String gameRoot, String projectRoot,
                                              Handler handler, ProgressListener progress,
                                              Completion completion) {
        if (handler == null || completion == null) {
            throw new IllegalArgumentException("handler e completion são obrigatórios");
        }
        if (projectName == null || projectName.isEmpty() || xexPath == null || xexPath.isEmpty()
                || gameRoot == null || gameRoot.isEmpty() || projectRoot == null
                || projectRoot.isEmpty()) {
            handler.post(() -> completion.onComplete("Nome ou caminho de entrada inválido."));
            return;
        }

        CODEGEN_EXECUTOR.execute(() -> {
            ProgressListener forwarded = progress == null ? null : message ->
                    handler.post(() -> progress.onProgress(message));
            String error = nativeInitAndCodegen(projectName, xexPath, gameRoot, projectRoot,
                    forwarded);
            handler.post(() -> completion.onComplete(error));
        });
    }

    private static native boolean nativeInitialize(Context applicationContext);
    private static native String nativeRunCodegen(String manifestPath, ProgressListener listener);
    private static native String nativeInitAndCodegen(String projectName, String xexPath,
                                                       String gameRoot, String projectRoot,
                                                       ProgressListener listener);

    public interface ProgressListener {
        void onProgress(String message);
    }

    public interface Completion {
        /** @param error null when code generation completed successfully. */
        void onComplete(String error);
    }
}
