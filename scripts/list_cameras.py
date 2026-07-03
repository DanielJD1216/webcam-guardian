#!/usr/bin/env python3
"""Enumerate cameras available to OpenCV.

On macOS this uses AVFOUNDATION (indices 0..N). The OS picks a default each
session; if you want a specific one, pass its index to
`python -m guardian --camera-index N`.

Camera friendly names come from `system_profiler SPCameraDataType` —
AVFOUNDATION itself doesn't expose per-index names. The numeric ordering is
typically: USB / Continuity cams (iPhone via Danny Camera etc.) first,
then built-in (FaceTime HD), then virtual (OBS).
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from guardian.capture import default_backend


def list_sysprofiler_cameras() -> list[str]:
    if platform.system() != "Darwin":
        return []
    try:
        out = subprocess.check_output(
            ["system_profiler", "-json", "SPCameraDataType"], timeout=10)
    except Exception:
        return []
    import json
    try:
        data = json.loads(out)
    except Exception:
        return []
    names = []
    for k, v in (data.get("SPCameraDataType") or [{}])[0].items():
        if isinstance(v, dict) and "_name" in v:
            names.append(v["_name"])
    return names


def probe_index(index: int, backend: int) -> tuple[bool, tuple[int, int] | None, tuple[int, int] | None]:
    """Returns (opened, native_WH_or_None, frame_shape_or_None).

    `native_WH` is what the camera reports BEFORE we set width/height — useful
    for distinguishing a real USB cam (max 1280x720 or 640x480) from a
    placeholder feed that always reports 1920x1080.
    """
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        return False, None, None
    native = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
              int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        return True, native, None
    shape = (frame.shape[1], frame.shape[0])
    cap.release()
    return True, native, shape


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-index", type=int, default=8,
                        help="probe indices 0..max-index")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    backend = default_backend()
    name = {cv2.CAP_AVFOUNDATION: "avfoundation",
            cv2.CAP_DSHOW: "dshow",
            cv2.CAP_V4L2: "v4l2"}.get(backend, str(backend))
    print(f"backend={name}  (auto-selected from platform={platform.system()})")
    print()

    sys_names = list_sysprofiler_cameras()
    if sys_names:
        print("Cameras known to the OS:")
        for i, n in enumerate(sys_names):
            print(f"  [~{i}] {n}")
        print()

    print(f"Probing indices 0..{args.max_index}:")
    print(f"  {'idx':<5} {'opens':<6} {'native':<12} {'got':<12}  recommendation")
    working: list[tuple[int, tuple[int, int]]] = []
    for i in range(args.max_index + 1):
        ok, native, shape = probe_index(i, backend)
        rec = "USE THIS" if i == 0 else ("alt" if (ok and shape is not None) else "—")
        native_str = (f"{native[0]}x{native[1]}" if native else "n/a")
        shape_str = (f"{shape[0]}x{shape[1]}" if shape else "n/a")
        marker = ""
        if ok and shape is None:
            marker = "  (opens but read failed — likely placeholder)"
        elif ok and native and shape and native != shape:
            marker = "  (requested res honored)"
        print(f"  {i:<5} {ok!s:<6} {native_str:<12} {shape_str:<12}  {rec}{marker}")
        if ok and shape is not None:
            working.append((i, shape))

    if not working:
        print()
        print("No cameras opened. On macOS:")
        print("  1. System Settings → Privacy & Security → Camera → grant your terminal.")
        print("  2. Quit opencode / close it, then run from a fresh Terminal.app.")
        return 2

    print()
    if len(working) == 1:
        print(f"Only one camera reachable: index {working[0][0]}  ({working[0][1][0]}x{working[0][1][1]}).")
        print("Set it explicitly with: python -m guardian --camera-index", working[0][0])
    else:
        print("To pick a specific camera:")
        print("  python -m guardian --camera-index N")
        print()
        print("Examples on this machine (run the command above, watch the window):")
        for i, shape in working:
            name_hint = sys_names[i] if i < len(sys_names) else ""
            print(f"  --camera-index {i}   → {shape[0]}x{shape[1]}"
                  + (f"  ({name_hint})" if name_hint else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
