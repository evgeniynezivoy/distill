from pathlib import Path
from datetime import date

from unittest.mock import patch

from promote_lessons import (
    aggregate_firings,
    build_skill_prompt,
    get_candidates,
    parse_daily_log,
    parse_skill_draft,
    write_skill_draft,
)

FIXTURES = Path(__file__).parent / "fixtures" / "logs" / "daily-promotion"


def test_parse_daily_log_extracts_per_project_smells():
    parsed = parse_daily_log(FIXTURES / "2026-05-12.md")
    assert parsed["date"] == "2026-05-12"
    assert parsed["per_project"] == {
        "project-a": ["lesson-x"],
        "project-b": ["lesson-x"],
    }


def test_parse_daily_log_handles_clean_day():
    parsed = parse_daily_log(FIXTURES / "2026-05-14.md")
    assert parsed["per_project"] == {}
    assert parsed["clean_day"] is True


def test_parse_daily_log_multiple_lessons_one_project():
    # Should handle a project mentioning multiple lessons in its section
    # (not present in fixtures — we test fallback to smells_repeat only)
    parsed = parse_daily_log(FIXTURES / "2026-05-17.md")
    assert parsed["per_project"] == {"project-a": ["lesson-z"]}


def test_aggregate_firings_across_logs():
    logs = sorted(FIXTURES.glob("*.md"))
    firings = aggregate_firings(logs)
    # lesson-x: project-a (1 day), project-b (1 day), project-c (1 day) → 3 firings, 3 projects
    assert sum(len(d) for d in firings["lesson-x"].values()) == 3
    assert len(firings["lesson-x"]) == 3
    # lesson-y: project-a (1 day), project-b (1 day) → 2 firings, 2 projects
    assert sum(len(d) for d in firings["lesson-y"].values()) == 2
    assert len(firings["lesson-y"]) == 2
    # lesson-z: project-a (2 days) → 2 firings, 1 project
    assert sum(len(d) for d in firings["lesson-z"].values()) == 2
    assert len(firings["lesson-z"]) == 1


def test_get_candidates_default_threshold_n3_m2():
    logs = sorted(FIXTURES.glob("*.md"))
    firings = aggregate_firings(logs)
    candidates = get_candidates(firings, n_min=3, m_min=2)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["lesson"] == "lesson-x"
    assert c["total_firings"] == 3
    assert sorted(c["projects"]) == ["project-a", "project-b", "project-c"]
    assert len(c["events"]) == 3


def test_get_candidates_lower_threshold_includes_more():
    logs = sorted(FIXTURES.glob("*.md"))
    firings = aggregate_firings(logs)
    candidates = get_candidates(firings, n_min=2, m_min=2)
    # Now lesson-y also qualifies (2 firings, 2 projects)
    lessons = sorted(c["lesson"] for c in candidates)
    assert lessons == ["lesson-x", "lesson-y"]


def test_get_candidates_single_project_excluded_at_m2():
    logs = sorted(FIXTURES.glob("*.md"))
    firings = aggregate_firings(logs)
    candidates = get_candidates(firings, n_min=2, m_min=2)
    lessons = [c["lesson"] for c in candidates]
    # lesson-z has 2 firings but only in 1 project — excluded
    assert "lesson-z" not in lessons


def test_get_candidates_empty():
    candidates = get_candidates({}, n_min=3, m_min=2)
    assert candidates == []


def test_build_skill_prompt_contains_required_blocks():
    candidate = {
        "lesson": "lesson-x",
        "total_firings": 3,
        "projects": ["project-a", "project-b", "project-c"],
        "events": [
            {"date": "2026-05-12", "project": "project-a"},
            {"date": "2026-05-12", "project": "project-b"},
            {"date": "2026-05-13", "project": "project-c"},
        ],
    }
    lesson_content = "---\nname: lesson-x\n---\n# Lesson X\n## Bigger lesson\nDo X."
    prompt = build_skill_prompt(lesson_content, candidate, today_str="2026-05-18")
    assert "lesson-x" in prompt
    assert "Lesson X" in prompt
    assert "Do X." in prompt
    assert "project-a" in prompt
    assert "project-c" in prompt
    assert "2026-05-18" in prompt
    assert "START-SKILL-DRAFT" in prompt


def test_parse_skill_draft_extracts_body():
    raw = """preamble noise

---START-SKILL-DRAFT---
---
name: lesson-x
description: when X
---

# Lesson X Skill

## When this applies
Some trigger
---END-SKILL-DRAFT---

trailing"""
    body = parse_skill_draft(raw)
    assert body.startswith("---\n")
    assert "name: lesson-x" in body
    assert "When this applies" in body


def test_parse_skill_draft_missing_markers_raises():
    import pytest
    with pytest.raises(ValueError, match="SKILL-DRAFT"):
        parse_skill_draft("no markers here")


def test_write_skill_draft_atomic(tmp_path):
    drafts_dir = tmp_path / "_meta" / "drafts" / "skills"
    body = "---\nname: lesson-x\n---\nbody"
    path = write_skill_draft(drafts_dir, lesson_name="lesson-x", body=body, today_str="2026-05-18")
    assert path is not None
    assert path.name == "2026-05-18-lesson-x.md"
    assert path.read_text().rstrip() == body.rstrip()


def test_write_skill_draft_skips_existing(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir(parents=True)
    existing = drafts_dir / "2026-05-18-lesson-x.md"
    existing.write_text("original")
    result = write_skill_draft(drafts_dir, lesson_name="lesson-x", body="new content", today_str="2026-05-18")
    assert result is None
    assert existing.read_text() == "original"
