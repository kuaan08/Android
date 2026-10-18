package org.xbo360.app;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.provider.DocumentsContract;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.channels.FileChannel;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;

/** Xbox 360 library, SAF importer, experimental on-device codegen, and native launch menu. */
public final class LauncherActivity extends Activity {
    final ExecutorService worker = Executors.newSingleThreadExecutor();
    LinearLayout content; TextView status; JSONObject metadata;
    File library; volatile boolean closed; boolean busy; boolean codegenReady; String codegenError; long lastProgress;
    static final int GREEN = 0xff7cd336, BG = 0xff111318;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            metadata = new JSONObject(read(getAssets().open("project.json"), 1024 * 1024));
            File base = getExternalFilesDir(null); if (base == null) base = getFilesDir();
            library = new File(base, "games"); if (!library.mkdirs() && !library.isDirectory()) throw new IOException("Cannot open game library");
            File codegenLibrary = new File(getApplicationInfo().nativeLibraryDir, "libxbo360_codegen_jni.so");
            if (codegenLibrary.isFile()) {
                try { codegenReady = CodegenBridge.initialize(this); }
                catch (LinkageError | RuntimeException e) { codegenError = e.toString(); }
                if (!codegenReady && codegenError == null) codegenError = "ReXGlue Android runtime initialization failed.";
            }
            draw();
        } catch (Exception e) { new AlertDialog.Builder(this).setMessage(e.toString()).setPositiveButton("Close", (d,w)->finish()).show(); }
    }

    void draw() {
        ScrollView scroll = new ScrollView(this); scroll.setBackgroundColor(BG);
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(28,28,28,28); scroll.addView(content); setContentView(scroll);
        text("XBOX 360 RECOMP", 27, GREEN); text(metadata.optString("title"), 18, Color.WHITE);
        text("Library · Xbox 360 → native Android", 14, 0xff9ca5b2);
        if (codegenReady) text("Experimental: this device can generate C++ for single-XEX titles; it cannot yet compile a playable APK.", 13, 0xffefba63);
        else if (codegenError != null) text("On-device codegen unavailable: " + codegenError, 13, 0xffefba63);
        button("Select ISO / XISO", () -> pick(false)); button("Select extracted game folder", () -> pick(true));
        status = text(busy ? "Import in progress..." : "Choose a game below or import your files.", 14, GREEN);
        if (!metadata.optBoolean("native")) text("This library APK has no game code. Export a title-specific native APK using the PC application to play that title.", 14, 0xffefba63);
        File[] entries = library.listFiles(f -> f.isDirectory() && !f.getName().startsWith(".import-"));
        if (entries != null) for (File root : entries) {
            File info = new File(root,"xbo-game.json"); if (!info.isFile()) continue;
            try {
                JSONObject game = new JSONObject(read(new FileInputStream(info),1024*1024));
                String title = game.optString("title",root.getName());
                boolean nativeReady = metadata.optBoolean("native") && metadata.optString("sha256").equals(game.optString("sha256"));
                text(title,21,Color.WHITE);
                text(nativeReady ? "Native build available" : "Needs a native APK for this executable",13,nativeReady?GREEN:0xff9ca5b2);
                if (codegenReady) button("Generate C++ on this device (experimental)", () -> generateCode(root, game));
                button(nativeReady ? "Play " + title : "Details", () -> {
                    if (nativeReady) verifyAndLaunch(root,game);
                    else message("Export this title from the desktop application's Library → Export APK. Selecting an ISO does not compile its PowerPC code on the phone.");
                });
            } catch (Exception e) { text("Unreadable library entry: " + root.getName(),13,Color.RED); }
        }
        button("Updates", () -> startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse("https://github.com/kuaan08/xbo360/releases/latest"))));
        button("About / credits", () -> message("Xbox 360 Recomp 0.3.1\nFork: katakishi0 · hosted by kuaan08\nSwitchRecomp by MZ Labs\nReXGlue by Tom Clay and contributors\nAndroid runtime: AlanConstantino, Andrew Nakas, Buku313 and contributors\nNo commercial-game compatibility is established by the synthetic build tests."));
        if (metadata.optBoolean("native")) text("ARM64 · Android 13+ · Vulkan · physical gamepad recommended",13,0xff9ca5b2);
    }

    TextView text(String value,int size,int color) { TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(color);t.setPadding(0,8,0,10);content.addView(t);return t; }
    void button(String title,Runnable action) { Button b=new Button(this);b.setText(title);b.setAllCaps(false);b.setTextColor(Color.WHITE);b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff24321e));content.addView(b);b.setOnClickListener(v->{if(!busy)action.run();}); }
    void message(String value){new AlertDialog.Builder(this).setTitle("Xbox 360 Recomp").setMessage(value).setPositiveButton("OK",null).show();}

    void pick(boolean folder) {
        Intent i=new Intent(folder?Intent.ACTION_OPEN_DOCUMENT_TREE:Intent.ACTION_OPEN_DOCUMENT);
        if(!folder){i.addCategory(Intent.CATEGORY_OPENABLE);i.setType("*/*");}
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(i,folder?102:101);
    }

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data); if(result!=RESULT_OK||data==null||data.getData()==null)return;
        Uri uri=data.getData();
        try {getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){}
        busy=true; status.setText("Importing... keep this app open.");
        worker.execute(()->importGame(uri,request==102));
    }

    void progress(String text) throws IOException {
        if(closed)throw new IOException("Import cancelled");
        long now=System.currentTimeMillis();if(now-lastProgress>250){lastProgress=now;runOnUiThread(()->status.setText(text));}
    }

    void importGame(Uri uri,boolean folder) {
        File stage=new File(library,".import-"+System.nanoTime());stage.mkdirs();
        try {
            if(folder)copyTree(uri,DocumentsContract.getTreeDocumentId(uri),stage,0,new HashSet<>());
            else {
                ParcelFileDescriptor fd=getContentResolver().openFileDescriptor(uri,"r");
                if(fd==null)throw new IOException("Cannot open selected ISO");
                    try(FileInputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)) {
                        FileChannel channel=in.getChannel();
                        // File-backed SAF documents support bounded random reads. Providers
                        // exposing a stream are rejected rather than copied without bounds.
                        IsoReader image=new IsoReader(channel);image.extract(stage,this::progress);
                }
            }
            File xex;
            String expected=metadata.optString("xex_path");
            if(metadata.optBoolean("native")&&!expected.isEmpty()) {
                xex=new File(stage,expected);
                if(!xex.getCanonicalPath().startsWith(stage.getCanonicalPath()+File.separator)||!xex.isFile())throw new IOException("Selected data does not contain "+expected);
            } else {ArrayList<File> found=new ArrayList<>();findDefault(stage,found,0);if(found.size()!=1)throw new IOException("Choose data containing one default.xex");xex=found.get(0);}
            try(FileInputStream f=new FileInputStream(xex)){byte[] magic=new byte[4];if(f.read(magic)!=4||!Arrays.equals(magic,new byte[]{88,69,88,50}))throw new IOException("Not an Xbox 360 XEX2 executable");}
            String hash=hash(xex);
            if(metadata.optBoolean("native")&&!hash.equals(metadata.optString("sha256")))throw new IOException("This APK was compiled for a different executable/version. Export a matching APK on PC.");
            File target=new File(library,hash.substring(0,20));
            if(target.exists())throw new IOException("This game is already in the library");
            String rel=stage.toURI().relativize(xex.toURI()).getPath();
            JSONObject info=new JSONObject().put("title",metadata.optBoolean("native")?metadata.optString("title"):"Xbox 360 "+hash.substring(0,8)).put("sha256",hash).put("xex_path",rel);
            try(FileOutputStream out=new FileOutputStream(new File(stage,"xbo-game.json"))){out.write(info.toString(2).getBytes("UTF-8"));}
            if(!stage.renameTo(target))throw new IOException("Cannot finish library import");
            runOnUiThread(()->{busy=false;draw();if(metadata.optBoolean("native"))verifyAndLaunch(target,info);else message("Import completed. Export/install the native APK for this title to play.");});
        } catch(Exception e){delete(stage);runOnUiThread(()->{busy=false;draw();message("Import failed: "+e.getMessage());});}
    }

    void copyTree(Uri tree,String id,File destination,int depth,Set<String> seen)throws Exception {
        if(depth>64||seen.size()>200000||!seen.add(id))throw new IOException("Invalid/excessive folder tree");
        Uri children=DocumentsContract.buildChildDocumentsUriUsingTree(tree,id);
        try(Cursor c=getContentResolver().query(children,new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_DISPLAY_NAME,DocumentsContract.Document.COLUMN_MIME_TYPE},null,null,null)) {
            if(c==null)throw new IOException("Cannot read folder");
            while(c.moveToNext()) {
                String child=c.getString(0),name=c.getString(1),mime=c.getString(2);
                if(name==null||name.equals(".")||name.equals("..")||name.matches(".*[/\\\\:\\x00-\\x1f].*"))throw new IOException("Unsafe file name");
                File out=new File(destination,name);if(out.exists())throw new IOException("Duplicate file");
                if(DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)){out.mkdirs();copyTree(tree,child,out,depth+1,seen);}
                else {progress("Copying "+name);try(InputStream in=getContentResolver().openInputStream(DocumentsContract.buildDocumentUriUsingTree(tree,child));FileOutputStream dest=new FileOutputStream(out)){if(in==null)throw new IOException("Unreadable file");byte[] b=new byte[1024*1024];int n;while((n=in.read(b))!=-1){progress("Copying "+name);if(out.getUsableSpace()<n+32L*1024*1024)throw new IOException("Insufficient storage");dest.write(b,0,n);}}}
            }
        }
    }

    void verifyAndLaunch(File root,JSONObject info) {
        busy=true;status.setText("Verifying executable...");worker.execute(()->{
            try {
                File xex=new File(root,info.getString("xex_path"));
                if(!xex.getCanonicalPath().startsWith(root.getCanonicalPath()+File.separator)||!hash(xex).equals(metadata.optString("sha256")))throw new IOException("Executable does not match the native build");
                Class<?> activity=Class.forName("org.xbo360.app.GameActivity");
                runOnUiThread(()->{busy=false;Intent i=new Intent(this,activity);i.putExtra("game_root",root.getAbsolutePath());startActivity(i);});
            }catch(Exception e){runOnUiThread(()->{busy=false;message(e.getMessage());});}
        });
    }
    void generateCode(File root,JSONObject info) {
        if(!codegenReady){message("On-device codegen library is not available in this APK.");return;}
        try {
            String rootPath=root.getCanonicalPath();
            File xex=new File(root,info.getString("xex_path"));
            String xexPath=xex.getCanonicalPath();
            if(!xexPath.startsWith(rootPath+File.separator)||!xex.isFile())throw new IOException("Executable path is outside the imported game folder");
            File project=new File(new File(getFilesDir(),"recomp"),root.getName());
            String projectPath=project.getCanonicalPath();
            busy=true;status.setText("Preparing on-device code generation...");
            Handler handler=new Handler(Looper.getMainLooper());
            CodegenBridge.initAndRunCodegenAsync("Game_"+root.getName(),xexPath,rootPath,projectPath,handler,
                progress->{if(!closed&&status!=null)status.setText(progress);},
                error->{if(closed)return;busy=false;draw();if(error==null)message("C++ sources generated in:\n"+projectPath+"\n\nThey are not compiled into a playable APK yet.");else message("Code generation failed:\n"+error);});
        } catch(Exception e) {busy=false;message("Code generation could not start: "+e.getMessage());}
    }
    void findDefault(File dir,List<File> found,int depth)throws IOException{if(depth>64)throw new IOException("Folder too deep");File[] files=dir.listFiles();if(files!=null)for(File f:files){if(f.isDirectory())findDefault(f,found,depth+1);else if(f.getName().equalsIgnoreCase("default.xex"))found.add(f);}}
    String hash(File file)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))!=-1){progress("Checking executable...");d.update(b,0,n);}}StringBuilder s=new StringBuilder();for(byte b:d.digest())s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();}
    static String read(InputStream in,int limit)throws IOException{try(InputStream src=in;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=src.read(b))!=-1){if(out.size()+n>limit)throw new IOException("Metadata too large");out.write(b,0,n);}return out.toString("UTF-8");}}
    static void delete(File f){if(f.isDirectory()){File[] all=f.listFiles();if(all!=null)for(File p:all)delete(p);}f.delete();}
    @Override protected void onDestroy(){closed=true;worker.shutdownNow();super.onDestroy();}
}
