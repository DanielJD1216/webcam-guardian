"""Regression: camera_stalled must NOT spam the log when the main loop
polls faster than the camera produces fresh frames (a83).

Original logic: \`seq == last_frame_seq\` -> stall. Fires every poll when
the loop runs at 100 Hz but the camera only produces 30 Hz, since
\`read()\` returns the same seq until the reader thread advances it.
Fixed: stall fires only when \`now - cap_t > 1.0\` (the actual
capture-monotonic clock says the camera hasn't produced a fresh frame).
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace


class FakeCam:
    """Stand-in for LatestFrameCamera with controllable timing."""

    def __init__(self, frame, seq, cap_t):
        self._frame = frame
        self._seq = seq
        self._cap_t = cap_t

    def read(self):
        return (self._frame, self._seq, self._cap_t)


def _is_stale(now: float, cap_t: float) -> bool:
    """Mirror the post-a83 guard from main.py."""
    return cap_t > 0.0 and (now - cap_t) > 1.0


def test_poll_faster_than_camera_is_not_stale():
    """100 Hz main loop, 30 Hz camera: every poll after a frame
    arrives still sees the same seq but cap_t is fresh.
    """
    cam = FakeCam(frame=object(), seq=42, cap_t=100.0)
    now = 100.05  # 50 ms after capture — frame is fresh
    assert _is_stale(now, cam.read()[2]) is False


def test_no_frame_for_over_one_second_is_stale():
    """Camera produced a frame at t=100, main loop sees it at t=101.5
    (1.5 s later, no new frames) — this IS a stall.
    """
    cam = FakeCam(frame=object(), seq=42, cap_t=100.0)
    now = 101.5
    assert _is_stale(now, cam.read()[2]) is True


def test_exactly_one_second_boundary():
    """Boundary case: 1.0 s is NOT stale (must be strictly greater)."""
    cam = FakeCam(frame=object(), seq=42, cap_t=100.0)
    now = 101.0
    assert _is_stale(now, cam.read()[2]) is False


def test_zero_cap_t_not_stale():
    """cap_t == 0 means no frame yet; not a stall condition."""
    cam = FakeCam(frame=object(), seq=0, cap_t=0.0)
    now = 200.0
    assert _is_stale(now, cam.read()[2]) is False