#!/usr/bin/env python3
"""Debug: what is RT-DETR actually seeing?

Bypasses config conf_threshold and draw_min_streak so you can see every
detection the model produces, regardless of strength. Saves an annotated
JPEG so you can eyeball whether the model is on-target at all.

Run:
  python scripts/debug_detect.py            # uses config camera
  python scripts/debug_detect.py --conf 0.10
  python scripts/debug_detect.py --image snapshots/smoke.jpg
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import psutil

from guardian.config import load as load_cfg
from guardian.guard.rtdetr import RTDetrGuard


def annotate(frame, dets, color=(0, 255, 255)):
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{d.label} {d.conf:.2f}" if d.conf is not None else d.label
        cv2.putText(frame, label, (x1 + 4, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", type=float, default=None,
                    help="override conf_threshold (default: from config.yaml)")
    ap.add_argument("--show-all", action="store_true",
                    help="set conf to ~0 so you see every raw detection")
    ap.add_argument("--image", default=None,
                    help="use a saved JPEG instead of a live camera frame")
    ap.add_argument("--out", default="snapshots/debug_detect.jpg")
    args = ap.parse_args()

    cfg = load_cfg("config.yaml")
    guard = RTDetrGuard(cfg.guard)
    if args.show_all:
        object.__setattr__(guard.cfg, "conf_threshold", 0.001)
    elif args.conf is not None:
        object.__setattr__(guard.cfg, "conf_threshold", args.conf)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"ERROR: cannot read {args.image}")
            return 2
        print(f"[debug] source image: {args.image}  {frame.shape[1]}x{frame.shape[0]}")
    else:
        from guardian.capture import LatestFrameCamera
        cam = LatestFrameCamera(index=cfg.camera.index, backend=None,
                                width=cfg.camera.width, height=cfg.camera.height)
        frame = cam.read()
        cam.release()
        if frame is None:
            print("ERROR: no frame from camera")
            return 2
        print(f"[debug] live camera index {cfg.camera.index}  {frame.shape[1]}x{frame.shape[0]}")

    print(f"[debug] conf_threshold = {guard.cfg.conf_threshold}")
    print(f"[debug] coco_to_canonical = {guard.coco_to_canonical}")
    print(f"[debug] model device = {guard.device}")

    t0 = time.monotonic()
    raw_all = guard.detect(frame)
    inf_ms = (time.monotonic() - t0) * 1000
    print(f"[debug] inference: {inf_ms:.0f} ms")

    print(f"\n[debug] {len(raw_all)} detection(s) after canonicalization:")
    for d in raw_all:
        x1, y1, x2, y2 = d.box
        print(f"  {d.label:8s} conf={d.conf:.3f}  box=({x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f})  "
              f"size={x2-x1:.0f}x{y2-y1:.0f}")

    rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    print(f"\n[debug] process RSS: {rss_mb:.0f} MB")

    annotated = frame.copy()
    annotate(annotated, raw_all)
    cv2.putText(annotated,
                f"debug detect  conf={guard.cfg.conf_threshold}  {len(raw_all)} hits",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    print(f"[debug] annotated frame written to {args.out}")
    print()
    print("Inspect: open the JPEG and confirm whether the boxes line up with")
    print("what's actually in frame.  If empty/ghost: lower --conf; if correct")
    print("boxes are present but the live loop hides them, the issue is the")
    print("streak filter (set draw_min_streak: 1 in config.yaml).")
    return 0


if __name__ == "__main__":
    sys.exit(main())