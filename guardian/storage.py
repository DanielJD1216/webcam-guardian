"""EventLog — JSONL, append-only, write→flush→fsync per event.

Per BUILD-PLAN.md §3.3 glue layer:
   "JSONL, append-only, write → flush() → os.fsync() per event (crash-safe).
    SQLite is overkill for a single-process prototype."
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping


class EventLog:
    """Crash-safe JSONL log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.path, "a", encoding="utf-8")
        self._lock = threading.Lock()

    def log(self, event: Mapping[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            self._fp.write(line + "\n")
            self._fp.flush()
            os.fsync(self._fp.fileno())

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
