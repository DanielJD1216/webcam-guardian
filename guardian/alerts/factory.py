"""Factory wiring string channel names to instances."""

from __future__ import annotations

import sys

from .base import AlertChannel
from .telegram import TelegramChannel
from .resend import ResendChannel
from .desktop import DesktopChannel
from .ntfy import NtfyChannel

from ..config import AlertCfg


def _make(name: str, cfg: AlertCfg) -> AlertChannel | None:
    """Construct a single channel; return None on construction failure.

    Audit #35: was all-or-nothing — one channel with a missing
    env var (e.g. TELEGRAM_BOT_TOKEN unset) aborted the whole
    list, silently disabling every other channel too. Now each
    channel is built independently and errors are logged.
    """
    try:
        if name == "telegram":
            return TelegramChannel(chat_id=cfg.telegram_chat_id)
        if name == "email":
            return ResendChannel(
                from_addr=cfg.email.from_addr,
                to_addr=cfg.email.to_addr,
            )
        if name == "desktop":
            return DesktopChannel()
        if name == "ntfy":
            return NtfyChannel(topic=cfg.ntfy_topic)
    except Exception as e:
        print(f"[boot] {name} channel unavailable: {e}", file=sys.stderr)
        return None
    print(f"[boot] unknown alert channel: {name!r}", file=sys.stderr)
    return None


def build_channels(cfg: AlertCfg) -> list[AlertChannel]:
    out: list[AlertChannel] = []
    for name in cfg.channels:
        ch = _make(name, cfg)
        if ch is not None:
            out.append(ch)
    return out
