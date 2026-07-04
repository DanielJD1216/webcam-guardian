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

## Wave 3 (done)

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

## Wave 4 (done)

- [x] #58 — `log.save_escalation_frames` now actually controls
        per-escalation frame persistence (was silently AND-ed
        with `alert.attach_snapshot`). SECURITY.md's instruction
        "set save_escalation_frames: false to stop persisting frames"
        is now a real control. LocateAnythingGuard.jpeg_quality
        AttributeError fixed (hard-coded to 80 in the guard).
- [x] #73 — Detective prompt now includes the IANA tzname so the
        model knows whether "Local time" is home-TZ or away-TZ
        when the user is traveling.
- [x] #74 — Alert title + body include tzname + UTC timestamp so
        a user reviewing alerts after travel knows when each event
        actually happened.
- [x] #62 — Camera-offline alert. When a camera stalls >5 s,
        fires a one-shot "Webcam Guardian · camera_offline"
        through the existing channels; fires a "camera_restored"
        on recovery. Doesn't burn the hourly alert cap. Closes the
        "system silently goes blind" silent safety failure.

## Wave 5 (done)

- [x] #75 — Watchdog per-start accumulation guard. Generation
        counter in GuardianState; leaked watchdogs self-terminate
        within 2 s of a new start.
- [x] #77 — WebSocket reconnect chain. Effect declares a
        `cancelled` flag + `retryTimer` handle; cleanup cancels
        the chain. Exponential backoff capped at 8 s.
- [x] #33 + #34 — Accessibility. :focus-visible outline; status-pill
        colors meet WCAG AA contrast.

## Wave 6 (done)

- [x] #36 — Real test coverage. Refactored detective.py parse
        block to a pure `parse_decision(msg)` function and rewrote
        test_parsing.py to actually call it. Fixed the duplicate
        test name that was silently shadowing a real test. 7 new
        tests cover: valid tool-call parse, invalid JSON, valid
        prompt-JSON, garbage in (trap #13), real `<think>` tags with
        'think' inside the JSON body, encode_frame downsize, and
        encode_frame no-upsize. **17 tests pass** (was 15 with a
        silent duplicate).
- [x] #29 follow-up — Alert-replay gallery is grouped by date
        (Today / Yesterday / "<Mon> <Day>") via groupAlertsByDate().
- [x] #65 — Detective prompt: appended a guideline that explicitly
        forbids describing protected attributes (race, ethnicity,
        gender, age, religion, disability) in alert messages.
- [x] #50 residual — log-tail live status pill uses the right
        value (the previous pill color revision in Wave 5 also fixed
        this — text color was being inherited instead of set per
        state).

## Wave 7 (done)

- [x] #56 — Unknown / misspelled config keys are loud at boot.
        Per-section allow-list plus a cross-field check that every
        trigger/draw class is mapped in coco_ids. A typo'd
        `trigger_clases:` no longer silently defaults.
- [x] #57 — alert.email.api_key_env is now plumbed through to
        ResendChannel — the dead config knob is now alive.
- [x] #54 — EventLog.log is now safe under disk-full / closed-file
        conditions (catches OSError + ValueError, falls back to
        stderr) so a logging failure can't kill the detective
        worker. NaN / +Inf / -Inf are sanitized to None before
        serialization so the JSONL line is always parseable JSON
        (no more silent drop in the Tauri log viewer).

## Wave 8 (done)

- [x] #52 — Tauri listeners unlistened. Collect the listen
        Promises in an array and call them all in cleanup so React
        StrictMode dev double-mount doesn't double-register.
- [x] #51 — MovingBorder + Spotlight defaults fixed to current
        palette tokens (#0b80d1 and rgba(11,128,209,0.18)
        respectively) so the preview panel no longer glows in
        retired-palette cyan.
- [x] #66 follow-up — log.retention_days + prune_older_than()
        startup sweep for GDPR/CCPA storage limitation. Snapshots
        and events older than N days are deleted at boot. Malformed
        lines are kept for forensics.

## Wave 9 (done)

- [x] #52 follow-up — refreshAlerts was firing twice (on the
        [logLines] effect and on the 5 s interval). Dropped the
        [logLines] effect; the live event push keeps the log
        current without a separate list_alerts per status poll.
        Saves one IPC + one list_alerts per status poll.
