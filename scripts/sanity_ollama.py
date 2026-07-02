#!/usr/bin/env python3
"""M8 provider sanity check — Ollama keyless path (BUILD-PLAN §15).

"the implementing agent must sanity-check the other rows against current
 provider docs and run at least one non-MiniMax row end-to-end — Ollama is
 free and also exercises the keyless code path."

Usage:
    # 1. install Ollama, then in another shell:
    ollama pull llava:7b
    ollama serve

    # 2. in the project venv:
    python scripts/sanity_ollama.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="snapshots/smoke.jpg")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--model", default="llava:7b")
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: {image_path} missing — run scripts/smoke_camera.py first.",
              file=sys.stderr)
        return 2

    from guardian.config import DetectiveCfg, load as load_cfg
    from guardian.detective import Detective
    import cv2

    frame = cv2.imread(str(image_path))
    cfg = load_cfg("config.yaml")

    test_cfg = DetectiveCfg(
        base_url=args.base_url,
        model=args.model,
        api_key_env="",                          # KEYLESS — Ollama validates this path
        extra_body={},                            # no thinking toggle needed for Ollama
        timeout_seconds=120,
        use_tool_call=False,                      # small local VLMs can be weak on tool calls
        scene_description=cfg.detective.scene_description,
    )

    det = Detective(test_cfg, override_prompt_path="guardian/prompts/judge.txt")
    res = det.judge(frame, guard_labels=["smoke"])
    print(f"Ollama sanity OK: alert={res.decision.get('alert')} "
          f"cat={res.decision.get('category')} lat={res.latency_s}s "
          f"in={res.prompt_tokens} out={res.completion_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
