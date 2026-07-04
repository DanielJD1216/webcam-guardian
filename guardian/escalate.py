"""Escalator — pure logic for debounce + per-class cooldown + hard caps.

Per BUILD-PLAN.md §5.4 (pinned semantics, implement exactly this):

  - Debounce: a trigger class must be present in ≥ `debounce_frames` (3)
    CONSECUTIVE analyzed frames before it is escalation-eligible.
  - Cooldown: gates detective CALLS (not alerts). Per trigger class, the gate is
    `now - last_call_dispatched_at >= cooldown_seconds`. The timer starts WHEN
    THE CALL IS DISPATCHED, REGARDLESS OF THE VERDICT (alert:false still
    consumes the cooldown).
  - Hard caps: max_detective_calls_per_run (30) and max_alerts_per_hour (10).
  - Multiple trigger classes in one frame (person + car) ⇒ ONE call carrying
    both labels; the cooldown is charged to BOTH classes.

Trap-list reminders (§13):
  trap 5 — cooldown starts at dispatch, regardless of verdict.
  trap 13 — parse failure from detective yields alert:false (logged elsewhere);
             the cooldown is still charged.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable


@dataclass
class EscalationStats:
    """Counters exposed for the README and event logging."""

    calls_dispatched: int = 0
    alerts_sent: int = 0
    cooldown_skips: int = 0
    cap_hits: int = 0


class Escalator:
    """Pure logic. No I/O. Cheap to unit-test (tests/test_escalate.py)."""

    def __init__(
        self,
        debounce_frames: int = 3,
        cooldown_seconds: int = 45,
        max_detective_calls_per_run: int = 30,
        max_alerts_per_hour: int = 10,
    ) -> None:
        self.debounce_frames = int(debounce_frames)
        self.cooldown_seconds = int(cooldown_seconds)
        # audit #69: was a 'per-run' counter that never reset; 24/7
        # deployments would stop alerting after N calls. Treat as a
        # rolling-hour budget instead — same cap, same name, but
        # auto-resets every hour via _call_times.
        self.max_detective_calls_per_run = int(max_detective_calls_per_run)
        self.max_alerts_per_hour = int(max_alerts_per_hour)

        self._streak: dict[str, int] = {}
        self._last_call_at: dict[str, float] = {}
        self._call_times: deque[float] = deque()  # rolling 1h of dispatch ts
        self._alert_times: deque[float] = deque()
        self.stats = EscalationStats()

    # --------------------------------------------------------------------- debounce
    def _debounced(self, present: Iterable[str]) -> set[str]:
        out: set[str] = set()
        for label in present:
            self._streak[label] = self._streak.get(label, 0) + 1
            if self._streak[label] >= self.debounce_frames:
                out.add(label)
        for label in list(self._streak.keys()):
            if label not in present:
                self._streak[label] = 0
        return out

    # ------------------------------------------------------------------- cooldown
    def _in_cooldown(self, label: str, now: float) -> float:
        last = self._last_call_at.get(label)
        if last is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (now - last))

    def _can_call(self, labels: Iterable[str], now: float) -> tuple[bool, dict[str, float]]:
        remaining_per_label: dict[str, float] = {}
        for lab in labels:
            r = self._in_cooldown(lab, now)
            if r > 0:
                remaining_per_label[lab] = r
        return (len(remaining_per_label) == 0, remaining_per_label)

    # --------------------------------------------------------------------- caps
    def _calls_capped(self, now: float) -> bool:
        """Rolling-hour cap (audit #69). Drops entries older than 1h on every check."""
        hour_ago = now - 3600.0
        while self._call_times and self._call_times[0] < hour_ago:
            self._call_times.popleft()
        return len(self._call_times) >= self.max_detective_calls_per_run

    def _alerts_capped(self, now: float) -> bool:
        hour_ago = now - 3600.0
        while self._alert_times and self._alert_times[0] < hour_ago:
            self._alert_times.popleft()
        return len(self._alert_times) >= self.max_alerts_per_hour

    # ----------------------------------------------------------------- public API
    def observe(
        self,
        present: Iterable[str],
        now: float | None = None,
    ) -> tuple[bool, set[str], dict[str, float]]:
        """Decide whether to escalate right now.

        Returns:
          (should_call, labels_to_call, cooldown_state_per_label)
        """
        if now is None:
            now = time.monotonic()

        eligible = self._debounced(present)
        if not eligible:
            return (False, set(), {})

        ok, remaining = self._can_call(eligible, now)
        if not ok:
            self.stats.cooldown_skips += 1
            return (False, set(eligible), remaining)

        if self._calls_capped(now):
            self.stats.cap_hits += 1
            return (False, set(eligible), remaining)

        return (True, eligible, remaining)

    def on_dispatch(self, labels: Iterable[str], now: float | None = None) -> None:
        """Charge the per-class cooldown for ALL labels in the call."""
        if now is None:
            now = time.monotonic()
        for lab in labels:
            self._last_call_at[lab] = now
        self._call_times.append(now)
        self.stats.calls_dispatched += 1

    def on_alert(self, now: float | None = None) -> bool:
        """Record an alert. Returns True if accepted, False if hourly cap tripped."""
        if now is None:
            now = time.monotonic()
        if self._alerts_capped(now):
            self.stats.cap_hits += 1
            return False
        self._alert_times.append(now)
        self.stats.alerts_sent += 1
        return True

    def snapshot_cooldowns(self, now: float | None = None) -> dict[str, float]:
        if now is None:
            now = time.monotonic()
        out: dict[str, float] = {}
        for lab, last in self._last_call_at.items():
            r = self.cooldown_seconds - (now - last)
            if r > 0:
                out[lab] = r
        return out
