const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const $ = (id) => document.getElementById(id);

const els = {
  btnStart: $("btn-start"),
  btnStop: $("btn-stop"),
  pill: $("status-pill"),
  previewImg: $("preview-img"),
  previewEmpty: $("preview-empty"),
  metricPid: $("metric-pid"),
  metricConfig: $("metric-config"),
  configEditor: $("config-editor"),
  btnReload: $("btn-reload-config"),
  btnSave: $("btn-save-config"),
  logView: $("log-view"),
  btnClear: $("btn-clear-log"),
  footerMsg: $("footer-msg"),
};

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

async function reloadConfig() {
  try {
    const contents = await invoke("read_config");
    els.configEditor.value = contents;
    els.footerMsg.textContent = `config reloaded · ${contents.length} chars`;
  } catch (e) {
    els.footerMsg.textContent = `read_config: ${e}`;
  }
}

async function saveConfig() {
  try {
    await invoke("write_config", { contents: els.configEditor.value });
    els.footerMsg.textContent = `config saved · ${els.configEditor.value.length} chars`;
  } catch (e) {
    els.footerMsg.textContent = `write_config: ${e}`;
  }
}

function renderLog(lines) {
  const last = lines.slice(-200);
  els.logView.innerHTML = last.map(line => {
    const type = (line.event_type || "").replace(/[^a-z0-9_]/g, "");
    return `<div class="log-line ${type}">
      <span class="lt">[${line.event_type}]</span>
      <span class="ts">${new Date(line.ts).toLocaleTimeString()}</span>
      <span class="msg">${escapeHtml(JSON.stringify(line.payload))}</span>
    </div>`;
  }).join("");
  els.logView.scrollTop = els.logView.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
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

async function clearLog() {
  await invoke("clear_log");
  els.logView.innerHTML = "";
  els.footerMsg.textContent = "log cleared";
}

els.btnStart.addEventListener("click", startGuardian);
els.btnStop.addEventListener("click", stopGuardian);
els.btnReload.addEventListener("click", reloadConfig);
els.btnSave.addEventListener("click", saveConfig);
els.btnClear.addEventListener("click", clearLog);

(async () => {
  await reloadConfig();
  await refreshStatus();
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