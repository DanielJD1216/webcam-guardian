"""Detective — provider-agnostic OpenAI-compatible client.

Per BUILD-PLAN.md §7 (verbatim-adapted):
  - Forced tool call → JSON via tool arguments.
  - Prompt-JSON + hardened parser fallback when tool calling is weak/absent.
  - `extra_body` carries thinking toggle (passed under that key, NOT as a kwarg).
  - JSON parse failure ⇒ alert:false (logged) — never crash, never alert on garbage.

Trap-list reminders (§13):
  trap 1  — thinking mode is ON by default; must ride extra_body. Strip  trademarks defensively.
  trap 2  — no response_format on /v1/chat/completions; do NOT use it.
  trap 10 — tool_choice forcing is [VERIFY AT RUNTIME]; rejection path is coded.
  trap 13 — parse failure = alert:false + log; never crash.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

import cv2
from openai import OpenAI

from .config import DetectiveCfg


THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


ASSESSMENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "report_assessment",
        "description": "Report the security assessment of this webcam frame.",
        "parameters": {
            "type": "object",
            "properties": {
                "alert": {"type": "boolean",
                          "description": "True only if the resident should be notified right now."},
                "category": {"type": "string",
                             "description": "One of: delivery, visitor, resident, pet, vehicle, "
                                            "suspicious_person, prowler, package_theft, false_positive, other."},
                "reason": {"type": "string",
                           "description": "One sentence describing what is actually visible in the frame."},
                "message": {"type": "string",
                            "description": "The short, calm, specific notification text the resident reads. "
                                           "Empty string if alert is false."},
            },
            "required": ["alert", "category", "reason", "message"],
        },
    },
}


DEFAULT_SYSTEM_PROMPT = (
    "You are a home-security camera judge. You receive ONE still frame from a webcam "
    "pointed at {scene}, plus the local time and the label(s) a cheap local detector flagged. "
    "Decide whether the resident should be alerted right now.\n\n"
    "Guidelines:\n"
    "- A delivery driver actively delivering (uniform, package, delivery van, walking to/from the door): "
    "usually NO alert; category 'delivery'.\n"
    "- Routine events (a resident-like person walking straight in, a pet, a car simply passing on the street): NO alert.\n"
    "- An unknown person lingering, peering into windows, trying the door handle, circling back repeatedly, "
    "or concealing their face: ALERT; category 'suspicious_person' or 'prowler'.\n"
    "- Someone taking a package AWAY from the door: ALERT; category 'package_theft'.\n"
    "- A vehicle stopped directly outside for a long time at odd hours: alert only if genuinely unusual.\n"
    "- Empty scene, shadow, reflection, or obvious detector mistake: NO alert; category 'false_positive'.\n"
    "- When genuinely uncertain, prefer NO alert, and say why in 'reason'.\n\n"
    "Report your decision by calling the report_assessment tool. 'message' must read like a notification a "
    "person would actually want to receive — specific and plain, e.g. 'Delivery driver is dropping off a "
    "package at your door.' or 'Someone in a dark hoodie has been standing at your door for a while and "
    "isn't delivering anything.'"
)


def encode_frame(frame_bgr, long_side: int = 1024, quality: int = 80) -> str:
    """Resize to long-side ≤ long_side and JPEG-encode at `quality` (BUILD-PLAN trap 6)."""
    h, w = frame_bgr.shape[:2]
    scale = long_side / max(h, w)
    if scale < 1.0:
        frame_bgr = cv2.resize(frame_bgr, (round(w * scale), round(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return base64.b64encode(buf).decode("ascii")


def parse_decision(msg) -> tuple[dict | None, str | None]:
    """audit #36: extract the parse-and-validate block of
    Detective.judge into a pure function so the trap-13 safety
    property (garbage in → alert:false, no crash) can be tested
    directly. Returns (decision, parse_error). decision is None when
    no valid JSON could be extracted.
    """
    try:
        if getattr(msg, "tool_calls", None):
            decision = json.loads(msg.tool_calls[0].function.arguments)
        else:
            text = THINK_RE.sub("", msg.content or "").strip()
            m = re.search(r"\{.*\}", text, re.DOTALL)
            decision = json.loads(m.group(0)) if m else None
        return decision, None
    except (json.JSONDecodeError, AttributeError, IndexError) as e:
        return None, repr(e)


def load_system_prompt(cfg: DetectiveCfg, override_path: str | None) -> str:
    """Per BUILD-PLAN §15: judge.txt is the user-editable surface for house rules."""
    if override_path and os.path.exists(override_path):
        with open(override_path, "r", encoding="utf-8") as f:
            return _format_prompt_safely(f.read(), scene=cfg.scene_description)
    return DEFAULT_SYSTEM_PROMPT


def _format_prompt_safely(template: str, /, **kwargs) -> str:
    """Substitute {key} placeholders without using str.format().

    Review finding #71: str.format({scene}) on user-edited judge.txt
    raises KeyError if the file contains any literal { or } that does
    not match a kwarg — silently disabling every detective call.

    Plain string substitution: any literal { or } in the template is
    preserved unchanged. Only named placeholders we explicitly pass
    are replaced. Values may not contain '{key}' substrings (the only
    kwarg today is scene_description, a free-text field, so this is
    acceptable; document the limitation).
    """
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


@dataclass
class JudgeResult:
    decision: dict
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    raw_finish_reason: str | None
    parse_error: str | None
    tool_call_accepted: bool


class Detective:
    """One-shot client. DetectiveWorker (§8 / main loop) owns the long-lived thread."""

    def __init__(self, cfg: DetectiveCfg, override_prompt_path: str | None = None) -> None:
        self.cfg = cfg
        api_key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""
        self.client = OpenAI(
            api_key=api_key or "none",   # "none" enables keyless local servers (Ollama §15)
            base_url=cfg.base_url,
            timeout=cfg.timeout_seconds,
            max_retries=1,
        )
        self.system_prompt = load_system_prompt(cfg, override_prompt_path)
        self.tool_call_accepted: bool | None = None  # discovered at first call

    def judge(self, frame_bgr, guard_labels: list[str]) -> JudgeResult:
        b64 = encode_frame(frame_bgr, self.cfg.image_long_side, self.cfg.jpeg_quality)
        # audit #73: include timezone name so the model knows whether
        # the local clock is home-TZ (user lives here) or away-TZ
        # (user is traveling). strftime alone is ambiguous; the model
        # can otherwise mis-attribute "22:00 on a Tuesday" to a Tuesday
        # that was actually yesterday in the user's mind.
        from datetime import datetime
        now = datetime.now().astimezone()
        local_when = now.strftime("%A %H:%M %Z")
        user_content = [
            {"type": "text",
             "text": (f"Camera frame from {self.cfg.scene_description}. "
                      f"Local time: {local_when}. "
                      f"Local detector flagged: {', '.join(guard_labels) or 'nothing'}.")},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{b64}",
                "detail": self.cfg.image_detail,
            }},
        ]

        kwargs: dict[str, Any] = dict(
            model=self.cfg.model,
            messages=[
                {"role": "system", "content": _format_prompt_safely(
                    self.system_prompt, scene=self.cfg.scene_description)},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=self.cfg.max_completion_tokens,
            temperature=self.cfg.temperature,
            extra_body=self.cfg.extra_body or None,
        )

        if self.cfg.use_tool_call and self.tool_call_accepted is not False:
            kwargs["tools"] = [ASSESSMENT_TOOL]
            if self.tool_call_accepted is not False:
                kwargs["tool_choice"] = {
                    "type": "function",
                    "function": {"name": "report_assessment"},
                }

        t0 = time.monotonic()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            if self.cfg.use_tool_call and "tool_choice" in str(exc):
                self.tool_call_accepted = False
                kwargs.pop("tool_choice", None)
                resp = self.client.chat.completions.create(**kwargs)
            else:
                raise
        latency = round(time.monotonic() - t0, 2)

        if self.tool_call_accepted is None:
            self.tool_call_accepted = True

        msg = resp.choices[0].message
        # audit #36: parse-and-validate extracted into parse_decision()
        # so the trap-13 safety property (garbage in → alert:false,
        # no crash) is unit-testable.
        decision, parse_error = parse_decision(msg)

        if not isinstance(decision, dict) or "alert" not in decision:
            decision = {
                "alert": False,
                "category": "parse_error",
                "reason": f"unparseable model output: {parse_error}",
                "message": "",
            }

        u = getattr(resp, "usage", None)
        return JudgeResult(
            decision=decision,
            latency_s=latency,
            prompt_tokens=getattr(u, "prompt_tokens", None) if u else None,
            completion_tokens=getattr(u, "completion_tokens", None) if u else None,
            raw_finish_reason=getattr(resp.choices[0], "finish_reason", None),
            parse_error=parse_error,
            tool_call_accepted=bool(self.tool_call_accepted),
        )
