"""LatestFrameCamera — reader-thread webcam capture.

BUILD-PLAN.md §6.1 (verbatim, semantics preserved).
Trap-list reminders (§13):
  trap 3 — cv2.imshow/waitKey MUST be on the main thread (handled in main.py).
  trap 7 — macOS TCC: denial looks like read() returning no frames, not an error.
  trap 8 — explicit AVFOUNDATION on macOS.

Audit review additions:
  - Each captured frame is stamped with a monotonic capture_time and a
    sequence number so consumers (the main loop, the WS broadcaster)
    can tell a fresh frame from a frozen one. This is the core
    mitigation for audit finding #1 (silent camera stall): without
    a sequence, the main loop happily re-analyzes the last good frame
    forever while reporting healthy fps.
  - The reader increments sequence/time on every successful read but
    never clears them. read() returns (None, 0, 0) when the camera
    has never produced a frame yet; (frame, seq, t) on every call.
    - The shutdown race (audit #1 low) is partially mitigated by
      exposing the reader Thread handle so callers can join it.
"""

from __future__ import annotations

import sys
import threading
import time

import cv2


def default_backend() -> int:
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    return cv2.CAP_V4L2


class LatestFrameCamera:
    """Reader thread consumes at camera rate; callers always get the newest frame.

    Returned tuple: (frame_bgr_or_None, sequence, capture_monotonic).
    Sequence starts at 0 and increments by 1 per successful frame.
    A repeat sequence means a frozen frame (camera stalled or revoked);
    the main loop should treat that as a fault.
    """

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
        self._seq: int = 0
        self._capture_time: float = 0.0
        self._stopped = False
        self._thread = threading.Thread(target=self._reader, daemon=True, name="cam-reader")
        self._thread.start()

    def _reader(self) -> None:
        while not self._stopped:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
                    self._seq += 1
                    self._capture_time = time.monotonic()

    def read(self):
        """Returns (frame_or_None, sequence, capture_monotonic)."""
        with self._lock:
            if self._frame is None:
                return (None, 0, 0.0)
            return (self._frame.copy(), self._seq, self._capture_time)

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def last_ok_monotonic(self) -> float:
        """audit #62: monotonic time of the last successful
        cap.read() — main loop uses this to detect a camera stall."""
        with self._lock:
            return self._capture_time

    def release(self) -> None:
        self._stopped = True
        # Audit #1 low: don't release cap while reader may be inside read().
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self.cap.release()
        except Exception:
            pass
