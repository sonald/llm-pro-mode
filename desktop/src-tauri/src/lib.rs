use std::error::Error;
use std::fmt::{Display, Formatter};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::{env, io, thread, time::Duration};

use tauri::{App, AppHandle, Manager, WindowEvent};

struct DesktopServerState {
    child: Mutex<Option<Child>>,
}

impl DesktopServerState {
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    fn store(&self, child: Child) {
        *self.child.lock().expect("poisoned mutex") = Some(child);
    }

    fn kill(&self) {
        if let Some(mut child) = self.child.lock().expect("poisoned mutex").take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[derive(Debug)]
struct BackendStartupError(&'static str);

impl Display for BackendStartupError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl Error for BackendStartupError {}

fn preferred_python_command() -> String {
    if let Ok(cmd) = env::var("LLM_PRO_PYTHON") {
        return cmd;
    }

    if cfg!(target_os = "windows") {
        "python".to_string()
    } else {
        "python3".to_string()
    }
}

fn project_root() -> PathBuf {
    let build_time_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .map(Path::to_path_buf)
        .expect("failed to resolve project root");

    if build_time_root.exists() {
        return build_time_root;
    }

    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn pythonpath_with_root(root: &Path) -> String {
    let root_str = root.to_string_lossy().to_string();
    match env::var("PYTHONPATH") {
        Ok(existing) if !existing.is_empty() => {
            if cfg!(target_os = "windows") {
                format!("{};{}", root_str, existing)
            } else {
                format!("{}:{}", root_str, existing)
            }
        }
        _ => root_str,
    }
}

fn find_open_port() -> io::Result<u16> {
    TcpListener::bind(("127.0.0.1", 0)).map(|listener| listener.local_addr().unwrap().port())
}

fn wait_for_server(port: u16, timeout: Duration) -> bool {
    let attempts = (timeout.as_millis() / 200).max(1) as usize;
    eprintln!("[Desktop] Waiting for server on port {}...", port);
    for i in 0..attempts {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            eprintln!("[Desktop] Server ready on port {} after {} attempts", port, i + 1);
            // Give the server a bit more time to fully initialize routes
            thread::sleep(Duration::from_millis(500));
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }
    eprintln!("[Desktop] Server failed to start after {} attempts", attempts);
    false
}

fn spawn_backend(port: u16) -> io::Result<Child> {
    let python = preferred_python_command();
    let project_root = project_root();
    let pythonpath = pythonpath_with_root(&project_root);

    let mut command = Command::new(python);
    command
        .args([
            "-m",
            "llm_pro_mode.desktop",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONPATH", pythonpath)
        .current_dir(&project_root)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    command.spawn()
}

fn load_web_ui(app: &mut App) -> Result<(), Box<dyn Error>> {
    app.manage(DesktopServerState::new());

    let port = find_open_port()?;
    eprintln!("[Desktop] Selected port: {}", port);

    let child = spawn_backend(port)?;
    eprintln!("[Desktop] Backend process spawned");

    let state = app.state::<DesktopServerState>();
    state.store(child);

    if !wait_for_server(port, Duration::from_secs(15)) {
        state.kill();
        return Err(Box::new(BackendStartupError("Backend server failed to start in time")));
    }

    if let Some(window) = app.get_webview_window("main") {
        let target_url = format!("http://127.0.0.1:{}", port);
        eprintln!("[Desktop] Navigating to: {}", target_url);

        // Navigate using the Tauri API - more reliable than JS eval
        window
            .navigate(target_url.parse()?)
            .map_err(|e| {
                eprintln!("[Desktop] Navigation failed: {}", e);
                Box::new(e) as Box<dyn Error>
            })?;

        // Set desktop flag after navigation
        let script = format!("window.__LLM_PRO_DESKTOP__ = {{ port: {} }};", port);
        thread::sleep(Duration::from_millis(1000)); // Wait for page to load
        if let Err(e) = window.eval(&script) {
            eprintln!("[Desktop] Warning: Failed to set desktop flag: {}", e);
        }

        eprintln!("[Desktop] Navigation complete");
    } else {
        eprintln!("[Desktop] Error: Main window not found");
        return Err(Box::new(BackendStartupError("Main window not found")));
    }

    Ok(())
}

fn shutdown_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<DesktopServerState>() {
        state.kill();
    }
}

// macOS-specific commands for window activation and focus management
#[cfg(target_os = "macos")]
#[tauri::command]
fn force_activate(app: AppHandle) -> Result<(), String> {
    use tauri::ActivationPolicy;

    app.set_activation_policy(ActivationPolicy::Regular)
        .map_err(|e| e.to_string())?;

    unsafe {
        use cocoa::appkit::{NSApp, NSApplication};
        use cocoa::base::YES;
        NSApp().activateIgnoringOtherApps_(YES);
    }

    eprintln!("[Desktop] App forcefully activated");
    Ok(())
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn debug_focus_state() -> String {
    unsafe {
        use cocoa::appkit::NSApp;
        use cocoa::base::id;
        use objc::{msg_send, sel, sel_impl};

        let app: id = NSApp();
        let is_active: bool = msg_send![app, isActive];
        format!("active_app={}", is_active)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    // Register macOS-specific commands
    #[cfg(target_os = "macos")]
    {
        builder = builder.invoke_handler(tauri::generate_handler![force_activate, debug_focus_state]);
    }

    builder
        .setup(|app| {
            // macOS: Set activation policy but don't show/focus yet
            #[cfg(target_os = "macos")]
            {
                use tauri::ActivationPolicy;
                if let Err(e) = app.handle().set_activation_policy(ActivationPolicy::Regular) {
                    eprintln!("[Desktop] Warning: Failed to set activation policy: {}", e);
                } else {
                    eprintln!("[Desktop] macOS activation policy set to Regular");
                }
            }

            // Load web UI (navigation only, window stays hidden initially)
            load_web_ui(app)?;
            eprintln!("[Desktop] Web UI loaded, waiting for Ready event to show/focus");

            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                WindowEvent::CloseRequested { .. } => {
                    shutdown_backend(&window.app_handle());
                }
                _ => {}
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            use tauri::RunEvent;
            match event {
                RunEvent::Ready | RunEvent::Resumed => {
                    eprintln!("[Desktop] RunEvent::Ready - activating and showing window");

                    if let Some(window) = app_handle.get_webview_window("main") {
                        // Critical activation sequence for macOS:
                        // 1. Force activate the app (bring to front)
                        #[cfg(target_os = "macos")]
                        {
                            if let Err(e) = force_activate(app_handle.clone()) {
                                eprintln!("[Desktop] Warning: Failed to force activate: {}", e);
                            }
                        }

                        // 2. Show the window
                        if let Err(e) = window.show() {
                            eprintln!("[Desktop] Warning: Failed to show window: {}", e);
                        } else {
                            eprintln!("[Desktop] Window shown");
                        }

                        // 3. Set focus on the window
                        if let Err(e) = window.set_focus() {
                            eprintln!("[Desktop] Warning: Failed to set focus: {}", e);
                        } else {
                            eprintln!("[Desktop] Window focused");
                        }

                        // 4. Debug: Check activation state
                        #[cfg(target_os = "macos")]
                        {
                            let state = debug_focus_state();
                            eprintln!("[Desktop] Focus state: {}", state);
                        }
                    }
                }
                RunEvent::Exit | RunEvent::ExitRequested { .. } => {
                    shutdown_backend(app_handle);
                }
                _ => {}
            }
        });
}
