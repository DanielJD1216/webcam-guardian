import { useEffect, useRef, useState } from "react";
import { tauri, LogLine, CameraOption } from "./lib/tauri";
import { cn } from "./lib/cn";
import { AnimatedGradientText } from "./components/AnimatedGradientText";
import { BackgroundGradient } from "./components/BackgroundGradient";
import { Spotlight } from "./components/Spotlight";
import { MovingBorder } from "./components/MovingBorder";
import { StatusPill } from "./components/StatusPill";

type Filter = "all" | "startup" | "guard_stats" | "escalation_dispatched" | "detective_result" | "alert_sent" | "alert_error";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "all" },
  { key: "startup", label: "startup" },
  { key: "guard_stats", label: "guard_stats" },
  { key: "escalation_dispatched", label: "escalation" },
  { key: "detective_result", label: "detective" },
  { key: "alert_sent", label: "alert" },
  { key: "alert_error", label: "alert_err" },
];

const RESOLUTIONS: { w: number; h: number; label: string }[] = [
  { w: 640, h: 480, label: "640 × 480 (fastest)" },
  { w: 1280, h: 720, label: "1280 × 720 (balanced)" },
  { w: 1920, h: 1080, label: "1920 × 1080 (best)" },
];

// audit #50: React text children are auto-escaped. The
// surrounding <span> wraps a JSON string. Calling escapeHtml on
// top of that double-escapes entities (so we were rendering
// {&quot;label&quot;:&quot;person&quot;} as text). Just JSON.stringify
// and let React handle it.

function parseConfigResolution(cfg: string): { w: number; h: number } | null {
  const wm = cfg.match(/^\s*width:\s*(\d+)/m);
  const hm = cfg.match(/^\s*height:\s*(\d+)/m);
  if (!wm || !hm) return null;
  return { w: parseInt(wm[1], 10), h: parseInt(hm[1], 10) };
}

function getConfigCameraIndex(cfg: string): number | null {
  const m = cfg.match(/^\s*index:\s*(\d+)/m);
  return m ? parseInt(m[1], 10) : null;
}

