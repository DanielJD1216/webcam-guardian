"""Factory wiring string channel names to instances."""

from __future__ import annotations

from .base import AlertChannel
from .telegram import TelegramChannel
from .resend import ResendChannel
from .desktop import DesktopChannel
from .ntfy import NtfyChannel

from ..config import AlertCfg


def build_channels(cfg: AlertCfg) -> list[AlertChannel]:
    out: list[AlertChannel] = []
    for name in cfg.channels:
        if name == "telegram":
            out.append(TelegramChannel(chat_id=cfg.telegram_chat_id))
        elif name == "email":
            out.append(ResendChannel(
                from_addr=cfg.email.from_addr,
                to_addr=cfg.email.to_addr,
            ))
        elif name == "desktop":
            out.append(DesktopChannel())
        elif name == "ntfy":
            out.append(NtfyChannel(topic=cfg.ntfy_topic))
        else:
            raise ValueError(f"unknown alert channel: {name}")
    return out
