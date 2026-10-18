package org.xbo360.app;

import android.app.Service;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.RemoteException;
import android.util.Log;

/**
 * Runs experimental ReXGlue JNI exclusively in the :codegen Android process.
 * A native abort must never kill the library/menu activity process.
 */
public final class CodegenService extends Service {
    public static final int RUN = 1, PROGRESS = 2, COMPLETE = 3;
    private static final String TAG = "Xbox360Codegen";
    private boolean running;

    private final Messenger messenger = new Messenger(new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) {
            if (message.what != RUN) {
                super.handleMessage(message);
                return;
            }
            final Messenger client = message.replyTo;
            if (client == null) return;
            if (running) {
                respond(client, COMPLETE, "Code generation is already running");
                return;
            }
            final Bundle data = message.getData();
            final String name = data.getString("name");
            final String xex = data.getString("xex");
            final String game = data.getString("game");
            final String project = data.getString("project");
            if (name == null || xex == null || game == null || project == null) {
                respond(client, COMPLETE, "Invalid codegen request");
                return;
            }
            running = true;
            try {
                // Native loading/initialization is intentionally performed in this
                // service's main thread, never in LauncherActivity's process.
                if (!CodegenBridge.initialize(CodegenService.this)) {
                    running = false;
                    respond(client, COMPLETE, "ReXGlue Android initialization returned false");
                    return;
                }
                respond(client, PROGRESS, "Native ReXGlue initialized in separate process");
                CodegenBridge.initAndRunCodegenAsync(name, xex, game, project,
                    new Handler(Looper.getMainLooper()),
                    text -> respond(client, PROGRESS, text),
                    error -> {
                        running = false;
                        respond(client, COMPLETE, error);
                    });
            } catch (LinkageError | RuntimeException e) {
                Log.e(TAG, "Native initialization failed", e);
                running = false;
                respond(client, COMPLETE, e.toString());
            }
        }
    });

    private static void respond(Messenger target, int what, String detail) {
        Message response = Message.obtain(null, what);
        // A missing error is deliberately the success indicator for COMPLETE.
        if (detail != null) {
            Bundle data = new Bundle();
            data.putString("detail", detail);
            response.setData(data);
        }
        try {
            target.send(response);
        } catch (RemoteException e) {
            Log.w(TAG, "Launcher disconnected during codegen", e);
        }
    }

    @Override public IBinder onBind(Intent intent) {
        return messenger.getBinder();
    }
}
