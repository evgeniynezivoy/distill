"""promote_lessons.py — L3 phase: aggregate lesson firings from daily logs,
identify candidates for skill promotion, generate skill drafts via claude --print.

Reads `logs/daily/*.md` frontmatter + per-project sections.
Writes skill drafts to `_meta/drafts/skills/<lesson-name>.md`.

A lesson qualifies for promotion when:
  - it fired N>=3 times across M>=2 distinct projects in the last 30 days

Both thresholds are env-configurable: PROMOTE_N, PROMOTE_M.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Tolerant key:value frontmatter parser (handles colons in values, lists, bools)."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    fm: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fm[key] = [t.strip() for t in inner.split(",") if t.strip()] if inner else []
            continue
        if value.lower() == "true":
            fm[key] = True
            continue
        if value.lower() == "false":
            fm[key] = False
            continue
        if value.lstrip("-").isdigit():
            fm[key] = int(value)
        else:
            fm[key] = value
    return fm


PER_PROJECT_HEADER_RE = re.compile(r"^###\s+(\S+)\s*$")
LESSON_LINK_RE = re.compile(r"\[\[lessons/([a-z0-9\-]+)\]\]")


def parse_daily_log(path: Path) -> dict[str, Any]:
    """Parse a daily log file. Returns:
      date: str
      clean_day: bool
      per_project: dict[project_nick, list[lesson_name]] — extracted from ### sections
    """
    text = path.read_text()
    fm = _parse_frontmatter(text)
    body = text.split("\n---\n", 1)[-1] if text.startswith("---\n") else text

    per_project: dict[str, list[str]] = {}
    current_nick: str | None = None
    in_per_project = False
    for line in body.splitlines():
        if line.strip().startswith("## Per-project"):
            in_per_project = True
            continue
        if in_per_project and line.startswith("## "):
            in_per_project = False
            current_nick = None
            continue
        if not in_per_project:
            continue
        m = PER_PROJECT_HEADER_RE.match(line)
        if m:
            current_nick = m.group(1)
            per_project.setdefault(current_nick, [])
            continue
        if current_nick:
            for lesson in LESSON_LINK_RE.findall(line):
                if lesson not in per_project[current_nick]:
                    per_project[current_nick].append(lesson)

    # Drop empty entries
    per_project = {k: v for k, v in per_project.items() if v}

    return {
        "date": fm.get("date") or path.stem,
        "clean_day": bool(fm.get("clean_day")),
        "per_project": per_project,
    }


def aggregate_firings(log_paths: list[Path]) -> dict[str, dict[str, set[str]]]:
    """Aggregate firings across logs.
    Returns: {lesson: {project: {dates}}}
    """
    firings: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for path in log_paths:
        parsed = parse_daily_log(path)
        date_str = parsed["date"]
        for project, lessons in parsed["per_project"].items():
            for lesson in lessons:
                firings[lesson][project].add(date_str)
    return {k: dict(v) for k, v in firings.items()}


def get_candidates(
    firings: dict[str, dict[str, set[str]]],
    n_min: int = 3,
    m_min: int = 2,
) -> list[dict[str, Any]]:
    """Filter firings → promotion candidates.

    A lesson qualifies if it has fired N>=n_min times across M>=m_min projects.
    Returns a list of candidate descriptors with project/date events.
    """
    candidates = []
    for lesson, by_project in firings.items():
        total_firings = sum(len(dates) for dates in by_project.values())
        project_count = len(by_project)
        if total_firings < n_min or project_count < m_min:
            continue
        events = []
        for project, dates in by_project.items():
            for d in sorted(dates):
                events.append({"project": project, "date": d})
        candidates.append({
            "lesson": lesson,
            "total_firings": total_firings,
            "projects": sorted(by_project.keys()),
            "events": sorted(events, key=lambda e: (e["date"], e["project"])),
        })
    return sorted(candidates, key=lambda c: -c["total_firings"])


def select_logs_in_window(daily_dir: Path, today: date, window_days: int = 30) -> list[Path]:
    """Return daily-log paths whose stem date is within the last window_days."""
    cutoff = today - timedelta(days=window_days)
    result = []
    if not daily_dir.exists():
        return result
    for path in sorted(daily_dir.glob("*.md")):
        try:
            d = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if cutoff <= d <= today:
            result.append(path)
    return result


SKILL_PROMPT = """\
You are converting a brain lesson into a Claude Code skill draft.

The lesson below describes a structural mistake the engineer has now made
{firings} times across {project_count} different projects in the last 30 days.
Your job: write a Claude Code skill (SKILL.md format) that activates when
the engineer is about to make this kind of mistake again, and suggests the
structural fix the lesson describes.

LESSON (full source):

{lesson_body}

FIRING EVENTS:
{events_summary}

REQUIRED OUTPUT FORMAT (wrap exactly between markers, no preamble or trailing text):

---START-SKILL-DRAFT---
---
name: {lesson_name}
description: <one-line — WHEN to activate, written for a tool-using LLM to recognize the trigger. Be concrete: name file patterns, commit message patterns, or content patterns.>
---

# <Skill title — short, action-oriented>

## When this applies

