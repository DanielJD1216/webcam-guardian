#!/usr/bin/env python3
"""M3 smoke test — one saved frame → MiniMax M3 → decision + tokens + latency.

Per BUILD-PLAN.md §10 M3 gate:
    "Printed decision dict + latency + tokens from a real call.
     If tool_choice is rejected → set the documented fallback and re-run."

Trap-list reminders respected here:
  trap 1 — thinking is ON by default; extra_body disables it.
  trap 2 — no response_format on /v1/chat/completions.
  trap 10 — tool_choice rejection handled in detective.py (auto-fallback).
  trap 9  — never prints the API key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="snapshots/smoke.jpg",
                        help="path to a JPEG (default: snapshots/smoke.jpg)")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        print("ERROR: config.yaml not found. Copy config.example.yaml -> config.yaml",
              file=sys.stderr)
        return 2

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: {image_path} missing. Run scripts/smoke_camera.py first.",
              file=sys.stderr)
        return 2

    import cv2
    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"ERROR: cannot decode {image_path}", file=sys.stderr)
        return 2

    from guardian.config import load as load_cfg
    from guardian.detective import Detective

    cfg = load_cfg(str(cfg_path))
    api_key = os.environ.get(cfg.detective.api_key_env, "")
    print(f"[smoke] provider base_url={cfg.detective.base_url}")
    print(f"[smoke] model={cfg.detective.model}")
    print(f"[smoke] api_key_env={cfg.detective.api_key_env} present={bool(api_key)}")

    if not api_key:
        print("ERROR: API key not set; fill MINIMAX_API_KEY in .env first.",
              file=sys.stderr)
        return 3

    det = Detective(cfg.detective, override_prompt_path="guardian/prompts/judge.txt")
    res = det.judge(frame, guard_labels=["smoke"])
    print(json.dumps({
        "decision": res.decision,
        "latency_s": res.latency_s,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
        "raw_finish_reason": res.raw_finish_reason,
        "parse_error": res.parse_error,
        "tool_call_accepted": res.tool_call_accepted,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
