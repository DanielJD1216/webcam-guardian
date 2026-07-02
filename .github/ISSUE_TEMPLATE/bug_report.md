name: Bug report
about: Something isn't working as documented
title: "[bug] "
labels: bug
assignees: ""

---

**Describe the bug**
A clear description of what goes wrong.

**To reproduce**
Steps, config, commands:
```bash
# commands run
```

**Expected**
What you expected to happen.

**Environment**
- macOS version (`sw_vers -productVersion`):
- Python version (`python --version`):
- `pip show webcam-guardian | head -3`:
- Guard backend / device (`config.yaml`):
- Detective provider (`config.yaml`):

**Logs / artifacts**
Paste relevant `events.jsonl` lines (redact any path that could identify a
captured webcam frame), `snapshots/bench_results.json`, or screenshots.

**Did `pytest -q` pass locally?**
Were all 15 tests green? (Paste the last line.)
