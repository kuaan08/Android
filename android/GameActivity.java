package org.xbo360.app;

import org.libsdl.app.SDLActivity;
import java.io.File;

/** Runs in a separate process so leaving a native title resets SDL/runtime state. */
public final class GameActivity extends SDLActivity {
    @Override protected String[] getLibraries(){return new String[]{"c++_shared","rexruntime","xbo_game"};}
    @Override protected String getMainSharedObject(){return new File(getApplicationInfo().nativeLibraryDir,"libxbo_game.so").getAbsolutePath();}
    @Override protected String[] getArguments(){
        String root=getIntent().getStringExtra("game_root");
        return new String[]{"--game_data_root",root,"--user_data_root",getFilesDir().getAbsolutePath(),"--gpu_backend","vulkan","--show_fps_counter=true"};
    }
    @Override protected void onDestroy(){super.onDestroy();android.os.Process.killProcess(android.os.Process.myPid());}
}
