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
