"""main.py — entry point.

Per BUILD-PLAN.md §5.1 threading contract (non-negotiable):
  - Capture = daemon thread, single lock-guarded latest-frame slot.
  - Main thread owns: guard inference, overlay drawing, imshow/waitKey, escalation decision.
  - Exactly ONE detective worker thread consumes queue.Queue.
  - API call (timeout 30 s, one retry on 429/5xx, 2 s backoff) + alert dispatch
    happen on the worker thread so the preview never freezes on network.

Per §13 trap 3: cv2.imshow/waitKey main thread only — detective calls NEVER on main thread.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import psutil
from dotenv import load_dotenv

from . import __version__
from .capture import LatestFrameCamera, default_backend
from .config import Config, load, resolve_device
from .detective import Detective
from .escalate import Escalator
from .guard.base import Detection, GuardBackend
from .guard.rtdetr import RTDetrGuard
from .guard.yolo import YoloGuard
from .guard.la_client import LocateAnythingGuard
from .overlay import HudState, draw as draw_overlay, set_banner
from .storage import EventLog, snapshot_save
from .alerts.base import dispatch as dispatch_alerts
from .alerts.factory import build_channels


CAMERA_BACKEND_NAMES = {"auto", "dshow", "msmf", "avfoundation", "v4l2"}


def _camera_backend(name: str):
    if name == "auto" or name not in CAMERA_BACKEND_NAMES:
        return None
    return {
        "dshow": cv2.CAP_DSHOW,
        "msmf": cv2.CAP_MSMF,
        "avfoundation": cv2.CAP_AVFOUNDATION,
        "v4l2": cv2.CAP_V4L2,
    }[name]


def _make_guard(cfg) -> GuardBackend:
    name = cfg.guard.backend
    if name == "rtdetr":
        return RTDetrGuard(cfg.guard)
    if name == "yolo11n":
        return YoloGuard(cfg.guard)
    if name == "locateanything":
        return LocateAnythingGuard(cfg.guard)
    raise ValueError(f"unknown guard backend: {name}")


class DetectiveWorker(threading.Thread):
    """Single-thread consumer. Owns the only network call in the app.

    Per BUILD-PLAN §5.1: API call, alert delivery, and event logging all here
    so the main thread is never blocked. Cap-aware: escalator decides; worker obeys.
    """

    def __init__(self, detective: Detective, escalator: Escalator,
                 channels: list, log: EventLog, cfg: Config, frame_provider) -> None:
        super().__init__(daemon=True, name="detective-worker")
        self.q: queue.Queue = queue.Queue(maxsize=2)
        self.detective = detective
        self.escalator = escalator
        self.channels = channels
        self.log = log
        self.cfg = cfg
        self._stop = threading.Event()
        self._frame_provider = frame_provider  # for snapshot save

    def submit(self, frame_copy, labels: list[str], now: float) -> bool:
        try:
            self.q.put_nowait((frame_copy, list(labels), now))
            return True
        except queue.Full:
            self.log.log({"type": "detective_queue_full",
                          "ts": datetime.now().isoformat(timespec="seconds")})
            return False

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                frame, labels, now = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            self.escalator.on_dispatch(labels, now=now)
            try:
                res = self.detective.judge(frame, labels)
                decision = res.decision
                decision.setdefault("latency_s", res.latency_s)
                if decision.get("alert"):
                    if not self.escalator.on_alert(time.monotonic()):
                        self.log.log({
                            "type": "alert_cap_hit",
                            "ts": datetime.now().isoformat(timespec="seconds"),
                        })
                        continue
                    snap = None
                    if self.cfg.alert.attach_snapshot:
                        snap = snapshot_save(frame, self.cfg.log.snapshots_dir,
                                              f"alert_{int(time.time())}.jpg")
                    title = "Webcam Guardian alert"
                    body = decision.get("message") or decision.get("reason", "")
                    dispatch_alerts(self.channels, title, body, str(snap) if snap else None, self.log)
                    self.log.log({"type": "alert_dispatched",
                                  "decision": decision})
                self.log.log({
                    "type": "detective_result",
                    "labels": labels,
                    "decision": decision,
                    "latency_s": res.latency_s,
                    "prompt_tokens": res.prompt_tokens,
                    "completion_tokens": res.completion_tokens,
                    "raw_finish_reason": res.raw_finish_reason,
                    "parse_error": res.parse_error,
                    "tool_call_accepted": res.tool_call_accepted,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                self.log.log({"type": "detective_error", "error": repr(e),
                              "labels": labels})


def _with_camera_override(cfg, *, index: int | None = None, backend: str | None = None):
    """Return a new Config with camera.index / camera.backend overridden.

    Config is a frozen dataclass, so we rebuild it. The CameraCfg is the only
    one we touch here.
    """
    from .config import CameraCfg, Config
    new_cam = CameraCfg(
        index=cfg.camera.index if index is None else int(index),
        backend=cfg.camera.backend if backend is None else str(backend),
        width=cfg.camera.width, height=cfg.camera.height,
    )
    return Config(
        camera=new_cam, guard=cfg.guard, escalation=cfg.escalation,
        detective=cfg.detective, alert=cfg.alert, log=cfg.log, raw=cfg.raw,
    )


def _list_cameras_only() -> int:
    """Delegate to scripts/list_cameras.py via subprocess so it parses its own argv."""
    import subprocess
    script = Path(__file__).resolve().parents[1] / "scripts" / "list_cameras.py"
    return subprocess.call([sys.executable, str(script)] + sys.argv[1:])


def _hud_record(hud: HudState, guard_name: str, analyzed_fps: float, camera_fps: float,
                calls: int, cooldowns: dict[str, float], last: str) -> None:
    hud.guard_backend = guard_name
    hud.analyzed_fps = analyzed_fps
    hud.camera_fps = camera_fps
    hud.detective_calls = calls
    hud.cooldowns = cooldowns
    hud.last_decision_summary = last


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="webcam-guardian",
                                     description="Two-tier webcam guardian.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--max-frames", type=int, default=0,
                        help="exit after N frames (0 = until q). used for benchmarks.")
    parser.add_argument("--camera-index", type=int, default=None,
                        help="override camera.index from config.yaml")
    parser.add_argument("--camera-backend", type=str, default=None,
                        choices=["auto", "dshow", "msmf", "avfoundation", "v4l2"],
                        help="override camera.backend from config.yaml")
    parser.add_argument("--list-cameras", action="store_true",
                        help="probe available cameras and exit")
    args = parser.parse_args(argv)

    if args.list_cameras:
        return _list_cameras_only()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    cfg = load(args.config)
    if args.camera_index is not None:
        cfg = _with_camera_override(cfg, index=args.camera_index)
    if args.camera_backend:
        cfg = _with_camera_override(cfg, backend=args.camera_backend)
    print(f"[boot] webcam-guardian v{__version__}")
    print(f"[boot] config={args.config} guard={cfg.guard.backend} detective={cfg.detective.model}")
    print(f"[boot] camera index={cfg.camera.index} backend={cfg.camera.backend}")

    log = EventLog(cfg.log.events_path)
    log.log({"type": "startup", "version": __version__,
             "guard": cfg.guard.backend, "detective": cfg.detective.model,
             "device": resolve_device(cfg.guard.device),
             "ts": datetime.now().isoformat(timespec="seconds")})

    backend = _camera_backend(cfg.camera.backend)
    try:
        cam = LatestFrameCamera(index=cfg.camera.index, backend=backend,
                                width=cfg.camera.width, height=cfg.camera.height)
    except RuntimeError as e:
        print(f"[boot] camera unavailable: {e}\n"
              "[boot] check System Settings → Privacy & Security → Camera "
              "(opencode / Terminal must be allowed).", file=sys.stderr)
        log.log({"type": "startup_error", "error": str(e)})
        log.close()
        return 2

    guard = _make_guard(cfg)
    detective = Detective(cfg.detective, override_prompt_path="guardian/prompts/judge.txt")
    escalator = Escalator(
        debounce_frames=cfg.escalation.debounce_frames,
        cooldown_seconds=cfg.escalation.cooldown_seconds,
        max_detective_calls_per_run=cfg.escalation.max_detective_calls_per_run,
        max_alerts_per_hour=cfg.escalation.max_alerts_per_hour,
    )

    try:
        channels = build_channels(cfg.alert)
    except RuntimeError as e:
        print(f"[boot] no alert channels ({e}); continuing in detect-only mode", file=sys.stderr)
        channels = []

    worker = DetectiveWorker(detective, escalator, channels, log, cfg, frame_provider=None)
    worker.start()

    hud = HudState()
    set_banner(hud, f"READY — guard={guard.name}", 2.0)
    last_analysis = 0.0
    last_guard_stats = 0.0
    fps_window: list[float] = []
    cam_window: list[float] = []
    frames_seen = 0
    last_decision_summary = ""
    t_start = time.monotonic()

    try:
        while True:
            frame = cam.read()
            if frame is None:
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    return 0
                continue
            now = time.monotonic()
            frames_seen += 1
            cam_window.append(now)
            cam_window = [t for t in cam_window if now - t < 1.0]

            interval = 1.0 / max(1, cfg.guard.analyzed_fps)
            if now - last_analysis >= interval:
                t0 = time.monotonic()
                detections = guard.detect(frame)
                analysis_ms = (time.monotonic() - t0) * 1000
                present = {d.label for d in detections if d.label in cfg.guard.trigger_classes}
                fps_window.append(1.0 / max(0.001, (time.monotonic() - t0)))
                fps_window = [t for t in fps_window if now - t < 0.001] or fps_window
                analyzed_fps = sum(fps_window) / max(1, len(fps_window))

                should, labels, _remaining = escalator.observe(present, now)
                if should:
                    if worker.submit(frame.copy(), sorted(labels), now):
                        set_banner(hud, f">>> DETECTIVE CALLED: {','.join(sorted(labels))}",
                                   seconds=2.0)
                        log.log({"type": "escalation_dispatched", "labels": sorted(labels),
                                 "frame": frames_seen,
                                 "ts": datetime.now().isoformat(timespec="seconds")})
                last_analysis = now
                if isinstance(guard, LocateAnythingGuard):
                    guard.submit_frame(frame)
                detect_to_draw = detections
            else:
                detect_to_draw = []
                analyzed_fps = sum(fps_window) / max(1, len(fps_window)) if fps_window else 0.0

            camera_fps = len(cam_window)

            if now - last_guard_stats > 5.0:
                last_guard_stats = now
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                gpu_mb = None
                try:
                    if resolve_device(cfg.guard.device) == "mps":
                        gpu_mb = torch_mps_allocated_mb()
                except Exception:
                    pass
                log.log({
                    "type": "guard_stats",
                    "analyzed_fps": round(analyzed_fps, 2),
                    "camera_fps": camera_fps,
                    "rss_mb": round(rss_mb, 1),
                    "mps_allocated_mb": gpu_mb,
                    "calls": escalator.stats.calls_dispatched,
                    "alerts": escalator.stats.alerts_sent,
                    "cooldown_skips": escalator.stats.cooldown_skips,
                    "cap_hits": escalator.stats.cap_hits,
                })

            _hud_record(hud, guard.name, analyzed_fps, camera_fps,
                        escalator.stats.calls_dispatched,
                        escalator.snapshot_cooldowns(now),
                        last_decision_summary)
            draw_overlay(frame, detect_to_draw, cfg.guard.draw_classes, hud)
            cv2.imshow("Webcam Guardian", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            if args.max_frames and frames_seen >= args.max_frames:
                break
    finally:
        worker.stop()
        worker.join(timeout=3)
        guard.close()
        cam.release()
        cv2.destroyAllWindows()
        log.log({"type": "shutdown", "ts": datetime.now().isoformat(timespec="seconds"),
                 "stats": escalator.stats.__dict__,
                 "frames": frames_seen,
                 "elapsed_s": round(time.monotonic() - t_start, 2)})
        log.close()
    return 0


def torch_mps_allocated_mb() -> float | None:
    import torch
    if hasattr(torch, "mps") and hasattr(torch.mps, "driver_allocated_memory"):
        return round(torch.mps.driver_allocated_memory() / (1024 * 1024), 1)
    return None


if __name__ == "__main__":
    sys.exit(main())
