"""Regression: the alert-dispatch path in DetectiveWorker.run() must
work when cfg.log.snapshots_dir is a plain string (as loaded from YAML).

Caught by scripts/run_e2e.py — without this guard, every real alert
with attach_snapshot=True + save_escalation_frames=True (the production
defaults) crashed at `snapshots_dir / "alert_...jpg"` and never
reached the channel.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from guardian.config import load
from guardian.detective import JudgeResult
from guardian.escalate import Escalator
from guardian.main import DetectiveWorker
from guardian.storage import EventLog


class StubDetective:
    name = "stub"

    def judge(self, frame, guard_labels):
        return JudgeResult(
            decision={"alert": True, "category": "delivery",
                     "reason": "test", "message": "test"},
            latency_s=0.0, prompt_tokens=0, completion_tokens=0,
            raw_finish_reason="stub", parse_error=None, tool_call_accepted=False,
        )


class StubChannel:
    name = "memory"
    sent: list = []

    def send(self, title, body, image_path=None):
        StubChannel.sent.append((title, body, image_path))

    def shutdown(self):
        pass


def test_worker_handles_string_snapshots_dir(tmp_path, monkeypatch):
    """Loading from YAML yields snapshots_dir as a plain str. The
    worker must wrap it before doing path concatenation — otherwise
    every alert crashes at `str / str`.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "camera:\n  index: 0\n  width: 640\n  height: 480\n"
        "guard:\n  backend: rtdetr\n  device: cpu\n  analyzed_fps: 5\n"
        "  draw_classes: [person]\n  trigger_classes: [person]\n"
        "escalation:\n  debounce_frames: 1\n  cooldown_seconds: 0\n"
        "  max_detective_calls_per_run: 4\n  max_alerts_per_hour: 4\n"
        "detective:\n  base_url: https://example.invalid/v1\n"
        "  model: stub\n  api_key_env: STUB_KEY\n"
        "  extra_body: {}\n  timeout_seconds: 5\n"
        "  max_completion_tokens: 100\n  temperature: 0\n"
        "  image_long_side: 1024\n  jpeg_quality: 80\n"
        "  image_detail: low\n  use_tool_call: false\n"
        "alert:\n  channels: [telegram]\n  attach_snapshot: true\n"
        "  telegram_chat_id: \"\"\n  email: {}\n  ntfy_topic: \"\"\n"
        "log:\n  events_path: events.jsonl\n  snapshots_dir: snapshots\n"
        "  save_escalation_frames: true\n  retention_days: 0\n"
    )
    cfg = load(str(tmp_path / "config.yaml"))
    assert isinstance(cfg.log.snapshots_dir, str)

    StubChannel.sent = []
    log = EventLog(str(tmp_path / "events.jsonl"))
    det = StubDetective()
    esc = Escalator(1, 0, 4, 4)
    worker = DetectiveWorker(det, esc, [StubChannel()], log, cfg, frame_provider=None)
    worker.start()

    try:
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        esc.on_dispatch({"person"}, now=time.monotonic())
        worker.submit(frame, ["person"], time.monotonic())
        worker.stop()
        worker.join(timeout=10)
    finally:
        log.close()

    # The single alert must have reached the channel with a valid snapshot
    # path. Before the fix, the worker raised TypeError before dispatch.
    assert len(StubChannel.sent) == 1, f"expected 1 alert, got {len(StubChannel.sent)}"
    title, body, snap = StubChannel.sent[0]
    assert "delivery" in title
    assert snap is not None
    from pathlib import Path
    assert Path(snap).exists(), f"snapshot path does not exist: {snap}"