"""Resend email channel — replaces Gmail SMTP per maintainer's choice.

Why Resend over Gmail SMTP:
  - one API key, no 2FA / App Password dance
  - JSON HTTP API, no SMTP reliability quirks
  - image attachments via JSON `attachments: [{filename, content(b64)}]`
  - 100 emails/day, 3000/month free tier — plenty for alerts

Endpoint (verified live, 2026-07-01):
  POST https://api.resend.com/emails
  Headers: Authorization: Bearer <RESEND_API_KEY>, Content-Type: application/json
  Body fields used: from, to, subject, text, attachments[]
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests


API_URL = "https://api.resend.com/emails"


class ResendChannel:
    name = "email"  # keep external name "email" — channel dispatcher's stable surface

    def __init__(self, from_addr: str, to_addr: str,
                 api_key_env: str = "RESEND_API_KEY",
                 api_key: str | None = None) -> None:
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.api_key_env = api_key_env
        self.api_key = api_key or os.environ.get(api_key_env, "")
        if not self.api_key:
            raise RuntimeError(f"{api_key_env} not set in .env (Resend API key required)")
        if not (from_addr and to_addr):
            raise RuntimeError("email.from_addr and email.to_addr must be set in config.yaml")

    def send(self, title: str, body: str, image_path: str | None = None) -> None:
        payload: dict = {
            "from": self.from_addr,
            "to": [self.to_addr],
            "subject": title,
            "text": body,
        }
        if image_path:
            jpeg = Path(image_path).read_bytes()
            payload["attachments"] = [{
                "filename": "alert.jpg",
                "content": base64.b64encode(jpeg).decode("ascii"),
            }]
        resp = requests.post(
            API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
