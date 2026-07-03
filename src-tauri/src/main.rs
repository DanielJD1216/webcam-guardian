// webcam-guardian Tauri shell
//
// Spawns the existing Python guardian as a child process; reads
// events.jsonl and config.yaml via filesystem watchers; exposes commands
// to the UI for start/stop/settings/log.

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use notify::{Event, EventKind, RecursiveMode, Watcher};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::time::{sleep, Duration};

#[derive(Default)]
struct GuardianState {
    child: Arc<Mutex<Option<Child>>>,
    events_path: Arc<Mutex<PathBuf>>,
    log_tail: Arc<Mutex<Vec<LogLine>>>,
    running: Arc<Mutex<bool>>,
}

#[derive(Clone, Serialize, Deserialize, Debug)]
struct LogLine {
    ts: DateTime<Utc>,
    event_type: String,
    payload: serde_json::Value,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct Status {
    running: bool,
    pid: Option<u32>,
    config_path: PathBuf,
    events_path: PathBuf,
    log_lines: Vec<LogLine>,
}

fn app_paths() -> (PathBuf, PathBuf) {
    let cwd = std::env::current_dir().unwrap_or(PathBuf::from("."));
    let config = cwd.join("config.yaml");
    let events = cwd.join("events.jsonl");
    (config, events)
}

#[tauri::command]
async fn status(state: State<'_, GuardianState>) -> Result<Status, String> {
    let (config_path, events_path) = app_paths();
    let running = *state.running.lock().await;
    let pid = {
        let guard = state.child.lock().await;
        guard.as_ref().and_then(|c| c.id())
    };
    let log_lines = state.log_tail.lock().await.clone();
    Ok(Status { running, pid, config_path, events_path, log_lines })
}

#[tauri::command]
async fn read_config(state: State<'_, GuardianState>) -> Result<String, String> {
    let (config_path, _) = app_paths();
    tokio::fs::read_to_string(&config_path)
        .await
        .map_err(|e| format!("read {}: {}", config_path.display(), e))
}

#[tauri::command]
async fn write_config(contents: String, state: State<'_, GuardianState>) -> Result<(), String> {
    let (config_path, _) = app_paths();
    tokio::fs::write(&config_path, contents)
        .await
        .map_err(|e| format!("write {}: {}", config_path.display(), e))
}

#[tauri::command]
async fn start(app: AppHandle, state: State<'_, GuardianState>) -> Result<u32, String> {
    {
        let mut running = state.running.lock().await;
        if *running { return Err("already running".into()); }
    }

    let venv_python = std::env::current_dir()
        .unwrap_or(PathBuf::from("."))
        .join(".venv")
        .join("bin")
        .join("python");
    let python = if venv_python.exists() { venv_python } else {
        std::env::current_dir().unwrap_or(PathBuf::from("."))
            .join(".venv-sys").join("bin").join("python3")
    };

    let mut cmd = Command::new(&python);
    cmd.arg("-m").arg("guardian")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = cmd.spawn().map_err(|e| format!("spawn python: {}", e))?;
    let pid = child.id().unwrap_or(0);

    let mut guard = state.child.lock().await;
    *guard = Some(child);
    drop(guard);

    *state.running.lock().await = true;
    app.emit("guardian:started", pid).ok();
    Ok(pid)
}

#[tauri::command]
async fn stop(app: AppHandle, state: State<'_, GuardianState>) -> Result<(), String> {
    let mut guard = state.child.lock().await;
    if let Some(mut child) = guard.take() {
        let _ = child.start_kill();
        let _ = child.wait().await;
    }
    drop(guard);
    *state.running.lock().await = false;
    app.emit("guardian:stopped", ()).ok();
    Ok(())
}

#[tauri::command]
async fn clear_log(state: State<'_, GuardianState>) -> Result<(), String> {
    state.log_tail.lock().await.clear();
    Ok(())
}

fn parse_event_line(line: &str) -> Option<LogLine> {
    let v: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let ts_str = v.get("ts").and_then(|x| x.as_str()).unwrap_or("");
    let ts: DateTime<Utc> = DateTime::parse_from_rfc3339(ts_str)
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(|_| Utc::now());
    let event_type = v.get("type").and_then(|x| x.as_str()).unwrap_or("").to_string();
    Some(LogLine { ts, event_type, payload: v })
}

async fn tail_events(app: AppHandle, events_path: PathBuf, state: Arc<GuardianState>) {
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<()>();
    let watcher_path = events_path.clone();
    let _ = std::fs::File::create(&watcher_path).ok();
    tokio::task::spawn_blocking(move || {
        let mut watcher = match notify::recommended_watcher(move |res: notify::Result<Event>| {
            if let Ok(ev) = res {
                if matches!(ev.kind, EventKind::Modify(_) | EventKind::Create(_)) {
                    let _ = tx.send(());
                }
            }
        }) {
            Ok(w) => w,
            Err(_) => return,
        };
        let _ = watcher.watch(&watcher_path, RecursiveMode::NonRecursive);
        loop { std::thread::park_timeout(Duration::from_secs(60)); }
    });

    while rx.recv().await.is_some() {
        let contents = match tokio::fs::read_to_string(&events_path).await {
            Ok(s) => s,
            Err(_) => continue,
        };
        let new_lines: Vec<LogLine> = contents
            .lines()
            .filter_map(parse_event_line)
            .collect();
        if new_lines.is_empty() { continue; }
        let mut log = state.log_tail.lock().await;
        *log = new_lines;
        drop(log);
        app.emit("guardian:events", &*state.log_tail.lock().await).ok();
    }
}

#[tokio::main]
async fn main() {
    let state = GuardianState::default();
    let (config_path, events_path) = app_paths();
    *state.events_path.lock().await = events_path.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            status, start, stop, read_config, write_config, clear_log
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let state_handle: State<GuardianState> = handle.state();
            let arc_state = GuardianState {
                child: state_handle.child.clone(),
                events_path: state_handle.events_path.clone(),
                log_tail: state_handle.log_tail.clone(),
                running: state_handle.running.clone(),
            };
            let events_path = std::path::Path::new(".")
                .join("events.jsonl")
                .canonicalize()
                .unwrap_or_else(|_| std::path::PathBuf::from("./events.jsonl"));
            tokio::spawn(tail_events(handle.clone(), events_path, Arc::new(arc_state)));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
    let _ = config_path;
    sleep(Duration::from_millis(1)).await;
}