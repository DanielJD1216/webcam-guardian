# Audit fixes tracker

Status of every finding in `Verdict/REVIEW-v0.3.0.md`. Updated as
commits land.

## Critical

- [ ] #1 — Camera stall/revocation undetected (CRITICAL, confirmed)
- [ ] #3 — Unauthenticated WebSocket (CRITICAL, confirmed)

## High (top 18)

- [ ] #9  — `log.save_escalation_frames` is a no-op (privacy)
- [ ] #9  — Tauri truncates `events.jsonl` on launch
- [ ] #12 — Telegram bot token leaks in `repr(e)`
- [ ] #17 — `DetectiveWorker.run` catch-all drops alert on snapshot failure
- [ ] #20 — UI staleness detector structurally defeated by 10 Hz broadcast
- [ ] #25 — `THINK_RE` regex missing angle brackets
- [ ] #27 — Config never loaded on mount; resolution picker no-op
- [ ] #35 — One misconfigured channel silently disables ALL alerting
- [ ] #41 — Bundled `.app` cannot run outside dev checkout
- [ ] #43 — `frontendDist` / vite `outDir` mismatch
- [ ] #44 — Tauri shell cannot launch on Windows
- [ ] #47 — Resolution picker is a no-op on shipped config
- [ ] #61 — Alert delivery has no retry / dead-letter
- [ ] #63 — Every timestamp shown in UI is fabricated at parse time
- [ ] #69 — `max_detective_calls_per_run` never resets
- [ ] #70 — MiniMax `thinking` extra_body default can't be cleared
- [ ] #71 — `judge.txt` brace makes every detective call raise

## Wave 1 (in progress)

Critical + alert reliability. See commit history — each fix gets
its own commit with a `fix(audit): #N — …` message prefix.

## Wave 2 (planned)

Tauri/build/cross-platform (#27, #43, #44, #47, #63, #41).

## Wave 3 (planned)

Medium findings, batched by domain.
