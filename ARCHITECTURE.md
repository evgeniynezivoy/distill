# Architecture

## The problem

Most "second brain" systems are archives — you write things into them, almost never read them, and they decay into noise. When the same architectural mistake happens for the third time across projects, nothing surfaces. The knowledge exists somewhere in the vault but doesn't reach the moment of decision.

distill is built around a different premise: **the vault is only useful if it makes the next commit cleaner than the last.** That requires a closed loop:

```
detect smell in today's commits
   → capture root cause + structural fix
   → compare across projects, find patterns
   → propose new lesson (if novel)
   → propose new skill (if a lesson keeps firing)
   → skill activates in next session, prevents recurrence
```

distill implements this loop as a daily AI cycle over a structured Obsidian vault.

## The vault as a typed graph

Every file has a role. The system depends on those roles being clean.

| Role | Path | Who writes it | Who reads it |
|---|---|---|---|
| **Source of truth** | `_meta/PROJECTS.tsv` | human | `harvest.py`, daily synthesis |
| **Project state** | `projects/<nick>.md` | `harvest.py` (frontmatter + auto blocks), human (curated sections), daily synthesis (regenerable slot) | everything |
| **Lessons** | `lessons/<slug>.md` | apply skill (human-gated) | daily synthesis (prompt input), human (browsing) |
| **Daily logs** | `logs/daily/YYYY-MM-DD.md` | `daily_synthesis.sh` | weekly synthesis, human (review) |
| **Weekly logs** | `logs/weekly/YYYY-Www.md` | `weekly-synthesis.sh` | human (browsing) |
| **Lesson drafts** | `_meta/drafts/lessons/<slug>.md` | daily synthesis | apply skill (human gates promotion) |
| **Capture drafts** | `_meta/drafts/<slug>.md` | `weekly-drafts.sh` (uses `candidates.json`) | apply skill |
| **Index** | `INDEX.md` | `harvest.py` (hot/warm/cold + timestamps), human (curated headers + Workflow section) | session-start hook (injected into Claude context) |

**Boundary discipline** is the architectural anchor. AI writes only to *regenerable* slots (`## Daily synthesis (auto)` block; HARVESTER block) and *new files* (logs, drafts). It never touches `## Open threads`, `## Architecture history`, `## Decisions` — those are human-curated.

## The daily cycle (current — phase L2)

```
launchd 09:00 → daily.sh
   │
   ├─ 1. harvest.py
   │    ├─ git fetch + log per project → updates frontmatter, INDEX hot/warm/cold,
   │    │  prunes merged Open threads
   │    └─ stable since phase L1
   │
   ├─ 2. scan-candidates.py
   │    ├─ 14-day rolling git log → scores commit groups by architectural keywords
   │    └─ writes _meta/candidates.json for weekly-drafts.sh
   │
   ├─ 3. daily_synthesis.sh  (phase L2)
   │    │
   │    ├─ build_daily_prompt.py
   │    │   ├─ Reads: active projects (last_commit_date in window),
   │    │   │   per-project git log + numstat, lessons library,
   │    │   │   previous 7-day daily-log frontmatter (for promotion detection)
   │    │   └─ Writes: structured prompt to stdout
   │    │
   │    ├─ claude --print --model claude-sonnet-4-6
   │    │   ├─ Reads prompt from stdin
   │    │   └─ Returns markdown with strict markers:
   │    │       ---START-DAILY-LOG--- / ---END-DAILY-LOG---
   │    │       ---START-LESSON-DRAFT--- / ---END-LESSON-DRAFT--- (optional, repeats)
   │    │
   │    └─ apply_daily_output.py
   │        ├─ Parses output, validates markers
   │        ├─ Writes logs/daily/YYYY-MM-DD.md atomically
   │        ├─ Updates `## Daily synthesis (auto)` slot in each touched project note
   │        │  (rolling 7-day window; curated sections untouched)
   │        └─ Writes lesson drafts to _meta/drafts/lessons/ (skip-if-exists)
   │
   ├─ 4. index_touch.py
   │    └─ Updates **Last harvest:** and **Last daily synthesis:** in INDEX.md
   │
   └─ 5. notify (osascript on macOS)
        ├─ Triggers on repeat smell OR cross-project pattern
        └─ Silent on clean days
