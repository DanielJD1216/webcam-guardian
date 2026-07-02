"""RT-DETR guard backend (default, Apache-2.0, MIT-clean).

Per BUILD-PLAN.md §5.2: "PekingU/rtdetr_r18vd via transformers. Apache-2.0 —
chosen as default so the repo can be MIT. ... bus/truck → 'car' (a delivery van
must trigger the car class; this is a deliberate decision)."

Trap-list reminders (§13):
  trap 14 — this module never imports ultralytics; AGPL stays in the [yolo] extra.

MPS note: transformers >= 5.x calls `torch.arange(..., dtype=torch.float64, ...)`
inside RT-DETR's position-embedding path. PyTorch's MPS backend doesn't support
float64. We bind the original torch.arange into the closure so a one-call
monkey-patch (downgrading float64 → float32) doesn't recurse.

Coordinate safety: `post_process_object_detection` rescales model outputs to
the original image's pixel space. The rescales correctly only when
`target_sizes` is the original frame's (H, W). Passing the model's
*internal* tensor shape (pixel_values.shape[-2:]) yields boxes that max
out around the resized grid instead of the original frame — labels right,
positions wrong. We pin target_sizes to the original frame's (H, W) in
both code paths.
"""

from __future__ import annotations

import torch
from PIL import Image

from ..config import GuardCfg, resolve_device
from .base import Detection, GuardBackend


_F64 = (torch.float64, torch.double)
_ORIGINAL_ARANGE = torch.arange


def _safe_arange(*args, **kwargs):
    """torch.arange that downgrades float64 to float32 (MPS-safe).

    Calls the *bound* original (not torch.arange) so recursion cannot happen
    even if a global monkey-patch leaves us installed in place of the original.
    """
    dtype = kwargs.get("dtype")
    if dtype in _F64:
        kwargs["dtype"] = torch.float32
    return _ORIGINAL_ARANGE(*args, **kwargs)


class RTDetrGuard(GuardBackend):
    name = "rtdetr"

    def __init__(self, cfg: GuardCfg) -> None:
        from transformers import RTDetrForObjectDetection, RTDetrImageProcessor

        self.cfg = cfg
        self.device = resolve_device(cfg.device)
        repo = "PekingU/rtdetr_r18vd"
        self.processor = RTDetrImageProcessor.from_pretrained(repo)
        self.model = RTDetrForObjectDetection.from_pretrained(repo).to(self.device).eval()
        self.id2label: dict[int, str] = self.model.config.id2label
        self.coco_to_canonical: dict[int, str] = {}
        for label, ids in (cfg.coco_ids or {}).items():
            for cid in ids:
                self.coco_to_canonical[int(cid)] = label

    def _forward(self, inputs):
        with torch.no_grad():
            try:
                return ("normal", self.model(**inputs))
            except TypeError as e:
                if "float64" in str(e) and self.device == "mps":
                    orig = torch.arange
                    torch.arange = _safe_arange
                    try:
                        return ("mps_shim", self.model(**inputs))
                    finally:
                        torch.arange = orig
                raise

    def _post(self, outputs, target_hw):
        target_sizes = torch.tensor([target_hw], device=self.device)
        return self.processor.post_process_object_detection(
            outputs, target_sizes=target_sizes,
            threshold=self.cfg.conf_threshold,
        )[0]

    def detect(self, frame_bgr) -> list[Detection]:
        if frame_bgr is None:
            return []
        rgb = frame_bgr[:, :, ::-1]
        pil_img = Image.fromarray(rgb)
        h, w = frame_bgr.shape[:2]
        inputs = self.processor(images=pil_img, return_tensors="pt").to(self.device)
        _, outputs = self._forward(inputs)
        results = self._post(outputs, (h, w))

        out: list[Detection] = []
        for score, label_id, box in zip(
            results["scores"], results["labels"], results["boxes"]
        ):
            cid = int(label_id.item())
            score_f = float(score.item())
            x1, y1, x2, y2 = (float(v) for v in box.tolist())
            canonical = self.coco_to_canonical.get(cid)
            if canonical is None:
                continue
            out.append(Detection(label=canonical, conf=round(score_f, 4),
                                 box=(x1, y1, x2, y2)))
        return out

    def close(self) -> None:
        del self.model
        if self.device == "mps" and hasattr(torch, "mps"):
            try:
                torch.mps.empty_cache()
            except Exception:
                pass