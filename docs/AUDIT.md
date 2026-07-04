# Audit — review-of-reviews

External engineers reviewed this repo against the **v0.3.0**
tag (commit `748f3f9`). 78 prompts, 248 findings, every critical/high
adversarially verified against the source.

## Files

- `Verdict/REVIEW-v0.3.0.md` — the full review. ~480 KB, 2636 lines.
  Every prompt answered, every finding tied to a file:line.
- `AUDIT-FIXES.md` — running list of which findings are fixed and
  in which commit. Start here to see "what's left."

## Snapshot state at v0.3.0

| | |
|---|---|
| Critical | 5 (2 confirmed via adversarial re-verification) |
| High | 23 (18 confirmed) |
| Medium | 97 |
| Low | 94 |
| Info | 29 |
| **Total findings** | **248** |

## Top-3 confirmed critical findings (every engineer re-verified)

1. **Camera stall/revocation is undetected.** The guardian
   analyzes a frozen frame forever while reporting healthy stats.
   `guardian/capture.py` has no sequence number or capture
   timestamp; `cam_window` in `guardian/main.py` counts loop
   iterations so the HUD reports a healthy fps even when frames
   stop arriving. A security product that goes blind while telling
   the user it is watching is the worst failure class it can have.

2. **Unauthenticated, origin-unchecked WebSocket on a fixed
   localhost port streams live webcam frames to any local process
   or web page.** `serve(handler, "127.0.0.1", 9876)` in
   `guardian/main.py:136` accepts every connection; browsers can
   open cross-origin `ws://127.0.0.1:9876` to silently receive
   the live feed. For a privacy-marketed webcam product this is a
   direct security hole.

3. **Tauri app truncates `events.jsonl` on every launch.**
   `File::create` at `src-tauri/src/main.rs:381` — the "append-
   only, crash-safe" log survives everything except opening the
   app. Every timestamp the UI shows is fabricated at parse time.

## What this review is *not*

- It is not a code style review. Most of the code is fine.
- It is not a "rewrite this" review. The pure-logic core
  (escalator, JSONL event log, detective parse-failure path) is
  genuinely solid and well-tested.
- It is not a final answer. The fixes for the Wave-1 set are
  tracked in `AUDIT-FIXES.md`; everything else is triaged by
  domain in the review itself.

## How to read `REVIEW-v0.3.0.md`

Each prompt gets a section. Each finding has:

- **Sev** — 🔴 critical / 🟠 high / 🔵 medium / ⚪ low / ℹ️ info
- **Verdict** — `confirmed` (adversarially re-verified) or
  `claimed` (single-pass observation)
- **Finding** — the actual bug, the file:line, and the fix
- **Verification** — usually a quoted snippet of the relevant
  source; this is the lead reviewer's audit trail

When we fix a finding, the commit message links to it.
