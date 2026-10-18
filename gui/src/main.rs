// Xbox 360 Recomp — Copyright 2026 katakishi0, hosted by kuaan08.
// Frontend derived from SwitchRecomp by MZ Labs (Apache-2.0).
// Modified: Xbox 360 project workflow, ReXGlue SDK, project persistence and Xbox theme.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod icon;
mod job;
mod theme;
mod toolchain;

use eframe::egui::{self, Align, Color32, Layout, Margin, RichText, Stroke};
use serde::{Deserialize, Serialize};
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;

#[derive(Default, Serialize, Deserialize)]
#[serde(default)]
struct Settings {
    input: String,
    game_root: String,
    project: String,
    name: String,
    sdk: String,
    python: String,
    projects: Vec<String>,
    renderer: String,
    jobs: u32,
    recent: Vec<String>,
    target_android: bool,
    force_codegen: bool,
    android_sdk: String,
    android_ndk: String,
    android_runtime_source: String,
}

struct App {
    settings: Settings,
    settings_path: PathBuf,
    job: Option<job::Job>,
    progress: job::Progress,
    log: Vec<String>,
    tab: usize,
    tools_rx: Option<Receiver<Result<serde_json::Value, String>>>,
    tools: Option<serde_json::Value>,
    update_rx: Option<Receiver<Result<serde_json::Value, String>>>,
    update: Option<serde_json::Value>,
    update_error: String,
    show_setup: bool,
    show_settings: bool,
    install_confirmation: Option<String>,
    edit_project: Option<String>,
    hint_project: Option<String>,
    hint_address: String,
    hint_size: String,
    hint_parent: String,
    hint_rx: Option<Receiver<Result<serde_json::Value, String>>>,
    hint_suggestions: Option<serde_json::Value>,
    hint_suggestions_error: String,
    check_after_job: bool,
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        theme::apply(&cc.egui_ctx);
        let base = std::env::var_os("LOCALAPPDATA")
            .or_else(|| std::env::var_os("XDG_CONFIG_HOME"))
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config")
            });
        let settings_path = base.join("Xbox360Recomp").join("settings.json");
        let mut settings: Settings = std::fs::read(&settings_path)
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or_default();
        if settings.python.is_empty()
            || (Path::new(&settings.python).is_absolute() && !Path::new(&settings.python).is_file())
        {
            settings.python = toolchain::python().to_string_lossy().into_owned();
        }
        if settings.renderer.is_empty() {
            settings.renderer = "any".into();
        }
        if settings.name.is_empty() {
            settings.name = "my_game".into();
        }
        let tools_rx = Some(request_json(&settings.python, "toolchain", &cc.egui_ctx));
        Self {
            settings,
            settings_path,
            job: None,
            progress: Default::default(),
            log: vec![],
            tab: 0,
            tools_rx,
            tools: None,
            update_rx: None,
            update: None,
            update_error: String::new(),
            show_setup: false,
            show_settings: false,
            install_confirmation: None,
            edit_project: None,
            hint_project: None,
            hint_address: String::new(),
            hint_size: String::new(),
            hint_parent: String::new(),
            hint_rx: None,
            hint_suggestions: None,
            hint_suggestions_error: String::new(),
            check_after_job: false,
        }
    }

    fn save(&mut self) {
        let result = (|| -> std::io::Result<()> {
            if let Some(p) = self.settings_path.parent() {
                std::fs::create_dir_all(p)?;
            }
            std::fs::write(
                &self.settings_path,
                serde_json::to_vec_pretty(&self.settings)?,
            )
        })();
        if let Err(e) = result {
            self.log
                .push(format!("Warning: settings could not be saved: {e}"));
        }
    }

    fn start(&mut self, ctx: &egui::Context, args: Vec<String>) {
        if self.job.is_some() {
            return;
        }
        if args.first().is_some_and(|a| a == "install-tools") {
            self.check_after_job = true;
        }
        self.save();
        let cfg = job::JobConfig {
            python: self.settings.python.clone().into(),
            home: toolchain::home(),
            args: args.into_iter().map(OsString::from).collect(),
        };
        self.log.clear();
        self.log.push(format!("> {}", cfg.display()));
        self.progress = Default::default();
        match job::Job::start(&cfg, ctx) {
            Ok(j) => self.job = Some(j),
            Err(e) => {
                self.log.push(format!("Error: {e}"));
                self.progress.phase = job::Phase::Failed;
            }
        }
    }

    fn sdk_args(&self, args: &mut Vec<String>) {
        if !self.settings.sdk.trim().is_empty() {
            args.extend(["--sdk".into(), self.settings.sdk.clone()]);
        }
    }

    fn create(&mut self, ctx: &egui::Context, stage: &str) {
        let s = &self.settings;
        let mut args = vec![
            stage.into(),
            s.input.clone(),
            "--project".into(),
            s.project.clone(),
            "--name".into(),
            s.name.clone(),
        ];
        if !s.game_root.trim().is_empty() {
            args.extend(["--game-root".into(), s.game_root.clone()]);
        }
        self.sdk_args(&mut args);
        if stage == "recompile" {
            args.extend(["--jobs".into(), self.settings.jobs.to_string()]);
            if self.settings.force_codegen { args.push("--force".into()); }
        }
        if !self.settings.projects.contains(&self.settings.project)
            && !self.settings.project.is_empty()
        {
            self.settings.projects.push(self.settings.project.clone());
        }
        if !self.settings.recent.contains(&self.settings.input) {
            self.settings.recent.insert(0, self.settings.input.clone());
            self.settings.recent.truncate(12);
        }
        self.start(ctx, args);
    }

    fn poll(&mut self) {
        let mut exited = None;
        if let Some(j) = &self.job {
            for event in j.events() {
                match event {
                    job::JobEvent::Line(s) => {
                        self.progress.feed(&s);
                        self.log.push(s);
                        if self.log.len() > 8000 {
                            self.log.drain(..1000);
                        }
                    }
                    job::JobEvent::Exited(code) => exited = Some((code, j.cancelled)),
                }
            }
        }
        if let Some((code, cancelled)) = exited {
            self.progress.phase = if cancelled {
                job::Phase::Cancelled
            } else if code == Some(0) {
                job::Phase::Done
            } else {
                job::Phase::Failed
            };
            self.log.push(format!("Process exited: {code:?}"));
            self.job = None;
        }
    }

    fn new_project(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        section(ui, "1  ·  Choose a game");
        ui.label("Open a folder, Xbox 360 XEX, or ISO/XISO.");
        ui.add_space(10.0);
        field(ui, "Game input", &mut self.settings.input, false, true);
        ui.horizontal_wrapped(|ui| {
            if ui.button("Folder...").clicked()
                && let Some(p) = rfd::FileDialog::new().pick_folder()
            {
                self.settings.input = p.to_string_lossy().into_owned();
            }
            ui.menu_button("Recent", |ui| {
                for path in self.settings.recent.clone() {
                    if ui.button(&path).clicked() {
                        self.settings.input = path;
                        ui.close();
                    }
                }
            });
        });
        section(ui, "2  ·  Data and output");
        field(
            ui,
            "Game data directory (optional)",
            &mut self.settings.game_root,
            true,
            false,
        );
        field(
            ui,
            "Project directory (empty)",
            &mut self.settings.project,
            true,
            false,
        );
        ui.label("Project name (lowercase, for example my_game)");
        ui.text_edit_singleline(&mut self.settings.name);
        ui.add_space(10.0);
        section(ui, "3  ·  Target and build");
        ui.checkbox(&mut self.settings.force_codegen, "Force code generation (experimental)");
        if self.settings.force_codegen {
            ui.colored_label(theme::WARNING, "Skips some analysis failures; generated code may crash or fail to compile.");
        }
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.settings.target_android, false, "Windows / Linux");
            ui.selectable_value(&mut self.settings.target_android, true, "Android APK");
        });
        if self.settings.target_android {
            ui.label("Prepare the project first, then export its native APK from Library.");
        }
        ui.horizontal_wrapped(|ui| {
            if ui.button("Verify input").clicked() {
                self.start(ctx, vec!["inspect".into(), self.settings.input.clone()]);
            }
            if ui.button("Prepare project").clicked() {
                self.create(ctx, "prepare");
            }
            if ui
                .add(
                    egui::Button::new(
                        RichText::new(if self.settings.target_android {
                            "Prepare for APK"
                        } else {
                            "Recompile + build"
                        })
                        .color(theme::BG),
                    )
                    .fill(theme::ACCENT),
                )
                .clicked()
            {
                if self.settings.target_android {
                    self.create(ctx, "prepare");
                } else {
                    self.create(ctx, "recompile");
                }
            }
        });
        ui.add_space(10.0);
        ui.colored_label(
            theme::WARNING,
            "Experimental: each title may need function boundaries, hooks and runtime fixes.",
        );
    }

    fn projects(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        ui.heading("Library");
        if ui.button("Open existing project...").clicked()
            && let Some(p) = rfd::FileDialog::new().pick_folder()
        {
            let s = p.to_string_lossy().to_string();
            if !self.settings.projects.contains(&s) {
                self.settings.projects.push(s);
                self.save();
            }
        }
        for root in self.settings.projects.clone() {
            let path = Path::new(&root);
            let state = std::fs::read(path.join("xbo360-project.json"))
                .ok()
                .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok());
            egui::Frame::group(ui.style()).show(ui, |ui| {
                let name = state
                    .as_ref()
                    .and_then(|s| s["name"].as_str())
                    .unwrap_or("Project");
                let status = state
                    .as_ref()
                    .and_then(|s| s["status"].as_str())
                    .unwrap_or("not prepared");
                ui.label(RichText::new(name).strong());
                ui.label(format!("{status} · {root}"));
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(state.is_some(), egui::Button::new("Generate C++"))
                        .clicked()
                    {
                        let mut args = vec!["codegen".into(), root.clone()];
                        self.sdk_args(&mut args);
                        if self.settings.force_codegen { args.push("--force".into()); }
                        self.start(ctx, args);
                    }
                    if ui
                        .add_enabled(state.is_some(), egui::Button::new("Build"))
                        .clicked()
                    {
                        let mut args = vec![
                            "build".into(),
                            root.clone(),
                            "--jobs".into(),
                            self.settings.jobs.to_string(),
                        ];
                        self.sdk_args(&mut args);
                        if self.settings.force_codegen { args.push("--force".into()); }
                        self.start(ctx, args);
                    }
                    if ui
                        .add_enabled(status == "built", egui::Button::new("Run"))
                        .clicked()
                    {
                        let mut args = vec!["run".into(), root.clone()];
                        if !path.join("launch-settings.json").is_file() {
                            args.extend(["--renderer".into(), self.settings.renderer.clone()]);
                        }
                        self.start(ctx, args);
                    }
                    if ui
                        .add_enabled(state.is_some(), egui::Button::new("Export APK"))
                        .clicked()
                    {
                        self.export_apk(ctx, Some(root.clone()));
                    }
                    if ui
                        .add_enabled(state.is_some(), egui::Button::new("Game settings"))
                        .clicked()
                    {
                        self.edit_project = Some(root.clone());
                    }
                    if ui.add_enabled(state.is_some(), egui::Button::new("Function hints")).clicked() {
                        self.hint_project = Some(root.clone());
                        self.hint_address.clear();
                        self.hint_size.clear();
                        self.hint_parent.clear();
                        self.hint_suggestions = None;
                        self.hint_suggestions_error.clear();
                    }
                    if ui.button("Open folder").clicked() {
                        open_path(path);
                    }
                });
            });
        }
    }

    fn settings_ui(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        ui.heading("Tools and runtime");
        field(ui, "Python 3.11+", &mut self.settings.python, false, false);
        field(
            ui,
            "ReXGlue 0.10.0 SDK prefix (blank = bundled/cache)",
            &mut self.settings.sdk,
            true,
            false,
        );
        ui.horizontal(|ui| {
            if ui.button("Install verified SDK").clicked() {
                let mut args = vec!["install-sdk".into()];
                self.sdk_args(&mut args);
                self.start(ctx, args);
            }
            if ui.button("Check toolchain").clicked() {
                let mut args = vec!["doctor".into()];
                self.sdk_args(&mut args);
                self.start(ctx, args);
            }
            if ui.button("Save settings").clicked() {
                self.save();
            }
        });
        ui.checkbox(&mut self.settings.force_codegen, "Force ReXGlue analysis (experimental)");
        ui.label("Force is optional and unsafe; it cannot fix bad function boundaries.");
        ui.label("Build jobs (0 = automatic)");
        ui.add(egui::DragValue::new(&mut self.settings.jobs).range(0..=256));
        egui::ComboBox::from_label("Renderer at launch")
            .selected_text(&self.settings.renderer)
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.settings.renderer, "any".into(), "Automatic");
                if cfg!(windows) {
                    ui.selectable_value(&mut self.settings.renderer, "d3d12".into(), "Direct3D 12");
                }
                ui.selectable_value(&mut self.settings.renderer, "vulkan".into(), "Vulkan");
            });
        ui.label("The chosen backend must be present in your SDK's Xenos plugin.");
        ui.label("Windows builds need Visual Studio 2022 C++, Clang 20+, CMake and Ninja.");
        ui.label("The app loads the installed Visual Studio build environment automatically.");
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.poll();
        self.poll_background(&ctx);
        if self.job.is_some() || self.tools_rx.is_some() || self.update_rx.is_some() {
            ctx.request_repaint_after(Duration::from_millis(120));
        }
        if let Some(path) =
            ctx.input(|i| i.raw.dropped_files.first().map(|f| f.path().to_path_buf()))
        {
            if self.job.is_none() {
                self.settings.input = path.to_string_lossy().into_owned();
                self.tab = 0;
            }
        }
        egui::Panel::top("top_bar")
            .frame(
                egui::Frame::new()
                    .fill(theme::BG)
                    .inner_margin(Margin::symmetric(16, 10)),
            )
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    logo(ui, 26.0);
                    ui.label(
                        RichText::new("Xbox360Recomp")
                            .size(19.0)
                            .strong()
                            .color(Color32::WHITE),
                    );
                    ui.add_space(12.0);
                    for (i, label) in ["Recompile", "Library", "About"].iter().enumerate() {
                        if ui.selectable_label(self.tab == i, *label).clicked() {
                            self.tab = i;
                        }
                    }
                    if ui
                        .add_enabled(self.update_rx.is_none(), egui::Button::new("Updates"))
                        .clicked()
                    {
                        self.update_error.clear();
                        self.update_rx = Some(request_json(&self.settings.python, "update", &ctx));
                    }
                    if ui.button("Settings").clicked() {
                        self.show_settings = true;
                    }
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        let ready = self
                            .tools
                            .as_ref()
                            .is_some_and(|v| v["desktop_ready"] == true);
                        if ui
                            .button(
                                RichText::new(if ready {
                                    "Toolchain ready"
                                } else {
                                    "Setup tools"
                                })
                                .color(if ready {
                                    theme::SUCCESS
                                } else {
                                    theme::WARNING
                                }),
                            )
                            .clicked()
                        {
                            self.show_setup = true;
                        }
                    });
                });
            });
        egui::Panel::bottom("status_bar")
            .frame(
                egui::Frame::new()
                    .fill(theme::BG)
                    .inner_margin(Margin::symmetric(16, 6)),
            )
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new(self.progress.describe()).small());
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new("Fork: katakishi0 · SwitchRecomp by MZ Labs")
                                .small()
                                .color(theme::TEXT_WEAK),
                        );
                    });
                });
            });
        if self.tab == 0 {
            egui::Panel::left("form")
                .resizable(false)
                .exact_size(420.0)
                .frame(
                    egui::Frame::new()
                        .fill(theme::PANEL)
                        .inner_margin(Margin::same(18)),
                )
                .show(ui, |ui| {
                    egui::ScrollArea::vertical().show(ui, |ui| {
                        ui.add_enabled_ui(self.job.is_none(), |ui| self.new_project(ui, &ctx));
                    });
                });
            egui::CentralPanel::default()
                .frame(page_frame())
                .show(ui, |ui| {
                    self.run_card(ui);
                    ui.add_space(14.0);
                    self.log_view(ui);
                });
        } else {
            egui::CentralPanel::default()
                .frame(page_frame())
                .show(ui, |ui| {
                    egui::ScrollArea::vertical().show(ui, |ui| {
                        ui.add_enabled_ui(self.job.is_none(), |ui| {
                            if self.tab == 1 {
                                self.projects(ui, &ctx);
                            } else {
                                self.about(ui);
                            }
                        });
                    });
                });
        }
        self.modals(&ctx);
        if ctx.input(|i| !i.raw.hovered_files.is_empty()) {
            egui::Area::new("drop_hint".into())
                .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
                .show(&ctx, |ui| {
                    ui.label(
                        RichText::new("Drop a game folder, XEX or ISO")
                            .size(28.0)
                            .color(theme::ACCENT),
                    );
                });
        }
    }
}

