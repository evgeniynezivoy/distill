#!/usr/bin/env python3
"""scan-candidates.py — daily heuristic scanner для architecture-event candidates.

Walks each project's remote git log + PR data за последние 14 дней.
Scores commit groups по architectural keywords + PR body depth + structural sections.
Outputs _meta/candidates.json для weekly drafter.

No LLM, no cost. Pure stdlib + subprocess (git + gh).
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

BRAIN = Path(os.environ.get("BRAIN_ROOT", str(Path.home() / "brain")))
PROJECTS_TSV = BRAIN / "_meta" / "PROJECTS.tsv"
CANDIDATES = BRAIN / "_meta" / "candidates.json"
DRAFTS_DIR = BRAIN / "_meta" / "drafts"
LOG_DIR = BRAIN / ".bin" / "logs"

LOOKBACK_DAYS = 14
SCORE_THRESHOLD = 5
MIN_COMMITS_PER_GROUP = 1

KEYWORDS_RE = re.compile(
    r"\b(phase|refactor|migration|migrate|split|merge|rewrite|cutover|incident|"
    r"schema|constraint|fk|invariant|deprecate|backfill|cooldown|trigger|"
    r"leak|conflation|lock|baseline|snapshot|breaking|architecture|architectural|"
    r"self[- ]join|cpu[- ]spike|data[- ]corruption|root[- ]cause)\b",
    re.IGNORECASE,
)
STRUCTURAL_SECTION_RE = re.compile(
    r"^##\s+(Why|Approach|Scope decision|Phases?|Background|Decisions|Root cause|"
    r"Migration plan|Test plan|Reversibility|Rollback|Summary)",
    re.IGNORECASE | re.MULTILINE,
)
PR_NUM_RE = re.compile(r"\(#(\d+)\)\s*$")
CONVENTIONAL_PREFIX_RE = re.compile(r"^[a-z]+(\([^)]*\))?:\s*", re.IGNORECASE)


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = LOG_DIR / f"scan-{datetime.now().strftime('%Y-%m')}.log"
    with f.open("a") as out:
        out.write(f"{datetime.now().isoformat()} {msg}\n")


def _env():
    e = os.environ.copy()
    e["GIT_TERMINAL_PROMPT"] = "0"
    return e


def git(repo: Path, *args: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, env=_env(), timeout=timeout,
        )
        return r.stdout
    except Exception as e:
        _log(f"git error {repo}: {e}")
        return ""


def gh_pr_view(slug: str, pr_num: int, timeout: int = 15) -> dict | None:
    """Fetch PR data via gh. Returns dict or None on failure."""
    try:
        r = subprocess.run(
            ["gh", "pr", "view", str(pr_num), "--repo", slug,
             "--json", "title,body,additions,deletions,labels,number,mergedAt,author"],
            capture_output=True, text=True, timeout=timeout, env=_env(),
        )
        if r.returncode != 0:
            _log(f"gh pr view {slug}#{pr_num} rc={r.returncode}: {r.stderr.strip()[:200]}")
            return None
        return json.loads(r.stdout)
    except Exception as e:
        _log(f"gh pr exception {slug}#{pr_num}: {e}")
        return None


def parse_remote_slug(remote_url: str) -> str | None:
    if not remote_url:
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/.\s]+?)(?:\.git)?$", remote_url.strip())
    return m.group(1) if m else None


def extract_pr_num(subject: str) -> int | None:
    m = PR_NUM_RE.search(subject)
    return int(m.group(1)) if m else None


def is_merge_commit(subject: str) -> bool:
    return subject.startswith("Merge pull request") or subject.startswith("Merge branch")


def score_group(commits: list, prs_data: list) -> tuple[int, list]:
    score = 0
    reasons: list = []

    all_subjects = " | ".join(c["subject"] for c in commits)
    kw_found = set(m.group(0).lower() for m in KEYWORDS_RE.finditer(all_subjects))
    if kw_found:
        score += 2 * len(kw_found)
        reasons.append(f"keywords:{','.join(sorted(kw_found))}")

    if len(commits) > 1:
        score += len(commits) - 1
        reasons.append(f"{len(commits)} commits")

    for pr in prs_data:
        if not pr:
            continue
        pr_num = pr.get("number")
        body = pr.get("body") or ""
        body_lines = body.count("\n") + 1
        if body_lines > 50:
            score += 1
            if body_lines > 150:
                score += 1
        sections = STRUCTURAL_SECTION_RE.findall(body)
        if len(sections) >= 2:
            score += 2
            reasons.append(f"structured-body#{pr_num}")
        elif body_lines > 50:
            reasons.append(f"long-body#{pr_num}")

        churn = (pr.get("additions") or 0) + (pr.get("deletions") or 0)
        if churn > 200:
            score += 1
            reasons.append(f"churn{churn}#{pr_num}")

        body_keywords = set(m.group(0).lower() for m in KEYWORDS_RE.finditer(body))
        if len(body_keywords) >= 3:
            score += 1
            reasons.append(f"body-kw#{pr_num}")

        for lbl in (pr.get("labels") or []):
            name = (lbl.get("name") or "").lower()
            if any(k in name for k in ["architecture", "breaking", "migration", "incident", "refactor"]):
                score += 1
                reasons.append(f"label:{name}")

    return score, reasons


def derive_slug(commits: list, prs_data: list) -> str:
    title = ""
    if prs_data and prs_data[0]:
        title = prs_data[0].get("title") or ""
    if not title:
        title = commits[0]["subject"]
    title = CONVENTIONAL_PREFIX_RE.sub("", title)
    title = PR_NUM_RE.sub("", title).strip()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    if len(slug) > 50:
        slug = slug[:50].rstrip("-")
    return slug or "unknown"


def already_captured(nick: str, slug: str, prs: list) -> bool:
    """Skip если slug ИЛИ any PR # уже в Architecture history."""
    note = BRAIN / "projects" / f"{nick}.md"
    if not note.exists():
        return False
    text = note.read_text()
    in_history = False
    for line in text.splitlines():
        stripped = line.lstrip("> ").rstrip()
        if stripped.startswith("## Architecture history"):
            in_history = True
            continue
        if stripped.startswith("## ") and in_history:
            in_history = False
        if in_history:
            if slug and slug in line:
                return True
            for pr in prs:
                if f"#{pr}" in line:
                    return True
    return False


