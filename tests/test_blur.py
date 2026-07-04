"""Tests for guardian.storage.blur_person_boxes (audit #66)."""

from __future__ import annotations

import numpy as np


def _solid_frame(h=240, w=320, color=(120, 120, 120)):
    return np.full((h, w, 3), color, dtype=np.uint8)


def test_blur_person_boxes_no_boxes_returns_same_frame():
    """With no boxes we return the input unchanged."""
    from guardian.storage import blur_person_boxes

    frame = _solid_frame()
    out = blur_person_boxes(frame, [])
    assert out is frame, "with no boxes, original frame should be returned as-is"


def test_blur_person_boxes_zero_top_fraction_returns_same_frame():
    """top_fraction=0 disables blurring; the function returns input unchanged."""
    from guardian.storage import blur_person_boxes

    frame = _solid_frame()
    boxes = [(50, 50, 150, 200)]
    out = blur_person_boxes(frame, boxes, top_fraction=0.0)
    assert out is frame


def test_blur_person_boxes_modifies_top_region():
    """The top portion of a person box must differ from the input
    while the rest of the box remains untouched.
    """
    from guardian.storage import blur_person_boxes

    # Frame with checkerboard texture in the box area so blur is observable.
    yy, xx = np.indices((300, 300))
    frame = np.where((xx // 8 + yy // 8) % 2 == 0, 200, 50).astype(np.uint8)
    frame = np.stack([frame] * 3, axis=-1)

    boxes = [(50, 50, 150, 250)]  # x1,y1,x2,y2
    out = blur_person_boxes(frame, boxes, top_fraction=0.4)

    # The bottom half of the box must be unchanged.
    assert np.array_equal(out[180:240, 50:150], frame[180:240, 50:150])
    # The top region should be visibly different (blur softened the texture).
    assert not np.array_equal(out[50:115, 50:150], frame[50:115, 50:150])


def test_blur_person_boxes_clips_out_of_bounds():
    """Boxes that extend past the frame must be clipped, not crash."""
    from guardian.storage import blur_person_boxes

    yy, xx = np.indices((200, 200))
    frame = np.where((xx // 4 + yy // 4) % 2 == 0, 200, 50).astype(np.uint8)
    frame = np.stack([frame] * 3, axis=-1)
    boxes = [(-100, -100, 100, 100), (180, 180, 9999, 9999)]
    out = blur_person_boxes(frame, boxes)
    assert out.shape == frame.shape
    # Some region near the origin should have changed.
    assert not np.array_equal(out[0:30, 0:30], frame[0:30, 0:30])


def test_blur_person_boxes_does_not_mutate_input():
    """The caller-owned frame must not be modified in place."""
    from guardian.storage import blur_person_boxes

    frame = _solid_frame()
    original = frame.copy()
    _ = blur_person_boxes(frame, [(20, 20, 80, 80)])
    assert np.array_equal(frame, original)