impl Drop for App {
    fn drop(&mut self) {
        self.save();
        if let Some(j) = &mut self.job {
            j.cancel();
        }
    }
}

impl App {
    fn poll_background(&mut self, ctx: &egui::Context) {
        if let Some(result) = self.tools_rx.as_ref().and_then(|r| r.try_recv().ok()) {
            self.tools_rx = None;
            match result {
                Ok(v) => {
                    self.show_setup = !v["desktop_ready"].as_bool().unwrap_or(false);
                    self.tools = Some(v);
                }
                Err(e) => self.log.push(e),
            }
        }
        if let Some(result) = self.update_rx.as_ref().and_then(|r| r.try_recv().ok()) {
            self.update_rx = None;
            match result {
                Ok(v) => self.update = Some(v),
                Err(e) => self.update_error = e,
            }
        }
        if let Some(result) = self.hint_rx.as_ref().and_then(|r| r.try_recv().ok()) {
            self.hint_rx = None;
            match result {
                Ok(v) => self.hint_suggestions = Some(v),
                Err(e) => self.hint_suggestions_error = e,
            }
        }
        if self.job.is_none() && self.check_after_job {
            self.check_after_job = false;
            self.tools_rx = Some(request_json(&self.settings.python, "toolchain", ctx));
        }
    }

