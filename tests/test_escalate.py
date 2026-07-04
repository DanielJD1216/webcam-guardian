"""Tests for the pure-logic Escalator — every branch from BUILD-PLAN §5.4."""

from __future__ import annotations

import time

import pytest

from guardian.escalate import Escalator


def test_flicker_below_debounce_does_not_fire():
    """Streak strictly below debounce_frames must not fire — a true 1–2 frame flicker."""
    e = Escalator(debounce_frames=4, cooldown_seconds=45)
    now = 1000.0
    e.observe({"person"}, now)         # streak = 1
    e.observe({"person"}, now + 0.05)  # streak = 2
    should, labels, _ = e.observe({"person"}, now + 0.10)  # streak = 3 < 4 → no fire
    assert should is False, "streak=3 must not satisfy debounce=4"
    assert labels == set()


def test_three_consecutive_presence_fires():
    e = Escalator(debounce_frames=3, cooldown_seconds=45)
    now = 1000.0
    e.observe({"person"}, now)
    e.observe({"person"}, now + 0.05)
    should, labels, _ = e.observe({"person"}, now + 0.1)
    assert should is True
    assert labels == {"person"}


def test_disappearance_resets_streak():
    e = Escalator(debounce_frames=3, cooldown_seconds=45)
    now = 1000.0
    e.observe({"person"}, now)
    e.observe({"person"}, now + 0.05)
    e.observe(set(), now + 0.1)
    should, labels, _ = e.observe({"person"}, now + 0.15)
    assert should is False
    e.observe({"person"}, now + 0.20)
    should, labels, _ = e.observe({"person"}, now + 0.25)
    assert should is True


def test_cooldown_charged_at_dispatch_not_at_verdict():
    """TRAP-LIST §13 trap 5: alert:false still consumes the cooldown."""
    e = Escalator(debounce_frames=1, cooldown_seconds=45)
    now = 1000.0
    should, labels, _ = e.observe({"person"}, now)
    e.on_dispatch(labels, now)
    should2, labels2, remaining = e.observe({"person"}, now + 1.0)
    assert should is True
    assert should2 is False
    assert "person" in remaining
    assert 43.9 < remaining["person"] <= 45.0


def test_cooldown_burns_money_on_lingering_false_positive_runs_out():
    e = Escalator(debounce_frames=1, cooldown_seconds=10)
    now = 1000.0
    should, labels, _ = e.observe({"person"}, now)
    e.on_dispatch(labels, now)
    assert should is True
    later = now + 11.0
    should2, labels2, _ = e.observe({"person"}, later)
    e.on_dispatch(labels2, later)
    assert should2 is True, "after cooldown expires, the next call must fire"


def test_three_consecutive_presence_fires_and_cooldown():
    e = Escalator(debounce_frames=3, cooldown_seconds=45)
    now = 1000.0
    e.observe({"person"}, now)
    e.observe({"person"}, now + 0.05)
    should, labels, _ = e.observe({"person"}, now + 0.1)
    assert should is True
    assert labels == {"person"}
    # audit #36: the original second test was a shadow of this one
    # that reused a stale `now`. The combined test exercises the
    # full flow: fire -> dispatch -> cooldown blocks -> expires.
    e.on_dispatch(labels, now)
    should2, _, remaining = e.observe({"person"}, now + 5.0)
    assert should2 is False
    assert remaining.get("person", 0) >= 40


def test_multiple_classes_one_call():
    e = Escalator(debounce_frames=1, cooldown_seconds=45)
    now = 1000.0
    should, labels, _ = e.observe({"person", "car"}, now)
    assert should is True
    assert labels == {"person", "car"}
    e.on_dispatch(labels, now)
    should2, _, remaining = e.observe({"person", "car"}, now + 1.0)
    assert should2 is False
    assert "person" in remaining and "car" in remaining


def test_max_detective_calls_per_run_hard_cap():
    e = Escalator(debounce_frames=1, cooldown_seconds=0,
                  max_detective_calls_per_run=2)
    now = 1000.0
    for _ in range(2):
        should, labels, _ = e.observe({"person"}, now)
        e.on_dispatch(labels, now)
        now += 1
    should, labels, _ = e.observe({"person"}, now)
    assert should is False
    assert e.stats.cap_hits >= 1


def test_max_detective_calls_per_run_rolls_over_after_one_hour():
    """Audit #69: cap is rolling-hour, not per-run. After 1h+1s,
    a previously-capped call must be allowed again."""
    e = Escalator(debounce_frames=1, cooldown_seconds=0,
                  max_detective_calls_per_run=2)
    t0 = 1000.0
    for _ in range(2):
        should, labels, _ = e.observe({"person"}, t0)
        e.on_dispatch(labels, t0)
        t0 += 1
    should, labels, _ = e.observe({"person"}, t0)
    assert should is False, "should hit cap at 2 calls/hour"
    later = t0 + 3600.0 + 1.0
    should, labels, _ = e.observe({"person"}, later)
    assert should is True, "after 1h+1s the rolling window must have rolled"


def test_max_alerts_per_hour_caps_alerts_only_not_calls():
    e = Escalator(debounce_frames=1, cooldown_seconds=0,
                  max_alerts_per_hour=2, max_detective_calls_per_run=99)
    now = 1000.0
    assert e.on_alert(now) is True
    assert e.on_alert(now + 1) is True
    assert e.on_alert(now + 2) is False
    assert e.stats.cap_hits == 1


def test_alert_hourly_window_slides():
    e = Escalator(debounce_frames=1, cooldown_seconds=0,
                  max_alerts_per_hour=2)
    now = 1000.0
    assert e.on_alert(now) is True
    assert e.on_alert(now + 100) is True
    assert e.on_alert(now + 200) is False
    assert e.on_alert(now + 4000) is True


def test_snapshot_cooldowns_returns_only_active():
    e = Escalator(debounce_frames=1, cooldown_seconds=10)
    now = 1000.0
    should, labels, _ = e.observe({"person"}, now)
    e.on_dispatch(labels, now)
    snap = e.snapshot_cooldowns(now + 5)
    assert snap == {"person": pytest.approx(5.0)}
    snap2 = e.snapshot_cooldowns(now + 11)
    assert snap2 == {}
