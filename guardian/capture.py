"""LatestFrameCamera — reader-thread webcam capture.

BUILD-PLAN.md §6.1 (verbatim, semantics preserved).
Trap-list reminders (§13):
  trap 3 — cv2.imshow/waitKey MUST be on the main thread (handled in main.py).
  trap 7 — macOS TCC: denial looks like read() returning no frames, not an error.
  trap 8 — explicit AVFOUNDATION on macOS.
"""

from __future__ import annotations

import sys
import threading

import cv2


def default_backend() -> int:
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    return cv2.CAP_V4L2


class LatestFrameCamera:
    """Reader thread consumes at camera rate; callers always get the newest frame."""

    def __init__(self, index: int = 0, backend: int | None = None,
                 width: int = 1280, height: int = 720) -> None:
        self.cap = cv2.VideoCapture(index, backend if backend is not None else default_backend())
        if not self.cap.isOpened():
            raise RuntimeError(
                f"cannot open camera {index} — check OS camera permission "
                "(BUILD-PLAN §13 trap 7)."
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # best-effort (V4L2 honors)
        self._lock = threading.Lock()
        self._frame = None
        self._stopped = False
        threading.Thread(target=self._reader, daemon=True, name="cam-reader").start()

    def _reader(self) -> None:
        while not self._stopped:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self._frame = frame

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def release(self) -> None:
        self._stopped = True
        try:
            self.cap.release()
        except Exception:
            pass
