import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export type LogLine = { ts: string; event_type: string; payload: any };
export type CameraOption = {
  index: number;
  opens: boolean;
  native: [number, number] | null;
  frame: [number, number] | null;
  placeholder: boolean;
  label: string;
};
export type Status = {
  running: boolean;
  pid: number | null;
  project_root: string;
  config_path: string;
  events_path: string;
  snapshots_dir: string;
  log_lines: LogLine[];
  ws_token: string | null;
};

export type AlertItem = { name: string; path: string };

export const tauri = {
  status: () => invoke<Status>("status"),
  start: () => invoke<number>("start"),
  stop: () => invoke<void>("stop"),
  readConfig: () => invoke<string>("read_config"),
  writeConfig: (contents: string) => invoke<void>("write_config", { contents }),
  resetConfigFromExample: () => invoke<string>("reset_config_from_example"),
  clearLog: () => invoke<void>("clear_log"),
  listCameras: () => invoke<CameraOption[]>("list_cameras"),
  listAlerts: () => invoke<AlertItem[]>("list_alerts"),
  assetUrl: (path: string) => convertFileSrc(path),
  onStarted: (cb: (pid: number) => void) => listen<number>("guardian:started", (e) => cb(e.payload)),
  onStopped: (cb: () => void) => listen<void>("guardian:stopped", () => cb()),
  onCrashed: (cb: (info: { exit_code: number | null; stderr_tail: string[] }) => void) =>
    listen<{ exit_code: number | null; stderr_tail: string[] }>("guardian:crashed", (e) => cb(e.payload)),
  onEvents: (cb: (lines: LogLine[]) => void) => listen<LogLine[]>("guardian:events", (e) => cb(e.payload ?? [])),
};