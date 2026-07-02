# Contributing

Thanks for the help.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

Run the suite:

```bash
pytest -q
```

All 15 tests must pass. There are no integration tests in CI; the live-loop and detective are exercised in your own session.

## Code style

- Python 3.11/3.12, type hints throughout.
- No comments unless the reasoning isn't obvious from the code (modules and
  non-trivial helpers carry docstrings citing the BUILD-PLAN section they
  implement).
- One concern per module. `guardian/guard/` holds backends; `guardian/alerts/`
  holds alert channels. Don't import across concerns.

## Testing

- `tests/test_escalate.py` — pure-logic escalator, must run with no hardware
  or network.
- `tests/test_parsing.py` — detective parsing surface, no network.
- Add a test for any new pure-logic path BEFORE the implementation lands.

## Traps to respect

The traps list in `BUILD-PLAN.md §13` is a verbatim log of failure modes the
maintainer hit during the original build. Skim it before touching anything
that talks to the detective, the guard, or the OS camera/notification
surface.

Highlights:

- The local guard and the detective are the same package but **never share
  imports across the MIT / AGPL boundary** — Ultralytics stays opt-in.
- Cooldown starts at **dispatch**, regardless of the detective's verdict.
- Parse failure from the detective is an `alert:false` logged event. Never
  crash, never alert on garbage.
- `cv2.imshow` and `cv2.waitKey` only on the main thread.
- `extra_body={"thinking":{"type":"disabled"}}` rides to the OpenAI SDK via
  the `extra_body` kwarg, **not** as a named parameter.

## Pull requests

- One focus per PR.
- Don't bump `pyproject.toml` version unilaterally — the maintainer tags.
- Squash on merge.

## Reporting bugs

Use the **Bug report** issue template. Include:
- `pytest -q` output (15 tests must still pass)
- macOS / Python version (`python --version`, `sw_vers -productVersion`)
- relevant `events.jsonl` lines (redact any path that could identify a
  webcam frame)
