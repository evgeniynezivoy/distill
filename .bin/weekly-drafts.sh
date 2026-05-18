#!/usr/bin/env bash
# weekly-drafts.sh — drafts ~/brain/_meta/drafts/<slug>.md из candidates.json
# для top-5 architectural events. Headless `claude --print` per candidate.

set -uo pipefail
unset CLAUDECODE CLAUDE_CODE_SIMPLE 2>/dev/null || true

BRAIN="${BRAIN_ROOT:-$HOME/brain}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo claude)}"
PY="${PY:-$(command -v python3 || echo python3)}"
CANDIDATES="$BRAIN/_meta/candidates.json"
DRAFTS_DIR="$BRAIN/_meta/drafts"
LOG_DIR="$BRAIN/.bin/logs"
LOG="$LOG_DIR/weekly-drafts-$(date +%Y-%m).log"

mkdir -p "$DRAFTS_DIR" "$LOG_DIR"
echo "=== $(date) weekly-drafts start ===" >> "$LOG"

if [ ! -s "$CANDIDATES" ]; then
  echo "no candidates.json (run scan-candidates.py first)" >> "$LOG"
  echo "weekly-drafts.sh: no candidates"
  exit 0
fi

TOTAL=$("$PY" -c "import json; print(len(json.load(open('$CANDIDATES'))))" 2>>"$LOG" || echo 0)
echo "candidates.json has $TOTAL entries" >> "$LOG"

if [ "$TOTAL" -eq 0 ]; then
  echo "weekly-drafts.sh: 0 candidates"
  exit 0
fi

DRAFTED=0
SKIPPED=0
FAILED=0

# Process top-5
for IDX in 0 1 2 3 4; do
  if [ "$IDX" -ge "$TOTAL" ]; then
    break
  fi

  CTX=$("$PY" -c "
import json
c = json.load(open('$CANDIDATES'))
if $IDX < len(c):
    print(json.dumps(c[$IDX], ensure_ascii=False))
" 2>>"$LOG")

  if [ -z "$CTX" ]; then
    continue
  fi

  SLUG=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['slug'])")
  PROJECT=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['project'])")
  SHA_RANGE=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['sha_range'])")
  DATE_RANGE=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['date_range'])")
  PRS=$(echo "$CTX" | "$PY" -c "import json,sys; print(','.join(map(str,json.load(sys.stdin)['prs'])))")
  REMOTE_SLUG=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin).get('remote_slug') or '')")
  WHY=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['why'])")
  SUBJECT=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['subject'])")
  SCORE=$(echo "$CTX" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['score'])")

  DRAFT_FILE="$DRAFTS_DIR/$SLUG.md"
  if [ -f "$DRAFT_FILE" ]; then
    echo "skip $SLUG: draft exists" >> "$LOG"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  PROJECT_PATH=$(awk -F'\t' -v p="$PROJECT" 'BEGIN{IGNORECASE=0} $3==p {print $1; exit}' "$BRAIN/_meta/PROJECTS.tsv")
  if [ -z "$PROJECT_PATH" ]; then
    echo "skip $SLUG: project $PROJECT not in PROJECTS.tsv" >> "$LOG"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "=== drafting $SLUG (project=$PROJECT, prs=[$PRS], score=$SCORE) ===" >> "$LOG"

  PROMPT=$(cat <<PROMPT_EOF
Drafting architecture-history entry для brain vault — Project: $PROJECT (at $PROJECT_PATH).

Candidate context:
- slug: $SLUG
- date_range: $DATE_RANGE
- sha_range: $SHA_RANGE
- PRs: $PRS
- remote_slug: $REMOTE_SLUG
- subject (head): $SUBJECT
- scanner_score: $SCORE
- scanner_why: $WHY

ШАГИ:
1. Read \$HOME/.claude/skills/brain-capture/SKILL.md — template + rules
2. Read $BRAIN/projects/$PROJECT.md — existing Architecture history (если есть) чтобы match stylе
3. \`git -C $PROJECT_PATH log $SHA_RANGE --format='%h %ad %s%n%n%b%n----' --date=short\` — full commit messages в range
4. For PR N в $PRS: \`gh pr view N --repo $REMOTE_SLUG\` — full PR body + context

Distill в template (см. SKILL.md):
- ### YYYY-MM-DD → YYYY-MM-DD: <slug> (commits <sha-range>, PRs #N-#M)
- **Trigger:** одна строка
- **Root cause:** 1-2 параграфа — структурная причина, не симптом
- **Approach:** numbered list / table phases с reversibility
- **What worked:** 2-5 bullets — specific decisions, не platitudes
- **Tech debt remaining:** bullets с числами
- **Bigger lesson:** ОДНА pithy line — applies forward beyond этого project
- **Related:** [[<person>]], [[lessons/<pattern>]], [[<related-project>]]

Russian prose, English для code/paths/identifiers/PR refs/SHAs.

Output ТОЛЬКО the markdown entry — начинай с ### header. NO preamble. NO trailing commentary. НЕ пиши в файлы — только stdout.
PROMPT_EOF
)

  {
    echo "<!-- DRAFT FROM SCAN $(date +%Y-%m-%d) -->"
    echo "<!-- TARGET: projects/$PROJECT.md -->"
    echo "<!-- SLUG: $SLUG -->"
    echo "<!-- SCORE: $SCORE — $WHY -->"
    echo
  } > "$DRAFT_FILE.tmp"

  if printf '%s' "$PROMPT" | "$CLAUDE_BIN" --print --allowed-tools "Read,Glob,Grep,Bash(gh:*),Bash(git:*)" >> "$DRAFT_FILE.tmp" 2>>"$LOG"; then
    if [ -s "$DRAFT_FILE.tmp" ]; then
      mv "$DRAFT_FILE.tmp" "$DRAFT_FILE"
      echo "drafted: $DRAFT_FILE" >> "$LOG"
      DRAFTED=$((DRAFTED + 1))
    else
      rm -f "$DRAFT_FILE.tmp"
      echo "EMPTY draft for $SLUG" >> "$LOG"
      FAILED=$((FAILED + 1))
    fi
  else
    rm -f "$DRAFT_FILE.tmp"
    echo "FAILED to draft $SLUG (claude --print failed)" >> "$LOG"
    FAILED=$((FAILED + 1))
  fi
done

echo "=== $(date) weekly-drafts end (drafted=$DRAFTED skipped=$SKIPPED failed=$FAILED) ===" >> "$LOG"
echo "weekly-drafts.sh: drafted=$DRAFTED skipped=$SKIPPED failed=$FAILED → $DRAFTS_DIR"
