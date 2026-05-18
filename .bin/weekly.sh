#!/usr/bin/env bash
# weekly.sh — wrapper for launchd. Sunday 18:00 runs weekly-synthesis + weekly-drafts.
# Synthesis-first (reads current state), drafts-second (reads candidates.json).
#
# Env vars:
#   BRAIN_ROOT  — path to vault root (default: $HOME/brain)
#   PY          — python3 binary (default: from PATH)

set -uo pipefail

BRAIN="${BRAIN_ROOT:-$HOME/brain}"
BIN="$BRAIN/.bin"
PY="${PY:-$(command -v python3 || echo python3)}"

export BRAIN_ROOT="$BRAIN"

bash "$BIN/weekly-synthesis.sh" || echo "weekly.sh: weekly-synthesis.sh exit non-zero"
"$PY" "$BIN/extract-linkedin-drafts.py" || echo "weekly.sh: extract-linkedin-drafts.py exit non-zero"
bash "$BIN/weekly-drafts.sh" || echo "weekly.sh: weekly-drafts.sh exit non-zero"

echo "weekly.sh: done at $(date)"
