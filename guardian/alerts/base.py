"""AlertChannel interface + dispatcher with per-channel error isolation.

Per BUILD-PLAN.md §8 + audit #61: bounded retry on transient network
errors. Each channel can be retried up to 2 times with a short
backoff. The hourly cap slot is consumed only after at least one
channel has succeeded OR all retries are exhausted (so a transient
network blip doesn't burn the cap).

Each dispatched alert carries an `alert_id` (millisecond unix
timestamp) so the per-channel `alert_sent`/`alert_error` events
can be correlated back to the `alert_dispatched` event in events.jsonl.

Audit finding #12: the `requests` exception's repr can include the
prepared request URL — which for Telegram embeds the bot token. We
sanitize the message before logging.
"""

from __future__ import annotations

import re
import time
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


# Audit #61: errors that suggest a transient network condition get
# a bounded retry. Everything else (auth, schema, etc.) is one-shot
# — retrying won't help.
_RETRYABLE = (ConnectionError, TimeoutError)
_RETRY_BACKOFF_S = (2.0, 5.0)
_MAX_ATTEMPTS = 3


def dispatch(channels: Iterable[AlertChannel], alert_id: str, title: str, body: str,
             image_path: str | None, log) -> dict:
    """Returns {'delivered': [...channels...], 'failed': [...channels...]}.

    Audit #61: a transient network blip during a prowler event no
    longer permanently drops the alert. Channels retry up to 2
    times with backoff. The caller (main.py) uses the returned
    'delivered'/'failed' lists to know whether to credit the
    hourly alert cap.
    """
    delivered: list[str] = []
    failed: list[str] = []
    for ch in channels:
        name = getattr(ch, "name", "?")
        sent = False
        for attempt in range(_MAX_ATTEMPTS):
            try:
                ch.send(title, body, image_path)
                log.log({"type": "alert_sent", "channel": name,
                         "alert_id": alert_id, "title": title,
                         "attempt": attempt + 1})
                delivered.append(name)
                sent = True
                break
            except _RETRYABLE as e:
                if attempt < _MAX_ATTEMPTS - 1:
                    log.log({"type": "alert_retry", "channel": name,
                             "alert_id": alert_id,
                             "attempt": attempt + 1,
                             "max": _MAX_ATTEMPTS,
                             "in_s": _RETRY_BACKOFF_S[attempt],
                             "error": _sanitize_error(repr(e))})
                    time.sleep(_RETRY_BACKOFF_S[attempt])
                else:
                    log.log({"type": "alert_error", "channel": name,
                             "alert_id": alert_id,
                             "attempts": _MAX_ATTEMPTS,
                             "error": _sanitize_error(repr(e))})
            except Exception as e:
                log.log({"type": "alert_error", "channel": name,
                         "alert_id": alert_id,
                         "attempts": attempt + 1,
                         "error": _sanitize_error(repr(e))})
                break
        if not sent:
            failed.append(name)
    return {"delivered": delivered, "failed": failed}
