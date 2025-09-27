use std::error::Error;
use std::fmt::{Display, Formatter};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::{env, io, thread, time::Duration};

use tauri::{plugin::Builder as PluginBuilder, App, AppHandle, Manager, RunEvent, Url, WindowEvent, Wry};

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
    for _ in 0..attempts {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }
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
    let child = spawn_backend(port)?;
    let state = app.state::<DesktopServerState>();
    state.store(child);

    if !wait_for_server(port, Duration::from_secs(10)) {
        state.kill();
        return Err(Box::new(BackendStartupError("Backend server failed to start in time")));
    }

    if let Some(window) = app.get_webview_window("main") {
        let target_url = Url::parse(&format!("http://127.0.0.1:{}", port))?;
        window
            .navigate(target_url)
            .map_err(|e| Box::new(e) as Box<dyn Error>)?;

        let script = format!("window.__LLM_PRO_DESKTOP__ = {{ port: {} }};", port);
        window
            .eval(&script)
            .map_err(|e| Box::new(e) as Box<dyn Error>)?;
    }

    Ok(())
}

fn shutdown_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<DesktopServerState>() {
        state.kill();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            PluginBuilder::<Wry>::new("desktop-navigation")
                .on_navigation(|_, url| {
                    match url.scheme() {
                        "http" | "https" | "ws" | "wss" => match url.host_str() {
                            Some("127.0.0.1") | Some("localhost") => true,
                            _ => false,
                        },
                        _ => true,
                    }
                })
                .build(),
        )
        .setup(|app| {
            load_web_ui(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                shutdown_backend(&window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                shutdown_backend(app_handle);
            }
        });
}
