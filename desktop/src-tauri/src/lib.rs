//! Desktop shell: starts the bundled `clinic-server` sidecar (FastAPI +
//! SQLCipher), tells the React UI which port it listens on, and stops it when
//! the window closes.

use std::net::TcpListener;
use std::sync::Mutex;

use serde::Serialize;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const DEFAULT_PORT: u16 = 8000;

struct Server {
    port: u16,
    child: Mutex<Option<CommandChild>>,
    exiting: Mutex<bool>,
}

#[derive(Serialize)]
struct ServerInfo {
    port: u16,
}

#[tauri::command]
fn server_info(state: tauri::State<'_, Server>) -> ServerInfo {
    ServerInfo { port: state.port }
}

/// Port from settings.json if the clinic changed it, else 8000, else any free port.
fn pick_port() -> u16 {
    let preferred = std::env::var("CLINIC_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .or_else(read_settings_port)
        .unwrap_or(DEFAULT_PORT);
    if TcpListener::bind(("127.0.0.1", preferred)).is_ok() {
        return preferred;
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(preferred)
}

fn read_settings_port() -> Option<u16> {
    let home = std::env::var("CLINIC_HOME").ok().map(std::path::PathBuf::from).or_else(|| {
        if cfg!(target_os = "windows") {
            dirs::config_dir().map(|d| d.join("ClinicRecords"))
        } else if cfg!(target_os = "macos") {
            dirs::data_dir().map(|d| d.join("ClinicRecords"))
        } else {
            dirs::home_dir().map(|d| d.join(".clinic-records"))
        }
    })?;
    let text = std::fs::read_to_string(home.join("data").join("settings.json")).ok()?;
    let v: serde_json::Value = serde_json::from_str(&text).ok()?;
    v.get("port")?.as_u64().map(|p| p as u16)
}

fn spawn_server(app: &tauri::AppHandle, port: u16, attempt: u32) -> Result<(), Box<dyn std::error::Error>> {
    let pid = std::process::id().to_string();
    let port_s = port.to_string();
    let cmd = app
        .shell()
        .sidecar("clinic-server")?
        .args(["--port", port_s.as_str(), "--parent-pid", pid.as_str()]);
    let (mut rx, child) = cmd.spawn()?;
    *app.state::<Server>().child.lock().unwrap() = Some(child);
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stderr(line) | CommandEvent::Stdout(line) => {
                    eprintln!("[server] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Terminated(t) => {
                    eprintln!("[server] exited: {:?}", t.code);
                    let exiting = *handle.state::<Server>().exiting.lock().unwrap();
                    if !exiting && attempt < 5 {
                        // Restart the server if it stops while the window is open.
                        std::thread::sleep(std::time::Duration::from_millis(500));
                        if let Err(e) = spawn_server(&handle, port, attempt + 1) {
                            eprintln!("[server] restart failed: {e}");
                        }
                    }
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

pub fn run() {
    let port = pick_port();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(Server { port, child: Mutex::new(None), exiting: Mutex::new(false) })
        .invoke_handler(tauri::generate_handler![server_info])
        .setup(move |app| {
            spawn_server(app.handle(), port, 0)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Clinic Records");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let state = handle.state::<Server>();
            *state.exiting.lock().unwrap() = true;
            let child = state.child.lock().unwrap().take();
            if let Some(child) = child {
                let _ = child.kill();
            }
        }
    });
}
