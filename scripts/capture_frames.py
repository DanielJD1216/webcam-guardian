#!/usr/bin/env python3
"""Capture N webcam frames at intervals into snapshots/dry_test/ for the M6 dry test.

Per BUILD-PLAN §10 M6:
   "capture/collect 15–20 real frames covering {person plain,
    delivery-with-package, empty, pet, car/van}"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from guardian.capture import LatestFrameCamera


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="snapshots/dry_test")
    ap.add_argument("--count", type=int, default=18,
                    help="number of frames to capture (default 18)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between captures")
    ap.add_argument("--prefix", default="frame")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cam = LatestFrameCamera(index=0, backend=None,
                            width=args.width, height=args.height)
    print(f"capturing {args.count} frames at {args.interval}s intervals "
          f"into {out}.  sit / move / leave between captures.  Ctrl-C to stop.")

    saved = 0
    try:
        for i in range(args.count):
            frame = cam.read()
            if frame is None:
                print(f"  frame {i}: no frame from camera, retrying...", file=sys.stderr)
                time.sleep(0.5)
                continue
            name = f"{args.prefix}_{i:02d}.jpg"
            cv2.imwrite(str(out / name), frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            print(f"  [{i+1:2d}/{args.count}] {name}")
            saved += 1
            if i + 1 < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\ninterrupted by user")
    finally:
        cam.release()

    print(f"done. {saved}/{args.count} frames in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
