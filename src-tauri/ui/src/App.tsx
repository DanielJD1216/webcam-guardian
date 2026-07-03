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

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

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
  const [projectRoot, setProjectRoot] = useState("");
  const [footerMsg, setFooterMsg] = useState("ready");
  const [cameraIdx, setCameraIdx] = useState<number | "scanning" | "none" | "failed">("scanning");
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [resolution, setResolution] = useState<{ w: number; h: number }>({ w: 1280, h: 720 });
  const [currentConfig, setCurrentConfig] = useState("");
  const [configDraft, setConfigDraft] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [alertImgs, setAlertImgs] = useState<{ name: string; url: string }[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<"off" | "connecting" | "live" | "stale" | "disconnected">("off");
  const [crashInfo, setCrashInfo] = useState<{ exit_code: number | null; stderr_tail: string[] } | null>(null);
  const lastFrameAt = useRef<number>(0);
  const lastPreviewUrl = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

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
        setProjectRoot(s.project_root);
        setLogLines(s.log_lines || []);
      } catch (e) {
        setFooterMsg(`status: ${e}`);
      }
    };
    refresh();
    const interval = setInterval(refresh, 3000);
    tauri.onStarted((p) => { setRunning(true); setPid(p); setFooterMsg(`guardian started · pid ${p}`); });
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
    function connect() {
      if (!running) {
        setPreviewState("off");
        return;
      }
      try {
        setPreviewState("connecting");
        const ws = new WebSocket("ws://127.0.0.1:9876");
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
          setPreviewState("disconnected");
          setTimeout(connect, 1500);
        };
        ws.onerror = () => ws.close();
      } catch {
        setPreviewState("disconnected");
      }
    }
    connect();
    return () => wsRef.current?.close();
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
  useEffect(() => { rescanCameras(); }, []);

  // ----- config -----
  const reloadConfig = async () => {
    try {
      const c = await tauri.readConfig();
      setCurrentConfig(c);
      setConfigDraft(c);
      const idx = getConfigCameraIndex(c);
      if (idx != null) setCameraIdx(idx);
      const r = parseConfigResolution(c);
      if (r) setResolution(r);
      setFooterMsg(`config reloaded · ${c.length} chars`);
    } catch (e) {
      setFooterMsg(`read_config: ${e}`);
    }
  };

  const saveConfig = async () => {
    try {
      await tauri.writeConfig(configDraft);
      setCurrentConfig(configDraft);
      const idx = getConfigCameraIndex(configDraft);
      if (idx != null) setCameraIdx(idx);
      setFooterMsg(`config saved · ${configDraft.length} chars`);
    } catch (e) {
      setFooterMsg(`write_config: ${e}`);
    }
  };

  const onCameraChange = async (newIdx: number) => {
    const replaced = currentConfig.replace(
      /(^camera:[^\n]*\n[^\n]*index:\s*)\d+/m,
      `$1${newIdx}`,
    );
    const finalCfg = replaced === currentConfig
      ? currentConfig.replace(/(^camera:[^\n]*\n)/, `$1  index: ${newIdx}\n`)
      : replaced;
    setCurrentConfig(finalCfg);
    setConfigDraft(finalCfg);
    setCameraIdx(newIdx);
    try {
      await tauri.writeConfig(finalCfg);
      setFooterMsg(`camera switched to index ${newIdx} — restart guardian to apply`);
    } catch (e) {
      setFooterMsg(`write_config: ${e}`);
    }
  };

  const onResolutionChange = async (val: string) => {
    const m = val.match(/^(\d+)x(\d+)$/);
    if (!m) return;
    const w = parseInt(m[1], 10);
    const h = parseInt(m[2], 10);
    setResolution({ w, h });
    let newCfg = currentConfig.replace(/(^camera:[^\n]*\n[^\n]*width:\s*)\d+/m, `$1${w}`);
    if (newCfg === currentConfig) {
      newCfg = currentConfig.replace(/(^camera:[^\n]*\n)/, `$1  width: ${w}\n`);
    }
    newCfg = newCfg.replace(/(^camera:[^\n]*\n[^\n]*height:\s*)\d+/m, `$1${h}`);
    if (newCfg === currentConfig) {
      newCfg = currentConfig.replace(/(^camera:[^\n]*\n)/, `$1  height: ${h}\n`);
    }
    setCurrentConfig(newCfg);
    setConfigDraft(newCfg);
    try {
      await tauri.writeConfig(newCfg);
      setFooterMsg(`resolution ${w}×${h} saved — restart guardian to apply`);
    } catch (e) {
      setFooterMsg(`write_config: ${e}`);
    }
  };

  // ----- alerts gallery -----
  const refreshAlerts = async () => {
    try {
      const s = await tauri.status();
      const dir = s.events_path.replace(/[^/]+$/, "snapshots");
      const entries = await tauri.readDir(dir).catch(() => []);
      const jpgs = (entries || [])
        .filter((e: any) => e?.name?.startsWith?.("alert_") && e.name.endsWith(".jpg"))
        .map((e: any) => ({
          name: e.name as string,
          url: tauri.assetUrl(`${dir}/${e.name}`),
        }))
        .sort((a, b) => b.name.localeCompare(a.name))
        .slice(0, 24);
      setAlertImgs(jpgs);
    } catch { /* silent */ }
  };
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
            >
              {cameras.length === 0 && <option value="">(scanning…)</option>}
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
                  onClick={() => setLogLines([])}
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
                    <span className="break-all">{escapeHtml(JSON.stringify(l.payload))}</span>
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
                  <div className="grid grid-cols-4 gap-1.5">
                    {alertImgs.map((a) => (
                      <img
                        key={a.name}
                        src={a.url}
                        title={a.name}
                        className="aspect-video w-full rounded border border-line object-cover transition hover:border-cyan"
                        loading="lazy"
                      />
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