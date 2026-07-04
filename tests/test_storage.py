"""Tests for guardian.storage retention sweep (audit #66 follow-up)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone


def _make_file(directory, name, content=b"x"):
    p = directory / name
    p.write_bytes(content)
    return p


def test_prune_older_than_deletes_old_snapshots(tmp_path):
    """Snapshots with a timestamp < cutoff are deleted; >= cutoff stay."""
    from guardian.storage import prune_older_than

    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    old_ms = int((datetime.now() - timedelta(days=10)).timestamp() * 1000)
    recent_ms = int(datetime.now().timestamp() * 1000)
    _make_file(snapshots_dir := snaps, f"alert_{old_ms:013d}.jpg", b"old")
    _make_file(snaps, f"alert_{recent_ms:013d}.jpg", b"new")

    deleted_snap, _ = prune_older_than(snaps, tmp_path / "events.jsonl", days=5)
    assert deleted_snap == 1
    remaining = sorted(p.name for p in snaps.iterdir())
    assert len(remaining) == 1
    # Remaining file is the recent one, not the old one.
    assert remaining[0] == f"alert_{recent_ms:013d}.jpg"


def test_prune_older_than_zero_days_is_noop(tmp_path):
    """retention_days=0 disables pruning entirely."""
    from guardian.storage import prune_older_than

    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    old_ms = int((datetime.now() - timedelta(days=100)).timestamp() * 1000)
    _make_file(snaps, f"alert_{old_ms:013d}.jpg", b"old")

    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"ts": "2020-01-01T00:00:00+00:00", "type": "x"}) + "\n")

    n_snap, n_evt = prune_older_than(snaps, events, days=0)
    assert n_snap == 0 and n_evt == 0
    assert any(snaps.iterdir())
    assert events.exists()


def test_prune_older_than_filters_events_by_ts(tmp_path):
    """Lines with ts >= cutoff_ms are kept; < cutoff are dropped."""
    from guardian.storage import prune_older_than

    events = tmp_path / "events.jsonl"
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    new_ts = (now - timedelta(days=1)).isoformat()
    events.write_text(
        json.dumps({"ts": old_ts, "type": "old"}) + "\n" +
        json.dumps({"ts": new_ts, "type": "new"}) + "\n",
    )

    n_snap, n_evt = prune_older_than(tmp_path / "snapshots_dir", events, days=14)
    assert n_snap == 0
    assert n_evt == 1
    lines = events.read_text().strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["type"] == "new"


def test_prune_older_than_keeps_malformed_lines(tmp_path):
    """A line that doesn't parse stays put (we'd rather keep unknown
    state than silently drop forensic data."""
    from guardian.storage import prune_older_than

    events = tmp_path / "events.jsonl"
    events.write_text("not a json line\n" + "{\"ts\":\"2020-01-01T00:00:00+00:00\"}\n")

    n_snap, n_evt = prune_older_than(tmp_path / "snapshots_dir", events, days=14)
    # The malformed line stays put; the old valid line is pruned.
    assert n_evt == 1
    lines = events.read_text().splitlines()
    assert lines == ["not a json line"]