export default function App() {
  const [running, setRunning] = useState(false);
  const [pid, setPid] = useState<number | null>(null);
  const [configPath, setConfigPath] = useState("");
  const [, setProjectRoot] = useState("");   // audit #50: kept as unused-arg-only state to satisfy the autoCreate path below; remove once tsconfig noUnusedParameters is off.
  void setProjectRoot;
  const [footerMsg, setFooterMsg] = useState("ready");
  const [cameraIdx, setCameraIdx] = useState<number | "scanning" | "none" | "failed">("scanning");
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [resolution, setResolution] = useState<{ w: number; h: number }>({ w: 1280, h: 720 });
  const [currentConfig, setCurrentConfig] = useState("");
  const [configDraft, setConfigDraft] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [alertImgs, setAlertImgs] = useState<{ name: string; url: string; when: string }[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<"off" | "connecting" | "live" | "stale" | "disconnected">("off");
  const [crashInfo, setCrashInfo] = useState<{ exit_code: number | null; stderr_tail: string[] } | null>(null);
  const lastFrameAt = useRef<number>(0);
  const lastPreviewUrl = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const wsTokenRef = useRef<string | null>(null);   // audit #3: per-launch token
  const retryCountRef = useRef(0);                  // audit #77: backoff state for WS reconnect

  // ----- status & log streaming -----
  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      try {
        const s = await tauri.status();
        if (!mounted) return;
        setRunning(s.running);
        setPid(s.pid);
        setConfigPath(s.config_path);
        // audit #50: projectRoot is unused; drop the state to satisfy
        // noUnusedLocals. The path is already visible in the preview
        // bar (`config: ${configPath}`) and the StatusBar.
        setLogLines(s.log_lines || []);
      } catch (e) {
        setFooterMsg(`status: ${e}`);
      }
    };
    refresh();
    const interval = setInterval(refresh, 3000);
    tauri.onStarted((p) => {
      // audit #3: the payload is now { pid, ws_token } not just pid.
      const info = (typeof p === "object" && p) ? p : { pid: p, ws_token: null };
      setRunning(true);
      setPid(info.pid ?? null);
      wsTokenRef.current = info.ws_token ?? null;
      setFooterMsg(`guardian started · pid ${info.pid ?? "?"}`);
    });
    tauri.onStopped(() => { setRunning(false); setPid(null); setFooterMsg("guardian stopped"); });
    tauri.onCrashed((info) => {
      setRunning(false);
      setPid(null);
      setCrashInfo(info);
      const last = (info.stderr_tail || []).slice(-3).join(" | ");
      setFooterMsg(`guardian crashed (exit ${info.exit_code ?? "?"}): ${last}`);
    });
    tauri.onEvents((lines) => setLogLines(lines));
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // ----- live preview websocket -----
  useEffect(() => {
    // audit #77: closure-scoped cancellation flag + retry timer handle
    // so the effect cleanup can actually stop the reconnect chain
    // (cancelled flag) and clear the next pending retry (retryTimer).
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    function connect() {
      if (cancelled || !running) {
        setPreviewState("off");
        return;
      }
      try {
        setPreviewState("connecting");
        // audit #3: include the per-launch token in the URL. The
        // Python WS server rejects connections without it (and
        // browsers that always send an Origin header).
        const tok = wsTokenRef.current;
        const url = tok ? `ws://127.0.0.1:9876/?token=${encodeURIComponent(tok)}` : "ws://127.0.0.1:9876";
        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.binaryType = "arraybuffer";
        ws.onopen = () => setPreviewState("live");
        ws.onmessage = (e) => {
          if (!(e.data instanceof ArrayBuffer) || e.data.byteLength < 8) return;
          const bytes = new Uint8Array(e.data);
          const nl = bytes.indexOf(0x0a);
          if (nl < 0) return;
          const jpeg = bytes.slice(nl + 1);
          const blob = new Blob([jpeg], { type: "image/jpeg" });
          const url = URL.createObjectURL(blob);
          setPreviewUrl(url);
          if (lastPreviewUrl.current) URL.revokeObjectURL(lastPreviewUrl.current);
          lastPreviewUrl.current = url;
          lastFrameAt.current = Date.now();
          setPreviewState("live");
        };
        ws.onclose = () => {
          if (cancelled) return;
          setPreviewState("disconnected");
          // audit #77: exponential backoff capped at 8 s so a
          // perpetually dead port doesn't hammer it. Cancellable via
          // the effect-scope `cancelled` flag and `retryTimer` handle
          // (without those, onclose + setTimeout chain survives the
          // effect cleanup and keeps retrying the dead port after
          // Stop).
          const backoff = Math.min(8000, 1500 * Math.pow(1.4, retryCountRef.current));
          retryCountRef.current += 1;
          retryTimer = setTimeout(connect, backoff);
        };
        ws.onerror = () => { try { ws.close(); } catch { /* already closing */ } };
      } catch {
        setPreviewState("disconnected");
      }
    }
    retryCountRef.current = 0;
    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      try { wsRef.current?.close(); } catch { /* noop */ }
    };
  }, [running]);

  // ----- cameras -----
  const rescanCameras = async () => {
    setCameraIdx("scanning");
    try {
      const cs = await tauri.listCameras();
      setCameras(cs);
      setCameraIdx(cs.length ? "none" : "none");
    } catch (e) {
      setCameraIdx("failed");
      setFooterMsg(`list_cameras: ${e}`);
    }
  };
  useEffect(() => {
    // audit #27 + #28: load config + cameras on mount. If config is
    // missing or empty, auto-create from the example so the pickers
    // and editor are populated. The Reset button then sees "Reset to
    // defaults" copy (destructive confirm) rather than the bare
    // "Create config" path.
    (async () => {
      try {
        let c = await tauri.readConfig();
        const isFresh = !c || c.trim() === "";
        if (isFresh) {
          c = await tauri.resetConfigFromExample();
          setFooterMsg(`first-run: config.yaml auto-created from example (${c.length} chars). Review and edit, then Start.`);
        }
        setCurrentConfig(c);
        setConfigDraft(c);
        const idx = getConfigCameraIndex(c);
        if (idx != null) setCameraIdx(idx);
        const r = parseConfigResolution(c);
        if (r) setResolution(r);
      } catch (e) {
        setFooterMsg(`mount load: ${e}`);
      }
    })();
    rescanCameras();
  }, []);

  // ----- config -----
  const reloadConfig = async () => {
    try {
      const c = await tauri.readConfig();
      if (!c || c.length === 0) {
        setFooterMsg("config empty — config.yaml missing or unreadable");
        console.warn("readConfig returned empty");
        return;
      }
      setCurrentConfig(c);
      setConfigDraft(c);
      const idx = getConfigCameraIndex(c);
      if (idx != null) setCameraIdx(idx);
      const r = parseConfigResolution(c);
      if (r) setResolution(r);
      setFooterMsg(`config reloaded · ${c.length} chars`);
      console.log("config reloaded", c.length, "chars; camera=", idx, "res=", r);
    } catch (e) {
      setFooterMsg(`read_config: ${e}`);
      console.error("read_config failed", e);
    }
  };

  const saveConfig = async () => {
    try {
      if (!configDraft.trim()) {
        setFooterMsg("refusing to save empty config — click Reset to restore defaults");
        return;
      }
      await tauri.writeConfig(configDraft);
      setCurrentConfig(configDraft);
      const idx = getConfigCameraIndex(configDraft);
      if (idx != null) setCameraIdx(idx);
      setFooterMsg(`config saved · ${configDraft.length} chars`);
    } catch (e) {
      setFooterMsg(`write_config: ${e}`);
    }
  };

  const resetConfig = async () => {
    // audit #28: button label + copy adapt to whether config exists
    // already. If it does, "Reset to defaults" with a destructive
    // confirm; if not, "Create config" with no confirm at all.
    const isFresh = !currentConfig.trim();
    if (!isFresh) {
      const ok = window.confirm(
        "Reset config.yaml to defaults from config.example.yaml? " +
        "Your current config will be overwritten.");
      if (!ok) return;
    }
    try {
      const fresh = await tauri.resetConfigFromExample();
      setCurrentConfig(fresh);
      setConfigDraft(fresh);
      const idx = getConfigCameraIndex(fresh);
      if (idx != null) setCameraIdx(idx);
      const r = parseConfigResolution(fresh);
      if (r) setResolution(r);
      setFooterMsg(`config reset from example · ${fresh.length} chars`);
    } catch (e) {
      setFooterMsg(`reset_config: ${e}`);
    }
  };

  const onCameraChange = async (newIdx: number) => {
    if (!currentConfig.trim()) {
      setFooterMsg("config is empty — click Reset to create one first");
      return;
    }
    setCameraIdx(newIdx);
    try {
      const fresh = await tauri.setCameraIndex(newIdx);
      setCurrentConfig(fresh);
      setConfigDraft(fresh);
      setFooterMsg(`camera switched to index ${newIdx} — restart guardian to apply`);
    } catch (e) {
      setFooterMsg(`set_camera_index: ${e}`);
    }
  };

  const onResolutionChange = async (val: string) => {
    if (!currentConfig.trim()) {
      setFooterMsg("config is empty — click Reset to create one first");
      return;
    }
    const m = val.match(/^(\d+)x(\d+)$/);
    if (!m) return;
    const w = parseInt(m[1], 10);
    const h = parseInt(m[2], 10);
    setResolution({ w, h });
    try {
      const fresh = await tauri.setResolution(w, h);
      setCurrentConfig(fresh);
      setConfigDraft(fresh);
      setFooterMsg(`resolution ${w}×${h} saved — restart guardian to apply`);
    } catch (e) {
      setFooterMsg(`set_resolution: ${e}`);
    }
  };

  // ----- log clear (audit #50 follow-on) -----
  const clearLog = async () => {
    try {
      await tauri.clearLog();
      setLogLines([]);
      setFooterMsg("log cleared");
    } catch (e) {
      setFooterMsg(`clearLog: ${e}`);
    }
  };

  // ----- alerts gallery -----
  const refreshAlerts = async () => {
    try {
      const items = await tauri.listAlerts();
      const imgs = items.map((a) => ({
        name: a.name,
        url: tauri.assetUrl(a.path),
        // audit #29: derive a human label from the alert's millisecond
        // timestamp so the gallery isn't a wall of identical filenames.
        when: alertLabelFromName(a.name),
      }));
      setAlertImgs(imgs);
    } catch (e) {
      console.error("listAlerts failed", e);
    }
  };

  function alertLabelFromName(name: string): string {
    // alert_<unix_ms>.jpg
    const m = name.match(/^alert_(\d+)\.jpg$/);
    if (!m) return name;
    const t = new Date(parseInt(m[1], 10));
    if (isNaN(t.getTime())) return name;
    const now = new Date();
    const sameDay = t.toDateString() === now.toDateString();
    const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
    const isYesterday = t.toDateString() === yesterday.toDateString();
    const time = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return `Today ${time}`;
    if (isYesterday) return `Yesterday ${time}`;
    return `${t.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
  }

  // audit #29 follow-up: bucket alerts by date for the gallery.
  // Returns an ordered map from bucket label → array of items.
  function groupAlertsByDate(
    items: { name: string; url: string; when: string }[],
  ): Record<string, typeof items> {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const buckets: Record<string, typeof items> = {};
    for (const a of items) {
      const m = a.name.match(/^alert_(\d+)\.jpg$/);
      if (!m) {
        (buckets["Earlier"] ??= []).push(a);
        continue;
      }
      const t = new Date(parseInt(m[1], 10));
      t.setHours(0, 0, 0, 0);
      const key =
        t.getTime() === today.getTime() ? "Today"
        : t.getTime() === yesterday.getTime() ? "Yesterday"
        : t.toLocaleDateString([], { month: "short", day: "numeric" });
      (buckets[key] ??= []).push(a);
    }
    return buckets;
  }

  useEffect(() => { refreshAlerts(); }, [logLines]);
  useEffect(() => { const i = setInterval(refreshAlerts, 5000); return () => clearInterval(i); }, []);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => {
      const age = Date.now() - lastFrameAt.current;
      if (lastFrameAt.current > 0 && age > 5000 && previewState === "live") {
        setPreviewState("stale");
        setFooterMsg(`stream stale: no frame in ${(age/1000).toFixed(1)}s — camera may have disconnected`);
      }
    }, 1500);
    return () => clearInterval(id);
  }, [running, previewState]);

  // ----- actions -----
  const start = async () => {
    setFooterMsg("starting…");
    try {
      await tauri.start();
    } catch (e) {
      setFooterMsg(`start: ${e}`);
    }
  };
  const stop = async () => {
    setFooterMsg("stopping…");
    try { await tauri.stop(); } catch (e) { setFooterMsg(`stop: ${e}`); }
  };

  const filteredLogs = logLines
    .filter((l) => filter === "all" || l.event_type === filter)
    .slice(-200);

  return (
    <BackgroundGradient>
      <div className="flex h-screen flex-col">
        {/* Crash banner */}
        {crashInfo && (
          <div className="border-b border-red/40 bg-red/15 px-6 py-2 font-mono text-xs text-red">
            <div className="flex items-start justify-between gap-4">
              <div>
                <strong className="font-sans">Guardian crashed</strong> — exit code{" "}
                {crashInfo.exit_code ?? "?"}. Last stderr:
                <div className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap rounded bg-bg/60 p-2">
                  {crashInfo.stderr_tail.join("\n") || "(no stderr captured)"}
                </div>
              </div>
              <button
                onClick={() => setCrashInfo(null)}
                className="shrink-0 rounded px-2 py-0.5 text-red hover:bg-red/20"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Topbar */}
        <header className="flex items-center justify-between gap-4 border-b border-line bg-panel/60 px-6 py-3 backdrop-blur">
          <div className="flex items-center gap-3">
            <div
              className="h-7 w-7 rounded-lg border border-cyan"
              style={{
                background:
                  "radial-gradient(circle at 50% 50%, #ffc857 0 6px, transparent 7px), radial-gradient(circle at 50% 50%, transparent 11px, #5ec8ff 12px 14px, transparent 15px), linear-gradient(135deg, #1d2436 0%, #0e121c 100%)",
              }}
            />
            <AnimatedGradientText className="text-lg font-semibold">
              webcam-guardian
            </AnimatedGradientText>
            <span className="text-xs text-grey">v0.2.0</span>
          </div>

          <div className="flex items-center gap-3">
            <label className="text-xs font-semibold uppercase tracking-wider text-grey">Camera</label>
            <select
              value={typeof cameraIdx === "number" ? String(cameraIdx) : ""}
              onChange={(e) => onCameraChange(parseInt(e.target.value, 10))}
              disabled={cameras.length === 0}
              className="rounded-md border border-line bg-elev px-3 py-1.5 text-sm text-text outline-none focus:border-cyan-dim min-w-[180px] max-w-[240px]"
              title="Camera source (use the Rescan button if your iPhone isn't listed)"
            >
              {/* audit #30: distinct placeholder per real state */}
              {cameraIdx === "scanning" && <option value="">(scanning…)</option>}
              {cameraIdx === "none" && cameras.length === 0 && (
                <option value="">(no cameras found — check permissions)</option>
              )}
              {cameraIdx === "failed" && (
                <option value="">(scan failed — see status bar)</option>
              )}
              {cameras.map((c) => (
                <option key={c.index} value={String(c.index)} disabled={!c.opens}>
                  {c.label}{c.placeholder ? "  — placeholder?" : ""}
                </option>
              ))}
            </select>
            <label className="ml-2 text-xs font-semibold uppercase tracking-wider text-grey">Res</label>
            <select
              value={`${resolution.w}x${resolution.h}`}
              onChange={(e) => onResolutionChange(e.target.value)}
              className="rounded-md border border-line bg-elev px-3 py-1.5 text-sm text-text outline-none focus:border-cyan-dim"
            >
              {RESOLUTIONS.map((r) => (
                <option key={`${r.w}x${r.h}`} value={`${r.w}x${r.h}`}>{r.label}</option>
              ))}
            </select>
            <MovingBorder
              onClick={rescanCameras}
              variant="secondary"
              className="!px-2.5 !py-1.5 text-xs"
              title="Rescan cameras"
            >
              ↻
            </MovingBorder>
          </div>

          <div className="flex items-center gap-3">
            <MovingBorder onClick={start} disabled={running} variant="primary">
              Start guardian
            </MovingBorder>
            <MovingBorder onClick={stop} disabled={!running} variant="danger">
              Stop
            </MovingBorder>
            <StatusPill
              state={running ? "running" : (crashInfo ? "error" : "stopped")}
              label={running ? `running · pid ${pid ?? "?"}` : (crashInfo ? `crashed · exit ${crashInfo.exit_code ?? "?"}` : "stopped")}
            />
          </div>
        </header>

        {/* Main */}
        <main className="grid min-h-0 flex-1 grid-cols-[1fr_380px] gap-4 p-4">
          {/* Preview */}
<Spotlight className="relative flex min-h-0 flex-col overflow-hidden">
              <div className="relative flex flex-1 items-center justify-center bg-elev/60">
              {previewUrl ? (
                <img
                  src={previewUrl}
                  alt="live preview"
                  className="max-h-full max-w-full animate-fade-in"
                />
              ) : (
                <div className="flex flex-col items-center gap-2 text-grey">
                  <div className="text-6xl opacity-20">📷</div>
                  <p className="text-sm">
                    {previewState === "off" && "Start the guardian to see the live preview."}
                    {previewState === "connecting" && "Connecting to frame stream…"}
                    {previewState === "live" && "Loading…"}
                    {previewState === "disconnected" && "Disconnected. Restarting…"}
                  </p>
                </div>
              )}
              <div className="pointer-events-none absolute left-4 top-4 flex items-center gap-2 rounded-full border border-line bg-panel/80 px-3 py-1 font-mono text-xs text-grey backdrop-blur">
                <span className={cn("h-1.5 w-1.5 rounded-full", running ? "bg-green animate-pulse-slow" : "bg-grey")} />
                {running ? "live" : "offline"} · {previewState}
              </div>
            </div>
            <div className="flex gap-4 border-t border-line bg-panel/40 px-4 py-2 font-mono text-xs text-grey">
              <span>pid: {pid ?? "—"}</span>
              <span className="truncate">config: {configPath}</span>
            </div>
          </Spotlight>

          {/* Sidebar */}
          <aside className="flex min-h-0 flex-col gap-3">
            {/* Config */}
            <Spotlight className="flex flex-col overflow-hidden p-3" spotlightColor="rgba(196,122,0,0.10)">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-dim">Config</h3>
                <span className="font-mono text-[10px] text-grey">{configPath.split("/").pop()}</span>
              </div>
              <textarea
                spellCheck={false}
                value={configDraft}
                onChange={(e) => setConfigDraft(e.target.value)}
                className="min-h-[100px] flex-1 resize-y rounded-md border border-line bg-bg/60 p-2 font-mono text-xs leading-relaxed text-text outline-none focus:border-yellow/40"
              />
              <div className="mt-2 flex justify-end gap-2">
                <MovingBorder
                  onClick={resetConfig}
                  variant="secondary"
                  className="!px-3 !py-1 text-xs"
                >
                  {/* audit #28: label adapts — 'Create config' for
                      first run (no destructive confirm), 'Reset to
                      defaults' for an existing user. */}
                  {currentConfig.trim() ? "Reset to defaults" : "Create config"}
                </MovingBorder>
                <MovingBorder onClick={reloadConfig} variant="secondary" className="!px-3 !py-1 text-xs">
                  Reload
                </MovingBorder>
                <MovingBorder onClick={saveConfig} variant="primary" className="!px-3 !py-1 text-xs">
                  Save
                </MovingBorder>
              </div>
            </Spotlight>

            {/* Log */}
            <Spotlight className="flex min-h-0 flex-1 flex-col overflow-hidden p-3" spotlightColor="rgba(11,128,209,0.10)">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-dim">Live log</h3>
                <button
                  onClick={clearLog}
                  className="text-[10px] text-grey hover:text-text"
                >
                  Clear
                </button>
              </div>
              <div className="mb-2 flex flex-wrap gap-1">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 font-mono text-[10px]",
                      filter === f.key
                        ? "border-cyan-dim bg-cyan/10 text-cyan"
                        : "border-line bg-bg/40 text-grey hover:border-cyan-dim/50 hover:text-text",
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <div className="no-scrollbar min-h-0 flex-1 overflow-y-auto rounded-md border border-line bg-bg/60 p-2 font-mono text-[10px]">
                {filteredLogs.length === 0 && (
                  <div className="py-6 text-center text-grey">no events</div>
                )}
                {filteredLogs.map((l, i) => (
                  <div
                    key={i}
                    className={cn(
                      "border-b border-dashed border-cyan/5 py-1",
                      l.event_type === "alert_sent" && "text-green",
                      l.event_type === "alert_error" && "text-red",
                      l.event_type === "detective_result" && "text-yellow",
                      l.event_type === "escalation_dispatched" && "text-cyan",
                    )}
                  >
                    <span className="mr-2 font-semibold">[{l.event_type}]</span>
                    <span className="mr-2 text-grey">
                      {new Date(l.ts).toLocaleTimeString()}
                    </span>
                    <span className="break-all">{JSON.stringify(l.payload)}</span>
                  </div>
                ))}
              </div>
            </Spotlight>

            {/* Alerts */}
            <Spotlight className="flex flex-col overflow-hidden p-3" spotlightColor="rgba(31,143,95,0.10)">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-dim">Alert replay</h3>
                <button onClick={refreshAlerts} className="text-[10px] text-grey hover:text-text">
                  Refresh
                </button>
              </div>
              <div className="max-h-[160px] overflow-y-auto">
                {alertImgs.length === 0 ? (
                  <div className="py-4 text-center text-[11px] text-grey">No alerts yet.</div>
                ) : (
                  /* audit #29 follow-up: group by date bucket so a
                     week's worth of alerts is scannable instead of a
                     single flat grid. Today, Yesterday, and earlier
                     dates each get a small label. */
                  <div className="flex flex-col gap-2">
                    {Object.entries(groupAlertsByDate(alertImgs)).map(([bucket, items]) => (
                      <div key={bucket}>
                        <div className="mb-1 text-[10px] uppercase tracking-wider text-grey">{bucket}</div>
                        <div className="grid grid-cols-4 gap-1.5">
                          {items.map((a) => (
                            <div key={a.name} className="relative">
                              <img
                                src={a.url}
                                title={a.name}
                                className="aspect-video w-full rounded border border-line object-cover transition hover:border-cyan"
                                loading="lazy"
                              />
                              <div className="absolute bottom-0 left-0 right-0 truncate rounded-b bg-bg/80 px-1 py-0.5 text-center font-mono text-[9px] text-grey">
                                {a.when ?? a.name}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Spotlight>
          </aside>
        </main>

        {/* Statusbar */}
        <footer className="flex items-center justify-between border-t border-line bg-panel/40 px-6 py-2 text-[11px] text-grey">
          <span>MIT · v0.2.0 · Python core + Tauri shell + Aceternity UI</span>
          <span className="font-mono">{footerMsg}</span>
        </footer>
      </div>
    </BackgroundGradient>
  );
}