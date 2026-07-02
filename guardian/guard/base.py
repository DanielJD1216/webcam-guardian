"""Guard backend interface + canonical Detection dataclass.

Per BUILD-PLAN.md §5.2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Detection:
    label: str                                          # person | car | dog (canonical)
    conf: float | None                                  # None when backend emits no scores
    box: tuple[float, float, float, float]              # x1, y1, x2, y2 in PIXELS


class GuardBackend:
    """All guard backends (RT-DETR, YOLO11n, LocateAnything) implement this."""

    name: str = "guard"

    def detect(self, frame_bgr) -> list[Detection]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        pass
