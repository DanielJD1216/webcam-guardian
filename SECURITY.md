# Security Policy

This is a webcam-always-running tool. Security disclosures are taken
seriously; reports go straight to the maintainer.

## Threat model, in scope

- An attacker gaining access to your webcam feed via a bug in this project.
- An attacker using this project's logs / events.jsonl / snapshots/ to
  reconstruct activity in your home.
- An attacker tricking the detective into alerting on fabricated events
  via prompt injection in the user-editable `guardian/prompts/judge.txt`.

## Out of scope

- The detective model (MiniMax M3 / Ollama / etc.) leaking data — that's
  the detective provider's security posture, not ours.
- The webcam OS driver — Apple's, Logitech's, or whoever made it.
- Cloud alert channels (Telegram, Resend) leaking data — that's their
  posture.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | yes       |
| 0.1.x   | best-effort |
| older   | no        |

## Reporting a vulnerability

**Email:** open an issue marked `private` via GitHub's
[security advisories](https://github.com/DanielJD1216/webcam-guardian/security/advisories/new)
flow, or contact the maintainer through the GitHub profile.

Please **do not** open a public issue for security bugs — exploit code
in a public repo helps attackers more than defenders.

What to include:
- Steps to reproduce (preferrably in a fresh venv)
- A minimal `events.jsonl` excerpt showing the issue (redact any path
  that could identify a captured frame)
- macOS / Linux version, Python version, detective provider

Response target: **within 7 days**, fix or status update. Critical
issues get a tagged patch release on top of the current minor.

## Operational hygiene for users

This project ships with privacy defaults — `.env`, `config.yaml`,
`events.jsonl`, and `snapshots/` are all gitignored from the first
commit (§13 trap 15). Keep them that way:

- Don't `git add -f .env` to "fix" something.
- Don't share screenshots of `.env` or `config.yaml` in support chats.
- Don't publish `events.jsonl` — it can carry frame paths.
- Before opening the repo publicly, run:
  ```bash
  git log --all --full-history -p | grep -E "sk-[A-Za-z0-9]{20,}|re_[A-Za-z0-9]{20,}|TELEGRAM_BOT_TOKEN=[0-9]+:" || echo "clean"
  ```
  If that returns anything, rotate those keys before publishing.

## Hardening checklist for self-hosters

- [ ] Run the live loop from a dedicated user account, not your daily driver.
- [ ] Enable macOS / Linux disk encryption (FileVault / LUKS) so a stolen
      laptop doesn't yield `snapshots/`.
- [ ] If you don't need frames persisted, set
      `log.save_escalation_frames: false` in `config.yaml`.
- [ ] If you don't need local logs, set `log.events_path: /dev/null`
      (Linux) or redirect to a tmpfs that gets wiped on reboot.
- [ ] For Ollama path: ensure the Ollama daemon listens on
      `127.0.0.1` only — not `0.0.0.0`.
- [ ] For Resend path: rotate the API key every 90 days; verify the
      `from_addr` domain is `verified` in the Resend dashboard.