    fn export_apk(&mut self, ctx: &egui::Context, project: Option<String>) {
        let mut args = vec![
            "android".into(),
            "--jobs".into(),
            self.settings.jobs.max(2).to_string(),
        ];
        if let Some(root) = project {
            args.extend(["--project".into(), root, "--runtime".into()]);
        }
        for (flag, value) in [
            ("--android-sdk", &self.settings.android_sdk),
            ("--ndk", &self.settings.android_ndk),
            ("--sdk-source", &self.settings.android_runtime_source),
        ] {
            if !value.is_empty() {
                args.extend([flag.into(), value.clone()]);
            }
        }
        self.start(ctx, args);
    }

    fn run_card(&mut self, ui: &mut egui::Ui) {
        let phase = self.progress.phase;
        let color = match phase {
            job::Phase::Failed => theme::ERROR,
            job::Phase::Done => theme::SUCCESS,
            _ => theme::BORDER,
        };
        card(ui, color, |ui| {
            if let Some(j) = &mut self.job {
                ui.horizontal(|ui| {
                    ui.spinner();
                    ui.label(RichText::new(self.progress.describe()).strong().size(16.0));
                    ui.label(format!("{}s", j.started.elapsed().as_secs()));
                });
                ui.add(
                    egui::ProgressBar::new(self.progress.fraction())
                        .desired_height(8.0)
                        .fill(theme::ACCENT)
                        .animate(true),
                );
                if ui.button("Cancel").clicked() {
                    j.cancel();
                }
            } else if self.log.is_empty() {
                ui.heading("Bring your Xbox 360 project to PC and Android");
                ui.label("Choose your game on the left. Verify, prepare, recompile, then launch from Library.");
                ui.label("ReXGlue supplies PowerPC translation and the guest runtime.");
            } else {
                ui.label(RichText::new(self.progress.describe()).strong().size(18.0));
                if let Some(exe) = self.progress.exe.clone() {
                    ui.label(exe.display().to_string());
                    if ui.button("Show output folder").clicked()
                        && let Some(p) = exe.parent()
                    {
                        open_path(p);
                    }
                }
                if phase == job::Phase::Failed {
                    ui.label(
                        "Review the output below. Full compiler logs remain in the project folder.",
                    );
                }
            }
        });
    }

