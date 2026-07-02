"""YOLO11n guard backend — OPT-IN ([yolo] extra) because Ultralytics is AGPL-3.0.

Per BUILD-PLAN.md §5.2 + §13 trap 14:
   "ultralytics (AGPL) must never be imported in the core path — lazy-import it
    inside the yolo11n backend only, and keep it an optional extra so the repo
    stays MIT."
"""

from __future__ import annotations

from ..config import GuardCfg, resolve_device
from .base import Detection, GuardBackend


class YoloGuard(GuardBackend):
    name = "yolo11n"

    def __init__(self, cfg: GuardCfg) -> None:
        try:
            from ultralytics import YOLO  # AGPL-3.0 — OPT-IN ONLY
        except ImportError as e:
            raise RuntimeError(
                "yolo11n backend requires the [yolo] extra: pip install '.[yolo]'"
            ) from e

        self.cfg = cfg
        self.device = resolve_device(cfg.device)
        self.model = YOLO("yolo11n.pt")
        coco_ids: list[int] = []
        for ids in (cfg.coco_ids or {}).values():
            coco_ids.extend(int(i) for i in ids)

    def detect(self, frame_bgr) -> list[Detection]:
        if frame_bgr is None:
            return []
        results = self.model.predict(
            frame_bgr,
            classes=None,  # we filter after canonicalization
            conf=self.cfg.conf_threshold,
            verbose=False,
            device=self.cfg.device if self.cfg.device != "auto" else None,
        )
        out: list[Detection] = []
        if not results:
            return out
        names = results[0].names
        boxes = results[0].boxes
        if boxes is None:
            return out
        coco_to_canonical = {}
        for label, ids in (self.cfg.coco_ids or {}).items():
            for cid in ids:
                coco_to_canonical[int(cid)] = label
        for b in boxes:
            cid = int(b.cls.item())
            canonical = coco_to_canonical.get(cid)
            if canonical is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            out.append(Detection(label=canonical, conf=round(float(b.conf.item()), 4),
                                 box=(x1, y1, x2, y2)))
        return out

    def close(self) -> None:
        del self.model
