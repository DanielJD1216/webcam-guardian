"""ntfy channel — OPT-IN per BUILD-PLAN §3.3.

Public server: no auth, topic name IS the password (use a long random string).
Caps: 250 msgs/day, 2 MB/attachment, 60-request burst refilling 1/5s.
Cooldown is MANDATORY — the alert caps handle it.
"""

from __future__ import annotations

import os

import requests


class NtfyChannel:
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh") -> None:
        self.server = server.rstrip("/")
        self.topic = topic or os.environ.get("NTFY_TOPIC", "")
        if not self.topic:
            raise RuntimeError("ntfy_topic empty — ntfy channel disabled")

    def _url(self) -> str:
        return f"{self.server}/{self.topic}"

    def send(self, title: str, body: str, image_path: str | None = None) -> None:
        url = self._url()
        if image_path:
            with open(image_path, "rb") as f:
                requests.put(
                    url, data=f,
                    headers={"Filename": "alert.jpg", "Title": title,
                             "Priority": "high", "Tags": "camera"},
                    timeout=30,
                ).raise_for_status()
        else:
            requests.post(
                url, data=body.encode("utf-8"),
                headers={"Title": title, "Priority": "high", "Tags": "camera"},
                timeout=10,
            ).raise_for_status()