    fn log_view(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Output").strong());
            ui.label(format!("{} lines", self.log.len()));
            if ui.button("Copy").clicked() {
                ui.ctx().copy_text(self.log.join("\n"));
            }
            if ui
                .add_enabled(self.job.is_none(), egui::Button::new("Clear"))
                .clicked()
            {
                self.log.clear();
            }
            if ui.button("Save...").clicked()
                && let Some(p) = rfd::FileDialog::new()
                    .set_file_name("xbo360.log")
                    .save_file()
            {
                if let Err(e) = std::fs::write(p, self.log.join("\n")) {
                    self.log.push(format!("Error: {e}"));
                }
            }
        });
        egui::Frame::new()
            .fill(theme::LOG_BG)
            .stroke(Stroke::new(1.0, theme::BORDER))
            .corner_radius(10)
            .inner_margin(Margin::symmetric(12, 10))
            .show(ui, |ui| {
                ui.set_min_size(ui.available_size());
                let row = ui.text_style_height(&egui::TextStyle::Monospace);
                egui::ScrollArea::both()
                    .auto_shrink([false, false])
                    .stick_to_bottom(true)
                    .show_rows(ui, row, self.log.len(), |ui, range| {
                        for line in &self.log[range] {
                            let color = match job::classify(line) {
                                job::LineKind::Error => theme::ERROR,
                                job::LineKind::Warning => theme::WARNING,
                                job::LineKind::Success => theme::SUCCESS,
                                job::LineKind::Command => theme::ACCENT,
                                _ => theme::TEXT_WEAK,
                            };
                            ui.add(
                                egui::Label::new(RichText::new(line).monospace().color(color))
                                    .wrap_mode(egui::TextWrapMode::Extend),
                            );
                        }
                    });
            });
    }

    fn about(&mut self, ui: &mut egui::Ui) {
        ui.heading("Xbox360Recomp 0.3.1");
        ui.label("SwitchRecomp by MZ Labs — original interface foundation (Apache-2.0).");
        ui.label("Xbox 360 fork additions: katakishi0 · hosting: kuaan08.");
        ui.label("ReXGlue by Tom Clay and contributors, with Xenia and XenonRecomp research.");
        ui.label("Android runtime: AlanConstantino, Andrew Nakas, Buku313 and their contributors.");
        ui.hyperlink("https://github.com/kuaan08/xbo360");
        section(ui, "How it works");
        ui.label(
            "Game XEX → PowerPC analysis → C++ → native host executable or Android library + APK.",
        );
        ui.label("An Android APK contains code for its selected title. An arbitrary new ISO needs its own recompilation.");
        ui.label("Synthetic pipeline tests are separate from commercial-game compatibility.");
    }

    fn modals(&mut self, ctx: &egui::Context) {
        if let Some(root) = self.hint_project.clone() {
            let mut open = true;
            egui::Window::new("Function hints / Analysis errors")
                .open(&mut open).default_width(620.0).show(ctx, |ui| {
                    ui.label("Unresolved branches are not necessarily calls: a PowerPC b can jump inside an existing function.");
                    ui.colored_label(theme::WARNING, "Inspect the XEX disassembly first. Function sizes must be verified, never guessed from log addresses.");
                    let logfile = Path::new(&root).join("build.log");
                    match std::fs::read_to_string(logfile) {
                        Ok(log) => {
                            let errors = unresolved_calls(&log);
                            if errors.is_empty() { ui.label("No unresolved branch in the saved build log."); }
                            for (source, target) in errors {
                                ui.horizontal_wrapped(|ui| {
                                    ui.monospace(format!("{source} -> {target}"));
                                    if ui.button("Select target").clicked() {
                                        self.hint_address = target;
                                        self.hint_size.clear();
                                    }
                                });
                            }
                        }
                        Err(_) => { ui.label("Run Generate C++ first to create a build log."); }
                    }
                    ui.separator();
                    if ui.add_enabled(self.hint_rx.is_none(), egui::Button::new("Check verified hints for this XEX")).clicked() {
                        self.hint_suggestions = None;
                        self.hint_suggestions_error.clear();
                        self.hint_rx = Some(request_json_project(&self.settings.python, "suggest-hints", &root, ctx));
                    }
                    if self.hint_rx.is_some() { ui.spinner(); }
                    if !self.hint_suggestions_error.is_empty() {
                        ui.colored_label(theme::ERROR, &self.hint_suggestions_error);
                    }
                    if let Some(known) = self.hint_suggestions.clone() {
                        if known["matching_revision"] == true {
                            ui.label(format!("Exact executable match: {}", known["title"].as_str().unwrap_or("unknown")));
                            if let Some(hints) = known["hints"].as_array() {
                                for hint in hints {
                                    let address = hint["address"].as_str().unwrap_or("");
                                    let bytes = hint["size"].as_u64().unwrap_or(0);
                                    ui.horizontal_wrapped(|ui| {
                                        ui.monospace(format!("{address} / {bytes} bytes"));
                                        if ui.button("Use verified hint").clicked() {
                                            self.hint_address = address.to_string();
                                            self.hint_size = bytes.to_string();
                                            self.hint_parent.clear();
                                        }
                                    });
                                    if let Some(evidence) = hint["evidence"].as_str() {
                                        ui.label(evidence);
                                    }
                                }
                            }
                        } else {
                            ui.label("No known hints for this exact XEX checksum; enter verified sizes manually.");
                        }
                        ui.colored_label(theme::WARNING, "Hints still require explicit Save and do not guarantee game compatibility.");
                    }
                    ui.separator();
                    ui.label("Verified entrypoint address (0xXXXXXXXX)");
                    ui.text_edit_singleline(&mut self.hint_address);
                    ui.label("Verified function size (bytes, divisible by 4)");
                    ui.text_edit_singleline(&mut self.hint_size);
                    ui.label("Parent address for a discontiguous function chunk (optional)");
                    ui.text_edit_singleline(&mut self.hint_parent);
                    let parse_addr = |s: &str| s.strip_prefix("0x")
                        .filter(|v| v.len() == 8 && v.chars().all(|c| c.is_ascii_hexdigit()))
                        .and_then(|v| u32::from_str_radix(v, 16).ok())
                        .filter(|v| v % 4 == 0);
                    let address = parse_addr(self.hint_address.trim());
                    let size = self.hint_size.trim().parse::<u32>().ok()
                        .filter(|v| *v >= 4 && *v <= 1048576 && v % 4 == 0);
                    let parent = if self.hint_parent.trim().is_empty() { Some(None) }
                        else { parse_addr(self.hint_parent.trim()).map(Some) };
                    if ui.add_enabled(self.job.is_none() && address.is_some() && size.is_some() && parent.is_some(),
                                      egui::Button::new("Save verified boundary")).clicked() {
                        let mut args = vec!["function-hint".to_owned(), root.clone(),
                            "--address".into(), self.hint_address.clone(),
                            "--size".into(), size.unwrap().to_string()];
                        if let Some(Some(p)) = parent {
                            args.extend(["--parent".into(), format!("0x{p:08X}")]);
                        }
                        self.start(ctx, args);
                    }
                    ui.label("This saves a dedicated project TOML include. Original game files are never changed.");
                    ui.label("After saving, run Library > Generate C++; use Force only for diagnostics.");
                });
            if !open { self.hint_project = None; }
        }
        if self.show_setup {
            let mut open = true;
            egui::Window::new("Install required build tools?").open(&mut open).collapsible(false).default_width(570.0).show(ctx, |ui| {
                ui.label("The app can start official installers for missing prerequisites. Choose what to install; Windows may show installer and administrator dialogs.");
                if let Some(tools) = &self.tools {
                    let vs_ready = tools["visual_studio"].is_string();
                    ui.label(format!("Visual Studio C++: {}", if vs_ready {"detected"} else {"missing"}));
                    if let Some(list) = tools["tools"].as_array() { for t in list { ui.label(format!("{}: {}",t["name"].as_str().unwrap_or(""), t["version"].as_str().filter(|s|!s.is_empty()).unwrap_or("missing"))); } }
                }
                ui.add_enabled_ui(self.job.is_none(), |ui| {
                    if cfg!(windows) {
                        ui.horizontal_wrapped(|ui| { for (tool,label) in [("visual-studio","Visual Studio C++ + Clang"),("clang","LLVM/Clang"),("cmake","CMake"),("ninja","Ninja"),("java","Java 17"),("git","Git")] { if ui.button(format!("Install {label}")).clicked() { self.install_confirmation = Some(tool.into()); } } });
                        if ui.button("Install Android SDK / NDK + Java tools").clicked() { self.install_confirmation = Some("android-tools".into()); }
                    } else { ui.label("Linux: install Clang 20, CMake, Ninja, Git and JDK 17 using your system package manager."); }
                    if ui.button("Check again").clicked() {self.tools_rx=Some(request_json(&self.settings.python,"toolchain",ctx));}
                });
                ui.label("You can close this window and install later from Settings.");
            });
            self.show_setup = open;
        }
        if let Some(tool) = self.install_confirmation.clone() {
            egui::Window::new("Confirm installation").collapsible(false).show(ctx,|ui| {
                ui.label(format!("Install {tool}? This downloads tools and starts their installers. Android tools require accepting the Android SDK/NDK license at developer.android.com/studio/terms."));
                ui.horizontal(|ui| {
                    if ui.button("Install").clicked() {
                        self.install_confirmation=None;
                        if tool == "android-tools" {self.start(ctx,vec!["setup-android".into(),"--yes".into()]);}
                        else {self.start(ctx,vec!["install-tools".into(),tool,"--yes".into()]);}
                    }
                    if ui.button("Cancel").clicked() {self.install_confirmation=None;}
                });
            });
        }
        if self.show_settings {
            let mut open = true;
            egui::Window::new("Settings")
                .open(&mut open)
                .default_width(620.0)
                .show(ctx, |ui| {
                    egui::ScrollArea::vertical().show(ui, |ui| {
                        self.settings_ui(ui, ctx);
                        if ui.button("Install / detect prerequisites").clicked() {
                            self.show_setup = true;
                        }
                        section(ui, "Android APK export");
                        field(
                            ui,
                            "Android SDK (blank = detected/cache)",
                            &mut self.settings.android_sdk,
                            true,
                            false,
                        );
                        field(
                            ui,
                            "Android NDK r27c (blank = detected/cache)",
                            &mut self.settings.android_ndk,
                            true,
                            false,
                        );
                        field(
                            ui,
                            "Android ReXGlue source (optional)",
                            &mut self.settings.android_runtime_source,
                            true,
                            false,
                        );
                        if ui.button("Build Android menu APK").clicked() {
                            self.export_apk(ctx, None);
                        }
                    });
                });
            self.show_settings = open;
        }
        if self.update.is_some() || !self.update_error.is_empty() {
            let mut open = true;
            let info = self.update.clone();
            egui::Window::new("Updates").open(&mut open).show(ctx, |ui| {
                if let Some(v) = &info {
                    ui.label(if v["current"]==true {"You have the current version."} else {"A newer version is available."});
                    ui.label(v["version"].as_str().unwrap_or(""));
                    if let Some(url)=v["url"].as_str() {ui.hyperlink(url);}
                    if ui.add_enabled(v["current"]!=true && self.job.is_none(),egui::Button::new("Download verified update")).clicked() {self.start(ctx,vec!["update".into(),"--download".into()]);}
                    ui.label("The download is SHA-256 checked. Extract it and replace the portable app after closing it; settings are retained.");
                } else {ui.label(&self.update_error);}
            });
            if !open {
                self.update = None;
                self.update_error.clear();
            }
        }
        if let Some(root) = self.edit_project.clone() {
            let mut open = true;
            egui::Window::new("Game settings")
                .open(&mut open)
                .show(ctx, |ui| {
                    let path = Path::new(&root).join("launch-settings.json");
                    let id = egui::Id::new(format!("launch_{root}"));
                    let value = ctx
                        .data_mut(|d| d.get_temp::<String>(id))
                        .unwrap_or_else(|| {
                            std::fs::read_to_string(&path).unwrap_or_else(|_| "{}".into())
                        });
                    let config =
                        serde_json::from_str::<serde_json::Value>(&value).unwrap_or_default();
                    let mut renderer = config["renderer"].as_str().unwrap_or("any").to_string();
                    let mut fullscreen = config["fullscreen"].as_bool().unwrap_or(false);
                    egui::ComboBox::from_label("Graphics backend")
                        .selected_text(&renderer)
                        .show_ui(ui, |ui| {
                            for (value, label) in [
                                ("any", "Automatic"),
                                ("d3d12", "Direct3D 12"),
                                ("vulkan", "Vulkan"),
                            ] {
                                ui.selectable_value(&mut renderer, value.into(), label);
                            }
                        });
                    ui.checkbox(&mut fullscreen, "Start in fullscreen");
                    let serialized = serde_json::to_string_pretty(
                        &serde_json::json!({"renderer":renderer,"fullscreen":fullscreen}),
                    )
                    .unwrap_or_default();
                    ctx.data_mut(|d| d.insert_temp(id, serialized.clone()));
                    if ui.button("Save").clicked() {
                        if let Err(e) = std::fs::write(path, serialized) {
                            self.log.push(e.to_string());
                        } else {
                            self.edit_project = None;
                        }
                    }
                });
            if !open {
                self.edit_project = None;
            }
        }
    }
}

