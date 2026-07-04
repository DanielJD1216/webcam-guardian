"""EventLog — JSONL, append-only, write→flush→fsync per event.

Per BUILD-PLAN.md §3.3 glue layer:
   "JSONL, append-only, write → flush() → os.fsync() per event (crash-safe).
    SQLite is overkill for a single-process prototype."

Audit #54:
- log() never raises; failures fall back to stderr. The detective
  worker previously could die if a log() inside its except handler
  raised, killing the only consumer of the queue and silently
  starving alerts.
- NaN/Infinity from model output round-trips into invalid JSONL
  lines (bare `NaN` is not valid JSON; serde_json drops the line
  silently in the Tauri log viewer). sanitize_nan() converts
  non-finite floats to None so the line is always valid JSON.
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from pathlib import Path
from typing import Any, Mapping


def sanitize_nan(obj: Any) -> Any:
    """Recursively replace NaN / +Inf / -Inf floats with None so the
    resulting JSON is always parseable. audit #54."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_nan(v) for v in obj]
    return obj


class EventLog:
    """Crash-safe JSONL log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.path, "a", encoding="utf-8")
        self._lock = threading.Lock()

    def log(self, event: Mapping[str, Any]) -> None:
        # audit #54: allow_nan=False (NaN/Inf → ValueError). Catch
        # OSError on write/flush/fsync (disk full, etc.) and fall
        # back to stderr so a log failure can't kill the worker.
        try:
            clean = sanitize_nan(dict(event))
            line = json.dumps(clean, ensure_ascii=False, default=str,
                              allow_nan=False)
        except (TypeError, ValueError) as e:
            print(f"[EventLog] sanitize/serialize failed: {e!r}", file=sys.stderr)
            return
        try:
            with self._lock:
                self._fp.write(line + "\n")
                self._fp.flush()
                os.fsync(self._fp.fileno())
        except (OSError, ValueError) as e:
            # audit #54: never raise from log(). The detective worker
            # previously could die here, silently starving alerts.
            # Catch OSError (real I/O failures: disk full, EPERM) and
            # ValueError (closed file, unsupported operation) — both
            # indicate a permanently-bad file handle, not a transient
            # condition worth retrying.
            print(f"[EventLog] write failed for {self.path}: {e!r}",
                  file=sys.stderr)

    def close(self) -> None:
        with self._lock:
            try:
                self._fp.flush()
                os.fsync(self._fp.fileno())
                self._fp.close()
            except Exception:
                pass


def snapshot_save(frame, snapshots_dir: str | Path, name: str, quality: int = 85) -> Path:
    """Save a JPEG snapshot next to events.jsonl. Returns the saved path."""
    import cv2  # local import keeps storage testable without opencv

    out_dir = Path(snapshots_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    target.write_bytes(buf.tobytes())
    return target
