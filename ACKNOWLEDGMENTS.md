# Acknowledgments

This project was created with significant AI assistance. Disclosing who did
what is part of the project's stated privacy posture — anyone using this
code to understand or audit it should know how it came together.

## Roles

| Component | Author | Tooling |
|---|---|---|
| End-to-end build plan (`BUILD-PLAN.md`) | **Fable 5** | Not disclosed — author worked from the original brief, verified every API fact against live docs, and explicitly routed around three claims in the brief that were wrong (MiniMax M3 not supporting `response_format`, LocateAnything's Linux-only constraint, thinking-mode default on the OpenAI-compatible endpoint). |
| All source code (`guardian/`, `scripts/`, `tests/`, `pyproject.toml`, `BUILD-PLAN.md`, all docs) | **MiniMax-M3** (`MiniMax/MiniMax-M3`) | Running inside [opencode](https://opencode.ai) on macOS |
| Repo infrastructure (git, CI, GitHub-side settings, social preview image) | **human maintainer** | Local terminal, GitHub.com UI |
| Project decisions (Mac dev machine, pay-as-you-go MiniMax key, Telegram + email alerts, MIT license, Resend over Gmail SMTP, RT-DETR over LocateAnything on Mac) | **human maintainer** | Brief + back-and-forth during M0–M8 |

## What MiniMax-M3 actually produced

Roughly 3,000 lines of code + 700 lines of docs across 49 tracked files.
Every code path, test, comment, and diagram was generated from the
build plan and the maintainer's iterative feedback. No code was copied
from other open-source projects beyond what the build plan explicitly
recommended (RT-DETR via HuggingFace transformers, Ultralytics opt-in
extra, ntfy / Telegram / Resend client patterns). Every third-party
component retains its original license.

## What was NOT done by AI

- The Mac itself isn't an AI artifact.
- The webcam footage, the Telegram bot token, the Resend API key, and
  the Gmail App Password in `.env` (gitignored, never committed).
- The decision to ship at all.
- The decision to make it open source under MIT.

## Why disclose

Two reasons:

1. **Trust.** A security tool that quietly has AI authorship is harder
   to audit. Anyone reviewing the diff, the trap list, the alert flow,
   or the detective integration should know the code was generated and
   can ask "what did the model get wrong?" — and the `BUILD-PLAN.md`
   §13 trap list is the honest answer.
2. **Reproducibility.** If a maintainer changes the project's AI
   tooling, downstream forks know what to verify.

## Source-of-truth documents

- `BUILD-PLAN.md` — the design contract. Every code choice should trace
  back to a section number in there. If you find a code path that
  doesn't, it's a bug in the plan's traceability, not necessarily in
  the code.
- `CHANGELOG.md` — every change is attributed to a commit; every
  commit message states the why.
- `CONTRIBUTING.md` — explicitly tells contributors to skim §13 before
  touching anything that talks to the detective, the guard, or the OS
  camera/notification surface. Those traps are the AI's own
  self-corrections; they're load-bearing.

If a future maintainer audits the project and finds a code path that
doesn't match the plan, that's a defect — please open an issue.