fn unresolved_calls(log: &str) -> Vec<(String, String)> {
    let mut found = Vec::new();
    for line in log.lines() {
        if !line.contains("target not in any function") { continue; }
        let Some((target, suffix)) = line.trim().split_once(" from ") else { continue; };
        let Some((source, _)) = suffix.split_once(':') else { continue; };
        let valid = |v: &str| v.len() == 10 && v.starts_with("0x")
            && v[2..].chars().all(|c| c.is_ascii_hexdigit());
        if valid(source) && valid(target) {
            let entry = (source.to_string(), target.to_string());
            if !found.contains(&entry) { found.push(entry); }
        }
    }
    found
}

#[cfg(test)]
mod analysis_ui_tests {
    use super::unresolved_calls;
    #[test]
    fn parses_original_unresolved_branch() {
        let log = "0x82C21240 from 0x82C22B14: b 0x82C21240 from 0x82C22B14 - target not in any function";
        assert_eq!(unresolved_calls(log), vec![("0x82C22B14".into(), "0x82C21240".into())]);
    }
}

fn request_json_project(
    python: &str,
    command: &str,
    project: &str,
    ctx: &egui::Context,
) -> Receiver<Result<serde_json::Value, String>> {
    let (tx, rx) = mpsc::channel();
    let python = python.to_string();
    let command = command.to_string();
    let project = project.to_string();
    let ctx = ctx.clone();
    std::thread::spawn(move || {
        let mut c = std::process::Command::new(python);
        c.arg(toolchain::home().join("xbo360.py")).arg(command).arg(project);
        toolchain::hide_console(&mut c);
        let result = c.output().map_err(|e| e.to_string()).and_then(|o| {
            if !o.status.success() {
                return Err(String::from_utf8_lossy(&o.stderr).to_string());
            }
            serde_json::from_slice(&o.stdout).map_err(|e| e.to_string())
        });
        let _ = tx.send(result);
        ctx.request_repaint();
    });
    rx
}

