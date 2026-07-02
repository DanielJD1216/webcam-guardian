"""Overlay — bounding boxes, labels, HUD (fps, call counts, cooldown state).

Per BUILD-PLAN.md §9.

Streak smoothing (draw_min_streak): RT-DETR can flicker detections between
analyzed frames (shadows, edges, lighting). To stabilize the live preview,
a label must be present in `draw_min_streak` consecutive analyzed frames
before its box is drawn. The underlying detector still fires every frame
(so escalation, logs, etc. see every detection) — only the visualization
is smoothed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import cv2

from .guard.base import Detection


CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "person": (0, 200, 0),
    "dog":    (255, 140, 0),
    "car":    (0, 140, 255),
}


@dataclass
class HudState:
    guard_backend: str = ""
    analyzed_fps: float = 0.0
    camera_fps: float = 0.0
    detective_calls: int = 0
    cooldowns: dict[str, float] = field(default_factory=dict)
    last_decision_summary: str = ""
    banner: tuple[str, float] = ("", 0.0)  # message, expires_at_monotonic


class LabelStreakTracker:
    """Counts consecutive analyzed frames where each label has been present."""

    def __init__(self) -> None:
        self._streak: dict[str, int] = {}

    def observe(self, present_labels: Iterable[str], min_streak: int) -> set[str]:
        present = set(present_labels)
        allowed: set[str] = set()
        for lab in present:
            self._streak[lab] = self._streak.get(lab, 0) + 1
            if self._streak[lab] >= max(1, min_streak):
                allowed.add(lab)
        for lab in list(self._streak.keys()):
            if lab not in present:
                self._streak[lab] = 0
        return allowed


def _draw_hud(frame, hud: HudState) -> None:
    h, w = frame.shape[:2]
    margin, line_h = 14, 22
    lines = [
        f"guard: {hud.guard_backend}  analyzed {hud.analyzed_fps:.1f}fps  cam {hud.camera_fps:.1f}fps",
        f"detective calls: {hud.detective_calls}",
    ]
    if hud.cooldowns:
        cds = "  ".join(f"{k} cd {int(max(0.0, v))}s"
                        for k, v in sorted(hud.cooldowns.items()))
        lines.append(f"cooldowns: {cds}")
    if hud.last_decision_summary:
        lines.append(f"last: {hud.last_decision_summary}")

    panel_w = max(28 + max(len(s) for s in lines) * 9, 380)
    panel_h = line_h * len(lines) + margin * 2
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    y = margin + line_h - 6
    for s in lines:
        cv2.putText(frame, s, (margin, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (235, 235, 235), 1, cv2.LINE_AA)
        y += line_h

    now = time.monotonic()
    if hud.banner and now < hud.banner[1]:
        text = hud.banner[0]
        size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
        bx1 = (w - size[0]) // 2 - 18
        bx2 = (w + size[0]) // 2 + 18
        by1 = 90
        by2 = by1 + size[1] + 30
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), (20, 20, 60), -1)
        cv2.putText(frame, text, (bx1 + 18, by2 - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 240, 120), 2, cv2.LINE_AA)


def _draw_boxes(frame, detections: Iterable[Detection],
                draw_classes: Sequence[str],
                allowed_labels: set[str]) -> None:
    for d in detections:
        if d.label not in draw_classes or d.label not in allowed_labels:
            continue
        x1, y1, x2, y2 = (int(v) for v in d.box)
        color = CLASS_COLORS.get(d.label, (200, 200, 200))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = d.label if d.conf is None else f"{d.label} {d.conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv2.putText(frame, label, (x1 + 3, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)


def draw(frame, detections: Iterable[Detection], draw_classes: Sequence[str],
         hud: HudState, streak_tracker: LabelStreakTracker,
         min_streak: int = 2) -> set[str]:
    """Update the streak tracker and draw boxes only for stabilized labels.

    Returns the set of labels currently allowed to draw (also written into
    hud.cooldowns-ish stream if you want to surface them).
    """
    present = {d.label for d in detections}
    allowed = streak_tracker.observe(present, min_streak)
    _draw_boxes(frame, detections, draw_classes, allowed)
    _draw_hud(frame, hud)
    return allowed


def set_banner(hud: HudState, text: str, seconds: float = 2.0) -> None:
    hud.banner = (text, time.monotonic() + seconds)