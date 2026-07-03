const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const { convertFileSrc } = window.__TAURI__.core;

const $ = (id) => document.getElementById(id);

const els = {
  btnStart: $("btn-start"),
  btnStop: $("btn-stop"),
  pill: $("status-pill"),
  cameraSelect: $("camera-select"),
  btnRescan: $("btn-rescan-cameras"),
  previewImg: $("preview-img"),
  previewEmpty: $("preview-empty"),
  metricPid: $("metric-pid"),
  metricConfig: $("metric-config"),
  configEditor: $("config-editor"),
  btnReload: $("btn-reload-config"),
  btnSave: $("btn-save-config"),
  logFilters: $("log-filters"),
  logView: $("log-view"),
  btnClear: $("btn-clear-log"),
  alertGallery: $("alert-gallery"),
  btnRefreshAlerts: $("btn-refresh-alerts"),
  footerMsg: $("footer-msg"),
};

let currentLogFilter = "all";
let currentConfig = "";
let currentConfigPath = "";

// ---------- status / start / stop ----------

function setStatus(state, label) {
  els.pill.classList.remove("pill-stopped", "pill-running", "pill-error");
  els.pill.classList.add(`pill-${state}`);
  els.pill.textContent = label;
  els.btnStart.disabled = state === "running";
  els.btnStop.disabled = state !== "running";
}

async function refreshStatus() {
  try {
    const s = await invoke("status");
    currentConfigPath = s.config_path;
    if (s.running) {
      setStatus("running", `running · pid ${s.pid ?? "?"}`);
      els.metricPid.textContent = `pid: ${s.pid ?? "—"}`;
    } else {
      setStatus("stopped", "stopped");
      els.metricPid.textContent = "pid: —";
    }
    els.metricConfig.textContent = `config: ${s.config_path}`;
    renderLog(s.log_lines || []);
  } catch (e) {
    setStatus("error", "error");
    els.footerMsg.textContent = `status: ${e}`;
  }
}

async function startGuardian() {
  setStatus("error", "starting…");
  try {
    const pid = await invoke("start");
    els.footerMsg.textContent = `started · pid ${pid}`;
    refreshStatus();
  } catch (e) {
    setStatus("error", "start failed");
    els.footerMsg.textContent = `start: ${e}`;
  }
}

async function stopGuardian() {
  try {
    await invoke("stop");
    els.footerMsg.textContent = "stopped";
    refreshStatus();
  } catch (e) {
    els.footerMsg.textContent = `stop: ${e}`;
  }
}

// ---------- config ----------

async function reloadConfig() {
  try {
    currentConfig = await invoke("read_config");
    els.configEditor.value = currentConfig;
    syncCameraDropdownFromConfig();
    els.footerMsg.textContent = `config reloaded · ${currentConfig.length} chars`;
  } catch (e) {
    els.footerMsg.textContent = `read_config: ${e}`;
  }
}

async function saveConfig() {
  try {
    const contents = els.configEditor.value;
    await invoke("write_config", { contents });
    currentConfig = contents;
    syncCameraDropdownFromConfig();
    els.footerMsg.textContent = `config saved · ${contents.length} chars`;
  } catch (e) {
    els.footerMsg.textContent = `write_config: ${e}`;
  }
}

function parseYamlScalar(line) {
  const idx = line.indexOf(":");
  if (idx < 0) return null;
  return line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
}

function getConfigCameraIndex() {
  const m = currentConfig.match(/^\s*index:\s*(\d+)/m);
  return m ? parseInt(m[1], 10) : null;
}

// ---------- cameras ----------

async function rescanCameras() {
  els.cameraSelect.disabled = true;
  els.cameraSelect.innerHTML = `<option>(scanning…)</option>`;
  try {
    const cams = await invoke("list_cameras");
    els.cameraSelect.innerHTML = "";
    if (!cams || cams.length === 0) {
      els.cameraSelect.innerHTML = `<option>(no cameras found)</option>`;
      return;
    }
    for (const c of cams) {
      const opt = document.createElement("option");
      opt.value = String(c.index);
      const flags = [];
      if (c.placeholder) flags.push("placeholder?");
      const wh = c.frame ? `${c.frame[0]}x${c.frame[1]}` : "?";
      opt.textContent = `${c.label}${flags.length ? "  —  " + flags.join(", ") : ""}`;
      if (!c.opens) opt.disabled = true;
      els.cameraSelect.appendChild(opt);
    }
    syncCameraDropdownFromConfig();
  } catch (e) {
    els.cameraSelect.innerHTML = `<option>(scan failed)</option>`;
    els.footerMsg.textContent = `list_cameras: ${e}`;
  } finally {
    els.cameraSelect.disabled = false;
  }
}

function syncCameraDropdownFromConfig() {
  const idx = getConfigCameraIndex();
  if (idx != null) els.cameraSelect.value = String(idx);
}

async function onCameraSelect() {
  const idx = els.cameraSelect.value;
  if (!idx) return;
  const newConfig = currentConfig.replace(
    /(^camera:[^\n]*\n[^\n]*index:\s*)\d+/m,
    `$1${idx}`,
  );
  if (newConfig === currentConfig) {
    currentConfig = currentConfig.replace(
      /(^camera:[^\n]*\n)/,
      `$1  index: ${idx}\n`,
    );
  } else {
    currentConfig = newConfig;
  }
  els.configEditor.value = currentConfig;
  await saveConfig();
  els.footerMsg.textContent = `camera switched to index ${idx} — restart guardian to apply`;
}

