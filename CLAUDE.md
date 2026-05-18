# CLAUDE.md — distill engine

This file is read by Claude Code when sessions start in the `distill` repo. It tells Claude what this repo IS and how to behave inside it.

## What this repo is

The **engine** for daily AI-driven synthesis over an Obsidian vault. The engine is generic; it doesn't know your project nicknames or your team's names. It reads `$BRAIN_ROOT` (an Obsidian vault following a specific structure) and writes back to it via cron / launchd.

The full design lives in [`ARCHITECTURE.md`](ARCHITECTURE.md). Read it before making any non-trivial change.

## Behavioral rules

### This repo never contains real vault data

`examples/sample-vault/` is a minimal demo. Real user vaults (with real project names, real PR numbers, real colleague names) live OUTSIDE this repo, at whatever `BRAIN_ROOT` the user points the engine at. Do not commit anyone's real vault content here.

### Boundary discipline (non-negotiable)

In `projects/<nick>.md` files of a target vault:
- **Curated** — `## Open threads`, `## Architecture history`, `## Decisions`, `## Risks`, `## Status`, and anything else the user typed by hand. **Never touch these from automation.**
- **Auto-regenerable** — YAML frontmatter, `## Recent activity` (between `<!-- HARVESTER-START -->` and `<!-- HARVESTER-END -->`), and `## Daily synthesis (auto, regenerated each run)`. These get rewritten by daemons and are safe to overwrite.

The boundary is enforced by tests in `.bin/tests/test_apply_daily_output.py`. Don't break those tests.

### Frontmatter format

Vault project-note frontmatter is **not** strict YAML. Values contain colons (e.g., `last_commit: abc1234 fix(issues): example`). The engine's parser (`build_daily_prompt.py:_parse_frontmatter`) treats the first `:` as separator and keeps everything after as a raw string. If you write new tooling, use that parser, not `yaml.safe_load`.

Standard fields (defined by `harvest.py:YAML_ORDER`):
```
name, path, tier, last_commit_date, last_commit, default_branch, remote, current_branch, behind
```

### Lessons are source-of-truth for daily AI

The daily prompt forbids AI from interpreting smells without a lesson anchor. Adding a new lesson is the way to teach the daemon a new pattern; the AI cannot invent lesson categories on its own. If users complain "the daemon doesn't notice X" — the answer is usually "add a lesson for X." Don't change the prompt to make AI more autonomous; that'll just increase false positives.

### Tests

Anything in `.bin/` is covered by `pytest .bin/tests/`. Run tests before and after every change:
```bash
cd ~/distill && pytest .bin/tests/ -v
```
All 24 tests must pass. If you change behavior, **add a test first** that captures the new expectation.

### Shell style

Shell scripts use `set -uo pipefail` (NOT `-e`) and graceful `|| echo "exit non-zero"` chains. The system is designed to keep running even when one step fails — one broken project shouldn't kill the daemon. Preserve that style.

`daily_synthesis.sh` and `weekly-synthesis.sh` use `set -euo pipefail` (with `-e`) because the synthesis steps are atomic — if they fail, retrying makes more sense than continuing with bad state.

### Env vars

The engine is env-driven. Don't hardcode paths.

| Var | Default | Purpose |
|---|---|---|
| `BRAIN_ROOT` | `$HOME/brain` | Vault root |
| `MODEL` | `claude-sonnet-4-6` | Claude model for daily synthesis |
| `CLAUDE_BIN` | `$(command -v claude)` | Claude CLI binary |
| `PY` | `$(command -v python3)` | Python 3 binary |
| `TODAY` | `$(date +%Y-%m-%d)` | Override date for testing |

### Git workflow

- Conventional-commits style prefixes (`feat(daily):`, `fix(harvest):`, `docs(arch):`, `chore:`).
- Small, descriptive commits. One concern per commit.
- Always run tests before committing changes to `.bin/`.
- The repo has a public remote; no NDA-sensitive references in commit messages, docs, or code.

### Style

- English only in code, docstrings, function names, comments, commit messages.
- README and ARCHITECTURE.md — English.
- Markdown headers consistent style (sentence-case for content, title-case for sections).

## Common requests and where they live

| User says | What to do |
|---|---|
| "Run daily synthesis manually" | `BRAIN_ROOT=/path/to/vault bash .bin/daily_synthesis.sh` |
| "Run the full cycle now" | `BRAIN_ROOT=/path/to/vault bash .bin/daily.sh` |
| "Run tests" | `pytest .bin/tests/ -v` |
| "Add a new lesson detection rule" | Add a lesson to the user's vault `lessons/<slug>.md`; don't edit the engine. |
| "Why is the daemon flagging X?" | Look at the user's `lessons/<X>.md` — the AI is anchored there. |

## Anti-patterns (do not do)

- Don't hardcode user-specific paths. Use `BRAIN_ROOT` env or CLI arg.
- Don't bypass the frontmatter parser. Use `build_daily_prompt.py:_parse_frontmatter`.
- Don't generate lessons from code paths other than the apply skill (human-gated). Two sources = drift.
- Don't change `set -uo pipefail` to `set -euo pipefail` in `daily.sh` / `weekly.sh` — graceful continue-on-failure is intentional.
- Don't introduce a service layer / dashboard / web UI. The vault is the UI; the engine is plumbing.
- Don't change the AI's autonomy boundaries (boundary discipline, lessons-as-anchor) without an architectural discussion. The design is intentional.

## When in doubt

Read [`ARCHITECTURE.md`](ARCHITECTURE.md), then look at `.bin/tests/` for behavioral specifications. The tests document expected behavior more precisely than any comment.
