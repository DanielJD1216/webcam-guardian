# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-07-02

Camera hardening, box-coord fix, demo-runner.

### Added

- **Camera selection** — `python -m guardian --camera-index N` /
  `--camera-backend NAME` overrides config at runtime without editing the
  yaml. `python -m guardian --list-cameras` (or `scripts/list_cameras.py`)
  probes indices 0..N and prints each camera's native resolution vs the
  requested one — that split is how you spot placeholder feeds (most real
  cameras honor a smaller requested resolution; placeholders return their
  fixed size regardless).
- **`scripts/preview_camera.py`** — open a single index in a labeled
  OpenCV window for 3 s so you can identify which physical camera an
  index corresponds to.
- **`scripts/debug_detect.py`** — one-shot diagnostic that bypasses both
  `conf_threshold` and `draw_min_streak`, prints every detection (label,
  conf, box, size), and saves an annotated JPEG. `--show-all` drops conf
  to ~0 so you can see every raw detection the model produces.
- **`scripts/record_demo.sh`** — one-shot demo runner for the
  screen-recording session (sources `~/.venv-sys`, runs
  `python -m guardian --max-frames 300`, dumps event summary).
- **`RECORDING.md`** — preflight checklist + macOS screen-capture +
  choreography table + troubleshooting for the demo.
- **`draw_min_streak` config** — `LabelStreakTracker` overlay that
  suppresses boxes that don't persist for N consecutive analyzed
  frames. Detector still fires every frame (escalator + logs see
  everything); only the visualization is smoothed.

### Fixed

- **MPS float64 shim path was rescaling boxes to the wrong frame size.**
  `post_process_object_detection` was getting `pixel_values.shape[-2:]`
  (the model's *internal* resized shape, e.g. 640×640) instead of the
  original frame's `(H, W)`. Labels came out right, positions wrong.
  Both code paths now use the original frame's `(H, W)` for
  `target_sizes`. On a 1280×720 frame, boxes now correctly span the
  full width instead of being clamped to 640 px.
- **`conf_threshold` default 0.4 was too aggressive for real-webcam
  people** — raised then settled at 0.45 (still above the 0.04 noise
  floor but catches real people in normal indoor lighting).
- **`debug_detect.py --conf 0` short-circuited** the override. Renamed
  to `--show-all` and made it explicitly set conf to 0.001.
- **`--list-cameras` was passing `sys.argv[1:]` to the inner script**
  which doesn't know guardian's flags; now it forwards only `--max-index`
  / `--width` / `--height`.
- **`pyproject.toml` `requires-python` capped at `<3.13`** — blocked
  python.org 3.13.13 install. Bumped to `<3.14`.
- **`Pillow` was only a transitive dep of transformers** — promoted to
  a direct dep so RT-DETR's image processor imports cleanly.
- **`scripts/smoke_*.py` failed when run as a script** because Python
  added the script's directory (not the project root) to `sys.path[0]`.
  Each script now prepends `Path(__file__).resolve().parents[1]`.

### Verified

- 17-frame M6 dry-test (real captured frames through M3, 0 false
  positives, 0 parse errors)
- RT-DETR on MPS at 14.76 fps (66 ms p50 / 74 ms p95)
- Detective latency 1.65 s p50 / 3.43 s p95 over 17 calls
- Ollama keyless path (9.6 s, parse-error safe default per §13 trap 13)
- 15/15 unit tests pass

[Unreleased]: https://github.com/DanielJD1216/webcam-guardian/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/DanielJD1216/webcam-guardian/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/DanielJD1216/webcam-guardian/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/DanielJD1216/webcam-guardian/releases/tag/v0.1.0

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
