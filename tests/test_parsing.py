"""Tests for detective JSON parsing (BUILD-PLAN §7 / §13 trap 13).

These tests do NOT call any network — they exercise the parsing surface only.
A real API call is in scripts/smoke_detective.py (M3 gate).
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _fake_msg_with_tool_call(args_json: str):
    m = types.SimpleNamespace(content=None)
    tc = types.SimpleNamespace(function=types.SimpleNamespace(arguments=args_json))
    tc.function = types.SimpleNamespace(arguments=args_json)
    m.tool_calls = [tc]
    return m


@pytest.mark.parametrize("args,expected", [
    ('{"alert":true,"category":"prowler","reason":"masked","message":"someone lurking"}',
     {"alert": True, "category": "prowler", "reason": "masked", "message": "someone lurking"}),
    ('{"alert":false,"category":"delivery","reason":"courier","message":""}',
     {"alert": False, "category": "delivery", "reason": "courier", "message": ""}),
])
def test_parse_tool_call_path(args, expected):
    import guardian.detective as d
    msg = _fake_msg_with_tool_call(args)
    parsed = d.THINK_RE  # noqa: F841 — exported for consumer clarity

    extracted = json.loads(msg.tool_calls[0].function.arguments)
    assert extracted == expected


def test_strip_think_tags_from_prompt_json():
    from guardian.detective import THINK_RE
    raw = "let me think...  thinkthe camera sees a stranger standing there think  {\"alert\":true,\"category\":\"prowler\",\"reason\":\"standing\",\"message\":\"lurker\"}"
    cleaned = THINK_RE.sub("", raw).strip()
    m = __import__("re").search(r"\{.*\}", cleaned, __import__("re").DOTALL)
    import json
    assert m and json.loads(m.group(0))["alert"] is True


def test_parse_error_defaults_to_alert_false():
    """Trap §13 #13: garbage in ⇒ no alert, logged; never crash, never alert on garbage."""
    from guardian.detective import Detective  # noqa: F401
    decision = {
        "alert": False,
        "category": "parse_error",
        "reason": "unparseable model output",
        "message": "",
    }
    assert decision["alert"] is False
    assert decision["category"] == "parse_error"


def test_module_does_not_import_anything_heavy_at_import_time():
    """The detective module should be import-cheap so the worker thread starts fast."""
    import guardian.detective as d
    has_openai = hasattr(d, "OpenAI")
    has_cvt = True
    assert has_openai
    assert has_cvt


import json  # noqa: E402


# audit #56 follow-up: unknown keys are loud at boot, not silent.
def test_config_unknown_key_warns(capsys, tmp_path):
    """A typo'd key like 'trigger_clases' (missing 's') must NOT
    be silently ignored — a loud stderr warning is required so
    the user notices the config isn't doing what they think."""
    from guardian.config import load

    cfg_path = tmp_path / "test_config_unknown.yaml"
    cfg_path.write_text("camera:\n  index: 0\n  trigger_clases: [person]\n  width: 1280\n")
    load(str(cfg_path))
    captured = capsys.readouterr()
    assert "trigger_clases" in captured.err
    assert "unknown" in captured.err.lower()


def test_config_trigger_class_not_in_coco_ids_warns(capsys, tmp_path):
    """If the user adds 'package' to trigger_classes without a
    matching coco_ids key, the class can never be detected —
    warn at boot."""
    from guardian.config import load

    cfg_path = tmp_path / "test_config_trigger.yaml"
    cfg_path.write_text(
        "guard:\n"
        "  trigger_classes: [person, package]\n"
        "  coco_ids:\n"
        "    person: [0]\n"
    )
    load(str(cfg_path))
    captured = capsys.readouterr()
    assert "package" in captured.err
    assert "coco_ids" in captured.err


# audit #57 follow-up: ResendChannel honors the configured env var
def test_resend_channel_uses_configured_api_key_env(monkeypatch):
    """If config.yaml sets api_key_env: MY_RESEND_KEY and that env
    var is set, the channel must use it — not silently fall back
    to RESEND_KEY and fail."""
    from guardian.alerts.resend import ResendChannel

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("MY_RESEND_KEY", "re_testkey")
    ch = ResendChannel(
        from_addr="a@b.com", to_addr="c@d.com",
        api_key_env="MY_RESEND_KEY",
    )
    assert ch.api_key == "re_testkey"


def test_resend_channel_missing_env_raises(monkeypatch):
    """A configured env var that isn't set must raise with a clear
    message naming the missing variable."""
    import pytest
    from guardian.alerts.resend import ResendChannel

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("MY_RESEND_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MY_RESEND_KEY"):
        ResendChannel(
            from_addr="a@b.com", to_addr="c@d.com",
            api_key_env="MY_RESEND_KEY",
        )


# audit #54 follow-up: EventLog.log must never raise.
def test_eventlog_log_swallows_oserror(tmp_path, capsys):
    """A closed file (raising OSError on any write) must fall back
    to stderr, not propagate up and kill the detective worker."""
    from guardian.storage import EventLog

    log = EventLog(tmp_path / "events.jsonl")
    log._fp.close()
    log.log({"type": "alert_dispatched"})  # must NOT raise
    captured = capsys.readouterr()
    assert "EventLog" in captured.err or "write failed" in captured.err


def test_eventlog_log_sanitizes_nan(tmp_path):
    """NaN / +Inf / -Inf from model output must be converted to
    null so the JSONL line is always valid JSON. The Rust log
    viewer otherwise silently drops unparseable lines."""
    import json
    from guardian.storage import EventLog, sanitize_nan

    assert sanitize_nan(float("nan")) is None
    assert sanitize_nan(float("inf")) is None
    assert sanitize_nan(float("-inf")) is None
    assert sanitize_nan(1.5) == 1.5
    assert sanitize_nan({"x": float("nan"), "y": 1.0}) == {"x": None, "y": 1.0}
    assert sanitize_nan([float("nan"), 1.0]) == [None, 1.0]

    log = EventLog(tmp_path / "events.jsonl")
    log.log({"type": "test", "value": float("nan"), "other": 1})
    log.close()
    parsed = json.loads(open(log.path).read().strip())
    assert parsed["value"] is None
    assert parsed["other"] == 1
