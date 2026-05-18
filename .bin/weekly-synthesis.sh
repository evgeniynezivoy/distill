#!/usr/bin/env bash
# weekly-synthesis.sh — Sunday 18:00 via launchd.
# Invokes headless claude (`claude --print`) with vault context (read-only).
# Writes synthesis to $BRAIN/logs/weekly/<YYYY-Www>.md and updates INDEX Last weekly review.
#
# Env vars:
#   BRAIN_ROOT  — path to vault root (default: $HOME/brain)
#   CLAUDE_BIN  — claude CLI binary (default: from PATH)

set -uo pipefail

unset CLAUDECODE CLAUDE_CODE_SIMPLE 2>/dev/null || true

BRAIN="${BRAIN_ROOT:-$HOME/brain}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo claude)}"
WEEK=$(date +%G-W%V)
OUTPUT="$BRAIN/logs/weekly/$WEEK.md"
LOG_DIR="$BRAIN/.bin/logs"
LOG="$LOG_DIR/weekly-$(date +%Y-%m).log"

mkdir -p "$(dirname "$OUTPUT")" "$LOG_DIR"

{
  echo "=== $(date) weekly start ($WEEK) ==="
} >> "$LOG"

PROMPT=$(cat <<EOF
Read:
1. $BRAIN/INDEX.md
2. all $BRAIN/projects/*.md (especially '## Recent activity' between <!-- HARVESTER-START --> and <!-- HARVESTER-END --> + the '## Daily synthesis (auto, regenerated each run)' slot with rolling 7-day signal)
3. all $BRAIN/logs/daily/*.md from the last 7 days (the main input — distilled signal, not raw harvest)
4. all $BRAIN/_meta/drafts/lessons/*.md if any (lesson candidates pending apply)

Output clean markdown to stdout. NO tool calls beyond Read/Glob/Grep. Do not write files — text output only.

Structure:

# Weekly review — $WEEK

_Generated $(date '+%Y-%m-%d %H:%M %Z')_

## Per-project narrative

For each tracked project: 2-3 sentences about the week's work — synthesis over daily logs (aggregate the week, don't restate each day). If 0 commits — short "quiet, focus elsewhere".

## Cross-project themes

Patterns visible only when looking across projects AND across multiple daily logs (shared smell patterns, repeating lessons, synchronous shipping events). If no patterns — say so directly.

## Promotion candidates (L3 future)

Lessons that fired 2+ times across the last 7 days across 2+ projects (see smells_repeat frontmatter in logs/daily/*.md). These are candidates for future skill promotion. If nothing repeated — "(none)". This section is a flag for the future L3 phase; nothing needs to be done now.

## Stuck / abandoned

Projects with activity dropped 5+ days while previously hot. Feature/fix branches without commits 7+ days. Open threads sitting longer than 14 days.

## LinkedIn drafts (optional)

**CRITICAL RULES for this section — different from the rest of the synthesis:**

1. **ENGLISH ONLY.** Per-project narrative, cross-project themes, stuck section above can be in any language (private notes). LinkedIn drafts are PUBLIC content. English prose mandatory.

2. **Confidentiality-safe — abstract all sensitive references.** Replace internal app names, colleague names, client codes, exact PR numbers that could uniquely identify a project with generic descriptions ("an internal lead-verification platform", "a colleague on our architecture team", "a six-phase migration"). Personal public projects can be named directly. Anything you wouldn't say at a public conference shouldn't be in a draft.

3. **Quality > quantity.** If no genuinely non-generic insight from the week — write 1 strong draft, not 2 mediocre ones. ZERO drafts is acceptable.

4. **Anti-fool rules** — eager "look-what-I-built" drafts read as fabricated. Specifically:
   - Every factual claim must reference a specific artifact (a real PR by number, a real incident date, a real metric)
   - Lesson must be proportional to story scale — don't extract cosmic insight from a minor bug
   - Reflective tone: include something that didn't work, took longer than expected, counterintuitive finding
   - No buzzword density without grounding examples
   - No template structures ("Three things I keep coming back to:", "Hard-won pattern:") — those scream LLM
   - No formulaic CTAs ("happy to compare notes") — replace with a specific question only this author could ask
   - You must be able to defend every claim if a senior peer pushes back

5. Each draft block:

### <Hook line — 1 line, English>

**Story** (3-5 lines — what happened, what we tried, what we got. Abstracted references.)

**Lesson** (1-2 lines — takeaway that applies forward beyond this project)

**Open question** (1 line for engagement)

---

Output ONLY markdown, nothing before or after.

REMINDER: synthesis body (per-project / cross-project / stuck) — any language. LinkedIn drafts subsection — ENGLISH + confidentiality-safe ONLY.
EOF
)

# Headless claude — read-only tools, prompt via stdin
if ! printf '%s' "$PROMPT" | "$CLAUDE_BIN" --print --allowed-tools "Read,Glob,Grep" > "$OUTPUT" 2>>"$LOG"; then
  EXIT_CODE=$?
  echo "=== $(date) weekly FAILED (exit=$EXIT_CODE) ===" >> "$LOG"
  exit 1
fi

if [ ! -s "$OUTPUT" ]; then
  echo "=== $(date) weekly EMPTY output ===" >> "$LOG"
  exit 1
fi

# Update INDEX.md Last weekly review line
sed -i.bak "s|^\*\*Last weekly review:\*\*.*|**Last weekly review:** [[logs/weekly/$WEEK]] · $(date +%Y-%m-%d)|" "$BRAIN/INDEX.md"
rm -f "$BRAIN/INDEX.md.bak"

echo "=== $(date) weekly DONE → $OUTPUT ===" >> "$LOG"
echo "weekly-synthesis.sh: done — $OUTPUT"
