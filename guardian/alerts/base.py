"""AlertChannel interface + dispatcher with per-channel error isolation.

Per BUILD-PLAN.md §8:
  for ch in channels:
      try: ch.send(...); log ok
      except Exception: log error but continue

Each dispatched alert carries an `alert_id` (millisecond unix timestamp)
so the per-channel `alert_sent`/`alert_error` events can be correlated back
to the `alert_dispatched` event in events.jsonl.

Audit finding #12: the `requests` exception's repr can include the
prepared request URL — which for Telegram embeds the bot token. We
sanitize the message before logging.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Protocol


class AlertChannel(Protocol):
    name: str

    def send(self, title: str, body: str, image_path: str | None = None) -> None: ...


# Audit #12: redact any embedded credential / token that may have ended
# up inside the exception's repr. Telegram embeds the bot token in the
# URL; Resend embeds the API key in the Authorization header (which can
# also appear in the prepared request's repr for some exception types).
_TOKEN_PATTERNS = [
    (re.compile(r"bot\d+:[A-Za-z0-9_-]+"), "bot[REDACTED]"),
    (re.compile(r"re_[A-Za-z0-9]+"), "re_[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "sk-[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_-]{20,}"), "AIza[REDACTED]"),
    (re.compile(r"key-[A-Za-z0-9_-]{20,}"), "key-[REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"), "Bearer [REDACTED]"),
]


def _sanitize_error(s: str) -> str:
    out = s
    for pat, repl in _TOKEN_PATTERNS:
        out = pat.sub(repl, out)
    return out


def dispatch(channels: Iterable[AlertChannel], alert_id: str, title: str, body: str,
             image_path: str | None, log) -> None:
    for ch in channels:
        try:
            ch.send(title, body, image_path)
            log.log({"type": "alert_sent", "channel": getattr(ch, "name", "?"),
                     "alert_id": alert_id, "title": title})
        except Exception as e:                       # dead channel NEVER crashes the loop
            log.log({"type": "alert_error", "channel": getattr(ch, "name", "?"),
                     "alert_id": alert_id, "error": _sanitize_error(repr(e))})
