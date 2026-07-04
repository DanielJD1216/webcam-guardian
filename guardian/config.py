"""Typed config loader — YAML + env, with validation.

BUILD-PLAN.md §6.2 schema.

Order of resolution (highest to lowest):
  1. Environment variables (`os.environ`) — already loaded from .env by python-dotenv in main.py
  2. `config.yaml` (gitignored, user-local)
  3. Defaults listed inline below

Trap-list reminders (§13):
  trap 9 — secrets only in .env (never in config.yaml); never print keys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class CameraCfg:
    index: int = 0
    backend: str = "auto"  # auto | dshow | msmf | avfoundation | v4l2
    width: int = 1280
    height: int = 720


@dataclass(frozen=True)
class GuardCfg:
    backend: str = "rtdetr"  # rtdetr | yolo11n | locateanything
    device: str = "auto"  # auto | mps | cuda | cpu
    analyzed_fps: int = 5
    conf_threshold: float = 0.45
    draw_min_streak: int = 1  # require label present N consecutive analyzed frames before drawing
    draw_classes: tuple[str, ...] = ("person", "dog", "car")
    trigger_classes: tuple[str, ...] = ("person", "car")
    coco_ids: Mapping[str, tuple[int, ...]] = field(
        default_factory=lambda: {"person": (0,), "car": (2, 5, 7), "dog": (16,)}
    )
    la_command: tuple[str, ...] = ()
    la_input_long_side: int = 960


@dataclass(frozen=True)
class EscalationCfg:
    debounce_frames: int = 3
    cooldown_seconds: int = 45
    max_detective_calls_per_run: int = 30
    max_alerts_per_hour: int = 10


@dataclass(frozen=True)
class DetectiveCfg:
    base_url: str = "https://api.minimax.io/v1"
    model: str = "MiniMax-M3"
    api_key_env: str = "MINIMAX_API_KEY"
    extra_body: Mapping[str, Any] = field(default_factory=lambda: {"thinking": {"type": "disabled"}})
    timeout_seconds: int = 30
    max_completion_tokens: int = 500
    temperature: float = 0.2
    image_long_side: int = 1024
    jpeg_quality: int = 80
    image_detail: str = "low"
    use_tool_call: bool = True
    scene_description: str = "a front door / home entry area"


@dataclass(frozen=True)
class EmailCfg:
    from_addr: str = ""              # e.g. "Webcam Guardian <alerts@yourdomain.com>"
    to_addr: str = ""                # recipient
    api_key_env: str = "RESEND_API_KEY"


@dataclass(frozen=True)
class AlertCfg:
    channels: tuple[str, ...] = ("telegram", "email")
    attach_snapshot: bool = True
    telegram_chat_id: str = ""
    email: EmailCfg = field(default_factory=EmailCfg)
    ntfy_topic: str = ""


@dataclass(frozen=True)
class LogCfg:
    events_path: str = "events.jsonl"
    snapshots_dir: str = "snapshots"
    save_escalation_frames: bool = True
    # audit #66 follow-up: identifiable data (alert snapshots +
    # person descriptions in events.jsonl) accumulates indefinitely.
    # Set to 0 to disable pruning (default off for backwards compat);
    # otherwise deletes events and snapshots older than N days at
    # every guardian boot.
    retention_days: int = 0


@dataclass(frozen=True)
class Config:
    camera: CameraCfg
    guard: GuardCfg
    escalation: EscalationCfg
    detective: DetectiveCfg
    alert: AlertCfg
    log: LogCfg
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return _CONFIG_PATH


_CONFIG_PATH: Path = Path("config.yaml")


def _tupleize(value):
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _mapping_keys_to_tuples(d: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    return {k: _tupleize(v) for k, v in d.items()}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping, got {type(data).__name__}")
    return data


def _camera(raw: dict) -> CameraCfg:
    return CameraCfg(
        index=int(raw.get("index", 0)),
        backend=str(raw.get("backend", "auto")),
        width=int(raw.get("width", 1280)),
        height=int(raw.get("height", 720)),
    )


def _guard(raw: dict) -> GuardCfg:
    return GuardCfg(
        backend=str(raw.get("backend", "rtdetr")),
        device=str(raw.get("device", "auto")),
        analyzed_fps=int(raw.get("analyzed_fps", 5)),
        conf_threshold=float(raw.get("conf_threshold", 0.45)),
        draw_min_streak=int(raw.get("draw_min_streak", 1)),
        draw_classes=_tupleize(raw.get("draw_classes", ["person", "dog", "car"])),
        trigger_classes=_tupleize(raw.get("trigger_classes", ["person", "car"])),
        coco_ids=_mapping_keys_to_tuples(raw.get("coco_ids", {}) or {}),
        la_command=_tupleize(raw.get("la_command", []) or []),
        la_input_long_side=int(raw.get("la_input_long_side", 960)),
    )


def _escalation(raw: dict) -> EscalationCfg:
    return EscalationCfg(
        debounce_frames=int(raw.get("debounce_frames", 3)),
        cooldown_seconds=int(raw.get("cooldown_seconds", 45)),
        max_detective_calls_per_run=int(raw.get("max_detective_calls_per_run", 30)),
        max_alerts_per_hour=int(raw.get("max_alerts_per_hour", 10)),
    )


def _detective(raw: dict) -> DetectiveCfg:
    # audit #70: was `or DEFAULT` which made it impossible to clear
    # the thinking-toggle default via config (empty dict is falsy in
    # the `or` chain). Use explicit None check so `extra_body: {}`
    # in YAML legitimately clears the default.
    eb = raw.get("extra_body")
    if eb is None:
        eb = {"thinking": {"type": "disabled"}}
    return DetectiveCfg(
        base_url=str(raw.get("base_url", "https://api.minimax.io/v1")),
        model=str(raw.get("model", "MiniMax-M3")),
        api_key_env=str(raw.get("api_key_env", "MINIMAX_API_KEY")),
        extra_body=dict(eb),
        timeout_seconds=int(raw.get("timeout_seconds", 30)),
        max_completion_tokens=int(raw.get("max_completion_tokens", 500)),
        temperature=float(raw.get("temperature", 0.2)),
        image_long_side=int(raw.get("image_long_side", 1024)),
        jpeg_quality=int(raw.get("jpeg_quality", 80)),
        image_detail=str(raw.get("image_detail", "low")),
        use_tool_call=bool(raw.get("use_tool_call", True)),
        scene_description=str(raw.get("scene_description", "a front door / home entry area")),
    )


def _email(raw: dict) -> EmailCfg:
    return EmailCfg(
        from_addr=str(raw.get("from_addr", "")),
        to_addr=str(raw.get("to_addr", "")),
        api_key_env=str(raw.get("api_key_env", "RESEND_API_KEY")),
    )


def _alert(raw: dict) -> AlertCfg:
    return AlertCfg(
        channels=_tupleize(raw.get("channels", ["telegram", "email"])),
        attach_snapshot=bool(raw.get("attach_snapshot", True)),
        telegram_chat_id=str(raw.get("telegram_chat_id", "")),
        email=_email(raw.get("email") or {}),
        ntfy_topic=str(raw.get("ntfy_topic", "")),
    )


def _log(raw: dict) -> LogCfg:
    return LogCfg(
        events_path=str(raw.get("events_path", "events.jsonl")),
        snapshots_dir=str(raw.get("snapshots_dir", "snapshots")),
        save_escalation_frames=bool(raw.get("save_escalation_frames", True)),
        retention_days=int(raw.get("retention_days", 0)),
    )


def load(path: str | Path = "config.yaml") -> Config:
    global _CONFIG_PATH
    _CONFIG_PATH = Path(path).resolve()
    raw = _load_yaml(_CONFIG_PATH)
    cfg = Config(
        camera=_camera(raw.get("camera") or {}),
        guard=_guard(raw.get("guard") or {}),
        escalation=_escalation(raw.get("escalation") or {}),
        detective=_detective(raw.get("detective") or {}),
        alert=_alert(raw.get("alert") or {}),
        log=_log(raw.get("log") or {}),
        raw=raw,
    )
    # audit #56: warn on unknown keys per section, and validate
    # cross-field constraint trigger_classes/draw_classes are subsets
    # of coco_ids. Without this, a typo like `trigger_clases:` would
    # silently fall back to defaults — the user thinks they tightened
    # the config but didn't.
    _validate_unknown_keys(raw)
    _validate_trigger_classes(cfg)
    return cfg


# audit #56: explicit allow-list per section. Anything in the raw
# YAML that doesn't match a known key is logged to stderr so a
# misconfigured config is loud at boot, not silent.
_KNOWN_KEYS: dict[str, set[str]] = {
    "camera": {"index", "backend", "width", "height"},
    "guard": {"backend", "device", "analyzed_fps", "conf_threshold",
              "draw_min_streak", "draw_classes", "trigger_classes",
              "coco_ids", "la_command", "la_input_long_side"},
    "escalation": {"debounce_frames", "cooldown_seconds",
                   "max_detective_calls_per_run", "max_alerts_per_hour"},
    "detective": {"base_url", "model", "api_key_env", "extra_body",
                  "timeout_seconds", "max_completion_tokens",
                  "temperature", "image_long_side", "jpeg_quality",
                  "image_detail", "use_tool_call", "scene_description"},
    "alert": {"channels", "attach_snapshot", "telegram_chat_id",
              "email", "ntfy_topic"},
    "alert.email": {"smtp_host", "smtp_port", "from_addr", "to_addr",
                    "api_key_env"},   # legacy; #57 marks some of
                                      # these as dead but we keep
                                      # accepting them
    "log": {"events_path", "snapshots_dir", "save_escalation_frames"},
}


def _validate_unknown_keys(raw: dict) -> None:
    for section, allowed in _KNOWN_KEYS.items():
        if section not in raw:
            continue
        sub = raw[section]
        if not isinstance(sub, dict):
            continue
        unknown = set(sub.keys()) - allowed
        if unknown:
            import sys
            print(
                f"[config] WARNING: section '{section}' has unknown "
                f"key(s) {sorted(unknown)} (allowed: {sorted(allowed)}). "
                f"They will be ignored — fix the typo or remove them.",
                file=sys.stderr,
            )


# audit #56 follow-up: cross-field validation. The RT-DETR guard
# only maps coco_ids.keys() to canonical labels; any string in
# trigger_classes or draw_classes that isn't there can never be
# detected. The user's instinct is "more trigger classes = more
# coverage" but it's actually "no coverage at all if missing".
def _validate_trigger_classes(cfg: Config) -> None:
    coco_keys = set(cfg.guard.coco_ids.keys())
    for label in cfg.guard.trigger_classes + cfg.guard.draw_classes:
        if label not in coco_keys:
            import sys
            print(
                f"[config] WARNING: trigger/draw class '{label}' is "
                f"not a key of guard.coco_ids (have: {sorted(coco_keys)}). "
                f"It will never be detected — add a mapping or remove "
                f"the label.",
                file=sys.stderr,
            )


def resolve_device(requested: str) -> str:
    """Map 'auto' to mps/cuda/cpu based on what's actually available."""
    import torch  # local import keeps import surface tight
    if requested == "auto":
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    return requested
