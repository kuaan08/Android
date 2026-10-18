//! Xbox 360 tool discovery. Modified from SwitchRecomp's portable-folder approach.
use std::path::PathBuf;
use std::process::Command;

pub fn home() -> PathBuf {
    [std::env::current_exe().ok(), std::env::current_dir().ok()]
        .into_iter()
        .flatten()
        .flat_map(|p| p.ancestors().map(|p| p.to_path_buf()).collect::<Vec<_>>())
        .find(|p| p.join("xbo360.py").is_file())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default())
}

pub fn python() -> PathBuf {
    let bundled = home().join("python").join("python.exe");
    if bundled.is_file() {
        bundled
    } else if cfg!(windows) {
        "python".into()
    } else {
        "python3".into()
    }
}

pub fn hide_console(cmd: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    #[cfg(not(windows))]
    let _ = cmd;
}
