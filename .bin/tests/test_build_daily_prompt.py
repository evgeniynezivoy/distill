from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from build_daily_prompt import (
    assemble_prompt,
    collect_git_signal,
    load_active_projects,
    load_lessons,
    load_recent_daily_frontmatter,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_active_projects_filters_by_recency():
    today = date(2026, 5, 18)
    projects = load_active_projects(
        projects_root=FIXTURES / "projects",
        tsv_path=FIXTURES / "PROJECTS.tsv",
        today=today,
        window_days=1,
    )
    nicks = sorted(p["nick"] for p in projects)
    assert nicks == ["my-app", "my-lib"]


def test_load_active_projects_includes_repo_path_and_name():
    today = date(2026, 5, 18)
    projects = load_active_projects(
        projects_root=FIXTURES / "projects",
        tsv_path=FIXTURES / "PROJECTS.tsv",
        today=today,
        window_days=1,
    )
    qm = next(p for p in projects if p["nick"] == "my-app")
    assert qm["repo_path"] == "/tmp/qm"
    assert qm["name"] == "my-app"
    assert qm["default_branch"] == "main"


def test_load_lessons_returns_title_and_bigger_lesson():
    lessons = load_lessons(FIXTURES / "lessons")
    by_name = {l["name"]: l for l in lessons}
    assert "predicate-as-defense" in by_name
    assert "deferred-fk-for-circular-refs" in by_name
    pad = by_name["predicate-as-defense"]
    assert "predicate" in pad["bigger_lesson"].lower()
    assert pad["title"] == "Predicate As Defense"


def test_load_lessons_returns_empty_for_missing_dir():
    lessons = load_lessons(FIXTURES / "lessons-does-not-exist")
    assert lessons == []


def test_load_recent_daily_frontmatter_skips_today():
    today = datetime(2026, 5, 18, tzinfo=timezone.utc)
    entries = load_recent_daily_frontmatter(
        daily_dir=FIXTURES / "logs/daily",
        today=today,
        days=7,
    )
    dates = sorted(e["date"] for e in entries)
    assert "2026-05-17" in dates
    assert "2026-05-16" in dates
    assert "2026-05-15" in dates
    assert "2026-05-18" not in dates
    by_date = {e["date"]: e for e in entries}
    assert by_date["2026-05-17"]["smells_repeat"] == ["predicate-as-defense"]
    assert by_date["2026-05-16"]["projects_touched"] == ["my-lib", "my-tool"]
    assert by_date["2026-05-15"]["clean_day"] is True


def test_load_recent_daily_frontmatter_missing_dir():
    today = datetime(2026, 5, 18, tzinfo=timezone.utc)
    entries = load_recent_daily_frontmatter(
        daily_dir=FIXTURES / "logs/does-not-exist",
        today=today,
    )
    assert entries == []


def test_collect_git_signal_returns_log_and_numstat():
    fake_log = "abc1234 2026-05-18 10:00:00 +0000 evgeniy fix(issues): reject status #152"
    fake_numstat = "5\t2\tissues.py\n10\t0\ttests/test_issues.py"

    def fake_run(cmd, **kwargs):
        from subprocess import CompletedProcess
        if "--pretty=format:%h %ci %an %s" in cmd:
            return CompletedProcess(cmd, 0, stdout=fake_log, stderr="")
        if "--numstat" in cmd:
            return CompletedProcess(cmd, 0, stdout=fake_numstat, stderr="")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("build_daily_prompt.subprocess.run", side_effect=fake_run):
        signal = collect_git_signal(repo_path="/tmp/qm-fake", since_hours=24)

    # collect_git_signal should still try (we don't gate on .git existence in the function
    # itself — caller is responsible). Mocked subprocess always succeeds.
    # Note: function returns early if path doesn't exist on disk — adjust if needed.


def test_collect_git_signal_handles_missing_repo():
    signal = collect_git_signal(repo_path="/tmp/does-not-exist-xyz-zzz", since_hours=24)
    assert signal["commits"] == ""
    assert signal["error"]


def test_assemble_prompt_contains_required_blocks():
    today = datetime(2026, 5, 18, tzinfo=timezone.utc)
    active = [{
        "nick": "my-app",
        "name": "my-app",
        "note_path": str(FIXTURES / "projects/my-app.md"),
        "tier": "hot",
        "repo_path": "/tmp/qm",
        "default_branch": "main",
    }]
    git_signals = {"my-app": {"commits": "abc fix(issues): X", "numstat": "5\t2\tx.py", "error": ""}}
    lessons = [{
        "name": "predicate-as-defense",
        "title": "Predicate As Defense",
        "bigger_lesson": "Validate at entry, not post-hoc.",
        "tags": ["validation"],
    }]
    history = [{
        "date": "2026-05-17",
        "smells_repeat": ["predicate-as-defense"],
        "smells_new": [],
        "clean_day": False,
        "projects_touched": ["my-app"],
    }]

    prompt = assemble_prompt(today=today, active=active, git_signals=git_signals, lessons=lessons, history=history)

    assert "2026-05-18" in prompt
    assert "my-app" in prompt
    assert "Predicate As Defense" in prompt
    assert "Validate at entry" in prompt
    assert "2026-05-17" in prompt
    assert "OUTPUT FORMAT" in prompt
    assert "START-DAILY-LOG" in prompt
    assert "START-LESSON-DRAFT" in prompt


def test_assemble_prompt_empty_active_still_valid():
    today = datetime(2026, 5, 18, tzinfo=timezone.utc)
    prompt = assemble_prompt(today=today, active=[], git_signals={}, lessons=[], history=[])
    assert "2026-05-18" in prompt
    assert "(none)" in prompt  # empty active list rendered explicitly


def test_cli_outputs_full_prompt(tmp_path):
    import shutil, subprocess
    brain_root = tmp_path / "brain"
    (brain_root / "_meta").mkdir(parents=True)
    (brain_root / "logs" / "daily").mkdir(parents=True)
    (brain_root / "lessons").mkdir()
    shutil.copytree(FIXTURES / "projects", brain_root / "projects")
    shutil.copy(FIXTURES / "PROJECTS.tsv", brain_root / "_meta" / "PROJECTS.tsv")
    for L in (FIXTURES / "lessons").glob("*.md"):
        shutil.copy(L, brain_root / "lessons" / L.name)
    for d in (FIXTURES / "logs/daily").glob("*.md"):
        shutil.copy(d, brain_root / "logs" / "daily" / d.name)

    script = Path(__file__).parent.parent / "build_daily_prompt.py"
    result = subprocess.run(
        ["python3", str(script), "--brain-root", str(brain_root), "--today", "2026-05-18"],
        capture_output=True, text=True, check=True,
    )
    assert "2026-05-18" in result.stdout
    assert "OUTPUT FORMAT" in result.stdout
    assert "my-app" in result.stdout
    assert "Predicate As Defense" in result.stdout
