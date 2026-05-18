# distill

> Every morning, distill your git noise into one signal. Catch the same mistake before you make it the third time — then, eventually, **let the system stop you from making it at all**.

**distill** is a small automation that turns an Obsidian vault into an *immune system for your projects*. It reads what you committed across all your tracked repos overnight, compares the work to a library of structural lessons you've recorded from past incidents, flags repeats, drafts new lesson candidates when it sees something structurally novel, and surfaces cross-project patterns you'd never notice on a single project.

But that's just the loop's first half. The real point is the **closed loop**:

```
detect repeat smell in today's commits
   → draft a lesson (you accept it)
   → daemon sees it fire N times across projects
   → it drafts a Claude Code skill (you accept it)
   → that skill auto-activates in your next coding session
   → and stops the mistake before commit
```

In other words: instead of you reading post-mortems and trying to remember, **the next pair-programming session already knows**. Your vault grows from passive archive → active library of lessons → executable skills that prevent recurrence at the keyboard.

The daily/lesson half is shipping today (phase L2). The skills-promotion half is phase L3 — designed, hooks in place in the data, not built yet. The point of going public now is to validate the design before building the rest.

The whole arc: each commit you make next week is cleaner than the one this week — and a few months from now, mistakes that used to take three project-incidents to learn won't make it past your editor.

---

```
launchd 09:00 ───┐
                 ├──► harvest.py        — git → frontmatter, INDEX hot/warm/cold
                 ├──► scan-candidates.py — heuristic scan for architecture events
daily.sh ────────┼──► daily_synthesis    — claude --print, structured prompt
                 │      └─► build_daily_prompt.py → prompt
                 │           apply_daily_output.py → daily log, project slot, lesson drafts
                 └──► index_touch.py    — timestamp refresh
                                                                  │
                                                                  ▼
                                                    macOS push notification
                                                    on repeat smell / pattern

launchd Sun 18:00 ── weekly.sh ── weekly-synthesis ── reads 7 daily logs
                                                       + lesson drafts
                                                       writes weekly review
                                                       extracts LinkedIn drafts
```

## What this gets you

- **Daily narrative** at `logs/daily/YYYY-MM-DD.md` — what you did across all projects today, what patterns it matches.
- **Project notes auto-augmented** at `projects/<nick>.md` — a rolling 7-day signal slot the system keeps fresh; curated sections (Open threads, Architecture history, Decisions) never touched.
- **Lesson candidates** at `_meta/drafts/lessons/` — when the system spots a structural concern not covered by your existing lessons, it drafts one for you to review and accept.
- **Weekly review** at `logs/weekly/YYYY-Www.md` — cross-project themes, stuck branches, promotion candidates for future Claude Code skills, optional LinkedIn drafts.

## Quick start

Requirements:
- macOS (for `launchctl` + `osascript`; Linux works with `cron` instead — see `docs/INSTALL.md`)
- Python 3.11+
- [Claude Code CLI](https://docs.claude.com/claude-code) installed and authenticated
- An Obsidian vault you'll use as `BRAIN_ROOT`
- `gh` CLI for `weekly-drafts.sh` (optional — only for capture-candidates flow)

```bash
git clone https://github.com/evgeniynezivoy/distill ~/distill
cd ~/distill

# Point at your vault
export BRAIN_ROOT=~/your-vault

# Run the tests to confirm the engine works
pytest .bin/tests/ -v

# Bootstrap your vault from the sample
cp -r examples/sample-vault/* $BRAIN_ROOT/
git -C $BRAIN_ROOT init  # optional but recommended

# Edit $BRAIN_ROOT/_meta/PROJECTS.tsv to point at your real repos
# Edit $BRAIN_ROOT/projects/my-app.md (or rename it to match your project nick)

# First manual run — read-only, no API call
python3 .bin/build_daily_prompt.py --brain-root "$BRAIN_ROOT" --today $(date +%Y-%m-%d)

# Full cycle (will call Claude API — costs ~$0.05-0.10/day on Sonnet 4.6)
bash .bin/daily.sh

# Inspect outputs
cat $BRAIN_ROOT/logs/daily/$(date +%Y-%m-%d).md
```

Schedule via launchd:

```bash
# Copy plist examples, edit YOUR_USERNAME, then load
cp examples/launchd/com.example.distill.daily.plist  ~/Library/LaunchAgents/com.YOUR_USERNAME.distill.daily.plist
cp examples/launchd/com.example.distill.weekly.plist ~/Library/LaunchAgents/com.YOUR_USERNAME.distill.weekly.plist
# Open both files and replace YOUR_USERNAME + BRAIN_ROOT path

launchctl load ~/Library/LaunchAgents/com.YOUR_USERNAME.distill.daily.plist
launchctl load ~/Library/LaunchAgents/com.YOUR_USERNAME.distill.weekly.plist
```

That's it. Tomorrow at 09:00 the daemon runs.

## Why this is different from "daily AI summary" tools

Plenty of tools will read your git log and produce a daily writeup. distill is built around a different goal: the writeup is a **byproduct**. The actual artifact is a growing library of structural lessons that eventually compile down to Claude Code skills.

| Daily AI summary tools | distill |
|---|---|
| Output: a paragraph you read | Output: structured lessons + (L3) skills that activate at the keyboard |
| Detection: AI interprets each day fresh | Detection: AI is anchored to your lessons library — can only flag what fits an existing structural concept (or propose a new one for review) |
| Cross-project: not really | Cross-project: explicit — patterns visible in 2+ projects same day are surfaced as a section |
| Memory: lossy paragraph in a folder | Memory: typed graph — lessons feed into next day's prompt as source-of-truth |
| Failure mode: drowns in noise / shallow daily | Failure mode: misses novel smells (anchored detection is conservative by design) |

distill is the conservative bet. It misses some signal in exchange for not making things up. The lessons library is the throttle.

## Design philosophy

- **Lessons are the anchor.** The daily AI is forbidden from interpreting "smells" without reference to your existing lessons library. This keeps false positives from drowning the drafts queue. New lesson candidates are produced only when the system sees a structural concern that no existing lesson covers.
- **Boundary discipline.** The system writes only to *regenerable* slots — never to your curated sections. AI cannot break "Open threads" / "Architecture history" / "Decisions" even if the prompt is malformed; this is enforced at the code level by `apply_daily_output.py` and verified by tests.
- **Local-first.** Your vault is yours. The engine reads from `BRAIN_ROOT` and writes back there; nothing leaves your machine except the daily Claude API call.
- **Cost-aware.** ~$1.50-2.50/month on Sonnet 4.6 for a 7-project active vault. Upgrade to Opus only if Sonnet's pattern matching gets sloppy.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — full design, data flow, lesson lifecycle, future phases
- [`docs/INSTALL.md`](docs/INSTALL.md) — detailed install on macOS and Linux
- [`CLAUDE.md`](CLAUDE.md) — for Claude Code: how to behave inside this repo
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — pull request guidelines (tests, style, scope)

## Roadmap

- ✅ **L1** — Static vault, manual notes, harvest daemon for git state.
- ✅ **L2** — Generative daily synthesis (this release).
- 🔜 **L3** — Self-improving skills: lessons triggered N times → auto-generate Claude Code skills that activate in next sessions and prevent recurrence before commit.
- 🔜 **L4** — Monthly drift detection: re-read each project's CLAUDE.md, diff against your vault, flag architecture drift.

## Status

L2 is live in production for the author's personal vault as of 2026-05-18. This is the first public release. Issues + PRs welcome.

## License

[MIT](LICENSE) — use it however helps you.
