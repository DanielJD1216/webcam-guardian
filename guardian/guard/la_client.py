"""LocateAnything client — EXPERIMENTAL Mac-port subprocess backend.

Per BUILD-PLAN.md §5.3:
   "spawn once, one exchange per frame: send the detection prompt with a JPEG
    resized to long side ≤960 px, parse <ref>label</ref><box><x1><y1><x2><y2></box>
    with coords normalized to [0,1000]. Because it will be ~1 s/frame class at
    best, the client must be asynchronous: fire the request, keep drawing the
    *previous* boxes, swap when the reply lands."

Trap-list reminders (§13):
  trap 4 — DO NOT attempt the official PyTorch stack on this Mac; only the
            community ggml/Metal port is viable, and only if/when M7 passes.
  trap 11 — output has no confidence scores → Detection.conf=None path.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from ..config import GuardCfg
from .base import Detection, GuardBackend


_REF_RE = re.compile(r"<ref>([^<]+)</ref>", re.IGNORECASE)
_BOX_RE = re.compile(r"<box>(\d+)\s+(\d+)\s+(\d+)\s+(\d+)</box>", re.IGNORECASE)
_DETECT_PROMPT = "Locate all the instances that matches the following description: {labels}."
_COORD_MAX = 1000.0


def _resize_long_side(frame_bgr, long_side: int):
    h, w = frame_bgr.shape[:2]
    m = max(h, w)
    if m <= long_side:
        return frame_bgr
    scale = long_side / m
    return cv2.resize(frame_bgr, (round(w * scale), round(h * scale)))


class LocateAnythingGuard(GuardBackend):
    name = "locateanything"

    def __init__(self, cfg: GuardCfg) -> None:
        self.cfg = cfg
        if not cfg.la_command:
            raise RuntimeError(
                "guard.backend=locateanything requires guard.la_command in config.yaml "
                "(see BUILD-PLAN §5.3 for the launch arguments)."
            )
        if shutil.which(cfg.la_command[0]) is None:
            raise RuntimeError(f"locateanything launcher not on PATH: {cfg.la_command[0]}")
        labels = [lab for lab in cfg.coco_ids.keys() if lab in cfg.draw_classes]
        if not labels:
            raise RuntimeError("locateanything backend needs at least one label in coco_ids")
        self._prompt = _DETECT_PROMPT.format(labels="</c>".join(labels))
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._latest: list[Detection] = []

    def _ensure_proc(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                list(self.cfg.la_command),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )

    def detect(self, frame_bgr) -> list[Detection]:
        with self._lock:
            return list(self._latest)

    def submit_frame(self, frame_bgr) -> None:
        """Asynchronous handoff: render a JPEG, hand to the subprocess, parse later."""
        small = _resize_long_side(frame_bgr, self.cfg.la_input_long_side)
        # audit #58: GuardCfg has no jpeg_quality (it lives on
        # DetectiveCfg). Hard-code 80 — same as detective default; this
        # is just the JPEG quality for the encoded handoff to the
        # external LocateAnything subprocess.
        jpeg_quality = 80
        ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY),
                                                jpeg_quality])
        if not ok:
            return
        threading.Thread(target=self._exchange, args=(buf.tobytes(),),
                         daemon=True, name="la-exchange").start()

    def _exchange(self, jpeg_bytes: bytes) -> None:
        try:
            self._ensure_proc()
            assert self._proc is not None
            self._proc.stdin.write(f"{self._prompt}\n")
            self._proc.stdin.flush()
            self._proc.stdin.write("JPEG_BYTES\n")
            self._proc.stdin.flush()
            self._proc.stdin.buffer.write(jpeg_bytes)
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            dets = self._parse(line or "")
            with self._lock:
                self._latest = dets
        except Exception:
            with self._lock:
                self._latest = []

    def _parse(self, text: str) -> list[Detection]:
        out: list[Detection] = []
        refs = _REF_RE.findall(text)
        boxes = _BOX_RE.findall(text)
        if not boxes:
            return out
        # Pair refs and boxes 1:1, iterating all refs to keep them aligned.
        for i, box in enumerate(boxes):
            label = refs[i].strip().lower() if i < len(refs) else "object"
            canonical = self._canonicalize(label)
            if canonical is None:
                continue
            x1n, y1n, x2n, y2n = (int(v) / _COORD_MAX for v in box)
            out.append(Detection(label=canonical, conf=None,
                                 box=(x1n, x2n, y1n, y2n)))  # scaled by caller
        return out

    @staticmethod
    def _canonicalize(label: str) -> str | None:
        label = label.lower()
        if "person" in label:
            return "person"
        if "dog" in label:
            return "dog"
        if "car" in label or "truck" in label or "bus" in label or "vehicle" in label:
            return "car"
        return None

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
