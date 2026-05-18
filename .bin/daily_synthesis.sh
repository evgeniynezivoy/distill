#!/usr/bin/env bash
# daily_synthesis.sh — invoked by daily.sh after harvest + scan-candidates.
# Pipes structured prompt to `claude --print`, then applies output via apply_daily_output.py.
#
# Env vars:
#   BRAIN_ROOT  — path to vault root (default: $HOME/brain)
#   TODAY       — date string (default: today, YYYY-MM-DD)
#   MODEL       — Claude model (default: claude-sonnet-4-6)
#   CLAUDE_BIN  — claude CLI binary (default: from PATH)
#   PY          — python3 binary (default: from PATH)

set -euo pipefail

# Allow nested invocation from a Claude Code interactive session
unset CLAUDECODE CLAUDE_CODE_SIMPLE 2>/dev/null || true

BRAIN_ROOT="${BRAIN_ROOT:-$HOME/brain}"
TODAY="${TODAY:-$(date +%Y-%m-%d)}"
MODEL="${MODEL:-claude-sonnet-4-6}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo claude)}"
PY="${PY:-$(command -v python3 || echo python3)}"

cd "$BRAIN_ROOT"

PROMPT_FILE="$(mktemp -t distill-daily-prompt.XXXXXX)"
OUTPUT_FILE="$(mktemp -t distill-daily-output.XXXXXX)"
trap 'rm -f "$PROMPT_FILE" "$OUTPUT_FILE"' EXIT

# 1. Build prompt
"$PY" .bin/build_daily_prompt.py --brain-root "$BRAIN_ROOT" --today "$TODAY" > "$PROMPT_FILE"

# 2. Pipe into claude --print
"$CLAUDE_BIN" --print --model "$MODEL" < "$PROMPT_FILE" > "$OUTPUT_FILE"

# 3. Sanity check
if ! grep -q -- "---START-DAILY-LOG---" "$OUTPUT_FILE"; then
  echo "ERROR: claude output missing ---START-DAILY-LOG--- marker" >&2
  mkdir -p "$BRAIN_ROOT/.bin/logs"
  cp "$OUTPUT_FILE" "$BRAIN_ROOT/.bin/logs/daily-${TODAY}.raw"
  exit 3
fi

# 4. Apply artifacts
"$PY" .bin/apply_daily_output.py \
  --brain-root "$BRAIN_ROOT" \
  --today "$TODAY" \
  --input-file "$OUTPUT_FILE"

echo "daily_synthesis.sh: OK for $TODAY"
