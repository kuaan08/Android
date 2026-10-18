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
import java.util.zip.*;

/** Xbox 360 library, SAF importer, experimental on-device codegen, and native launch menu. */
public final class LauncherActivity extends Activity {
    final ExecutorService worker = Executors.newSingleThreadExecutor();
    LinearLayout content; TextView status; JSONObject metadata;
    File library; volatile boolean closed; boolean busy; boolean codegenInstalled; String codegenError; long lastProgress;
    File pendingExportProject; File pendingExportGameRoot;
    static final int EXPORT_PROJECT_REQUEST = 103;
    static final int GREEN = 0xff7cd336, BG = 0xff111318;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            metadata = new JSONObject(read(getAssets().open("project.json"), 1024 * 1024));
            File base = getExternalFilesDir(null); if (base == null) base = getFilesDir();
            library = new File(base, "games"); if (!library.mkdirs() && !library.isDirectory()) throw new IOException("Cannot open game library");
            // Never load a JNI library from LauncherActivity: native crashes are
            // process-fatal and must not terminate the menu on app startup.
            codegenInstalled = new File(getApplicationInfo().nativeLibraryDir,
                    "libxbo360_codegen_jni.so").isFile();
            draw();
        } catch (Exception e) { new AlertDialog.Builder(this).setMessage(e.toString()).setPositiveButton("Close", (d,w)->finish()).show(); }
    }

    void draw() {
        ScrollView scroll = new ScrollView(this); scroll.setBackgroundColor(BG);
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(28,28,28,28); scroll.addView(content); setContentView(scroll);
        text("XBOX 360 RECOMP", 27, GREEN); text(metadata.optString("title"), 18, Color.WHITE);
        text("Library · Xbox 360 → native Android", 14, 0xff9ca5b2);
        if (codegenInstalled) text("Experimental C++ generator packaged. ReXGlue starts only when you request codegen, in a separate crash-isolated process. It cannot compile a playable APK.", 13, 0xffefba63);
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
                if (codegenInstalled) button("Generate C++ on this device (experimental)", () -> generateCode(root, game));
                if (hasGeneratedProject(root)) button("Export generated sources (ZIP)", () -> saveGeneratedProject(root, title));
                button(nativeReady ? "Play " + title : "Details", () -> {
                    if (nativeReady) verifyAndLaunch(root,game);
                    else message("Export this title from the desktop application's Library → Export APK. Selecting an ISO does not compile its PowerPC code on the phone.");
                });
            } catch (Exception e) { text("Unreadable library entry: " + root.getName(),13,Color.RED); }
        }
        button("Device diagnostics (copy)", this::showDiagnostics);
        button("Updates", () -> startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse("https://github.com/kuaan08/Android/releases/latest"))));
        button("About / credits", () -> message("Xbox 360 Recomp 0.3.1\nFork: katakishi0 · hosted by kuaan08\nSwitchRecomp by MZ Labs\nReXGlue by Tom Clay and contributors\nAndroid runtime: AlanConstantino, Andrew Nakas, Buku313 and contributors\nNo commercial-game compatibility is established by the synthetic build tests."));
        if (metadata.optBoolean("native")) text("ARM64 · Android 13+ · Vulkan · physical gamepad recommended",13,0xff9ca5b2);
    }

    TextView text(String value,int size,int color) { TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(color);t.setPadding(0,8,0,10);content.addView(t);return t; }
    void button(String title,Runnable action) { Button b=new Button(this);b.setText(title);b.setAllCaps(false);b.setTextColor(Color.WHITE);b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff24321e));content.addView(b);b.setOnClickListener(v->{if(!busy)action.run();}); }
    void message(String value){new AlertDialog.Builder(this).setTitle("Xbox 360 Recomp").setMessage(value).setPositiveButton("OK",null).show();}
    
    /** Copy a privacy-conscious hardware/build report to help diagnose phone-only failures. */
    void showDiagnostics() {
        StringBuilder info = new StringBuilder("Xbox 360 Recomp Android diagnostics\n");
        info.append("Android: ").append(Build.VERSION.RELEASE)
            .append(" (API ").append(Build.VERSION.SDK_INT).append(")\n");
        info.append("ABIs: ").append(Arrays.toString(Build.SUPPORTED_ABIS)).append('\n');
        info.append("Vulkan feature advertised: ")
            .append(getPackageManager().hasSystemFeature("android.hardware.vulkan.version")).append('\n');
        info.append("Package: ").append(getPackageName()).append('\n');
        info.append("Native title APK: ").append(metadata.optBoolean("native")).append('\n');
        File libDir = new File(getApplicationInfo().nativeLibraryDir);
        info.append("Game library packaged: ")
            .append(new File(libDir, "libxbo_game.so").isFile()).append('\n');
        info.append("ReXGlue runtime packaged: ")
            .append(new File(libDir, "librexruntime.so").isFile()).append('\n');
        info.append("On-device codegen library packaged: ").append(codegenInstalled).append('\n');
        info.append("Codegen service bound: ").append(codegenBound).append('\n');
        if (codegenError != null) info.append("Codegen error: ").append(codegenError).append('\n');
        if (library != null) {
            info.append("Free game storage MiB: ").append(library.getUsableSpace() / (1024 * 1024)).append('\n');
            File[] games = library.listFiles(f -> f.isDirectory() && new File(f, "xbo-game.json").isFile());
            info.append("Imported library entries: ").append(games == null ? "unavailable" : games.length).append('\n');
        }
        ActivityManager manager = (ActivityManager) getSystemService(ACTIVITY_SERVICE);
        if (manager != null) {
            ActivityManager.MemoryInfo mem = new ActivityManager.MemoryInfo();
            manager.getMemoryInfo(mem);
            info.append("Device RAM MiB (total/available): ")
                .append(mem.totalMem / (1024 * 1024)).append('/')
                .append(mem.availMem / (1024 * 1024)).append('\n');
        }
        info.append("Java heap max MiB: ")
            .append(Runtime.getRuntime().maxMemory() / (1024 * 1024)).append('\n');
        info.append("Note: feature flags and APK files do not prove Vulkan or game compatibility.");
        final String report = info.toString();
        new AlertDialog.Builder(this).setTitle("Device diagnostics").setMessage(report)
            .setPositiveButton("Copy", (dialog, which) -> {
                android.content.ClipboardManager clipboard =
                    (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (clipboard != null) {
                    clipboard.setPrimaryClip(ClipData.newPlainText("Xbox 360 Recomp diagnostics", report));
                    Toast.makeText(this, "Diagnostics copied", Toast.LENGTH_SHORT).show();
                }
            }).setNegativeButton("Close", null).show();
    }

    void pick(boolean folder) {
        Intent i=new Intent(folder?Intent.ACTION_OPEN_DOCUMENT_TREE:Intent.ACTION_OPEN_DOCUMENT);
        if(!folder){i.addCategory(Intent.CATEGORY_OPENABLE);i.setType("*/*");}
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(i,folder?102:101);
    }

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==EXPORT_PROJECT_REQUEST) {
            File project=pendingExportProject,gameRoot=pendingExportGameRoot;pendingExportProject=null;pendingExportGameRoot=null;
            if(result!=RESULT_OK||data==null||data.getData()==null)return;
            if(project==null||gameRoot==null){message("There is no generated project to export.");return;}
            Uri destination=data.getData();busy=true;
            if(status!=null)status.setText("Exporting generated sources...");
            worker.execute(()->exportProjectZip(project,gameRoot,destination));
            return;
        }
        if(result!=RESULT_OK||data==null||data.getData()==null)return;
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
    private boolean codegenBound;
    private Messenger codegenRemote;
    private String activeCodegenProject;
    private final Messenger codegenReply = new Messenger(new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message msg) {
            String detail = msg.getData().getString("detail");
            if (closed || !codegenBound) return;
            if (msg.what == CodegenService.PROGRESS) {
                if (status != null) status.setText(detail == null ? "Generating C++..." : detail);
            } else if (msg.what == CodegenService.COMPLETE) {
                String path = activeCodegenProject;
                endCodegen();
                if (detail == null) message("C++ sources generated in:\n" + path
                    + "\n\nNot compiled into a playable APK yet.");
                else message("Code generation failed:\n" + detail);
            }
        }
    });
    private final ServiceConnection codegenConnection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            if (closed || !codegenBound) return;
            codegenRemote = new Messenger(binder);
            try {
                Message request = Message.obtain(null, CodegenService.RUN);
                request.replyTo = codegenReply;
                Bundle data = new Bundle();
                data.putString("name", codegenName);
                data.putString("xex", codegenXex);
                data.putString("game", codegenGame);
                data.putString("project", activeCodegenProject);
                request.setData(data);
                codegenRemote.send(request);
            } catch (RemoteException | RuntimeException e) {
                codegenError = e.toString();
                endCodegen();
                message("Cannot contact the codegen process:\n" + e);
            }
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            if (!closed && codegenBound) {
                codegenError = "Codegen service exited unexpectedly (possible native crash).";
                endCodegen();
                message(codegenError + "\nCapture the Android crash buffer using adb logcat.");
            }
        }
        @Override public void onNullBinding(ComponentName name) {
            if (!closed && codegenBound) {
                endCodegen();
                message("Android did not bind the codegen service.");
            }
        }
        @Override public void onBindingDied(ComponentName name) { onServiceDisconnected(name); }
    };
    private String codegenName, codegenXex, codegenGame;

    private void endCodegen() {
        if (codegenBound) {
            codegenBound = false;
            try { unbindService(codegenConnection); } catch (IllegalArgumentException ignored) {}
        }
        codegenRemote = null;
        busy = false;
        if (!closed) draw();
    }

    void generateCode(File root,JSONObject info) {
        if (!codegenInstalled) {
            message("The optional codegen JNI library is not installed in this APK.");
            return;
        }
        try {
            String rootPath = root.getCanonicalPath();
            File xex = new File(root, info.getString("xex_path"));
            String xexPath = xex.getCanonicalPath();
            if (!xexPath.startsWith(rootPath + File.separator) || !xex.isFile())
                throw new IOException("Executable path is outside the imported game folder");
            codegenName = "Game_" + root.getName();
            codegenXex = xexPath;
            codegenGame = rootPath;
            activeCodegenProject = new File(new File(getFilesDir(), "recomp"),
                root.getName()).getCanonicalPath();
            busy = true;
            status.setText("Starting separate codegen process...");
            Intent service = new Intent(this, CodegenService.class);
            codegenBound = bindService(service, codegenConnection, Context.BIND_AUTO_CREATE);
            if (!codegenBound) {
                busy = false;
                message("Failed to start the isolated codegen process.");
            }
        } catch (Exception e) {
            busy = false;
            message("Code generation could not start: " + e.getMessage());
        }
    }
    File generatedProject(File gameRoot){return new File(new File(getFilesDir(),"recomp"),gameRoot.getName());}
    boolean hasManifest(File project){File[] manifests=project.listFiles((dir,name)->name.endsWith("_manifest.toml"));return manifests!=null&&manifests.length==1;}
    boolean hasGeneratedProject(File gameRoot){
        try{File base=new File(getFilesDir(),"recomp"),project=generatedProject(gameRoot);String parent=base.getCanonicalPath()+File.separator;return project.getCanonicalPath().startsWith(parent)&&project.isDirectory()&&hasManifest(project);}
        catch(IOException e){return false;}
    }
    void saveGeneratedProject(File gameRoot,String title){
        if(!hasGeneratedProject(gameRoot)){message("No generated ReXGlue project was found for this game.");return;}
        String safe=title.replaceAll("[^A-Za-z0-9._-]+","_");if(safe.isEmpty())safe="xbox360-project";if(safe.length()>80)safe=safe.substring(0,80);
        pendingExportProject=generatedProject(gameRoot);pendingExportGameRoot=gameRoot;
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("application/zip");intent.putExtra(Intent.EXTRA_TITLE,safe+"-generated-sources.zip");
        try{startActivityForResult(intent,EXPORT_PROJECT_REQUEST);}catch(ActivityNotFoundException e){pendingExportProject=null;pendingExportGameRoot=null;message("No file picker is available to save the source archive.");}
    }
    void exportProjectZip(File project,File gameRoot,Uri destination){
        try{
            String canonical=project.getCanonicalPath(),canonicalGame=gameRoot.getCanonicalPath();File base=new File(getFilesDir(),"recomp");
            if(!canonical.startsWith(base.getCanonicalPath()+File.separator)||!hasManifest(project))throw new IOException("Generated project path or manifest is invalid.");
            File gameInfoFile=new File(gameRoot,"xbo-game.json");if(!gameInfoFile.isFile())throw new IOException("Game metadata is missing.");
            JSONObject game=new JSONObject(read(new FileInputStream(gameInfoFile),1024*1024));String originalXex=game.optString("xex_path");
            File xex=new File(gameRoot,originalXex);String canonicalXex=xex.getCanonicalPath();
            if(!canonicalXex.startsWith(canonicalGame+File.separator)||!xex.isFile())throw new IOException("XEX path is outside the imported game folder.");
            String relativeXex=gameRoot.toPath().toRealPath().relativize(xex.toPath().toRealPath()).toString().replace(File.separatorChar,'/');
            if(!hash(xex).equals(game.optString("sha256")))throw new IOException("Imported XEX checksum does not match its metadata.");
            OutputStream raw=getContentResolver().openOutputStream(destination,"w");if(raw==null)throw new IOException("Cannot open the selected destination.");
            try(ZipOutputStream zip=new ZipOutputStream(new BufferedOutputStream(raw))){
                zip.putNextEntry(new ZipEntry("xbo-game.json"));zip.write(game.toString(2).getBytes("UTF-8"));zip.closeEntry();
                int[] files={0};long[] bytes={0};Set<String> seen=new HashSet<>();addProjectFilesToZip(project,project,relativeXex,zip,files,bytes,seen);
                zip.putNextEntry(new ZipEntry("TERMUX-README.txt"));
                zip.write(("Generated ReXGlue sources only. This archive does not contain original game data and is not a playable APK.\n"+
                    "The archive contains generated-project/ and xbo-game.json. Extract your own game data into a sibling game/ directory, preserving xex_path from xbo-game.json.\n"+
                    "The generated manifest has portable references to ../game and ../game/<xex_path>; the game files are not copied or redistributed.\n"+
                    "A native Termux compiler/package step is still required. Do not run build tools or generated code as root.\n").getBytes("UTF-8"));
                zip.closeEntry();zip.finish();
            }
            if(!closed)runOnUiThread(()->{busy=false;draw();message("Generated sources and portable XEX metadata exported. The ZIP excludes game data and is not an installable APK; a Termux build step is still required.");});
        }catch(Exception e){if(!closed)runOnUiThread(()->{busy=false;draw();message("Source export failed: "+e.getMessage());});}
    }
    void addProjectFilesToZip(File root,File entry,String relativeXex,ZipOutputStream zip,int[] files,long[] bytes,Set<String> seen)throws IOException{
        if(closed||Thread.currentThread().isInterrupted())throw new IOException("Export cancelled.");
        String canonicalRoot=root.getCanonicalPath(),canonical=entry.getCanonicalPath();
        if(!canonical.equals(canonicalRoot)&&!canonical.startsWith(canonicalRoot+File.separator))throw new IOException("Project path escaped its root.");
        if(!seen.add(canonical))throw new IOException("Duplicate or cyclic project path.");
        if(entry.isDirectory()){File[] children=entry.listFiles();if(children==null)throw new IOException("Cannot enumerate generated project.");for(File child:children)addProjectFilesToZip(root,child,relativeXex,zip,files,bytes,seen);return;}
        if(!entry.isFile())throw new IOException("Unsupported project entry.");if(++files[0]>200000)throw new IOException("Project contains too many files.");
        String relative=root.toPath().relativize(entry.toPath()).toString().replace(File.separatorChar,'/');zip.putNextEntry(new ZipEntry("generated-project/"+relative));
        if(entry.getName().endsWith("_manifest.toml")){
            String manifest=read(new FileInputStream(entry),8*1024*1024);zip.write(rewriteManifestForArchive(manifest,relativeXex).getBytes("UTF-8"));zip.closeEntry();return;
        }
        try(InputStream in=new BufferedInputStream(new FileInputStream(entry))){byte[] buffer=new byte[64*1024];int n;while((n=in.read(buffer))!=-1){if(closed||Thread.currentThread().isInterrupted())throw new IOException("Export cancelled.");zip.write(buffer,0,n);bytes[0]+=n;if((bytes[0]&0x3fffff)==0)progress("Exporting generated sources: "+files[0]+" files");}}
        zip.closeEntry();
    }
    static String rewriteManifestForArchive(String source,String relativeXex){
        StringBuilder out=new StringBuilder();String section="";String[] lines=source.split("\\r?\\n",-1);
        for(int i=0;i<lines.length;i++){
            String line=lines[i],trim=line.trim();if(trim.startsWith("["))section=trim;
            if(section.equals("[project]")&&trim.startsWith("game_root" )&&trim.substring("game_root".length()).trim().startsWith("="))line="game_root = \"../game\"";
            if(section.equals("[entrypoint]")&&trim.startsWith("file_path")&&trim.substring("file_path".length()).trim().startsWith("="))line="file_path = "+tomlString("../game/"+relativeXex);
            out.append(line);if(i+1<lines.length)out.append('\n');
        }
        return out.toString();
    }
    static String tomlString(String value){
        StringBuilder out=new StringBuilder("\"");
        for(int i=0;i<value.length();i++){
            char c=value.charAt(i);
            if(c=='\\'||c=='\"')out.append('\\').append(c);
            else if(c=='\b')out.append("\\b");else if(c=='\t')out.append("\\t");
            else if(c=='\n')out.append("\\n");else if(c=='\f')out.append("\\f");else if(c=='\r')out.append("\\r");
            else if(c<0x20||c==0x7f)out.append(String.format(Locale.ROOT,"\\u%04x",(int)c));
            else out.append(c);
        }
        return out.append('\"').toString();
    }
    void findDefault(File dir,List<File> found,int depth)throws IOException{if(depth>64)throw new IOException("Folder too deep");File[] files=dir.listFiles();if(files!=null)for(File f:files){if(f.isDirectory())findDefault(f,found,depth+1);else if(f.getName().equalsIgnoreCase("default.xex"))found.add(f);}}
    String hash(File file)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))!=-1){progress("Checking executable...");d.update(b,0,n);}}StringBuilder s=new StringBuilder();for(byte b:d.digest())s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();}
    static String read(InputStream in,int limit)throws IOException{try(InputStream src=in;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=src.read(b))!=-1){if(out.size()+n>limit)throw new IOException("Metadata too large");out.write(b,0,n);}return out.toString("UTF-8");}}
    static void delete(File f){if(f.isDirectory()){File[] all=f.listFiles();if(all!=null)for(File p:all)delete(p);}f.delete();}
    @Override protected void onDestroy(){closed=true;if(codegenBound)endCodegen();worker.shutdownNow();super.onDestroy();}
}
