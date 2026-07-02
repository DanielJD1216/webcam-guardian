# Recording a demo run

This is the deliverable the build plan exists to produce. A 60–90 second
screen recording that shows: live preview → boxes → detective banner →
arriving Telegram/email → one escalation per delivery event thanks to the
45-second cooldown.

## 1. Pre-flight checklist

- [ ] Camera permission granted in **System Settings → Privacy & Security**
      (opencode/Terminal/your recording host).
- [ ] `MINIMAX_API_KEY`, `TELEGRAM_BOT_TOKEN`, `RESEND_API_KEY` set in `.env`.
- [ ] `config.yaml` has `telegram_chat_id`, `email.from_addr`, `email.to_addr`
      filled.
- [ ] venv ready. For the smoothest experience, use the Apple-Python
      `~/.venv-sys` (TCC-trusted on macOS 26). The project's `.venv` works
      too if python.org Python was installed.
- [ ] Ollama running (`ollama serve`) **only** if you intend to demo the
      privacy-first path. Otherwise: skip.

## 2. Screen recording

macOS:
1. **⌘ Shift 5** (or QuickTime Player → File → New Screen Recording).
2. Click **Options**, pick **Built-in Display** → **Record selected portion**
   covering only the guardian's OpenCV window (recommended) or **Record
   entire screen** if you want the HUD + alerts side-by-side.
3. **Start recording** about three seconds before you click into the demo.

## 3. Run the demo

In Terminal.app (one host app, full TCC plumbing):

```bash
cd "/Users/admin/Desktop/DOO MADE/Vibe Coding/OPENCODE/M3 Camara project testing/webcam-guardian"
./scripts/record_demo.sh
```

That script:
- Sources the Apple-Python venv (where TCC is granted)
- Runs `python -m guardian --max-frames 300` (~60 s at 5 fps)
- Pipes stdout + stderr to `snapshots/demo_<timestamp>.log`
- After exit, prints the most recent detective + alert events

## 4. Demo choreography

While the recorder is on and the window is open:

| t (s)     | Action                                              | Expected in HUD                                                  |
|-----------|-----------------------------------------------------|------------------------------------------------------------------|
| 0 – 5     | Stay out of frame. Empty scene.                     | No detections, no calls.                                         |
| 5 – 10    | Walk into frame, stand in middle of view.           | Boxes on person, `>>> DETECTIVE CALLED: person` banner.          |
| 10 – 14   | Stand still.                                        | Telegram + email arrive within ~3 s.                              |
| 14 – 75   | Stay in frame continuously.                         | One more call at ~t = 14 + 45 (cooldown wall-clock from dispatch).|
| 75 – 85   | Hold a box / package at chest height ("delivery").  | Box on person, no car; one call after debounce(3); likely alert or no-alert depending on framing. |
| 85 – 110  | Step out of frame.                                  | No calls, no alerts.                                              |
| 110       | Press `q`.                                           | Window closes; `events.jsonl` written.                            |

The exact verdicts vary by what MiniMax M3 sees. The make-or-break check is
that **a continuous in-frame presence produces ≤ 3 calls** (one initial + two
cooldown refreshes).

## 5. Stop the recording

⌘ Shift 5 again → Stop button. macOS saves a `.mov` to your Desktop by
default. Trim with QuickTime → Edit → Trim, or HandBrake for `.mp4`.

## 6. Post-demo cleanup

- `events.jsonl` contains real decisions. Open it and grep for
  `"alert_sent"` to confirm both Telegram and Resend fired.
- `snapshots/alert_*.jpg` are the snapshots that went out as attachments.
- Take a screenshot of the HUD at the moment of alert for the README hero
  image.

## 7. Troubleshooting

| Symptom                                                      | Fix                                                              |
|--------------------------------------------------------------|-----------------------------------------------------------------|
| Camera not authorized                                        | Re-grant in **System Settings → Privacy & Security → Camera**.   |
| Detective banner shows but no Telegram arrives               | Check `.env` has `TELEGRAM_BOT_TOKEN` and `config.yaml` has the right `telegram_chat_id`.  |
| Email doesn't arrive                                         | Check `info@shifthubpayroll.com` is **verified** in Resend dashboard; check spam folder. |
| Two detectives called back-to-back (no cooldown)            | Check `escalation.cooldown_seconds` in `config.yaml` (default 45). |
| Multiple alerts on the same person staying in frame          | Check `escalation.max_alerts_per_hour` (default 10).             |
| Empty detection list                                         | Check `guard.backend` (default `rtdetr`).                       |

## 8. What the demo proves (per BUILD-PLAN §1)

| Section                              | Verified by                                                |
|--------------------------------------|------------------------------------------------------------|
| Live preview + boxes                  | The OpenCV window itself.                                  |
| Detective called when class appears  | `>>> DETECTIVE CALLED:` banner.                             |
| Real notification + sensible message  | Telegram photo + email with the model's `message` field.    |
| One escalation per delivery event     | `events.jsonl` shows exactly one `escalation_dispatched` per appearance window.|
