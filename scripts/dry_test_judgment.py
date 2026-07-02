#!/usr/bin/env python3
"""M6 dry test — a folder of frames → table of decisions.

Per BUILD-PLAN.md §10 M6 gate:
    "Table reviewed; delivery-vs-stranger calls are sensible. This is the
     make-or-break filmability check."

Per BUILD-PLAN.md §15:
    "scripts/dry_test_judgment.py doubles as the public 'test your model' tool
     — drop 15-20 of your own frames in a folder, run it, read the decision table."
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-dir", default="snapshots/dry_test",
                        help="folder of JPEGs (default: snapshots/dry_test)")
    parser.add_argument("--labels", default="person",
                        help="comma-separated label(s) to inject as guard labels")
    parser.add_argument("--out", default="snapshots/dry_test_results.csv")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    frames_dir = Path(args.frames_dir)
    if not frames_dir.exists():
        print(f"ERROR: {frames_dir} does not exist. "
              f"Drop 15-20 JPEG frames in there and re-run.", file=sys.stderr)
        return 2

    jpegs = sorted(p for p in frames_dir.glob("*.jpg"))
    if not jpegs:
        print(f"ERROR: no *.jpg in {frames_dir}", file=sys.stderr)
        return 2

    from guardian.config import load as load_cfg
    from guardian.detective import Detective

    cfg = load_cfg("config.yaml")
    det = Detective(cfg.detective, override_prompt_path="guardian/prompts/judge.txt")
    labels = [l.strip() for l in args.labels.split(",") if l.strip()]

    import cv2

    rows = []
    for j in jpegs:
        frame = cv2.imread(str(j))
        if frame is None:
            print(f"skipping unreadable {j}", file=sys.stderr)
            continue
        t0 = time.monotonic()
        res = det.judge(frame, guard_labels=labels)
        elapsed = time.monotonic() - t0
        d = res.decision
        rows.append({
            "file": j.name,
            "guard_labels": ",".join(labels),
            "alert": d.get("alert"),
            "category": d.get("category"),
            "reason": d.get("reason"),
            "message": d.get("message", "")[:120],
            "latency_s": res.latency_s,
            "wall_s": round(elapsed, 2),
            "in_tokens": res.prompt_tokens,
            "out_tokens": res.completion_tokens,
            "parse_error": bool(res.parse_error),
        })
        print(f"{j.name:40s} alert={d.get('alert')} cat={d.get('category'):<20s} "
              f"lat={res.latency_s}s msg={d.get('message','')[:60]}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {args.out} ({len(rows)} rows).")

    alerts = sum(1 for r in rows if r["alert"])
    parse_err = sum(1 for r in rows if r["parse_error"])
    print(f"\n[summary] frames={len(rows)} alerts={alerts} parse_errors={parse_err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
