#!/usr/bin/env bash
# Record a demo run of webcam-guardian.
#
# Per BUILD-PLAN.md §1, demo success looks like:
#   "a live preview window with boxes, a visible 'detective called' moment when
#    a person appears, a real notification arriving with a sensible message,
#    and a continuous delivery event firing exactly one escalation thanks to
#    the cooldown."

set -euo pipefail

cd "$(dirname "$0")/.."

USE_SYS_VENV="${USE_SYS_VENV:-1}"
MAX_FRAMES="${MAX_FRAMES:-300}"   # ~60s @ 5 analyzed_fps
EXTRA_ARGS="${EXTRA_ARGS:-}"

if [[ "$USE_SYS_VENV" == "1" ]]; then
    if [[ -d "$HOME/.venv-sys" ]]; then
        echo "[demo] activating ~/.venv-sys (Apple-Python TCC-tracked)"
        # shellcheck disable=SC1091
        source "$HOME/.venv-sys/bin/activate"
    else
        echo "WARN: ~/.venv-sys not found. Falling back to project's .venv"
        echo "      (only works if brew-Python has already been TCC-granted)"
        source .venv/bin/activate
    fi
else
    source .venv/bin/activate
fi

mkdir -p snapshots
LOG="snapshots/demo_$(date +%Y%m%d_%H%M%S).log"

echo "[demo] python: $(which python)  version: $(python -c 'import sys; print(sys.version.split()[0])')"
echo "[demo] log: $LOG"
echo "[demo] max-frames: $MAX_FRAMES  extra: $EXTRA_ARGS"
echo
echo "When the window opens:"
echo "  1. Walk into frame (person)            → expect 1 detective call, 1 alert"
echo "  2. Stand still for ~60s                → expect ≤ 2 more calls (45 s cooldown)"
echo "  3. Leave, run a fake 'delivery' scene  → expect 0 alerts (delivery=false_positive)"
echo "  4. Press 'q' to quit."
echo
read -rp "Press Enter to start the demo... "

python -m guardian --max-frames "$MAX_FRAMES" $EXTRA_ARGS 2>&1 | tee "$LOG"

echo
echo "[demo] demo run complete; log saved to $LOG"
echo "[demo] key events:"
grep -E '"type": "detective_result|"type": "alert_sent|"type": "alert_dispatched|"type": "escalation_dispatched' \
     events.jsonl | tail -20 || true
