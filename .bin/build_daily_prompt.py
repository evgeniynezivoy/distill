"""Assemble structured prompt for daily synthesis from brain state."""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Tolerant key: value parser. Values keep any colons / brackets / quotes.

    Real brain frontmatter has values like
        last_commit: abc1234 fix(issues): reject disputed status on non-QA (#152)
    which yaml.safe_load rejects. We treat the first ':' as the separator and
    keep everything after as a raw string.
    """
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
        # Strip wrapping quotes if any
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        # List syntax: `[a, b, c]` or `[]`
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fm[key] = [t.strip() for t in inner.split(",") if t.strip()] if inner else []
            continue
        # Bool
        if value.lower() == "true":
            fm[key] = True
            continue
        if value.lower() == "false":
            fm[key] = False
            continue
        # Int coercion (for `behind`, etc.)
        if value.lstrip("-").isdigit():
            fm[key] = int(value)
        else:
            fm[key] = value
    return fm


def _parse_projects_tsv(tsv_path: Path) -> list[dict[str, str]]:
    """Parse PROJECTS.tsv. Format: `path\\ttier\\tnick`. Skip comment lines starting with #."""
    rows = []
    for line in tsv_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rows.append({
            "repo_path": parts[0].strip(),
            "base_tier": parts[1].strip(),
            "nick": parts[2].strip(),
        })
    return rows


def _extract_section(body: str, heading: str) -> str:
    """Return content of a `## <heading>` section up to the next `## ` (or EOF)."""
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("## ") and heading.lower() in line.lower():
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def load_lessons(lessons_dir: Path) -> list[dict[str, Any]]:
    if not lessons_dir.exists():
        return []
    lessons = []
    for path in sorted(lessons_dir.glob("*.md")):
        text = path.read_text()
        fm = _parse_frontmatter(text)
        body = text.split("\n---\n", 1)[-1] if text.startswith("---\n") else text
        bigger = _extract_section(body, "Bigger lesson")
        # tags may have come through as raw "[a, b]" string
        tags = fm.get("tags", "")
        if isinstance(tags, str) and tags.startswith("[") and tags.endswith("]"):
            tags = [t.strip() for t in tags[1:-1].split(",") if t.strip()]
        elif isinstance(tags, str) and not tags:
            tags = []
        lessons.append({
            "name": fm.get("name") or path.stem,
            "title": fm.get("title") or path.stem.replace("-", " ").title(),
            "tags": tags,
            "bigger_lesson": bigger.strip(),
            "path": str(path),
        })
    return lessons


PROMPT_HEADER = """\
Ты daily synthesis для brain Евгения. Сегодня {date}.

ВХОД:
- Active projects сегодня: {active_list}
- Per-project: git log + diff stat + текущие Open threads
- Lessons library: {n_lessons} файлов с title + bigger lesson каждого
- Previous 7-day frontmatter (для promotion-candidate detection)

ТВОЯ ЗАДАЧА:
1. Для каждого active project:
   a) Опиши что было сделано (1-3 строки фактическим тоном)
   b) Сверь активность с lessons. Если выглядит как application известного pattern
      → flag "smell repeat: <lesson-name>" + 1 строка почему
   c) Если видишь structural concern НЕ покрытый ни одним lesson — produce lesson candidate
2. Если 2+ проекта показали один pattern → cross-project секция
3. Если день clean — явно скажи об этом
4. Если конкретный lesson репитился 2+ раз за последние 7 дней (см. history block) — добавь "promotion candidate" пометку

ОГРАНИЧЕНИЯ:
- НЕ интерпретируй "ошибки" с нуля. Lessons — source of truth.
- НЕ предлагай micromanagement правки. Только structural concerns.
- НЕ трогай curated секции project notes. Твоя зона — ## Daily synthesis (auto) slot.
"""

PROMPT_OUTPUT_FORMAT = """\

OUTPUT FORMAT (strict markdown, ничего лишнего):

---START-DAILY-LOG---
---
date: {date}
projects_touched: [<list>]
smells_repeat: [<list of lesson names>]
smells_new: [<list of new draft slugs>]
cross_project: [<list of pattern names>]
clean_day: <true|false>
---

# Daily — {date}

## Per-project
### <nick>
- Commits: <count> (`<sha> <subject>`)
- Smell repeat: [[lessons/<name>]] — <one line why>
  OR
- Clean — без smell.

## Cross-project
- <if 2+ projects shared a pattern, else "(none)">

## New lesson candidates
- <bullet per draft created, with slug>
  OR "(none)"

## Promotion candidates (L3 future)
- <bullet per lesson repeated 2+ in last 7 days>
  OR "(none)"
---END-DAILY-LOG---

Для каждого NEW lesson candidate отдельно выдай:

---START-LESSON-DRAFT---
slug: <yyyy-mm-dd-short-slug>
---
name: <slug>
description: <one-line>
source: daily-synthesis {date}
trigger_project: <nick>
trigger_commit: <sha>
status: draft
---

## Trigger
<concrete event>

## Root cause
<structural cause>

## Structural fix
<how to fix / how it was fixed>

## Bigger lesson
<generalizable principle>
---END-LESSON-DRAFT---
"""


def assemble_prompt(
    today: datetime,
    active: list[dict[str, Any]],
    git_signals: dict[str, dict[str, str]],
    lessons: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> str:
    date_str = today.strftime("%Y-%m-%d")
    parts = [PROMPT_HEADER.format(
        date=date_str,
        active_list=", ".join(p["nick"] for p in active) or "(none)",
        n_lessons=len(lessons),
    )]

    parts.append("\n## ACTIVE PROJECTS DETAIL\n")
    for proj in active:
        note_text = Path(proj["note_path"]).read_text()
        body_after_fm = note_text.split("\n---\n", 1)[-1] if note_text.startswith("---\n") else note_text
        open_threads = _extract_section(body_after_fm, "Open threads")
        sig = git_signals.get(proj["nick"], {"commits": "", "numstat": "", "error": ""})
        parts.append(f"### {proj['nick']}\n")
        parts.append(f"**Open threads:**\n{open_threads or '(none)'}\n\n")
        parts.append(f"**Git commits (last 24h):**\n```\n{sig['commits'] or '(none)'}\n```\n\n")
        parts.append(f"**Numstat:**\n```\n{sig['numstat'] or '(none)'}\n```\n\n")
        if sig.get("error"):
            parts.append(f"**Note:** git collection error — {sig['error']}\n\n")

    parts.append("\n## LESSONS LIBRARY\n")
    for L in lessons:
        parts.append(f"### {L['title']} (`{L['name']}`)\n")
        if L.get("tags"):
            parts.append(f"tags: {', '.join(L['tags'])}\n\n")
        parts.append(f"{L['bigger_lesson']}\n\n")

    parts.append("\n## PREVIOUS 7-DAY HISTORY (frontmatter only)\n")
    if not history:
        parts.append("(no prior daily logs in window)\n")
    else:
        for h in history:
            parts.append(
                f"- {h['date']}: clean={h['clean_day']}, "
                f"repeats={h['smells_repeat']}, news={h['smells_new']}, "
                f"projects={h['projects_touched']}\n"
            )

    parts.append(PROMPT_OUTPUT_FORMAT.format(date=date_str))
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", required=True, type=Path)
    parser.add_argument("--today", default=None, help="YYYY-MM-DD (default: today local)")
    args = parser.parse_args(argv)

    if args.today:
        today_date = datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today_date = date.today()
    today_dt = datetime(today_date.year, today_date.month, today_date.day, tzinfo=timezone.utc)

    brain = args.brain_root
    active = load_active_projects(
        projects_root=brain / "projects",
        tsv_path=brain / "_meta" / "PROJECTS.tsv",
        today=today_date,
    )
    lessons = load_lessons(brain / "lessons")
    history = load_recent_daily_frontmatter(brain / "logs" / "daily", today=today_dt)

    git_signals = {}
    for proj in active:
        signal = collect_git_signal(repo_path=proj["repo_path"], since_hours=24)
        git_signals[proj["nick"]] = signal

    prompt = assemble_prompt(
        today=today_dt,
        active=active,
        git_signals=git_signals,
        lessons=lessons,
        history=history,
    )
    print(prompt)
    return 0


def collect_git_signal(repo_path: str, since_hours: int = 24) -> dict[str, str]:
    repo = Path(repo_path)
    if not repo.exists() or not (repo / ".git").exists():
        return {"commits": "", "numstat": "", "error": f"missing repo {repo_path}"}
    since = f"{since_hours} hours ago"
    try:
        commits = subprocess.run(
            ["git", "-C", str(repo), "log", f"--since={since}",
             "--pretty=format:%h %ci %an %s"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        numstat = subprocess.run(
            ["git", "-C", str(repo), "log", f"--since={since}", "--numstat", "--format="],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return {
            "commits": commits.stdout.strip(),
            "numstat": numstat.stdout.strip(),
            "error": "",
        }
    except Exception as exc:
        return {"commits": "", "numstat": "", "error": str(exc)}


def load_recent_daily_frontmatter(
    daily_dir: Path,
    today: datetime,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Read frontmatter of the prior `days` daily logs (excludes today)."""
    if not daily_dir.exists():
        return []
    cutoff = today - timedelta(days=days)
    today_midnight = today.replace(hour=0, minute=0, second=0, microsecond=0)
    entries: list[dict[str, Any]] = []
    for path in sorted(daily_dir.glob("*.md"), reverse=True):
        try:
            d = datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if d >= today_midnight:
            continue
        if d < cutoff:
            break
        fm = _parse_frontmatter(path.read_text())
        entries.append({
            "date": path.stem,
            "projects_touched": fm.get("projects_touched") or [],
            "smells_repeat": fm.get("smells_repeat") or [],
            "smells_new": fm.get("smells_new") or [],
            "clean_day": bool(fm.get("clean_day")),
        })
    return entries


def load_active_projects(
    projects_root: Path,
    tsv_path: Path,
    today: date,
    window_days: int = 1,
) -> list[dict[str, Any]]:
    """Active = last_commit_date within last `window_days` (inclusive of today and N prior).

    Day-precision because harvest.py stores `last_commit_date` as YYYY-MM-DD only.
    Default window_days=1 → today + yesterday.
    """
    cutoff = today - timedelta(days=window_days)
    rows = _parse_projects_tsv(tsv_path)

    active: list[dict[str, Any]] = []
    for row in rows:
        nick = row["nick"]
        note = projects_root / f"{nick}.md"
        if not note.exists():
            continue
        fm = _parse_frontmatter(note.read_text())
        lcd = fm.get("last_commit_date")
        if not lcd:
            continue
        if isinstance(lcd, str):
            try:
                lcd_date = datetime.strptime(lcd, "%Y-%m-%d").date()
            except ValueError:
                continue
        elif isinstance(lcd, date):
            lcd_date = lcd
        else:
            continue
        if lcd_date >= cutoff:
            active.append({
                "nick": nick,
                "name": fm.get("name") or nick,
                "last_commit_date": lcd_date,
                "note_path": str(note),
                "tier": fm.get("tier") or row["base_tier"],
                "repo_path": row["repo_path"],
                "default_branch": fm.get("default_branch", "main"),
            })
    return active


if __name__ == "__main__":
    raise SystemExit(main())