fn request_json(
    python: &str,
    command: &str,
    ctx: &egui::Context,
) -> Receiver<Result<serde_json::Value, String>> {
    let (tx, rx) = mpsc::channel();
    let python = python.to_string();
    let command = command.to_string();
    let ctx = ctx.clone();
    std::thread::spawn(move || {
        let mut c = std::process::Command::new(python);
        c.arg(toolchain::home().join("xbo360.py")).arg(command);
        toolchain::hide_console(&mut c);
        let result = c.output().map_err(|e| e.to_string()).and_then(|o| {
            if !o.status.success() {
                return Err(String::from_utf8_lossy(&o.stderr).to_string());
            }
            serde_json::from_slice(&o.stdout).map_err(|e| e.to_string())
        });
        let _ = tx.send(result);
        ctx.request_repaint();
    });
    rx
}

fn page_frame() -> egui::Frame {
    egui::Frame::new()
        .fill(theme::BG)
        .inner_margin(Margin::same(18))
}
fn card(ui: &mut egui::Ui, border: Color32, add: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::new()
        .fill(theme::CARD)
        .stroke(Stroke::new(1.0, border))
        .corner_radius(12)
        .inner_margin(Margin::same(16))
        .show(ui, add);
}
fn section(ui: &mut egui::Ui, label: &str) {
    ui.add_space(14.0);
    ui.label(RichText::new(label).strong().color(theme::TEXT));
    ui.add_space(4.0);
}
fn logo(ui: &mut egui::Ui, size: f32) {
    let (r, _) = ui.allocate_exact_size(egui::vec2(size, size), egui::Sense::hover());
    ui.painter().rect_filled(r, 6, theme::ACCENT);
    let c = r.center();
    let v = vec![
        c + egui::vec2(-3.0, -6.0),
        c + egui::vec2(6.0, 0.0),
        c + egui::vec2(-3.0, 6.0),
    ];
    ui.painter()
        .add(egui::Shape::convex_polygon(v, Color32::WHITE, Stroke::NONE));
}