```

## The weekly cycle (Sunday 18:00)

The weekly synthesizer reads:
1. `INDEX.md` + `projects/*.md` (human curation context)
2. `logs/daily/*.md` from the last 7 days (the distilled signal, not raw harvest)
3. `_meta/drafts/lessons/*.md` (pending lesson candidates from the week)

It produces:
- `logs/weekly/YYYY-Www.md` with cross-week patterns, stuck/abandoned projects, **promotion candidates** (lessons that fired 2+ times — flagged for future L3 skill generation), optional LinkedIn drafts.
- LinkedIn drafts extracted by `extract-linkedin-drafts.py` for separate review.

Anti-fool rules in the weekly prompt (confidentiality abstraction, no buzzword density, no formulaic CTAs, every claim defensible) prevent eager "look-what-I-built" drafts. These rules are baked into the prompt; you can edit them in `.bin/weekly-synthesis.sh`.

## Lesson lifecycle

```
incident in real project (a fix, a migration, a refactor)
   │
   ├─ Path A: weekly auto-detection
   │   └─ scan-candidates.py spots architectural keywords + structural sections in commits
   │      → weekly-drafts.sh drafts an entry → _meta/drafts/<slug>.md
   │      → user runs the apply skill
   │      → entry inserted into projects/<X>.md ## Architecture history
   │      → cross-project lesson created in lessons/<slug>.md if pattern detected
   │
   └─ Path B: daily auto-detection (phase L2)
       └─ daily synthesis sees a structural concern not covered by existing lessons
          → draft in _meta/drafts/lessons/YYYY-MM-DD-<slug>.md
          → user runs the apply skill
          → draft promoted to lessons/<slug>.md
```

Both paths converge on `lessons/`. From there, lessons feed back into daily prompts as the "source of truth" — daily synthesis is forbidden from interpreting smells with no lesson context, which prevents AI-hallucinated false positives.

## Phase L3 (current implementation)

L3 runs in the weekly cycle. Algorithm:
1. `promote_lessons.py` reads frontmatter of all `logs/daily/*.md` from the last 30 days.
2. For each per-project section, it parses the `## Per-project` body to attribute lessons to specific projects (more accurate than the frontmatter summary).
3. Aggregates: each (lesson, project, date) triple becomes a "firing event".
4. Threshold: lesson qualifies if total firings ≥ N (default 3) AND distinct projects ≥ M (default 2). Both tunable via `PROMOTE_N` / `PROMOTE_M` env vars.
5. For each candidate, invokes `claude --print` with the lesson body + firing events. Claude drafts a SKILL.md with frontmatter, trigger conditions, workflow, and reference back to the source lesson.
6. Draft is written atomically to `_meta/drafts/skills/<YYYY-MM-DD>-<lesson-name>.md`. Existing drafts are not overwritten (skip-if-exists).
7. User runs the apply skill to materialize approved drafts to `~/.claude/skills/<name>/SKILL.md`.

Why an extra human-in-the-loop gate (vs lessons): a sloppy lesson clutters the library; a sloppy skill modifies *every* future session's behavior. The cost asymmetry is large, so skill promotion requires explicit approval with visibility into the trigger + workflow content.

### Tunable thresholds

N=3 firings, M=2 projects, 30-day window — these are conservative defaults. If the threshold produces zero candidates for too long, lower them via env:
```bash
PROMOTE_N=2 PROMOTE_M=2 python3 .bin/promote_lessons.py --brain-root ~/brain
```
The right setting depends on your project portfolio diversity. The author's working hypothesis: N=3/M=2 catches genuine cross-cutting patterns without over-promoting one-project quirks.

### What L3 doesn't do

- It doesn't auto-install skills. The apply gate is mandatory.
- It doesn't curate the skill afterwards. The draft is what Claude produced; you edit it before approval if needed.
- It doesn't track which skills actually fire in real sessions. That's L5+ territory (effectiveness measurement).

## Design choices

### Why daily, not weekly only?

In an active day you can ship 5+ commits across 3 projects, and by Sunday the context for *why* you chose a specific approach is gone. Weekly synthesis would have to reconstruct it from `git log` (lossy). Daily catches signal while context is still warm — same day, often within minutes of the commit.

### Why lessons as the anchor?

A reflexion system without an anchor hallucinates. "Smell" is subjective — give an AI free rein and every refactor looks structurally important; you end up drowning in low-quality drafts. Anchoring detection to *existing lessons* (with the explicit rule "do not interpret smells from scratch") keeps false positives down. The cost: novel smells are harder to surface. The L2 prompt deliberately requests new lesson candidates only when *no existing lesson covers* the concern — making novelty a high bar.

### Why boundary discipline?

The vault has two kinds of state: **curated** (human intent: open threads, architecture history, decisions) and **derivable** (state of git, recent commits, today's signal). AI cleanly owns the derivable slots and can never overwrite curated content. This is enforced at the code level (boundary tests in `apply_daily_output.py`) — the AI can't break it even if the prompt is wrong.

### Why local-first?

Your vault may contain references you can't share. Storing the data on someone else's hardware with cleartext access is a violation regardless of the provider's policy. Private git remote with 2FA is the pragmatic middle (metadata may leak, content is access-controlled). Truly paranoid setup: restic to encrypted bucket with locally-held keys.

### Why no service layer / dashboard?

You already have an Obsidian vault and a git history — both are excellent UIs for navigating structured markdown. A dashboard would be one more thing to maintain. The daemon writes plain markdown; everything is grep-able, link-able, and Obsidian-renderable. If you want a different UI, build it on top — the vault is just files.