// ---------- log ----------

function renderLog(lines) {
  const last = lines.slice(-200);
  els.logView.innerHTML = last.map(line => {
    const type = (line.event_type || "").replace(/[^a-z0-9_]/g, "");
    const hidden = (currentLogFilter !== "all" && type !== currentLogFilter) ? " hidden" : "";
    return `<div class="log-line ${type}${hidden}">
      <span class="lt">[${line.event_type}]</span>
      <span class="ts">${new Date(line.ts).toLocaleTimeString()}</span>
      <span class="msg">${escapeHtml(JSON.stringify(line.payload))}</span>
    </div>`;
  }).join("");
  els.logView.scrollTop = els.logView.scrollHeight;
}

function setLogFilter(name) {
  currentLogFilter = name;
  els.logFilters.querySelectorAll(".filter-chip").forEach(c => {
    c.classList.toggle("active", c.dataset.filter === name);
  });
  document.querySelectorAll(".log-line").forEach(el => {
    const isMatch = name === "all" || el.classList.contains(name);
    el.classList.toggle("hidden", !isMatch);
  });
}

async function clearLog() {
  await invoke("clear_log");
  els.logView.innerHTML = "";
  els.footerMsg.textContent = "log cleared";
}

// ---------- alert replay ----------

async function refreshAlerts() {
  const dir = await listSnapshotsDir();
  if (!dir) {
    els.alertGallery.innerHTML = `<p class="muted">No snapshots/ directory yet.</p>`;
    return;
  }
  try {
    const entries = await invoke("read_dir", { path: dir }).catch(() => []);
    const jpgs = (entries || []).filter(e => e.name && e.name.startsWith("alert_") && e.name.endsWith(".jpg"));
    if (jpgs.length === 0) {
      els.alertGallery.innerHTML = `<p class="muted">No alerts captured yet.</p>`;
      return;
    }
    jpgs.sort((a, b) => (b.name || "").localeCompare(a.name || ""));
    const recent = jpgs.slice(0, 24);
    els.alertGallery.innerHTML = recent.map(e => {
      const url = convertFileSrc(`${dir}/${e.name}`);
      return `<img src="${url}" title="${escapeHtml(e.name)}" loading="lazy" />`;
    }).join("");
  } catch (e) {
    els.alertGallery.innerHTML = `<p class="muted">Couldn't read ${escapeHtml(dir)}.</p>`;
  }
}

async function listSnapshotsDir() {
  try {
    const s = await invoke("status");
    if (!s.events_path) return null;
    return s.events_path.replace(/[^/]+$/, "snapshots");
  } catch {
    return null;
  }
}

// ---------- live preview websocket ----------

let wsConn = null;
let lastPreviewUrl = null;

function connectPreview() {
  if (wsConn && wsConn.readyState === WebSocket.OPEN) return;
  try {
    wsConn = new WebSocket("ws://127.0.0.1:9876");
  } catch (e) {
    return;
  }
  wsConn.binaryType = "arraybuffer";
  wsConn.onopen = () => {
    els.footerMsg.textContent = "live preview: connected";
  };
  wsConn.onmessage = (e) => {
    const buf = e.data;
    if (!(buf instanceof ArrayBuffer) || buf.byteLength < 8) return;
    const bytes = new Uint8Array(buf);
    const newlineIdx = bytes.indexOf(0x0a);
    if (newlineIdx < 0) return;
    const header = new TextDecoder().decode(bytes.slice(0, newlineIdx));
    const m = header.match(/^(\d+)x(\d+)$/);
    if (!m) return;
    const jpegBytes = bytes.slice(newlineIdx + 1);
    const blob = new Blob([jpegBytes], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    els.previewImg.src = url;
    els.previewImg.style.display = "block";
    if (lastPreviewUrl) URL.revokeObjectURL(lastPreviewUrl);
    lastPreviewUrl = url;
  };
  wsConn.onclose = () => {
    wsConn = null;
    els.footerMsg.textContent = "live preview: disconnected (start guardian to connect)";
    setTimeout(connectPreview, 2000);
  };
  wsConn.onerror = () => {
    wsConn?.close();
  };
}

// ---------- utilities ----------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
}

// ---------- wire-up ----------

els.btnStart.addEventListener("click", startGuardian);
els.btnStop.addEventListener("click", stopGuardian);
els.btnReload.addEventListener("click", reloadConfig);
els.btnSave.addEventListener("click", saveConfig);
els.btnClear.addEventListener("click", clearLog);
els.btnRescan.addEventListener("click", rescanCameras);
els.cameraSelect.addEventListener("change", onCameraSelect);
els.btnRefreshAlerts.addEventListener("click", refreshAlerts);
els.logFilters.addEventListener("click", (e) => {
  const chip = e.target.closest(".filter-chip");
  if (chip) setLogFilter(chip.dataset.filter);
});

(async () => {
  await reloadConfig();
  await rescanCameras();
  await refreshStatus();
  await refreshAlerts();
  connectPreview();
})();

listen("guardian:started", (e) => {
  setStatus("running", `running · pid ${e.payload}`);
  els.footerMsg.textContent = `guardian started · pid ${e.payload}`;
});
listen("guardian:stopped", () => {
  setStatus("stopped", "stopped");
  els.footerMsg.textContent = "guardian stopped";
});
listen("guardian:events", (e) => {
  renderLog(e.payload || []);
});

setInterval(refreshStatus, 3000);
setInterval(refreshAlerts, 5000);