<concrete trigger conditions: file globs, commit messages, content patterns. NOT abstract — give exact things to look for.>

## Workflow

<what the skill does when triggered: check what / suggest what / refuse what. Be prescriptive.>

## References

- Source lesson: [[lessons/{lesson_name}]]
- Auto-promoted by distill on {today} after {firings} firings across {project_count} projects
---END-SKILL-DRAFT---

OUTPUT ONLY the marker block. No preamble, no trailing chatter.
"""


SKILL_DRAFT_RE = re.compile(
    r"---START-SKILL-DRAFT---\s*\n(.*?)\n---END-SKILL-DRAFT---",
    re.DOTALL,
)


def build_skill_prompt(
    lesson_content: str,
    candidate: dict[str, Any],
    today_str: str,
) -> str:
    """Assemble prompt for `claude --print` to draft a skill from a lesson."""
    events_summary = "\n".join(
        f"- {e['date']}: {e['project']}" for e in candidate["events"]
    )
    return SKILL_PROMPT.format(
        lesson_body=lesson_content.rstrip(),
        lesson_name=candidate["lesson"],
        firings=candidate["total_firings"],
        project_count=len(candidate["projects"]),
        events_summary=events_summary,
        today=today_str,
    )


def parse_skill_draft(raw: str) -> str:
    """Extract the markdown body between SKILL-DRAFT markers."""
    m = SKILL_DRAFT_RE.search(raw)
    if not m:
        raise ValueError("No ---START-SKILL-DRAFT---/---END-SKILL-DRAFT--- block found")
    return m.group(1).strip()


def write_skill_draft(
    drafts_dir: Path,
    lesson_name: str,
    body: str,
    today_str: str,
) -> Path | None:
    """Atomic write. Returns target path on success, None if already exists (skip)."""
    drafts_dir.mkdir(parents=True, exist_ok=True)
    target = drafts_dir / f"{today_str}-{lesson_name}.md"
    if target.exists():
        return None
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text(body.rstrip() + "\n")
    os.replace(tmp, target)
    return target


def invoke_claude(prompt: str, model: str = "claude-sonnet-4-6") -> str:
    """Pipe prompt into `claude --print`, return stdout. Used for skill drafting."""
    claude_bin = os.environ.get("CLAUDE_BIN") or "claude"
    result = subprocess.run(
        [claude_bin, "--print", "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Promote lessons to Claude Code skill drafts.")
    parser.add_argument("--brain-root", required=True, type=Path)
    parser.add_argument("--today", default=None, help="YYYY-MM-DD (default: today local)")
    parser.add_argument("--n-min", type=int, default=int(os.environ.get("PROMOTE_N", "3")),
                        help="Minimum firings across all projects (default: 3 or $PROMOTE_N)")
    parser.add_argument("--m-min", type=int, default=int(os.environ.get("PROMOTE_M", "2")),
                        help="Minimum distinct projects (default: 2 or $PROMOTE_M)")
    parser.add_argument("--window-days", type=int, default=30, help="Days to scan back (default: 30)")
    parser.add_argument("--model", default=os.environ.get("MODEL", "claude-sonnet-4-6"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Aggregate + list candidates only; no API call, no writes")
    args = parser.parse_args(argv)

    today = (
        datetime.strptime(args.today, "%Y-%m-%d").date()
        if args.today
        else date.today()
    )
    brain = args.brain_root

    logs = select_logs_in_window(brain / "logs" / "daily", today=today, window_days=args.window_days)
    firings = aggregate_firings(logs)
    candidates = get_candidates(firings, n_min=args.n_min, m_min=args.m_min)

    print(f"Promotion scan ({args.window_days}d window, N>={args.n_min}, M>={args.m_min}): "
          f"{len(logs)} daily logs, {len(firings)} lessons fired, {len(candidates)} candidates")

    if args.dry_run:
        for c in candidates:
            print(f"  - {c['lesson']}: {c['total_firings']} firings across {len(c['projects'])} "
                  f"projects ({', '.join(c['projects'])})")
        return 0

    if not candidates:
        print("  (no candidates this run)")
        return 0

    drafts_dir = brain / "_meta" / "drafts" / "skills"
    today_str = today.strftime("%Y-%m-%d")

    written = 0
    skipped = 0
    failed = 0
    for c in candidates:
        lesson_path = brain / "lessons" / f"{c['lesson']}.md"
        if not lesson_path.exists():
            print(f"  skip {c['lesson']}: lesson file missing at {lesson_path}")
            skipped += 1
            continue
        target = drafts_dir / f"{today_str}-{c['lesson']}.md"
        if target.exists():
            print(f"  skip {c['lesson']}: skill draft already exists at {target}")
            skipped += 1
            continue

        lesson_content = lesson_path.read_text()
        prompt = build_skill_prompt(lesson_content, c, today_str)
        try:
            raw = invoke_claude(prompt, model=args.model)
            body = parse_skill_draft(raw)
            path = write_skill_draft(drafts_dir, c["lesson"], body, today_str)
            print(f"  ✓ drafted: {path}")
            written += 1
        except Exception as exc:
            print(f"  fail {c['lesson']}: {exc}", file=sys.stderr)
            failed += 1

    print(f"Result: written={written} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
