# Audit fixes tracker

Status of every finding in `Verdict/REVIEW-v0.3.0.md`. Updated as
commits land.

## Critical

- [x] #1 — Camera stall/revocation undetected (CRITICAL, confirmed)
- [x] #3 — Unauthenticated WebSocket (CRITICAL, confirmed)

## High (top 18)

- [x] #9  — `log.save_escalation_frames` is a no-op (privacy)
- [x] #9  — Tauri truncates `events.jsonl` on launch
- [x] #12 — Telegram bot token leaks in `repr(e)`
- [x] #17 — `DetectiveWorker.run` catch-all drops alert on snapshot failure
- [x] #20 — UI staleness detector structurally defeated by 10 Hz broadcast
- [x] #25 — `THINK_RE` regex missing angle brackets
- [x] #27 — Config never loaded on mount; resolution picker no-op
- [x] #35 — One misconfigured channel silently disables ALL alerting
- [~] #41 — Bundled `.app` cannot run outside dev checkout (Info.plist + NSCameraUsageDescription done; full Python-runtime bundle + signing are separate work)
- [x] #43 — `frontendDist` / vite `outDir` mismatch
- [x] #44 — Tauri shell cannot launch on Windows
- [x] #47 — Resolution picker is a no-op on shipped config
- [x] #61 — Alert delivery has no retry / dead-letter
- [x] #63 — Every timestamp shown in UI is fabricated at parse time
- [x] #69 — `max_detective_calls_per_run` never resets
- [x] #70 — MiniMax `thinking` extra_body default can't be cleared
- [x] #71 — `judge.txt` brace makes every detective call raise

## Wave 1 (done)

Critical + alert reliability + config. Both criticals closed. 17/18
high-severity items closed. See commit history — each fix is its own
commit with `fix(audit): #N — …` prefix.

## Wave 2 (done)

Tauri/build/cross-platform. #27, #41 (partial), #43, #44, #47, #48,
#49, #61, #63 all closed. Remaining #41 work (PyInstaller-bundled
Python, code signing, notarization) is a separate packaging project
and is out of scope for this wave — see the "Plumbing beyond Wave 2"
note below.

## Plumbing beyond Wave 2 (separate work)

- `cargo tauri build` packages the Rust shell + UI but does NOT
  ship the Python interpreter. To make a real distributable .app
  we need a Tauri sidecar (externalBin) carrying a
  PyInstaller-frozen `python -m guardian` binary. That's a
  self-contained project of its own.
- The macOS bundle currently has no signing identity or
  notarization config. Without those, distributed copies get
  quarantined on macOS 15+/26 with no right-click bypass.
  Requires an Apple Developer ID and APPLE_API_KEY env vars.

## Wave 3 (in progress)

UX polish + remaining low-risk quality fixes. Closing medium
findings as they touch the same code paths.

Done in Wave 3:
  #28 — First-run UX: auto-create config, button adapts to
        "Create config" / "Reset to defaults", footer labels.
  #29 — Alert-replay gallery: each thumbnail labeled with
        Today HH:MM / Yesterday HH:MM / MMM D HH:MM.
  #30 — Camera dropdown: distinct placeholder per real state
        (scanning / no cameras / scan failed).
  #50 — tsconfig noUnusedLocals/Parameters → true. Removed
        unused projectRoot state. Fixed escapeHtml double-escape
        bug (React text-children are auto-escaped; calling
        escapeHtml on top produced literal '&quot;…').
  #5/#78 — Cooldown charged at submit time on the main
        thread, not at dequeue on the worker. Prevents duplicate
        paid detective calls when M3 is slow.

## Wave 4 (planned)

- #62 — Continuity Camera offline alert
- #75 — Watchdog per-start accumulation guard
- #77 — WebSocket auto-reconnect after network sleep
- #50 residual — log-tail live status pill uses the right value
- #73/74 — Timezone in alerts and detective prompt
- #36 — Test coverage gaps
- #56 — JSON Schema for config.yaml
- #58 — Dead config fields sweep
- #29 follow-up — Date-grouping of alert gallery
- #34 — Color contrast (WCAG)
- #33 — Keyboard navigation

## Lower-priority

- #41 (full) — Tauri sidecar bundling + signing + notarization
- #67 — README Continuity Camera failure-modes section
- #68 — Continuity Camera latency graceful-degrade
- #52 — useEffect cleanup audit
- #53 — Tailwind opacity-modifier compat check
- #51 — Tailwind palette drift check
- #65 — Detective prompt: no protected-attribute output
- #66 — GDPR face-blur in stored snapshots
- #54 — JSONL format robustness (embedded newlines)

Medium findings, batched by domain.
