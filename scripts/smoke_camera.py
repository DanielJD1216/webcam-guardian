#!/usr/bin/env python3
"""M0 smoke test — open the real webcam, print frame shape, save one JPEG.

Per BUILD-PLAN.md §10 M0 gate:
    "A real JPEG from the real webcam exists.
     (Camera permission prompt handled here, not during the demo.)"

Trap-list reminders respected here:
  §13 trap 7 — macOS TCC attributes the permission to the terminal/opencode host.
               First call triggers the prompt; denial silently returns no frames.
  §13 trap 8 — explicit AVFOUNDATION backend on macOS.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "snapshots"
SNAPSHOT_PATH = SNAPSHOT_DIR / "smoke.jpg"


def default_backend() -> int:
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    return cv2.CAP_V4L2


def open_camera(index: int = 0, width: int = 1280, height: int = 720) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index, default_backend())
    if not cap.isOpened():
        raise RuntimeError(
            f"cannot open camera index={index}. On macOS, grant camera permission "
            "to your terminal (and to opencode if used headless); see BUILD-PLAN §13 trap 7."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def main() -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    cap = open_camera()

    ok, frame = cap.read()
    if not ok or frame is None:
        print("ERROR: camera opened but returned no frame "
              "(macOS TCC denial can look like this; see BUILD-PLAN §13 trap 7)",
              file=sys.stderr)
        cap.release()
        return 2

    h, w = frame.shape[:2]
    print(f"camera frame shape: {w}x{h}x{frame.shape[2] if frame.ndim == 3 else 1}")

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        print("ERROR: JPEG encode failed", file=sys.stderr)
        cap.release()
        return 3

    SNAPSHOT_PATH.write_bytes(buf.tobytes())
    size_kb = SNAPSHOT_PATH.stat().st_size / 1024
    print(f"saved {SNAPSHOT_PATH} ({size_kb:.1f} KB)")

    cap.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
