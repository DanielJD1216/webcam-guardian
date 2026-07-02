#!/usr/bin/env python3
"""Preview a specific camera index for N seconds in an OpenCV window.

Use to identify which physical camera a given index corresponds to:
  python scripts/preview_camera.py --index 1   # ~3 s window
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from guardian.capture import default_backend


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    backend = default_backend()
    cap = cv2.VideoCapture(args.index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        print(f"index {args.index} did not open.")
        return 1

    print(f"index {args.index} opened — {args.seconds:.0f}s preview.  "
          f"Watch which physical camera lights up.  'q' to quit early.")

    start = time.monotonic()
    while time.monotonic() - start < args.seconds:
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        label = f"camera index = {args.index}    {w}x{h}    'q' to quit"
        cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 0), -1)
        cv2.putText(frame, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow(f"camera preview {args.index}", frame)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"index {args.index} preview closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())