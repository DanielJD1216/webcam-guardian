"""Telegram channel — primary, per BUILD-PLAN §8.

Multipart field name MUST be 'photo'. Caption ≤1024. Photo ≤10MB, w+h ≤10000.
"""

from __future__ import annotations

import os

import requests


API = "https://api.telegram.org"


class TelegramChannel:
    name = "telegram"

    def __init__(self, chat_id: str, bot_token: str | None = None) -> None:
        self.chat_id = chat_id
        self.token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")
        if not self.chat_id:
            raise RuntimeError("telegram_chat_id is empty in config.yaml")

    def send(self, title: str, body: str, image_path: str | None = None) -> None:
        url = f"{API}/bot{self.token}/sendPhoto" if image_path else f"{API}/bot{self.token}/sendMessage"
        caption = f"{title}\n{body}"[:1024] if image_path else None
        text = f"{title}\n{body}"[:4000] if not image_path else None
        if image_path:
            with open(image_path, "rb") as f:
                requests.post(
                    url,
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"photo": f}, timeout=30,
                ).raise_for_status()
        else:
            requests.post(
                url,
                data={"chat_id": self.chat_id, "text": text}, timeout=10,
            ).raise_for_status()
