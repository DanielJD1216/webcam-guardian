"""AlertChannel interface + dispatcher with per-channel error isolation.

Per BUILD-PLAN.md §8:
  for ch in channels:
      try: ch.send(...); log ok
      except Exception: log error but continue
"""

from __future__ import annotations

from typing import Iterable, Mapping, Protocol


class AlertChannel(Protocol):
    name: str

    def send(self, title: str, body: str, image_path: str | None = None) -> None: ...


def dispatch(channels: Iterable[AlertChannel], title: str, body: str,
             image_path: str | None, log) -> None:
    for ch in channels:
        try:
            ch.send(title, body, image_path)
            log.log({"type": "alert_sent", "channel": getattr(ch, "name", "?"), "title": title})
        except Exception as e:                       # dead channel NEVER crashes the loop
            log.log({"type": "alert_error", "channel": getattr(ch, "name", "?"),
                     "error": repr(e)})
