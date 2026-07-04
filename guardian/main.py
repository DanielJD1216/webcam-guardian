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
import asyncio
import base64
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
from datetime import timezone
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
from .overlay import HudState, draw as draw_overlay, LabelStreakTracker, set_banner
from .storage import EventLog, snapshot_save
from .alerts.base import dispatch as dispatch_alerts, _sanitize_error
from .alerts.factory import build_channels


def _ts() -> str:
    """Audit #63: timezone-aware ISO 8601 (UTC) so the Rust side's
    RFC3339 parser doesn't fall back to Utc::now() on every event.
    UI converts to local for display."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


CAMERA_BACKEND_NAMES = {"auto", "dshow", "msmf", "avfoundation", "v4l2"}

# audit #3 corrected: Tauri webview origin schemes.
# - Production (bundled app): Tauri registers a custom scheme, so the
#   webview sends `tauri://localhost` on Windows/Linux or
#   `http://tauri.localhost` on macOS.
# - Dev mode: the webview loads from `devUrl` directly, so the Origin
#   matches the devUrl (default `http://localhost:1420`). The Tauri
#   Rust side sets `devUrl` in tauri.conf.json — if you change that
#   port, add the new origin here too.
# - Some mobile/Android setups send `null`.
# - Empty Origin: local CLI clients that don't set Origin at all.
_ALLOWED_WS_ORIGINS = frozenset({
    "http://tauri.localhost",
    "tauri://localhost",
    "http://localhost:1420",   # Tauri dev mode default devUrl
    "http://127.0.0.1:1420",   # alt devUrl if user prefers loopback
    "null",
    "",
})


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


class FrameBroadcaster:
    """Latest-frame holder + asyncio WS server.

    The main loop calls `push(jpeg_bytes, w, h, seq)` after every draw. The
    WS server broadcasts to all connected clients — but ONLY when the
    sequence number advances, so a frozen camera does not push the
    same JPEG at 10 Hz and defeat the Tauri UI's staleness detector
    (audit finding #20).

    Audit #3: clients must present the configured token in the URL
    query string (?token=...) or as the first message. Connections
    presenting a browser Origin header are rejected (browsers can't
    sneak in through a local web page).
    """

    def __init__(self, port: int = 9876, token: str = "") -> None:
        self.port = port
        self.token = token
        self._latest: tuple[bytes, int, int, int] | None = None  # (jpeg, w, h, seq)
        self._lock = threading.Lock()
        self._last_broadcast_seq: int = -1
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set = set()
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def push(self, jpeg: bytes, w: int, h: int, seq: int) -> None:
        with self._lock:
            self._latest = (jpeg, w, h, seq)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="ws-broadcaster")
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as e:
            print(f"[ws] server stopped: {e}", file=sys.stderr)

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        from websockets.asyncio.server import serve
        from urllib.parse import parse_qs

        async def handler(conn):
            # audit #3: handshake checks (corrected)
            #
            # 1. URL must carry ?token=<expected> OR the first message
            #    must equal the token (for clients that can't set query).
            # 2. Origin header must be one of the Tauri webview schemes
            #    (`http://tauri.localhost` on macOS, `tauri://localhost`
            #    on Linux/Windows) or `null` (file:// scheme on some
            #    mobile/Android setups). Reject any other Origin so a
            #    cross-origin web page can't subscribe.
            #
            # Audit #3 originally rejected ALL Origins — that broke
            # the Tauri webview, which IS a browser and ALWAYS sends
            # an Origin header. The token is the actual security gate
            # (random 32-byte per-launch secret); the Origin check is
            # defense-in-depth, not the gate.
            request = conn.request
            origin = (request.headers.get("Origin") or "").strip()
            if origin not in _ALLOWED_WS_ORIGINS:
                # Loud on stderr so a future Tauri-version change that
                # shifts the dev origin is immediately diagnosable from
                # the guardian's stderr log (snapshots/guardian-<pid>.stderr.log
                # under Tauri; the terminal under python -m guardian).
                print(f"[ws] reject origin {origin!r} (allowed: "
                      f"{sorted(_ALLOWED_WS_ORIGINS)})", file=sys.stderr, flush=True)
                await conn.close(code=1008, reason=f"origin {origin!r} not allowed")
                return
            # DEBUG: log accepted connections too so we can confirm
            # the path is hit. Removed once #a80 is fully verified.
            print(f"[ws] accept origin {origin!r}", file=sys.stderr, flush=True)

            qs = parse_qs(request.path.split("?", 1)[1] if "?" in request.path else "")
            presented = (qs.get("token", [None])[0] or "").strip()
            print(f"[ws] token check: server={self.token!r} presented={presented!r} match={presented == self.token}",
                  file=sys.stderr, flush=True)
            if self.token:
                if presented == self.token:
                    pass  # URL-token match — proceed.
                elif not presented:
                    # No token in URL; allow the client to present the
                    # token as the first message instead (for clients
                    # that can't set query). Bounded 2 s wait.
                    try:
                        first = await asyncio.wait_for(conn.recv(), timeout=2.0)
                    except Exception:
                        first = None
                    if not (isinstance(first, (str, bytes))
                            and self._extract_token(first) == self.token):
                        await conn.close(code=1008, reason="bad or missing token")
                        return
                else:
                    # Wrong token presented in URL — reject immediately.
                    # Don't burn 2 s on the wait_for fallback: presenting
                    # a wrong token is a hard fail, not a soft one.
                    print(f"[ws] reject: token mismatch (presented={presented!r})",
                          file=sys.stderr, flush=True)
                    await conn.close(code=1008, reason="bad token")
                    return

            self._clients.add(conn)
            print(f"[ws] client added (n={len(self._clients)})", file=sys.stderr, flush=True)
            try:
                async for msg in conn:
                    # DEBUG: surface any message the client sends so we
                    # can see if the UI is sending keepalives or
                    # close handshakes that we didn't expect.
                    print(f"[ws] msg from client: {msg!r}",
                          file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[ws] client loop exception: {e!r}",
                      file=sys.stderr, flush=True)
            finally:
                self._clients.discard(conn)
                print(f"[ws] client removed (n={len(self._clients)})",
                      file=sys.stderr, flush=True)

        async def periodic():
            while not self._stopped.is_set():
                await asyncio.sleep(0.1)
                frame = None
                with self._lock:
                    frame = self._latest
                if not frame or not self._clients:
                    continue
                # audit #20: only broadcast when the camera produced a
                # NEW frame since the last broadcast. A frozen camera
                # (same seq across polls) leaves the UI staleness
                # detector able to fire.
                _, _, _, seq = frame
                if seq == self._last_broadcast_seq:
                    continue
                self._last_broadcast_seq = seq
                payload = f"{frame[1]}x{frame[2]}\n".encode() + frame[0]
                dead = []
                for c in list(self._clients):
                    try:
                        await c.send(payload)
                    except Exception as e:
                        print(f"[ws] send failed: {e!r}",
                              file=sys.stderr, flush=True)
                        dead.append(c)
                for d in dead:
                    self._clients.discard(d)
        server = await serve(handler, "127.0.0.1", self.port)
        print(f"[ws] frame broadcaster listening on ws://127.0.0.1:{self.port} (token-gated)", flush=True)
        try:
            await asyncio.gather(server.wait_closed(), periodic())
        except asyncio.CancelledError:
            pass
        server.close()

    @staticmethod
    def _extract_token(msg) -> str:
        s = msg.decode() if isinstance(msg, (bytes, bytearray)) else msg
        s = s.strip()
        if s.startswith("{"):
            import json
            try:
                return str(json.loads(s).get("token", ""))
            except Exception:
                return ""
        return s


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
        self._stop_event = threading.Event()  # e2e/a79: was self._stop — shadowed threading.Thread._stop() called from join()
        self._frame_provider = frame_provider  # for snapshot save

    def submit(self, frame_copy, labels: list[str], now: float) -> bool:
        try:
            self.q.put_nowait((frame_copy, list(labels), now))
            return True
        except queue.Full:
            self.log.log({"type": "detective_queue_full",
                          "ts": _ts()})
            return False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame, labels, now = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            # audit #5/#78: cooldown is now charged at submit time on the
            # main thread (see main loop). The worker no longer mutates
            # the escalator's per-class cooldowns — that would
            # otherwise race with the main thread's observe() check.
            try:
                res = self.detective.judge(frame, labels)
                decision = res.decision
                decision.setdefault("latency_s", res.latency_s)
                # audit #58: log.save_escalation_frames now controls
                # whether every escalated frame is persisted to disk
                # (independent of whether it becomes an alert). The
                # 'attach_snapshot' config below decides whether the
                # most-recently-saved frame is included in the alert
                # delivery. The two are no longer conflated.
                escalation_id = f"escalation_{int(time.time()*1000):013d}"
                snap_dir = Path(self.cfg.log.snapshots_dir)  # e2e/a78: was str→str TypeError when alert.attach_snapshot=True and save_escalation_frames=True
                if self.cfg.log.save_escalation_frames:
                    try:
                        snapshot_save(
                            frame, snap_dir,
                            f"{escalation_id}.jpg",
                        )
                    except Exception as e:
                        self.log.log({
                            "type": "snapshot_save_error",
                            "id": escalation_id,
                            "error": _sanitize_error(repr(e)),
                        })
                if decision.get("alert"):
                    if not self.escalator.on_alert(time.monotonic()):
                        self.log.log({
                            "type": "alert_cap_hit",
                            "ts": _ts(),
                        })
                        continue
                    alert_id = f"alert_{int(time.time()*1000):013d}"
                    snap = None
                    if self.cfg.alert.attach_snapshot:
                        # Reuse the escalation snapshot (above) if
                        # available — same frame, alert_id-prefixed
                        # name keeps the alert gallery organized. If
                        # save_escalation_frames is off, save fresh.
                        if self.cfg.log.save_escalation_frames:
                            snap = snap_dir / f"{escalation_id}.jpg"
                        else:
                            try:
                                snap = snapshot_save(
                                    frame, snap_dir,
                                    f"{alert_id}.jpg",
                                )
                            except Exception as e:
                                # audit #17: snapshot failure must
                                # NOT drop the alert.
                                self.log.log({"type": "snapshot_save_error",
                                              "alert_id": alert_id,
                                              "error": _sanitize_error(repr(e))})
                    category = decision.get("category", "alert")
                    # audit #74: include the local TZ in the alert
                    # body so a user reviewing alerts in Telegram
                    # after travel knows whether "2:00" was home-TZ
                    # or away-TZ. The model gives a relative
                    # description; the absolute timestamp is ours.
                    from datetime import datetime
                    local_tz = datetime.now().astimezone().strftime("%Z")
                    title = f"Webcam Guardian · {category} ({local_tz})"
                    message = (decision.get("message") or "").strip()
                    reason = (decision.get("reason") or "").strip()
                    body = message or reason or f"{category} detected"
                    body = f"{body}  ·  {_ts().replace('+00:00', ' UTC')}"
                    # audit #61: only credit the hourly alert cap if
                    # at least one channel delivered (or we retried
                    # the transient network and all failed). The
                    # dispatch() helper handles per-channel retry +
                    # error sanitization.
                    delivery = dispatch_alerts(
                        self.channels, alert_id, title, body,
                        str(snap) if snap else None, self.log,
                    )
                    if delivery["delivered"]:
                        self.log.log({
                            "type": "alert_dispatched",
                            "alert_id": alert_id,
                            "category": category,
                            "decision": decision,
                            "snapshot": str(snap) if snap else None,
                            "delivered": delivery["delivered"],
                            "failed": delivery["failed"],
                        })
                    else:
                        # every channel errored even after retries;
                        # do NOT credit the hourly cap (user got no
                        # alert) — log a distinct event so auditing
                        # can distinguish a real successful alert
                        # from a fully-failed one.
                        self.log.log({
                            "type": "alert_delivery_failed",
                            "alert_id": alert_id,
                            "category": category,
                            "decision": decision,
                            "channels": delivery["failed"],
                        })
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
                    "ts": _ts(),
                })
            except Exception as e:
                self.log.log({"type": "detective_error",
                              "error": _sanitize_error(repr(e)),
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
    """Delegate to scripts/list_cameras.py via subprocess with no argv pollution.

    Forwards only --max-index (the only flag list_cameras.py understands);
    anything else from sys.argv is intentionally dropped so callers don't have
    to know the inner script's arg parser.
    """
    import subprocess
    argv = sys.argv[1:]
    forwarded: list[str] = []
    skip_next = False
    for tok in argv:
        if skip_next:
            skip_next = False
            continue
        if tok in ("--max-index", "-w", "-h") or tok.startswith("--max-index="):
            forwarded.append(tok)
            if "=" not in tok:
                skip_next = True
        elif tok.startswith("--width=") or tok.startswith("--height="):
            forwarded.append(tok)
    script = Path(__file__).resolve().parents[1] / "scripts" / "list_cameras.py"
    return subprocess.call([sys.executable, str(script)] + forwarded)


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
    parser.add_argument("--no-imshow", action="store_true",
                        help="skip cv2.imshow (use when embedded in Tauri)")
    parser.add_argument("--ws-port", type=int, default=9876,
                        help="WebSocket port for live preview frame stream (Tauri)")
    parser.add_argument("--ws-token", type=str, default="",
                        help="audit #3: required token in WS URL (?token=...) "
                             "to gate the live-feed socket against local attackers.")
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
    print(f"[boot] camera index={cfg.camera.index} backend={cfg.camera.backend} "
          f"imshow={not args.no_imshow} ws_port={args.ws_port}")

    log = EventLog(cfg.log.events_path)
    log.log({"type": "startup", "version": __version__,
             "guard": cfg.guard.backend, "detective": cfg.detective.model,
             "device": resolve_device(cfg.guard.device),
             "ts": _ts()})

    # audit #66 follow-up: GDPR/CCPA storage-limitation. When
    # log.retention_days > 0, prune snapshots and events older than
    # that many days at startup. Default is 0 (off) for backwards
    # compat; the README Privacy section suggests a positive value
    # for self-hosters concerned about retention.
    if cfg.log.retention_days > 0:
        from .storage import prune_older_than
        n_snap, n_event = prune_older_than(
            cfg.log.snapshots_dir, cfg.log.events_path,
            cfg.log.retention_days,
        )
        if n_snap or n_event:
            log.log({"type": "retention_sweep",
                      "deleted_snapshots": n_snap,
                      "deleted_event_lines": n_event,
                      "kept_days": cfg.log.retention_days,
                      "ts": _ts()})

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

    broadcaster = FrameBroadcaster(port=args.ws_port, token=args.ws_token)
    broadcaster.start()

    hud = HudState()
    streak = LabelStreakTracker()
    set_banner(hud, f"READY — guard={guard.name}", 2.0)
    last_analysis = 0.0
    last_guard_stats = 0.0
    fps_window: list[float] = []
    cam_window: list[float] = []
    frames_seen = 0
    last_decision_summary = ""
    cached_detections: list = []   # boxes held between analyzed frames so the
                                  # overlay doesn't blink at camera fps (30)
    t_start = time.monotonic()
    last_frame_seq = 0             # audit #1: detect camera stall via seq
    last_stall_log_ts = 0.0        # throttle camera_stalled events to 1 / 5s
    camera_lost_at = 0.0          # audit #62: time we first noticed no new frames
    camera_lost_alerted = False   # whether the one-shot "camera offline" alert has fired

    try:
        while True:
            frame, seq, cap_t = cam.read()
            if frame is None:
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    return 0
                continue
            now = time.monotonic()
            frames_seen += 1
            cam_window.append(cap_t)
            cam_window = [t for t in cam_window if now - t < 1.0]

            # audit #1: if the camera isn't producing fresh frames,
            # log a stall event (throttled to once per 5 s). Without
            # this the guardian happily re-analyzes a frozen frame.
            #
            # The audit #1 check used `seq == last_frame_seq` as the
            # "is the frame stale" signal. That fires when the main
            # loop polls faster than the camera produces (which is
            # the *normal* case — 100 Hz loop vs 30 Hz camera). The
            # real signal is the capture_monotonic timestamp: if
            # `now - cap_t > 1.0`, the camera genuinely hasn't
            # produced a fresh frame in over a second, and that is
            # the actual stall we want to log. (a83)
            #
            # audit #62: after ~5 s of no new frames, also dispatch
            # an infra alert (bypassing the detective) so the user
            # is told the system is blind. When frames resume, fire a
            # "camera restored" alert and reset the flag.
            is_stale_frame = (cap_t > 0.0 and (now - cap_t) > 1.0)
            if is_stale_frame:
                if camera_lost_at == 0.0:
                    camera_lost_at = now
                since = now - (cap_t or camera_lost_at)
                if since > 5.0 and not camera_lost_alerted:
                    camera_lost_alerted = True
                    log.log({
                        "type": "camera_lost",
                        "since_s": round(since, 1),
                        "ts": _ts(),
                    })
                    from datetime import datetime
                    offline_msg = (
                        f"Camera signal lost at "
                        f"{datetime.now().astimezone().strftime('%H:%M %Z')}. "
                        f"Last frame {round(since)}s ago. "
                        f"Monitoring is paused until the camera reconnects."
                    )
                    dispatch_alerts(
                        self.channels,
                        f"camera_offline_{int(now*1000):013d}",
                        "Webcam Guardian · camera_offline",
                        offline_msg,
                        None, log,
                    )
                if now - last_stall_log_ts > 5.0:
                    log.log({
                        "type": "camera_stalled",
                        "last_seq": seq,
                        "since_s": round(since, 1),
                        "ts": _ts(),
                    })
                    last_stall_log_ts = now
                last_frame_seq = seq  # keep last_frame_seq current even when stale
            else:
                last_frame_seq = seq
                if camera_lost_alerted:
                    from datetime import datetime
                    recovered_at = datetime.now().astimezone().strftime('%H:%M %Z')
                    log.log({
                        "type": "camera_restored",
                        "ts": _ts(),
                    })
                    dispatch_alerts(
                        self.channels,
                        f"camera_restored_{int(now*1000):013d}",
                        "Webcam Guardian · camera_restored",
                        f"Camera signal recovered at {recovered_at}.",
                        None, log,
                    )
                    camera_lost_at = 0.0
                    camera_lost_alerted = False

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
                    # audit #5/#78: charge the per-class cooldown HERE, at
                    # submit time on the main thread. The worker's
                    # on_dispatch() is now a no-op (a class invariant
                    # documented in the worker). This prevents a slow
                    # M3 call (or a worker stuck in judge()) from
                    # leaving the cooldown uncharged, which let a
                    # still-eligible label pass observe() and enqueue
                    # a second copy while the first was still in flight.
                    escalator.on_dispatch(labels, now=now)
                    if worker.submit(frame.copy(), sorted(labels), now):
                        set_banner(hud, f">>> DETECTIVE CALLED: {','.join(sorted(labels))}",
                                   seconds=2.0)
                        log.log({"type": "escalation_dispatched", "labels": sorted(labels),
                                 "frame": frames_seen,
                                 "ts": _ts()})
                last_analysis = now
                if isinstance(guard, LocateAnythingGuard):
                    guard.submit_frame(frame)
                cached_detections = detections
            else:
                analyzed_fps = sum(fps_window) / max(1, len(fps_window)) if fps_window else 0.0
            detect_to_draw = cached_detections

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
            draw_overlay(frame, detect_to_draw, cfg.guard.draw_classes, hud,
                         streak, min_streak=cfg.guard.draw_min_streak)
            if not args.no_imshow:
                cv2.imshow("Webcam Guardian", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            else:
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                ok_jpg, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok_jpg:
                    broadcaster.push(jpg.tobytes(), frame.shape[1], frame.shape[0], seq)

            if args.max_frames and frames_seen >= args.max_frames:
                break
    finally:
        worker.stop()
        worker.join(timeout=3)
        broadcaster.stop()
        guard.close()
        cam.release()
        cv2.destroyAllWindows()
        log.log({"type": "shutdown", "ts": _ts(),
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
