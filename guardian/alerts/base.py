"""AlertChannel interface + dispatcher with per-channel error isolation.

Per BUILD-PLAN.md §8:
  for ch in channels:
      try: ch.send(...); log ok
      except Exception: log error but continue

Each dispatched alert carries an `alert_id` (millisecond unix timestamp)
so the per-channel `alert_sent`/`alert_error` events can be correlated back
to the `alert_dispatched` event in events.jsonl.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Protocol


class AlertChannel(Protocol):
    name: str

    def send(self, title: str, body: str, image_path: str | None = None) -> None: ...


def dispatch(channels: Iterable[AlertChannel], alert_id: str, title: str, body: str,
             image_path: str | None, log) -> None:
    for ch in channels:
        try:
            ch.send(title, body, image_path)
            log.log({"type": "alert_sent", "channel": getattr(ch, "name", "?"),
                     "alert_id": alert_id, "title": title})
        except Exception as e:                       # dead channel NEVER crashes the loop
            log.log({"type": "alert_error", "channel": getattr(ch, "name", "?"),
                     "alert_id": alert_id, "error": repr(e)})