- [x] #51 follow-up — 'dim' token renamed to 'accent' (was a dark-
        theme leftover name; the token is a vivid blue used for
        headings, not a tonal variant). The cyan.dim subfield stays
        as cyan.dim (it really is a tonal variant). Updated the
        three text-accent uses in App.tsx.
- [x] #53 — Tailwind opacity-modifier compatibility verified under
        pinned 3.4.14. All the bg-*/15, bg-*/30, text-*/N classes
        compile correctly. The custom hex colors (e.g. #0b80d1) are
        auto-rewritten to rgb(r g b / <alpha>) so bg-cyan/10
        produces the right alpha.

## Wave 10 (done — partial)

- [x] #66 (partial) — `blur_person_boxes(frame, boxes, top_fraction)`
        utility in `guardian/storage.py` (PR #1, merged `cb259b2`).
        Pure helper that returns a copy of `frame` with the top fraction
        of each RT-DETR person box Gaussian-blurred. Boxes clip to
        frame bounds; empty/0-fraction inputs pass through unchanged.
        5 tests in `tests/test_blur.py`. Integration through the
        live snapshot/save path stays as a follow-up.
- [x] **#a78 (new — caught by E2E)** — DetectiveWorker alert path
        crashed at `cfg.log.snapshots_dir / "alert_...jpg"` whenever
        `alert.attach_snapshot=True` AND `log.save_escalation_frames=True`
        (production defaults). Root cause: `LogCfg.snapshots_dir` is
        typed `str` (loaded from YAML); the worker treated it as a
        Path object. Fix in `guardian/main.py`: wrap with `Path()`
        once at the top of the alert block. Regression test
        `tests/test_worker_path.py` exercises this exact combination.
- [x] **#a79 (new — caught by E2E CI)** — `DetectiveWorker._stop`
        shadowed `threading.Thread._stop()` (an internal CPython
        method invoked from `Thread.join()`). The original method
        became a `threading.Event`; calling it raised
        `TypeError: 'Event' object is not callable`, surfaced as a
        failing `worker.join()` in tests. The bug existed since Wave
        1 but was masked in production because `main()` exits the
        process before any daemon thread's join lifecycle matters.
        Fix in `guardian/main.py`: rename to `_stop_event`.
- [x] **#a80 (new — caught by Tauri runtime)** — Audit #3's WS
        handler rejected ALL `Origin` headers, but the Tauri webview
        (WKWebView on macOS, WebView2 on Windows, WebKitGTK on Linux)
        IS a browser and ALWAYS sends one. Result: the live-preview
        pane stayed at "Disconnected. Restarting..." forever in
        Tauri mode. Fix: whitelist Tauri-internal origins
        (`http://tauri.localhost`, `tauri://localhost`, `null`,
        empty) instead of blanket-rejecting. The token check remains
        the actual security gate; the Origin check is defense-in-
        depth. 6 new tests in `tests/test_ws_origin.py` cover
        accept + reject paths.
- [x] **#a81 (new — follow-on from a80)** — When the URL had a
        *wrong* token, the handler still entered the 2-second
        `wait_for(conn.recv())` fallback before rejecting. That's a
        2-second window in which a wrong-token attacker could read
        frames. Fix: when the URL has a token at all and it doesn't
        match, reject immediately. The 2-second wait_for now runs
        only when no URL token was presented (clients that can only
        send the token as the first message).

## Wave 11 (planned)

- #66 (full) — wire `blur_person_boxes` into the snapshot/save path
  with a config flag and per-event opt-out
- #54 follow-up — `default=str` is a footgun (review suggested)

## Lower-priority

- #41 (full) — Tauri sidecar bundling + signing + notarization
- #67 — README Continuity Camera failure-modes section
- #68 — Continuity Camera latency graceful-degrade
- #54 — JSONL format robustness (embedded newlines)
- #52 — useEffect cleanup audit

Medium findings, batched by domain.
