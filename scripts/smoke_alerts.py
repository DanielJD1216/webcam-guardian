#!/usr/bin/env python3
"""M5 alert smoke — sends a real test message through Telegram + Resend.

Use this once to verify both channels deliver end-to-end, before running the
full guardian in front of the camera. Independent of the camera loop.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from guardian.alerts.factory import build_channels
from guardian.alerts.base import dispatch as dispatch_alerts
from guardian.config import load as load_cfg


class TmpLog:
    def log(self, event):
        print(f"[event] {event}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--image", default="snapshots/smoke.jpg")
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    cfg = load_cfg("config.yaml")
    channels = build_channels(cfg.alert)
    names = [type(c).__name__ for c in channels]
    print(f"[smoke] channels: {names}")

    title = "Webcam Guardian smoke test"
    body = "If you see this, both alert channels are wired correctly."
    image = args.image if Path(args.image).exists() else None
    print(f"[smoke] image attach: {image}")

    log = TmpLog()
    dispatch_alerts(channels, title, body, image, log)
    print("[smoke] done — check Telegram and your inbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
