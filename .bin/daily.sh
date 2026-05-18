#!/usr/bin/env bash
# daily.sh — wrapper for launchd @ 09:00.
# Sequence: harvest → scan-candidates → daily synthesis (L2) → index touch.
# Graceful style: each step logs its own failure but doesn't abort the chain.
#
# Env vars:
#   BRAIN_ROOT  — path to vault root (default: $HOME/brain)
#   PY          — python3 binary (default: from PATH)
#   CLAUDE_BIN  — claude CLI binary (default: from PATH)

set -uo pipefail

BRAIN="${BRAIN_ROOT:-$HOME/brain}"
BIN="$BRAIN/.bin"
PY="${PY:-$(command -v python3 || echo python3)}"

notify() {
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$1\" with title \"distill\"" 2>/dev/null || true
  fi
}

export BRAIN_ROOT="$BRAIN"

# 1. Harvest
"$PY" "$BIN/harvest.py" || { echo "daily.sh: harvest.py exit non-zero"; notify "harvest failed"; }
HARVEST_TS="$(date '+%Y-%m-%d %H:%M:%S')"

# 2. Scan candidates (feeds weekly-drafts via candidates.json)
"$PY" "$BIN/scan-candidates.py" || echo "daily.sh: scan-candidates.py exit non-zero"

# 3. Daily synthesis
if ! bash "$BIN/daily_synthesis.sh"; then
  echo "daily.sh: daily_synthesis.sh exit non-zero — retrying once"
  sleep 5
  if ! bash "$BIN/daily_synthesis.sh"; then
    echo "daily.sh: daily_synthesis.sh failed twice"
    notify "daily synthesis failed"
  fi
fi
DAILY_TS="$(date '+%Y-%m-%d %H:%M:%S')"

# 4. Index touch
"$PY" "$BIN/index_touch.py" \
  --brain-root "$BRAIN" \
  --harvest-ts "$HARVEST_TS" \
  --daily-ts "$DAILY_TS" || echo "daily.sh: index_touch.py exit non-zero"

# 5. Post-run notify
TODAY_LOG="$BRAIN/logs/daily/$(date +%Y-%m-%d).md"
if [ -f "$TODAY_LOG" ]; then
  if grep -qE "^smells_repeat:\s*\[[^]]" "$TODAY_LOG"; then
    REPEATS="$(grep "^smells_repeat:" "$TODAY_LOG" | head -1)"
    notify "repeat smell — $REPEATS"
  elif grep -qE "^cross_project:\s*\[[^]]" "$TODAY_LOG"; then
    notify "cross-project pattern — see logs/daily/"
  fi
fi

echo "daily.sh: done at $(date)"
