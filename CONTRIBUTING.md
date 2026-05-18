# Contributing

Thanks for considering a contribution. distill is a small, opinionated tool — the design space is intentionally narrow. Read [`ARCHITECTURE.md`](ARCHITECTURE.md) first.

## Pull request expectations

- **Tests required** for any behavior change in `.bin/*.py`. The 24-test suite is the contract; add to it, don't bypass it.
- **One concern per PR.** Refactoring + behavior change in the same PR makes review hard.
- **Boundary discipline preserved.** Changes that let the AI write to curated sections (`## Open threads`, `## Architecture history`, etc.) will be rejected unless the architectural rationale is overwhelming.
- **Conventional commits style** in commit messages (`feat(daily):`, `fix(harvest):`, `docs:`, `chore:`).

## Running tests

```bash
pytest .bin/tests/ -v
```

All 24 must pass. CI is not yet wired up; run them locally.

## Design changes

If you want to change the architecture (e.g., add a service layer, change the AI's autonomy boundaries, change how lessons interact with the daily prompt), open an issue first to discuss. The design is opinionated for a reason — see ARCHITECTURE.md "Design choices".

## Out of scope (won't merge)

- Web dashboard / GUI for the vault — Obsidian is the UI; the engine is plumbing.
- Replacing Claude with another model — out of scope for v1. The prompt structure is specific to Claude's tool-using behavior in `--print` mode.
- Removing the human-in-the-loop apply gate — drafts must be reviewed before becoming lessons / project entries.
- Real-time triggers (post-commit hooks, file watchers) — the daily cadence is intentional. Synchronous quality gates are the engineer's job, not the brain's.

## What WOULD be a great PR

- Better lesson-library indexing when vaults grow past 30 lessons (the current prompt loads them all)
- Robust Linux notification path (`notify-send` integration)
- Test coverage for `harvest.py` and `scan-candidates.py` (currently only the L2 additions have tests)
- A `--dry-run` flag for `daily.sh` that shows what would happen without calling the API
- Integration with a self-hosted LLM (Ollama) as an alternative to Claude Code CLI, while keeping the structured-output contract

## License

MIT. By submitting a PR, you agree your contribution is licensed the same.
