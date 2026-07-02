# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-01

Initial public release. Two-tier webcam guardian under MIT — local RT-DETR
guard + bring-your-own OpenAI-compatible detective.

### Added

- **Guard backends** (`guardian/guard/`):
  - `rtdetr` default — `PekingU/rtdetr_r18vd` via `transformers`, Apache-2.0,
    MPS float64 shim for `transformers` >= 5.x, ~15 fps measured on Apple
    Silicon.
  - `yolo11n` opt-in (`[yolo]` extra) — Ultralytics, AGPL-3.0, lazy-imported
    only so the core stays MIT.
  - `locateanything` experimental subprocess backend (off the critical path
    per BUILD-PLAN §5.3).
- **Detective client** (`guardian/detective.py`) — provider-agnostic
  OpenAI-compatible chat-completion caller with forced `tool_call` +
  prompt-JSON hardened parser. `thinking: {type: disabled}` rides via
  `extra_body`. Parse failure defaults to `alert:false`, never crashes.
- **Escalator** (`guardian/escalate.py`) — pure logic for debounce(3),
  per-class cooldown(45 s, charged at **dispatch**, not verdict — §13 trap 5),
  and per-run / per-hour hard caps. 10 unit tests cover every branch.
- **Detective worker thread** — single-thread consumer; API call + alert
  delivery + event logging all on the worker so the preview never freezes
  on the network.
- **Capture** (`guardian/capture.py`) — `LatestFrameCamera` daemon-thread
  reader with an AVFOUNDATION backend on macOS.
- **HUD** (`guardian/overlay.py`) — fps, call counts, cooldown state, last
  decision summary; per-detection colored boxes.
- **Alerts** (`guardian/alerts/`):
  - **Telegram** (primary) — multipart `photo`, caption ≤1024 chars.
  - **Resend** (primary) — JSON HTTP API, replaces Gmail SMTP per
    maintainer choice (no App Password dance).
  - **Desktop** (opt-in, `[desktop]` extra) — `desktop-notifier`,
    requires signed python.org Python on macOS.
  - **ntfy** (opt-in) — text or PUT-JPEG with Title / Priority / Tags.
  - Per-channel `try/except` isolation.
- **Storage** (`guardian/storage.py`) — JSONL event log with
  `write → flush → fsync` per event.
- **Config** (`guardian/config.py`) — typed YAML loader; secret keys live
  in `.env`, never in `config.yaml`.
- **Scripts**:
  - `scripts/smoke_camera.py` — open webcam, save `snapshots/smoke.jpg`.
  - `scripts/smoke_detective.py` — one frame to MiniMax M3, print decision
    + tokens + latency.
  - `scripts/smoke_alerts.py` — fan a fake decision through every channel.
  - `scripts/capture_frames.py` — capture N frames at intervals for M6.
  - `scripts/dry_test_judgment.py` — folder of frames → decision CSV.
  - `scripts/measure.py` — guard + detective bench → `bench_results.json`.
  - `scripts/sanity_ollama.py` — M8 non-MiniMax keyless privacy-first path.
- **Tests** (`tests/`) — 15 unit tests, no hardware or network required.
- **CI** — GitHub Actions matrix on Python 3.11 / 3.12, `pytest -q`.
- **Documentation** — `README.md` (quickstart, provider table, privacy,
  alert setup, measured results), `BUILD-PLAN.md` (the design source),
  `CONTRIBUTING.md`, this file.

### Verified

- M0 — env + camera TCC
- M1 — capture + preview
- M2 — RT-DETR guard (MPS, 14.76 fps)
- M3 — MiniMax M3 detective ($0.00044/call, 1.65 s p50 / 3.43 s p95)
- M4 — escalator + worker
- M5 — Telegram + Resend fan-out
- M6 — 17-frame dry-test table, 0 false positives, 0 parse errors
- M7 — measured bench numbers in README Results
- M8 — MIT packaging, provider table, judge.txt, gitignore audit

[Unreleased]: https://github.com/DanielJD1216/webcam-guardian/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/DanielJD1216/webcam-guardian/releases/tag/v0.1.0