fn field(ui: &mut egui::Ui, label: &str, value: &mut String, folder: bool, xex: bool) {
    ui.label(label);
    ui.horizontal(|ui| {
        ui.add(
            egui::TextEdit::singleline(value)
                .desired_width((ui.available_width() - 90.0).max(180.0)),
        );
        if ui.button("Browse...").clicked() {
            let dialog = rfd::FileDialog::new();
            let selected = if folder {
                dialog.pick_folder()
            } else if xex {
                dialog.add_filter("Game input", &["xex"]).pick_file()
            } else {
                dialog.pick_file()
            };
            if let Some(p) = selected {
                *value = p.to_string_lossy().into_owned();
            }
        }
    });
}

fn open_path(path: &Path) {
    let mut command = if cfg!(windows) {
        std::process::Command::new("explorer")
    } else {
        std::process::Command::new("xdg-open")
    };
    let _ = command.arg(path).spawn();
}

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Xbox 360 Recomp")
            .with_inner_size([1060.0, 800.0])
            .with_min_inner_size([1000.0, 640.0])
            .with_icon(theme::app_icon()),
        ..Default::default()
    };
    eframe::run_native(
        "Xbox360Recomp",
        options,
        Box::new(|cc| Ok(Box::new(App::new(cc)))),
    )
}