def draft_exists(slug: str) -> bool:
    return (DRAFTS_DIR / f"{slug}.md").exists()


def scan_project(rpath: str, nick: str) -> list:
    repo = Path(rpath)
    if not (repo / ".git").exists():
        return []

    sym = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    default_branch = sym.split("/")[-1] if sym else "main"
    if not default_branch or default_branch == "HEAD":
        default_branch = "main"

    raw = git(repo, "log", f"origin/{default_branch}",
              f"--since={LOOKBACK_DAYS}.days.ago",
              "--pretty=%H|%h|%ad|%s", "--date=short")
    commits: list = []
    for line in raw.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        sha, short, date, subject = parts
        if is_merge_commit(subject):
            continue
        commits.append({
            "sha": sha, "short": short, "date": date,
            "subject": subject, "pr": extract_pr_num(subject),
        })

    if not commits:
        return []

    remote_url = git(repo, "remote", "get-url", "origin").strip()
    gh_slug = parse_remote_slug(remote_url)

    # Group: same PR# OR adjacent PR-less commits in 3-day window
    groups: list = []
    for c in commits:
        if c["pr"] and groups and groups[-1].get("pr") == c["pr"]:
            groups[-1]["commits"].append(c)
            continue
        if not c["pr"] and groups and not groups[-1].get("pr"):
            try:
                last_d = datetime.strptime(groups[-1]["commits"][-1]["date"], "%Y-%m-%d")
                this_d = datetime.strptime(c["date"], "%Y-%m-%d")
                if abs((last_d - this_d).days) <= 3:
                    groups[-1]["commits"].append(c)
                    continue
            except Exception:
                pass
        groups.append({"pr": c["pr"], "commits": [c]})

    candidates: list = []
    for g in groups:
        if len(g["commits"]) < MIN_COMMITS_PER_GROUP:
            continue

        prs_data: list = []
        if g["pr"] and gh_slug:
            d = gh_pr_view(gh_slug, g["pr"])
            if d:
                prs_data.append(d)

        score, reasons = score_group(g["commits"], prs_data)
        if score < SCORE_THRESHOLD:
            continue

        slug = derive_slug(g["commits"], prs_data)
        prs_list = [g["pr"]] if g["pr"] else []

        if already_captured(nick, slug, prs_list):
            _log(f"skip {nick}/{slug}: already в Architecture history")
            continue
        if draft_exists(slug):
            _log(f"skip {nick}/{slug}: draft exists")
            continue

        dates = sorted({c["date"] for c in g["commits"]})
        shas = [c["short"] for c in g["commits"]]

        candidates.append({
            "project": nick,
            "slug": slug,
            "date_range": f"{dates[0]}..{dates[-1]}",
            "sha_range": f"{shas[-1]}..{shas[0]}",
            "prs": prs_list,
            "score": score,
            "why": "; ".join(reasons),
            "subject": g["commits"][0]["subject"],
            "remote_slug": gh_slug,
        })

    return candidates


def main() -> None:
    _log("=== scan-candidates start ===")
    if not PROJECTS_TSV.exists():
        print(f"ERROR: {PROJECTS_TSV} not found", file=sys.stderr)
        sys.exit(1)

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    all_candidates: list = []
    for line in PROJECTS_TSV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rpath, _tier, nick = parts[0], parts[1], parts[2]
        try:
            cands = scan_project(rpath, nick)
            all_candidates.extend(cands)
            _log(f"{nick}: {len(cands)} candidates")
        except Exception:
            _log(f"FAIL {nick}: {traceback.format_exc()}")

    all_candidates.sort(key=lambda c: -c["score"])

    tmp = CANDIDATES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(all_candidates, indent=2, ensure_ascii=False))
    tmp.replace(CANDIDATES)

    _log(f"=== scan-candidates end: {len(all_candidates)} total ===")
    print(f"scan-candidates.py: {len(all_candidates)} candidate(s) → {CANDIDATES}")


if __name__ == "__main__":
    main()
