from pathlib import Path
import pytest

from apply_daily_output import (
    extract_per_project_summary,
    parse_output,
    update_project_note_slot,
    write_daily_log,
    write_lesson_drafts,
)

FIXTURES = Path(__file__).parent / "fixtures"

CURATED_NOTE = """\
---
name: my-app
path: /tmp/qm
tier: hot
last_commit_date: 2026-05-18
default_branch: main
---

# my-app

## Open threads
- old thread one
- old thread two

## Architecture history
- 2026-04-15: chose deferred FK approach (see [[lessons/deferred-fk-for-circular-refs]])

## Decisions
- migrate to predicate-based validators by Q2
"""

NEW_DAILY_LINE = "- 2026-05-18: smell **repeat** [[lessons/predicate-as-defense]] · see [[logs/daily/2026-05-18#my-app]]"


def test_parse_output_extracts_daily_log_and_drafts():
    raw = (FIXTURES / "sample_claude_output.txt").read_text()
    parsed = parse_output(raw)
    assert "2026-05-18" in parsed["daily_log"]
    assert parsed["daily_log"].startswith("---\n")
    assert len(parsed["lesson_drafts"]) == 1
    draft = parsed["lesson_drafts"][0]
    assert draft["slug"] == "2026-05-18-jwt-refresh-staleness"
    assert "JWT" in draft["body"] or "jwt" in draft["body"]


def test_parse_output_missing_daily_log_raises():
    with pytest.raises(ValueError, match="DAILY-LOG"):
        parse_output("just some text without markers")


def test_parse_output_no_drafts_ok():
    minimal = """---START-DAILY-LOG---
---
date: 2026-05-18
clean_day: true
---
# Daily
clean
---END-DAILY-LOG---
"""
    parsed = parse_output(minimal)
    assert parsed["lesson_drafts"] == []
    assert "Daily" in parsed["daily_log"]


def test_write_daily_log_atomic(tmp_path):
    daily_dir = tmp_path / "logs" / "daily"
    content = "---\ndate: 2026-05-18\n---\n# Daily — 2026-05-18\nbody"
    path = write_daily_log(daily_dir, date_str="2026-05-18", body=content)
    assert path.exists()
    assert path.name == "2026-05-18.md"
    assert path.read_text() == content
    # No temp file leftover
    assert not list(daily_dir.glob(".*.tmp"))


def test_update_project_note_slot_creates_when_absent(tmp_path):
    note = tmp_path / "my-app.md"
    note.write_text(CURATED_NOTE)

    update_project_note_slot(
        note_path=note,
        new_entry=NEW_DAILY_LINE,
        today="2026-05-18",
        rolling_window_days=7,
    )

    text = note.read_text()
    assert "## Daily synthesis (auto, regenerated each run)" in text
    assert NEW_DAILY_LINE in text
    # Curated sections intact
    assert "old thread one" in text
    assert "Architecture history" in text
    assert "2026-04-15: chose deferred FK" in text
    assert "migrate to predicate-based validators" in text


def test_update_project_note_slot_rolls_window(tmp_path):
    pre_existing_slot = """
## Daily synthesis (auto, regenerated each run)

> Last update: 2026-05-17

- 2026-05-17: clean
- 2026-05-10: smell **repeat** [[lessons/predicate-as-defense]]
- 2026-05-09: clean
"""
    note = tmp_path / "qm.md"
    note.write_text(CURATED_NOTE + pre_existing_slot)

    update_project_note_slot(
        note_path=note,
        new_entry="- 2026-05-18: clean",
        today="2026-05-18",
        rolling_window_days=7,
    )

    text = note.read_text()
    assert "2026-05-18: clean" in text
    assert "2026-05-17: clean" in text
    # 2026-05-10 outside 7-day window
    assert "2026-05-10" not in text
    assert "Architecture history" in text


def test_update_project_note_slot_curated_byte_equal(tmp_path):
    note = tmp_path / "qm.md"
    note.write_text(CURATED_NOTE)
    original_curated_block = CURATED_NOTE.strip()

    update_project_note_slot(
        note_path=note,
        new_entry=NEW_DAILY_LINE,
        today="2026-05-18",
        rolling_window_days=7,
    )

    text = note.read_text()
    slot_idx = text.find("## Daily synthesis (auto")
    assert slot_idx > 0
    curated_part = text[:slot_idx].rstrip()
    assert curated_part == original_curated_block


def test_write_lesson_drafts(tmp_path):
    drafts_dir = tmp_path / "_meta" / "drafts" / "lessons"
    drafts = [{"slug": "2026-05-18-jwt-refresh-staleness",
               "body": "---\nname: jwt-refresh-staleness\n---\n## Trigger\nX"}]
    paths = write_lesson_drafts(drafts_dir, drafts)
    assert len(paths) == 1
    p = paths[0]
    assert p.name == "2026-05-18-jwt-refresh-staleness.md"
    assert "jwt-refresh-staleness" in p.read_text()


def test_write_lesson_drafts_skips_existing(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir(parents=True)
    existing = drafts_dir / "2026-05-18-foo.md"
    existing.write_text("---\nname: foo\n---\noriginal content")

    paths = write_lesson_drafts(drafts_dir, [{"slug": "2026-05-18-foo", "body": "different body"}])
    assert paths == []
    assert "original content" in existing.read_text()


def test_extract_per_project_summary():
    daily_log_body = """\
---
date: 2026-05-18
projects_touched: [my-app, my-lib]
---

# Daily — 2026-05-18

## Per-project
### my-app
- Commits: 1 (`abc fix(issues)...`)
- Smell repeat: [[lessons/predicate-as-defense]] — снова валидация post-hoc.

### my-lib
- Commits: 2 (`def feat(...)`, `ghi fix(...)`)
- Clean — без smell.

## Cross-project
(none)
"""
    summary = extract_per_project_summary(daily_log_body, today="2026-05-18")
    assert summary["my-app"].startswith("- 2026-05-18: smell **repeat**")
    assert "predicate-as-defense" in summary["my-app"]
    assert summary["my-lib"] == "- 2026-05-18: clean"


def test_cli_end_to_end(tmp_path):
    import subprocess
    brain_root = tmp_path / "brain"
    (brain_root / "logs" / "daily").mkdir(parents=True)
    (brain_root / "projects").mkdir()
    (brain_root / "_meta" / "drafts" / "lessons").mkdir(parents=True)
    note = brain_root / "projects" / "my-app.md"
    note.write_text(CURATED_NOTE)

    raw = (FIXTURES / "sample_claude_output.txt").read_text()
    raw_input_path = tmp_path / "claude_output.txt"
    raw_input_path.write_text(raw)

    script = Path(__file__).parent.parent / "apply_daily_output.py"
    result = subprocess.run(
        ["python3", str(script),
         "--brain-root", str(brain_root),
         "--today", "2026-05-18",
         "--input-file", str(raw_input_path)],
        capture_output=True, text=True, check=True,
    )

    daily_log = brain_root / "logs" / "daily" / "2026-05-18.md"
    assert daily_log.exists()
    assert "2026-05-18" in daily_log.read_text()
    drafts = list((brain_root / "_meta" / "drafts" / "lessons").glob("*.md"))
    assert len(drafts) == 1
    assert "jwt-refresh-staleness" in drafts[0].read_text()
    qm_text = note.read_text()
    assert "Daily synthesis (auto" in qm_text
    assert "predicate-as-defense" in qm_text
    assert "Architecture history" in qm_text
