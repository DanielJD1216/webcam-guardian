#!/usr/bin/env python3
"""M7 measurement harness — measured-only numbers for the README.

Per BUILD-PLAN.md §10 M7 gate:
    "60s guard bench: analyzed fps, p50/p95 inference ms, memory.
     10 sequential detective calls: p50/p95 latency.
     5-min integrated run: calls, alerts, cooldown skips.
     → paste outputs into README template."

Per §11 README Results template:
    "Guard: <backend> @ <analyzed fps> fps, inference p50 <ms> / p95 <ms>, memory <GB>
     Detective latency: p50 <s> / p95 <s> over <n> calls
     Judgment table: <n> frames, <fp> false positives, <fn> false negatives
     Session: <calls> calls, <alerts> alerts, <skips> cooldown skips in <minutes> min
     Tokens: <in> in / <out> out total → est. $<x>/day at observed escalation rate"
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return xs[k]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--guard-seconds", type=int, default=60)
    parser.add_argument("--detective-calls", type=int, default=10)
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    from guardian.config import load as load_cfg
    from guardian.detective import Detective
    from guardian.guard.rtdetr import RTDetrGuard
    from guardian.capture import LatestFrameCamera
    import cv2
    import psutil

    cfg = load_cfg("config.yaml")
    cam = LatestFrameCamera(index=cfg.camera.index, backend=None,
                            width=cfg.camera.width, height=cfg.camera.height)
    guard = RTDetrGuard(cfg.guard)

    print(f"[bench] {args.guard_seconds}s guard bench on {cfg.guard.backend}")
    infer_ms = []
    analyzed = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.guard_seconds:
        frame = cam.read()
        if frame is None:
            time.sleep(0.05)
            continue
        ta = time.monotonic()
        _ = guard.detect(frame)
        infer_ms.append((time.monotonic() - ta) * 1000)
        analyzed += 1
    guard_seconds = time.monotonic() - t0
    cam.release()
    guard.close()

    rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    analyzed_fps = analyzed / guard_seconds if guard_seconds else 0.0
    print(f"[bench] analyzed_fps={analyzed_fps:.2f}  n={analyzed}")
    print(f"[bench] inference p50={_pct(infer_ms, 0.5):.1f}ms  "
          f"p95={_pct(infer_ms, 0.95):.1f}ms")
    print(f"[bench] rss={rss_mb:.1f}MB")

    print(f"\n[bench] {args.detective_calls} detective calls")
    det = Detective(cfg.detective, override_prompt_path="guardian/prompts/judge.txt")
    cam = LatestFrameCamera(index=cfg.camera.index, backend=None,
                            width=cfg.camera.width, height=cfg.camera.height)
    latencies = []
    in_tok = 0
    out_tok = 0
    cost_per_call = (in_tok * 0.30 + out_tok * 1.20) / 1_000_000
    for i in range(args.detective_calls):
        frame = cam.read()
        if frame is None:
            time.sleep(0.2)
            continue
        res = det.judge(frame, guard_labels=["person"])
        latencies.append(res.latency_s)
        if res.prompt_tokens:
            in_tok += res.prompt_tokens
        if res.completion_tokens:
            out_tok += res.completion_tokens
        print(f"[bench] call {i+1}: {res.latency_s}s "
              f"in={res.prompt_tokens} out={res.completion_tokens} "
              f"alert={res.decision.get('alert')} cat={res.decision.get('category')}")
        time.sleep(1.0)
    cam.release()

    cost = (in_tok * 0.30 + out_tok * 1.20) / 1_000_000
    print(f"[bench] detective latency p50={_pct(latencies, 0.5):.2f}s "
          f"p95={_pct(latencies, 0.95):.2f}s over {len(latencies)} calls")
    print(f"[bench] tokens in={in_tok} out={out_tok} cost=${cost:.4f}")

    out = {
        "guard_bench": {
            "backend": cfg.guard.backend,
            "seconds": round(guard_seconds, 2),
            "frames_analyzed": analyzed,
            "analyzed_fps": round(analyzed_fps, 2),
            "inference_ms_p50": round(_pct(infer_ms, 0.5), 1),
            "inference_ms_p95": round(_pct(infer_ms, 0.95), 1),
            "rss_mb": round(rss_mb, 1),
            "ts": datetime.now().isoformat(timespec="seconds"),
        },
        "detective_bench": {
            "model": cfg.detective.model,
            "calls": len(latencies),
            "latency_s_p50": round(_pct(latencies, 0.5), 2),
            "latency_s_p95": round(_pct(latencies, 0.95), 2),
            "tokens_in": in_tok,
            "tokens_out": out_tok,
            "cost_usd": round(cost, 4),
        },
    }
    Path("snapshots").mkdir(exist_ok=True)
    with open("snapshots/bench_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\n[bench] wrote snapshots/bench_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
