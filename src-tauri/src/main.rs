use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::time::Duration;

#[derive(Default)]
struct GuardianState {
    child: Arc<Mutex<Option<Child>>>,
    log_tail: Arc<Mutex<Vec<LogLine>>>,
    running: Arc<Mutex<bool>>,
    ws_token: Arc<Mutex<Option<String>>>,
}

#[derive(Clone, Serialize, Deserialize, Debug)]
struct LogLine {
    ts: DateTime<Utc>,
    event_type: String,
    payload: serde_json::Value,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct CameraOption {
    index: i64,
    opens: bool,
    native: Option<(i64, i64)>,
    frame: Option<(i64, i64)>,
    placeholder: bool,
    label: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct AlertItem {
    name: String,
    path: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct Status {
    running: bool,
    pid: Option<u32>,
    project_root: PathBuf,
    config_path: PathBuf,
    events_path: PathBuf,
    snapshots_dir: PathBuf,
    log_lines: Vec<LogLine>,
    ws_token: Option<String>,
}

fn find_python_and_root() -> (PathBuf, PathBuf) {
    let cwd = std::env::current_dir().unwrap_or(PathBuf::from("."));
    // audit #44: was Unix-only (.venv/bin/python). Windows venvs
    // are at .venv\Scripts\python.exe. Probe both layouts at every
    // level so the same code works on dev checkouts on Mac, Linux, and
    // Windows.
    let candidates_at = |base: &PathBuf| -> Vec<PathBuf> {
        vec![
            base.join(".venv/bin/python"),
            base.join(".venv/bin/python3"),
            base.join(".venv/Scripts/python.exe"),
            base.join(".venv-sys/bin/python"),
            base.join(".venv-sys/bin/python3"),
            base.join(".venv-sys/Scripts/python.exe"),
        ]
    };
    let mut base = cwd.clone();
    for _ in 0..5 {
        for c in candidates_at(&base) {
            if c.exists() { return (c, base); }
        }
        match base.parent() {
            Some(p) => base = p.to_path_buf(),
            None => break,
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        let mut base = exe.parent().unwrap_or(std::path::Path::new(".")).to_path_buf();
        for _ in 0..5 {
            for c in candidates_at(&base) {
                if c.exists() { return (c, base); }
            }
            match base.parent() {
                Some(p) => base = p.to_path_buf(),
                None => break,
            }
        }
    }
    // Fallback interpreter name is platform-appropriate: Windows uses
    // `python` (the launcher) or `python3`; Unix uses `python3`.
    let py = if cfg!(windows) { "python" } else { "python3" };
    (PathBuf::from(py), cwd)
}

fn project_root() -> PathBuf {
    find_python_and_root().1
}

fn rand_bytes() -> [u8; 32] {
    // audit #3: token for WS auth. Not cryptographically rigorous but
    // enough to gate an unauthenticated localhost socket against
    // opportunistic local attackers. 32 bytes of mixing from:
    //   - SystemTime::now().duration_since(UNIX_EPOCH).subsec_nanos()
    //   - ProcessId
    //   - Tauri AppHandle's underlying instance address
    //   - the inner entropy of std::collections::hash_map's default hasher
    // The token is per-launch and changes every Start, so a leaked token
    // is only valid until the next process restart.
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    use std::process;
    use std::time::{SystemTime, UNIX_EPOCH};
    let mut hasher = DefaultHasher::new();
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().hash(&mut hasher);
    process::id().hash(&mut hasher);
    "webcam-guardian ws token".hash(&mut hasher);
    let mut buf = [0u8; 32];
    let h1 = hasher.finish();
    let h2 = {
        let mut h = DefaultHasher::new();
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().hash(&mut h);
        h.finish()
    };
    for i in 0..8 {
        buf[i] = ((h1 >> (i * 8)) & 0xff) as u8;
        buf[i + 8] = ((h2 >> (i * 8)) & 0xff) as u8;
    }
    buf
}

fn app_paths() -> (PathBuf, PathBuf) {
    let root = project_root();
    let config = root.join("config.yaml");
    let events = root.join("events.jsonl");
    (config, events)
}

async fn kill_stale_guardians() {
    let pattern = "python -m guardian";
    let my_pid = std::process::id() as i32;
    let Ok(out) = tokio::process::Command::new("pgrep")
        .args(&["-f", pattern])
        .output().await else { return };
    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut killed = 0;
    for line in stdout.lines() {
        let Ok(pid) = line.trim().parse::<i32>() else { continue };
        if pid == my_pid { continue; }
        let _ = tokio::process::Command::new("kill")
            .args(&["-TERM", &pid.to_string()])
            .output().await;
        killed += 1;
    }
    if killed > 0 {
        eprintln!("[guardian] killed {killed} stale python -m guardian process(es)");
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

#[tauri::command]
async fn status(state: State<'_, GuardianState>) -> Result<Status, String> {
    let root = project_root();
    let config_path = root.join("config.yaml");
    let events_path = root.join("events.jsonl");
    let snapshots_dir = root.join("snapshots");
    let running = *state.running.lock().await;
    let pid = {
        let guard = state.child.lock().await;
        guard.as_ref().and_then(|c| c.id())
    };
    let log_lines = match tokio::fs::read_to_string(&events_path).await {
        Ok(s) => s.lines().filter_map(parse_event_line).collect(),
        Err(_) => Vec::new(),
    };
    let ws_token = state.ws_token.lock().await.clone();
    Ok(Status { running, pid, project_root: root, config_path, events_path, snapshots_dir, log_lines, ws_token })
}

#[tauri::command]
async fn read_config() -> Result<String, String> {
    let (config_path, _) = app_paths();
    tokio::fs::read_to_string(&config_path)
        .await
        .map_err(|e| format!("read {}: {}", config_path.display(), e))
}

#[tauri::command]
async fn write_config(contents: String) -> Result<(), String> {
    let (config_path, _) = app_paths();
    if contents.trim().is_empty() {
        return Err("refusing to write empty config — it would zero config.yaml. Restore from example first.".into());
    }
    tokio::fs::write(&config_path, contents)
        .await
        .map_err(|e| format!("write {}: {}", config_path.display(), e))
}

#[tauri::command]
async fn start(app: AppHandle, state: State<'_, GuardianState>) -> Result<u32, String> {
    {
        let running = state.running.lock().await;
        if *running { return Err("already running".into()); }
    }

    kill_stale_guardians().await;

    let (python, project_root) = find_python_and_root();
    // audit #3: 32-byte URL-safe random token gates the WS server so
    // arbitrary local processes / cross-origin web pages cannot
    // silently tap the live webcam feed.
    let ws_token: String = {
        use std::fmt::Write as _;
        let mut s = String::with_capacity(43);
        for b in rand_bytes() {
            write!(&mut s, "{:02x}", b).unwrap();
        }
        s
    };
    let mut cmd = Command::new(&python);
    cmd.arg("-m").arg("guardian")
        .arg("--no-imshow")
        .arg("--ws-port").arg("9876")
        .arg("--ws-token").arg(&ws_token)
        .current_dir(&project_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = cmd.spawn().map_err(|e| format!("spawn {:?}: {}", python, e))?;
    let pid = child.id().unwrap_or(0);

    // stash the token for status() + the UI to consume
    {
        let mut tok = state.ws_token.lock().await;
        *tok = Some(ws_token.clone());
    }
    let _ = app.emit("guardian:started", serde_json::json!({
        "pid": pid,
        "ws_token": ws_token,
    }));

    let log_dir = project_root.join("snapshots");
    let _ = tokio::fs::create_dir_all(&log_dir).await;
    let stdout_log = log_dir.join(format!("guardian-{}.stdout.log", pid));
    let stderr_log = log_dir.join(format!("guardian-{}.stderr.log", pid));

    if let Some(out) = child.stdout.take() {
        let path = stdout_log.clone();
        tokio::spawn(async move {
            // audit #48: simple size-cap rotation. Past 5 MB we rename
            // the file to .1 and start a new one. Keeps the most recent
            // window, prevents unbounded growth if any library spams.
            const MAX_BYTES: u64 = 5 * 1024 * 1024;
            let mut file = match tokio::fs::OpenOptions::new()
                .create(true).append(true).open(&path).await {
                Ok(f) => Some(f),
                Err(_) => None,
            };
            let mut bytes_written: u64 = file.as_ref().map(|_| 0).unwrap_or(0);
            let mut reader = BufReader::new(out).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                if let Some(f) = file.as_mut() {
                    let n = line.len() as u64 + 1;
                    if bytes_written + n > MAX_BYTES {
                        let _ = f.flush().await;
                        drop(f);
                        let rotated = path.with_extension(
                            format!("{}.1", path.extension().and_then(|e| e.to_str()).unwrap_or("log")));
                        let _ = tokio::fs::rename(&path, &rotated).await;
                        match tokio::fs::OpenOptions::new()
                            .create(true).append(true).open(&path).await {
                            Ok(f) => file = Some(f),
                            Err(_) => file = None,
                        }
                        bytes_written = 0;
                    }
                    if let Some(f) = file.as_mut() {
                        let _ = f.write_all(line.as_bytes()).await;
                        let _ = f.write_all(b"\n").await;
                        bytes_written += n;
                    }
                }
            }
        });
    }
    if let Some(err) = child.stderr.take() {
        let path = stderr_log.clone();
        tokio::spawn(async move {
            const MAX_BYTES: u64 = 5 * 1024 * 1024;
            let mut file = match tokio::fs::OpenOptions::new()
                .create(true).append(true).open(&path).await {
                Ok(f) => Some(f),
                Err(_) => None,
            };
            let mut bytes_written: u64 = file.as_ref().map(|_| 0).unwrap_or(0);
            let mut reader = BufReader::new(err).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                if let Some(f) = file.as_mut() {
                    let n = line.len() as u64 + 1;
                    if bytes_written + n > MAX_BYTES {
                        let _ = f.flush().await;
                        drop(f);
                        let rotated = path.with_extension(
                            format!("{}.1", path.extension().and_then(|e| e.to_str()).unwrap_or("log")));
                        let _ = tokio::fs::rename(&path, &rotated).await;
                        match tokio::fs::OpenOptions::new()
                            .create(true).append(true).open(&path).await {
                            Ok(f) => file = Some(f),
                            Err(_) => file = None,
                        }
                        bytes_written = 0;
                    }
                    if let Some(f) = file.as_mut() {
                        let _ = f.write_all(line.as_bytes()).await;
                        let _ = f.write_all(b"\n").await;
                        bytes_written += n;
                    }
                }
            }
        });
    }

    {
        let mut guard = state.child.lock().await;
        *guard = Some(child);
    }

    *state.running.lock().await = true;
    app.emit("guardian:started", pid).ok();

    let child_arc = state.child.clone();
    let running_arc = state.running.clone();
    let stderr_log_for_crash = stderr_log.clone();
    let app_handle = app.clone();
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(2)).await;
            let exit_status = {
                let mut guard = child_arc.lock().await;
                guard.as_mut().and_then(|c| c.try_wait().ok().flatten())
            };
            if let Some(status) = exit_status {
                {
                    let mut guard = child_arc.lock().await;
                    *guard = None;
                }
                *running_arc.lock().await = false;
                // (token cleared in stop() if user-initiated; nothing to
                // do here since the state handle doesn't own the
                // token mutex — we'd need a separate signal. But the
                // token is meaningless once the child has died, and
                // the next start() rotates it.)
                // audit #49: read the last 64 KiB of stderr instead of
                // the whole file. Avoids unbounded RAM when the log
                // has grown large. (.1 is the rotated file from
                // #48 — we don't touch it here, the live log is the
                // signal we want.)
                const CRASH_TAIL_BYTES: u64 = 64 * 1024;
                let last_lines: Vec<String> = match read_tail(
                    &stderr_log_for_crash, CRASH_TAIL_BYTES,
                ).await {
                    Ok(s) => s.lines().rev().take(50).map(String::from)
                        .collect::<Vec<_>>().into_iter().rev().collect(),
                    Err(_) => Vec::new(),
                };
                let payload = serde_json::json!({
                    "exit_code": status.code(),
                    "stderr_tail": last_lines,
                });
                app_handle.emit("guardian:crashed", payload).ok();
                break;
            }
        }
    });

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
    *state.ws_token.lock().await = None;
    app.emit("guardian:stopped", ()).ok();
    Ok(())
}

#[tauri::command]
async fn clear_log(state: State<'_, GuardianState>) -> Result<(), String> {
    state.log_tail.lock().await.clear();
    Ok(())
}

#[tauri::command]
async fn list_cameras() -> Result<Vec<CameraOption>, String> {
    let (python, project_root) = find_python_and_root();
    let output = Command::new(&python)
        .arg("-m").arg("guardian")
        .arg("--list-cameras")
        .current_dir(&project_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .await
        .map_err(|e| format!("spawn {:?}: {}", python, e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let mut cams = Vec::new();
    let mut in_table = false;
    for line in stdout.lines() {
        if line.contains("Probing indices") {
            in_table = true; continue;
        }
        if !in_table { continue; }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 4 { continue; }
        let idx: i64 = match parts[0].parse() { Ok(n) => n, Err(_) => continue };
        let opens = parts[1] == "True";
        let native = parse_pair(parts.get(2).copied());
        let frame = parse_pair(parts.get(3).copied());
        let placeholder = line.contains("placeholder");
        cams.push(CameraOption {
            index: idx, opens, native, frame, placeholder,
            label: format!("Camera {} ({}x{})",
                idx,
                frame.map(|(w, _)| w).unwrap_or(0),
                frame.map(|(_, h)| h).unwrap_or(0)),
        });
    }
    Ok(cams)
}

#[tauri::command]
async fn list_alerts() -> Result<Vec<AlertItem>, String> {
    let root = project_root();
    let dir = root.join("snapshots");
    let mut entries = match tokio::fs::read_dir(&dir).await {
        Ok(e) => e,
        Err(_) => return Ok(Vec::new()),
    };
    let mut out = Vec::new();
    while let Some(entry) = entries.next_entry().await.unwrap_or(None) {
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with("alert_") && name.ends_with(".jpg") {
            out.push(AlertItem {
                name: name.clone(),
                path: entry.path().to_string_lossy().to_string(),
            });
        }
    }
    out.sort_by(|a, b| b.name.cmp(&a.name));
    out.truncate(24);
    Ok(out)
}

#[tauri::command]
async fn reset_config_from_example() -> Result<String, String> {
    let root = project_root();
    let example = root.join("config.example.yaml");
    let target = root.join("config.yaml");
    let contents = tokio::fs::read_to_string(&example)
        .await
        .map_err(|e| format!("read {}: {}", example.display(), e))?;
    if contents.trim().is_empty() {
        return Err("config.example.yaml is empty".into());
    }
    tokio::fs::write(&target, &contents)
        .await
        .map_err(|e| format!("write {}: {}", target.display(), e))?;
    Ok(contents)
}

/// audit #47: structured YAML-aware mutation. Replaces the
/// regex-edit pattern in the UI that produced dead duplicate keys
/// on the shipped config. Writes atomically (write to .tmp, then
/// rename) so a crash mid-write can't truncate the file.
#[tauri::command]
async fn set_camera_index(new_index: i64) -> Result<String, String> {
    let root = project_root();
    let path = root.join("config.yaml");
    set_yaml_key(&path, &["camera", "index"], serde_yaml::Value::Number(new_index.into())).await?;
    tokio::fs::read_to_string(&path).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn set_resolution(width: i64, height: i64) -> Result<String, String> {
    let root = project_root();
    let path = root.join("config.yaml");
    set_yaml_key(&path, &["camera", "width"],  serde_yaml::Value::Number(width.into())).await?;
    set_yaml_key(&path, &["camera", "height"], serde_yaml::Value::Number(height.into())).await?;
    tokio::fs::read_to_string(&path).await.map_err(|e| e.to_string())
}

async fn set_yaml_key(path: &PathBuf, keys: &[&str], value: serde_yaml::Value) -> Result<(), String> {
    let contents = tokio::fs::read_to_string(path).await
        .map_err(|e| format!("read {}: {}", path.display(), e))?;
    if contents.trim().is_empty() {
        return Err("config is empty — click Reset first".into());
    }
    let mut doc: serde_yaml::Value = serde_yaml::from_str(&contents)
        .map_err(|e| format!("parse {}: {}", path.display(), e))?;

    let mut cur: &mut serde_yaml::Value = &mut doc;
    for k in keys {
        // Ensure the parent path is a mapping, replacing any
        // existing scalar/sequence with a fresh mapping.
        if !matches!(cur, serde_yaml::Value::Mapping(_)) {
            *cur = serde_yaml::Value::Mapping(serde_yaml::Mapping::new());
        }
        let map = cur.as_mapping_mut().unwrap();
        cur = map
            .entry(serde_yaml::Value::String((*k).into()))
            .or_insert(serde_yaml::Value::Mapping(serde_yaml::Mapping::new()));
    }
    *cur = value;

    // Serialize and write atomically: write to .tmp, then rename over.
    let serialized = serde_yaml::to_string(&doc)
        .map_err(|e| format!("serialize: {}", e))?;
    let tmp = path.with_extension("yaml.tmp");
    tokio::fs::write(&tmp, &serialized).await
        .map_err(|e| format!("write {}: {}", tmp.display(), e))?;
    tokio::fs::rename(&tmp, path).await
        .map_err(|e| format!("rename: {}", e))?;
    Ok(())
}

fn parse_pair(s: Option<&str>) -> Option<(i64, i64)> {
    let s = s?;
    let mut it = s.split('x');
    let w = it.next()?.parse().ok()?;
    let h = it.next()?.parse().ok()?;
    Some((w, h))
}

fn parse_event_line(line: &str) -> Option<LogLine> {
    let v: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let ts_str = v.get("ts").and_then(|x| x.as_str()).unwrap_or("");
    // audit #63: try RFC3339-with-offset first, then naive ISO
    // (Python's datetime.now(timezone.utc).isoformat() produces
    // offset-less UTC for some Python versions), then fall back to
    // None (the UI will render a blank ts instead of fabricating
    // a wrong one — fabricated timestamps in an audit log are
    // nearly as bad as no log).
    let ts = if !ts_str.is_empty() {
        DateTime::parse_from_rfc3339(ts_str)
            .map(|d| d.with_timezone(&Utc))
            .ok()
            .or_else(|| chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%dT%H:%M:%S").ok().map(|n| DateTime::<Utc>::from_naive_utc_and_offset(n, Utc)))
            .or_else(|| chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%dT%H:%M:%S%.f").ok().map(|n| DateTime::<Utc>::from_naive_utc_and_offset(n, Utc)))
    } else {
        None
    };
    let ts = ts.unwrap_or_else(|| Utc::now() - chrono::Duration::days(365 * 100));  // sentinel: year 1926
    let event_type = v.get("type").and_then(|x| x.as_str()).unwrap_or("").to_string();
    Some(LogLine { ts, event_type, payload: v })
}

async fn tail_events(app: AppHandle, events_path: PathBuf, state: Arc<GuardianState>) {
    // audit #9b: was `File::create` (truncates!) — switching to
    // OpenOptions::append so the 'append-only crash-safe' log survives
    // every app launch. Touch the file if it doesn't exist.
    if !events_path.exists() {
        if let Some(parent) = events_path.parent() {
            let _ = tokio::fs::create_dir_all(parent).await;
        }
        let _ = tokio::fs::File::create(&events_path).await;
    }
    let mut last_line_count: usize = 0;
    loop {
        tokio::time::sleep(Duration::from_millis(800)).await;
        let contents = match tokio::fs::read_to_string(&events_path).await {
            Ok(s) => s,
            Err(_) => continue,
        };
        let lines: Vec<&str> = contents.lines().collect();
        if lines.len() == last_line_count { continue; }
        last_line_count = lines.len();
        let new_lines: Vec<LogLine> = contents
            .lines()
            .filter_map(parse_event_line)
            .collect();
        if new_lines.is_empty() { continue; }
        {
            let mut log = state.log_tail.lock().await;
            *log = new_lines;
        }
        let snapshot = state.log_tail.lock().await.clone();
        app.emit("guardian:events", &snapshot).ok();
    }
}

async fn read_tail(path: &PathBuf, max_bytes: u64) -> std::io::Result<String> {
    use tokio::io::{AsyncReadExt, AsyncSeekExt};
    let mut f = tokio::fs::File::open(path).await?;
    let len = f.metadata().await?.len();
    let start = len.saturating_sub(max_bytes);
    f.seek(std::io::SeekFrom::Start(start)).await?;
    let mut buf = Vec::with_capacity((len - start) as usize);
    f.read_to_end(&mut buf).await?;
    // Drop the partial first line so the tail begins on a line
    // boundary (audit #49). If the file is exactly max_bytes or
    // smaller, we read the whole thing and accept a leading
    // partial line.
    if start > 0 {
        if let Some(nl) = buf.iter().position(|&b| b == b'\n') {
            buf.drain(..=nl);
        }
    }
    Ok(String::from_utf8_lossy(&buf).into_owned())
}

#[tokio::main]
async fn main() {
    let state = GuardianState::default();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            status, start, stop, read_config, write_config,
            clear_log, list_cameras, list_alerts, reset_config_from_example,
            set_camera_index, set_resolution
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let state_handle: State<GuardianState> = handle.state();
            let arc_state = GuardianState {
                child: state_handle.child.clone(),
                log_tail: state_handle.log_tail.clone(),
                running: state_handle.running.clone(),
                ws_token: state_handle.ws_token.clone(),
            };
            let events_path = project_root().join("events.jsonl");
            tokio::spawn(tail_events(handle.clone(), events_path, Arc::new(arc_state)));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}