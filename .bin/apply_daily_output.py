"""Parse Claude --print output and write artifacts (daily log, project-note slot, lesson drafts)."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DAILY_RE = re.compile(
    r"---START-DAILY-LOG---\s*\n(.*?)\n---END-DAILY-LOG---",
    re.DOTALL,
)
DRAFT_RE = re.compile(
    r"---START-LESSON-DRAFT---\s*\nslug:\s*([^\n]+)\n(.*?)\n---END-LESSON-DRAFT---",
    re.DOTALL,
)


def parse_output(raw: str) -> dict[str, Any]:
    daily_match = DAILY_RE.search(raw)
    if not daily_match:
        raise ValueError("No ---START-DAILY-LOG---/---END-DAILY-LOG--- block found")
    daily_log = daily_match.group(1).strip()

    drafts = []
    for m in DRAFT_RE.finditer(raw):
        drafts.append({
            "slug": m.group(1).strip(),
            "body": m.group(2).strip(),
        })

    return {"daily_log": daily_log, "lesson_drafts": drafts}


def write_daily_log(daily_dir: Path, date_str: str, body: str) -> Path:
    daily_dir.mkdir(parents=True, exist_ok=True)
    target = daily_dir / f"{date_str}.md"
    tmp = daily_dir / f".{date_str}.md.tmp"
    tmp.write_text(body)
    os.replace(tmp, target)
    return target


SLOT_HEADER = "## Daily synthesis (auto, regenerated each run)"
SLOT_DISCLAIMER = "> Этот блок целиком перезаписывается ежедневно. Curated секции не трогаются."


def update_project_note_slot(
    note_path: Path,
    new_entry: str,
    today: str,
    rolling_window_days: int = 7,
) -> None:
    """Overwrite the auto-regenerable slot. Never touches curated sections.

    Slot lives at the END of the file. If it doesn't exist, it's appended.
    If it exists, it's regenerated with new_entry + rolling-window prior entries.
    """
    text = note_path.read_text()
    # Find SLOT_HEADER anywhere
    slot_idx = text.find(SLOT_HEADER)

    if slot_idx == -1:
        curated = text.rstrip()
        prior_entries: list[str] = []
    else:
        curated = text[:slot_idx].rstrip()
        slot_body = text[slot_idx:]
        prior_entries = [
            line.strip()
            for line in slot_body.splitlines()
            if line.strip().startswith("- 20")
        ]

    cutoff = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=rolling_window_days)

    kept = [new_entry.strip()]
    seen_dates = {today}
    for entry in prior_entries:
        m = re.match(r"-\s*(\d{4}-\d{2}-\d{2}):", entry)
        if not m:
            continue
        d_str = m.group(1)
        if d_str in seen_dates:
            continue
        try:
            d = datetime.strptime(d_str, "%Y-%m-%d")
        except ValueError:
            continue
        if d < cutoff:
            continue
        seen_dates.add(d_str)
        kept.append(entry)

    def _date_key(s: str) -> str:
        m = re.match(r"-\s*(\d{4}-\d{2}-\d{2}):", s)
        return m.group(1) if m else "0000-00-00"

    kept.sort(key=_date_key, reverse=True)

    new_slot = (
        f"{SLOT_HEADER}\n\n"
        f"> Last update: {today}\n"
        f"{SLOT_DISCLAIMER}\n\n"
        + "\n".join(kept)
        + "\n"
    )

    tmp = note_path.with_suffix(".md.tmp")
    tmp.write_text(curated + "\n\n" + new_slot)
    os.replace(tmp, note_path)


def write_lesson_drafts(drafts_dir: Path, drafts: list[dict[str, Any]]) -> list[Path]:
    drafts_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for d in drafts:
        target = drafts_dir / f"{d['slug']}.md"
        if target.exists():
            continue  # do not overwrite user edits
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text(d["body"].rstrip() + "\n")
        os.replace(tmp, target)
        created.append(target)
    return created


PER_PROJECT_HEADER_RE = re.compile(r"^###\s+(\S+)\s*$")
LESSON_LINK_RE = re.compile(r"\[\[lessons/([a-z0-9\-]+)\]\]")


def extract_per_project_summary(daily_log: str, today: str) -> dict[str, str]:
    """Return one-line summary per project, suitable for project-note slot."""
    lines = daily_log.splitlines()
    in_per_project = False
    current_nick: str | None = None
    sections: dict[str, list[str]] = {}
    for line in lines:
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
            sections.setdefault(current_nick, [])
            continue
        if current_nick and line.strip():
            sections[current_nick].append(line.strip())

    summary = {}
    for nick, body_lines in sections.items():
        joined = " | ".join(body_lines)
        m_repeat = LESSON_LINK_RE.search(joined)
        if "clean" in joined.lower() and not m_repeat:
            summary[nick] = f"- {today}: clean"
        elif m_repeat:
            lesson = m_repeat.group(1)
            summary[nick] = (
                f"- {today}: smell **repeat** [[lessons/{lesson}]] · "
                f"see [[logs/daily/{today}#{nick}]]"
            )
        else:
            summary[nick] = f"- {today}: activity · see [[logs/daily/{today}#{nick}]]"
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", required=True, type=Path)
    parser.add_argument("--today", required=True)
    parser.add_argument("--input-file", default=None, help="Read raw output from file; default stdin")
    args = parser.parse_args(argv)

    if args.input_file:
        raw = Path(args.input_file).read_text()
    else:
        raw = sys.stdin.read()

    parsed = parse_output(raw)
    daily_log_body = parsed["daily_log"]
    if not daily_log_body.startswith("---\n"):
        daily_log_body = "---\n" + daily_log_body

    brain = args.brain_root
    write_daily_log(brain / "logs" / "daily", date_str=args.today, body=daily_log_body)

    summaries = extract_per_project_summary(daily_log_body, today=args.today)
    for nick, line in summaries.items():
        note = brain / "projects" / f"{nick}.md"
        if note.exists():
            update_project_note_slot(note, new_entry=line, today=args.today)

    write_lesson_drafts(brain / "_meta" / "drafts" / "lessons", parsed["lesson_drafts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
