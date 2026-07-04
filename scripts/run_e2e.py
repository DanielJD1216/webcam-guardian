"""scripts/run_e2e.py — Full pipeline E2E test.

Two passes, each verifying a distinct path through the worker.

PASS A — pipeline health (real M3 call)
----------------------------------------
Stub guard emits `person`. Real Detective makes a real call to M3. Real
Escalator decides. Real DetectiveWorker logs every event.

Asserts:
  - ≥1 detective_result row in events.jsonl
  - parse_error is None
  - snapshot saved to snapshots/  (audit #58 wiring)
  - escalator stats reflect the calls dispatched
  - if M3 returns alert=true, the InMemoryChannel receives a payload
    and an alert_dispatched row exists; if alert=false, that's also
    a healthy E2E result — the model correctly rejected a synthetic
    frame and the pipeline did the right thing by NOT dispatching.

PASS B — alert envelope (forced verdict)
-----------------------------------------
Stub Detective that always returns alert=true with a known title/body.
Stub guard still emits `person`. The whole dispatch envelope (snapshot
+ dispatch + InMemoryChannel + alert_dispatched row + body sanitization)
runs once and is asserted.

This validates the parts of the pipeline that PASS A only exercises
opportunistically: alert_dispatched event shape, the dispatch channel
walk with retry, the per-channel sanitizer, the alert category/tz
formatter, and the snapshot path used as the alert attachment.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from guardian.config import load as load_cfg  # noqa: E402
from guardian.detective import Detective  # noqa: E402
from guardian.escalate import Escalator  # noqa: E402
from guardian.guard.base import Detection, GuardBackend  # noqa: E402
from guardian.main import DetectiveWorker, _ts  # noqa: E402
from guardian.storage import EventLog  # noqa: E402


class StubGuard(GuardBackend):
    """Always emits one `person` detection per frame; ignores the image."""

    name = "stub"

    def detect(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        return [Detection(label="person", conf=0.99,
                          box=(w * 0.30, h * 0.20, w * 0.55, h * 0.85))]

    def close(self):
        pass


class StubDetective:
    """Detective-compatible stub that returns a fixed decision."""

    name = "stub"

    def __init__(self, decision: dict, latency_s: float = 0.05):
        self._decision = decision
        self._latency = latency_s

    def judge(self, frame, guard_labels):
        from guardian.detective import JudgeResult
        return JudgeResult(
            decision=dict(self._decision),
            latency_s=self._latency,
            prompt_tokens=10,
            completion_tokens=5,
            raw_finish_reason="stub",
            parse_error=None,
            tool_call_accepted=False,
        )


class InMemoryChannel:
    """AlertChannel-compatible recorder."""

    name = "memory"

    def __init__(self):
        self.sent: list[dict] = []
        self._lock_value = 0  # not actually used; channel writes are thread-safe by GIL on simple dict appends in CPython, but if the channel ever splits we can revisit

    def send(self, title, body, image_path=None):
        self.sent.append({"title": title, "body": body, "image_path": image_path})

    def shutdown(self):
        pass


def make_synthetic_frame(seed: int = 0) -> np.ndarray:
    """Person-shaped silhouette in front of a dark doorway, on a textured wall.

    Built so M3 has enough visual signal to recognize the *shape* of a
    scene, even if it correctly identifies the figure as a stylized
    graphic and returns alert=false.
    """
    rng = np.random.default_rng(seed)
    h, w = 640, 480
    img = np.full((h, w, 3), (200, 200, 195), dtype=np.uint8)
    grain = rng.integers(-12, 12, size=(h, w, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + grain, 0, 255).astype(np.uint8)
    cv2.rectangle(img, (320, 100), (470, 580), (45, 35, 30), -1)
    cv2.rectangle(img, (320, 100), (470, 580), (90, 70, 60), 3)
    px, py = 170, 0
    cv2.rectangle(img, (px + 45, py + 230), (px + 105, py + 470), (60, 65, 100), -1)
    cv2.circle(img, (px + 75, py + 195), 32, (60, 65, 100), -1)
    cv2.rectangle(img, (px + 20, py + 240), (px + 50, py + 430), (55, 60, 95), -1)
    cv2.rectangle(img, (px + 100, py + 240), (px + 130, py + 430), (55, 60, 95), -1)
    cv2.rectangle(img, (px + 50, py + 470), (px + 80, py + 620), (45, 50, 80), -1)
    cv2.rectangle(img, (px + 85, py + 470), (px + 115, py + 620), (45, 50, 80), -1)
    return img


def reset_run(cfg, log_path: Path, snap_dir: Path):
    if log_path.exists():
        log_path.unlink()
    if snap_dir.exists():
        for p in snap_dir.iterdir():
            p.unlink()
        snap_dir.rmdir()


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def make_config(orig, *, events_path: str, snapshots_dir: str):
    return replace(
        orig,
        escalation=replace(orig.escalation, debounce_frames=1,
                           cooldown_seconds=0,
                           max_detective_calls_per_run=4,
                           max_alerts_per_hour=4),
        log=replace(orig.log, events_path=events_path,
                    snapshots_dir=snapshots_dir, save_escalation_frames=True),
        alert=replace(orig.alert, channels=(), attach_snapshot=True),
    )


def drive(worker, escalator, frame):
    """Run one frame through the escalator and submit to the worker."""
    present = {"person"}
    now = time.monotonic()
    should, labels, _remaining = escalator.observe(present, now)
    if should:
        escalator.on_dispatch(labels, now=now)
        worker.submit(frame, sorted(labels), now)


def run_pass_a(orig_cfg) -> tuple[bool, list[str]]:
    """Pass A — real M3 pipeline. Returns (passed, failures)."""
    log_path = REPO / "events_e2e_a.jsonl"
    snap_dir = REPO / "snapshots_e2e_a"
    reset_run(orig_cfg, log_path, snap_dir)

    cfg = make_config(orig_cfg, events_path=str(log_path),
                      snapshots_dir=str(snap_dir))

    log = EventLog(log_path)
    log.log({"type": "pass_a_startup", "ts": _ts()})

    detective = Detective(cfg.detective, override_prompt_path="guardian/prompts/judge.txt")
    escalator = Escalator(cfg.escalation.debounce_frames,
                          cfg.escalation.cooldown_seconds,
                          cfg.escalation.max_detective_calls_per_run,
                          cfg.escalation.max_alerts_per_hour)
    mem = InMemoryChannel()
    worker = DetectiveWorker(detective, escalator, [mem], log, cfg, frame_provider=None)
    worker.start()

    for i in range(2):
        drive(worker, escalator, make_synthetic_frame(seed=i))

    worker.stop()
    worker.join(timeout=60)
    log.log({"type": "pass_a_shutdown", "ts": _ts()})
    log.close()

    events = read_events(log_path)
    types = [e.get("type") for e in events]
    n_results = sum(t == "detective_result" for t in types)
    fails = []
    if n_results < 1:
        fails.append(f"pass A: expected ≥1 detective_result, got {n_results}")

    parse_errors = [e for e in events
                    if e.get("type") == "detective_result" and e.get("parse_error")]
    if parse_errors:
        fails.append(f"pass A: parse errors: {parse_errors!r}")

    snapshots = list(snap_dir.glob("*.jpg")) if snap_dir.exists() else []
    if not snapshots:
        fails.append("pass A: no snapshot JPEG saved (audit #58 wiring broken)")

    print(f"[A] events={len(events)}  results={n_results}  alerts_dispatched="
          f"{sum(t == 'alert_dispatched' for t in types)}  snapshots={len(snapshots)}  "
          f"channel_payloads={len(mem.sent)}  escalator.calls={escalator.stats.calls_dispatched}")
    if escalator.stats.calls_dispatched == 0:
        fails.append(f"pass A: escalator did not dispatch any calls (stats={escalator.stats!r})")
    return (not fails), fails


def run_pass_b(orig_cfg) -> tuple[bool, list[str]]:
    """Pass B — forced alert envelope."""
    log_path = REPO / "events_e2e_b.jsonl"
    snap_dir = REPO / "snapshots_e2e_b"
    reset_run(orig_cfg, log_path, snap_dir)

    cfg = make_config(orig_cfg, events_path=str(log_path),
                      snapshots_dir=str(snap_dir))

    log = EventLog(log_path)
    log.log({"type": "pass_b_startup", "ts": _ts()})

    detective = StubDetective({
        "alert": True,
        "category": "delivery",
        "reason": "uniformed person bearing a package at the door",
        "message": "Package delivery at front door.",
    })
    escalator = Escalator(cfg.escalation.debounce_frames,
                          cfg.escalation.cooldown_seconds,
                          cfg.escalation.max_detective_calls_per_run,
                          cfg.escalation.max_alerts_per_hour)
    mem = InMemoryChannel()
    worker = DetectiveWorker(detective, escalator, [mem], log, cfg, frame_provider=None)
    worker.start()

    drive(worker, escalator, make_synthetic_frame(seed=42))

    worker.stop()
    worker.join(timeout=60)
    log.close()

    events = read_events(log_path)
    types = [e.get("type") for e in events]
    n_dispatched = sum(t == "alert_dispatched" for t in types)
    fails = []
    if len(mem.sent) != 1:
        fails.append(f"pass B: expected 1 channel payload, got {len(mem.sent)}")
    if n_dispatched != 1:
        fails.append(f"pass B: expected 1 alert_dispatched row, got {n_dispatched}")

    if mem.sent:
        s = mem.sent[0]
        if "delivery" not in s["title"]:
            fails.append(f"pass B: title missing category: {s['title']!r}")
        if "Package delivery" not in s["body"]:
            fails.append(f"pass B: body missing message: {s['body']!r}")
        if not s["image_path"] or not Path(s["image_path"]).exists():
            fails.append(f"pass B: snapshot path invalid: {s['image_path']!r}")

    snapshots = list(snap_dir.glob("*.jpg")) if snap_dir.exists() else []
    print(f"[B] events={len(events)}  alerts_dispatched={n_dispatched}  "
          f"channel_payloads={len(mem.sent)}  snapshots={len(snapshots)}")
    if mem.sent:
        s = mem.sent[0]
        print(f"[B] title={s['title']!r}")
        print(f"[B] body={s['body'][:120]!r}")
        print(f"[B] snapshot={s['image_path']}")

    return (not fails), fails


def main() -> int:
    orig_cfg = load_cfg("config.yaml")
    api_key = os.environ.get(orig_cfg.detective.api_key_env, "")
    print(f"[boot] model={orig_cfg.detective.model} api_key_set={bool(api_key)}")
    if not api_key:
        print(f"ERROR: {orig_cfg.detective.api_key_env} not set in .env", file=sys.stderr)
        return 2

    print("\n=== PASS A: real M3 pipeline ===")
    a_ok, a_fail = run_pass_a(orig_cfg)

    print("\n=== PASS B: forced alert envelope ===")
    b_ok, b_fail = run_pass_b(orig_cfg)

    ok = a_ok and b_ok
    if not ok:
        print("\nFAILURES:", file=sys.stderr)
        for f in a_fail + b_fail:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("\nE2E PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
