#!/usr/bin/env python3
"""harvest.py v2.1 — live state harvester для ~/brain/ vault.

Для каждого project в _meta/PROJECTS.tsv:
  1. `git fetch --prune --quiet --no-tags` (timeout 30s, fail-fast на auth)
  2. Reads project truth с `origin/<default_branch>`:
       - last_commit_date / last_commit / today_commits / yday_commits
  3. Reads local working state:
       - current_branch / dirty / local_branches / behind (vs origin/<default>)
  4. Rewrites yaml frontmatter (remote-truth fields + local fields)
  5. Updates `**Last activity:**` (remote) и `**Local:**` line (current_branch, dirty, behind)
  6. Auto-prunes Open threads (branch gone = not in local AND not in remote)
  7. Appends today's line к HARVESTER block (idempotent) — показывает remote commits
  8. INDEX hot/warm/cold regen + Last harvest timestamp

Pure stdlib. Atomic per-file writes. Continue-on-exception.
"""

from __future__ import annotations
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

BRAIN = Path(os.environ.get("BRAIN_ROOT", str(Path.home() / "brain")))
PROJECTS_TSV = BRAIN / "_meta" / "PROJECTS.tsv"
INDEX = BRAIN / "INDEX.md"
LOG_DIR = BRAIN / ".bin" / "logs"

TODAY = datetime.now()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
YESTERDAY_STR = (TODAY - timedelta(days=1)).strftime("%Y-%m-%d")
NOW_STR = TODAY.strftime("%Y-%m-%d %H:%M:%S %Z").strip() or TODAY.strftime("%Y-%m-%d %H:%M:%S")

TIER_HOT_MAX = 7
TIER_WARM_MAX = 30

BRANCH_PREFIX_RE = re.compile(r"^(fix|feat|feature|revert|chore|hotfix|release|refactor|bugfix|wip)/")
FILE_EXT_RE = re.compile(r"\.(md|py|js|ts|tsx|jsx|json|yml|yaml|sql|sh|env|db|html|css|toml|lock|txt|csv|xlsx|pdf|docx|xml|conf)$", re.IGNORECASE)
YAML_ORDER = ["name", "path", "tier", "last_commit_date", "last_commit", "default_branch", "remote", "current_branch", "behind"]


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"harvest-{datetime.now().strftime('%Y-%m')}.log"
    with logfile.open("a") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")


def _env():
    e = os.environ.copy()
    e["GIT_TERMINAL_PROMPT"] = "0"
    e["GIT_ASKPASS"] = "true"
    return e


def git(repo: Path, *args: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, env=_env(), timeout=timeout,
        )
        return r.stdout.strip()
    except Exception as e:
        log(f"git error in {repo} ({' '.join(args)}): {e}")
        return ""


def git_fetch(repo: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "fetch", "--prune", "--quiet", "--no-tags"],
            capture_output=True, text=True, env=_env(), timeout=30,
        )
        if r.returncode != 0:
            log(f"fetch failed for {repo}: {r.stderr.strip()}")
            return False
        return True
    except Exception as e:
        log(f"fetch exception for {repo}: {e}")
        return False


def days_since(date_str: str) -> int:
    if not date_str:
        return 999
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return max((TODAY - d).days, 0)
    except Exception:
        return 999


def derive_tier(days: int) -> str:
    if days <= TIER_HOT_MAX:
        return "hot"
    if days <= TIER_WARM_MAX:
        return "warm"
    return "cold"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 5:]
    fm: dict = {}
    for line in fm_text.split("\n"):
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def serialize_frontmatter(fm: dict) -> str:
    lines = ["---"]
    seen: set = set()
    for k in YAML_ORDER:
        if k in fm:
            lines.append(f"{k}: {fm[k]}")
            seen.add(k)
    for k, v in fm.items():
        if k not in seen:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def get_state(repo: Path) -> dict:
    state: dict = {}

    state["fetched"] = git_fetch(repo)

    # Detect default branch on remote
    sym = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    default_branch = sym.split("/")[-1] if sym else "main"
    if not default_branch or default_branch in ("HEAD", ""):
        default_branch = "main"
    state["default_branch"] = default_branch

    # Verify origin/<default> exists; otherwise fallback to HEAD for project truth
    ref = f"origin/{default_branch}"
    verify = git(repo, "rev-parse", "--verify", "--quiet", ref)
    if not verify:
        log(f"no {ref} in {repo}, falling back to HEAD for project truth")
        ref = "HEAD"

    # Project truth (remote default branch)
    state["last_commit_date"] = git(repo, "log", ref, "-1", "--format=%ad", "--date=short")
    state["last_commit_sha"] = git(repo, "log", ref, "-1", "--format=%h")
    state["last_commit_msg"] = git(repo, "log", ref, "-1", "--format=%s")
    state["last_commit"] = (state["last_commit_sha"] + " " + state["last_commit_msg"]).strip()
    state["remote_url"] = git(repo, "remote", "get-url", "origin")

    today_log = git(repo, "log", ref, f"--since={TODAY_STR} 00:00:00", "--format=%h %s")
    state["today_commits"] = [line for line in today_log.splitlines() if line.strip()]
    yday_log = git(repo, "log", ref, f"--since={YESTERDAY_STR} 00:00:00", f"--until={TODAY_STR} 00:00:00", "--format=%h %s")
    state["yday_commits"] = [line for line in yday_log.splitlines() if line.strip()]

    # Local working state
    state["current_branch"] = git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    status = git(repo, "status", "--porcelain")
    state["dirty"] = len([line for line in status.splitlines() if line.strip()])

    behind_str = git(repo, "rev-list", "--count", f"HEAD..{ref}")
    state["behind"] = int(behind_str) if behind_str.isdigit() else 0

    # Local branches (user WIP)
    branches_out = git(repo, "branch", "--list")
    locals_: list = []
    for line in branches_out.splitlines():
        b = line.lstrip("* ").strip()
        if b and b not in ("main", "master") and not b.startswith("("):
            locals_.append(b)
    state["local_branches"] = locals_

    # Remote branches (for auto-prune comparison)
    remote_refs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/")
    remote_set: set = set()
    for line in remote_refs.splitlines():
        if line.startswith("origin/"):
            b = line[len("origin/"):]
            if b not in ("HEAD", "main", "master"):
                remote_set.add(b)
    state["remote_branches"] = remote_set

    return state


def update_status_and_local_lines(body: str, state: dict) -> str:
    if state["last_commit_date"] and state["last_commit_msg"]:
        new_la = f"**Last activity:** {state['last_commit_date']} — `{state['last_commit_msg']}` _(origin/{state['default_branch']})_"
        body = re.sub(r"^\*\*Last activity:\*\*.*$", new_la, body, count=1, flags=re.MULTILINE)

    behind_str = f", behind {state['behind']}" if state["behind"] > 0 else ""
    new_local = f"**Local:** branch `{state['current_branch']}`, dirty={state['dirty']}{behind_str}"

    if re.search(r"^\*\*Local:\*\*.*$", body, re.MULTILINE):
        body = re.sub(r"^\*\*Local:\*\*.*$", new_local, body, count=1, flags=re.MULTILINE)
    else:
        body = re.sub(
            r"^(\*\*Last activity:\*\*.*$)",
            r"\1\n" + new_local,
            body, count=1, flags=re.MULTILINE,
        )

    return body


def auto_prune_open_threads(body: str, state: dict) -> str:
    local = set(state["local_branches"])
    remote = state["remote_branches"]

    def looks_like_branch(s: str) -> bool:
        if not s or len(s) > 80 or " " in s:
            return False
        if s.startswith("/") or s.startswith("."):
            return False
        if s.endswith("/"):
            return False
        if FILE_EXT_RE.search(s):
            return False
        return bool(BRANCH_PREFIX_RE.match(s))

    def repl(m):
        line = m.group(0)
        if line.startswith("- [x]"):
            return line
        if "merged" in line.lower() or "deleted" in line.lower():
            return line
        ticks = re.findall(r"`([^`]+)`", line)
        for t in ticks:
            if looks_like_branch(t) and t not in local and t not in remote:
                marked = line.replace("- [ ]", "- [x]", 1).rstrip()
                return f"{marked} _(merged/deleted {TODAY_STR})_"
        return line

    return re.sub(r"^- \[ \] [^\n]+$", repl, body, flags=re.MULTILINE)


def update_harvester_block(body: str, state: dict) -> str:
    ref_label = f"origin/{state['default_branch']}"
    if state["today_commits"]:
        n = len(state["today_commits"])
        first = state["today_commits"][0]
        line = f"- {TODAY_STR} · {ref_label} · {n} commit(s) · head: {first}"
    elif state["yday_commits"]:
        n = len(state["yday_commits"])
        first = state["yday_commits"][0]
        line = f"- {TODAY_STR} · {ref_label} · 0 today / {n} yesterday · head: {first}"
    else:
        line = f"- {TODAY_STR} · {ref_label} · quiet · local: `{state['current_branch']}`, dirty={state['dirty']}, behind={state['behind']}"

    pat = re.compile(r"(<!-- HARVESTER-START -->)(.*?)(<!-- HARVESTER-END -->)", re.DOTALL)
    m = pat.search(body)
    if not m:
        return body
    inner = m.group(2)
    if re.search(rf"^- {re.escape(TODAY_STR)}\b", inner, re.MULTILINE):
        return body
    new_inner = inner.rstrip("\n ") + "\n" + line + "\n"
    return body[: m.start()] + m.group(1) + new_inner + m.group(3) + body[m.end():]


def regen_index(states: list) -> None:
    if not INDEX.exists():
        return

    text = INDEX.read_text()

    sections: dict = {"hot": [], "warm": [], "cold": []}
    for s in sorted(states, key=lambda x: days_since(x["last_commit_date"])):
        tier = s["tier"]
        if tier not in sections:
            continue
        nick = s["nick"]
        today_n = len(s["today_commits"])
        yday_n = len(s["yday_commits"])
        days = days_since(s["last_commit_date"])
        ref = f"origin/{s['default_branch']}"

        if today_n > 0:
            first = s["today_commits"][0]
            activity = f"{today_n} commit(s) на {ref} сегодня · `{first}`"
        elif yday_n > 0:
            first = s["yday_commits"][0]
            activity = f"{yday_n} commit(s) вчера · `{first}`"
        elif days <= 1:
            activity = f"тихо (last {s['last_commit_date']})"
        else:
            activity = f"last {ref} commit {days}д назад ({s['last_commit_date']})"

        local_note = f"локально `{s['current_branch']}`"
        if s["behind"] > 0:
            local_note += f" **behind {s['behind']}**"
        if s["dirty"] > 0:
            local_note += f", dirty={s['dirty']}"

        sections[tier].append(f"- [[{nick}]] — {activity}; {local_note}")

    tier_headers = [
        ("hot", "## 🔥 Hot (active right now)"),
        ("warm", "## 🌤️ Warm"),
        ("cold", "## ❄️ Cold (post-migration dormant)"),
    ]
    for tier, header in tier_headers:
        items = sections[tier]
        body_block = "\n".join(items) if items else "_(empty)_"
        pat = re.compile(
            rf"({re.escape(header)}\n\n)(.*?)(?=\n## |\Z)",
            re.DOTALL,
        )
        m = pat.search(text)
        if m:
            text = text[: m.start()] + m.group(1) + body_block + "\n" + text[m.end():]

    # Pending captures section — drafts created by weekly-drafts.sh
    drafts_dir = BRAIN / "_meta" / "drafts"
    drafts_lines: list = []
    pending_files = sorted(drafts_dir.glob("*.md")) if drafts_dir.exists() else []
    if pending_files:
        drafts_lines.append(f"**{len(pending_files)} pending** — invoke `/brain-capture-apply` to review + apply.")
        drafts_lines.append("")
        for d in pending_files[:8]:
            slug = d.stem
            target = ""
            try:
                head = d.read_text()[:500]
                tm = re.search(r"<!-- TARGET: projects/([^.]+)\.md -->", head)
                if tm:
                    target = tm.group(1)
            except Exception:
                pass
            target_note = f" → [[{target}]]" if target else ""
            drafts_lines.append(f"- [[_meta/drafts/{slug}]]{target_note}")
    else:
        drafts_lines.append("_(empty — scanner не нашёл candidates за последние 14 дней или все applied)_")

    pending_block = "\n".join(drafts_lines) + "\n"
    pending_header = "## 📥 Pending captures"
    pending_pat = re.compile(
        rf"({re.escape(pending_header)}\n\n)(.*?)(?=\n## |\Z)",
        re.DOTALL,
    )
    pm = pending_pat.search(text)
    if pm:
        text = text[: pm.start()] + pm.group(1) + pending_block + text[pm.end():]

    text = re.sub(
        r"^\*\*Last harvest:\*\*.*$",
        f"**Last harvest:** {NOW_STR}",
        text, count=1, flags=re.MULTILINE,
    )

    tmp = INDEX.with_suffix(".md.tmp")
    tmp.write_text(text)
    tmp.replace(INDEX)


def process_project(rpath: str, nick: str) -> dict | None:
    repo = Path(rpath)
    note = BRAIN / "projects" / f"{nick}.md"
    if not (repo / ".git").exists() or not note.exists():
        log(f"skip {nick}: missing git or note")
        return None

    state = get_state(repo)
    state["nick"] = nick
    state["tier"] = derive_tier(days_since(state["last_commit_date"]))

    text = note.read_text()
    fm, body = parse_frontmatter(text)

    fm["current_branch"] = state["current_branch"]
    fm["default_branch"] = state["default_branch"]
    if state["last_commit_date"]:
        fm["last_commit_date"] = state["last_commit_date"]
    if state["last_commit"]:
        fm["last_commit"] = state["last_commit"]
    fm["tier"] = state["tier"]
    fm["behind"] = str(state["behind"])
    if state["remote_url"]:
        fm["remote"] = state["remote_url"]

    body = update_status_and_local_lines(body, state)
    body = auto_prune_open_threads(body, state)
    body = update_harvester_block(body, state)

    new_text = serialize_frontmatter(fm) + body
    tmp = note.with_suffix(".md.tmp")
    tmp.write_text(new_text)
    tmp.replace(note)
    log(f"updated {nick}: local={state['current_branch']} remote={state['default_branch']} "
        f"behind={state['behind']} tier={state['tier']} fetched={state['fetched']}")
    return state


def main() -> None:
    log("=== harvest start ===")
    if not PROJECTS_TSV.exists():
        print(f"ERROR: {PROJECTS_TSV} not found", file=sys.stderr)
        sys.exit(1)

    states: list = []
    for line in PROJECTS_TSV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rpath, _tier_seed, nick = parts[0], parts[1], parts[2]
        try:
            s = process_project(rpath, nick)
            if s:
                states.append(s)
        except Exception:
            log(f"FAIL {nick}: {traceback.format_exc()}")

    try:
        regen_index(states)
    except Exception:
        log(f"FAIL regen_index: {traceback.format_exc()}")

    log("=== harvest end ===")
    print(f"harvest.py: done — {len(states)} project(s) updated; INDEX regenerated.")


if __name__ == "__main__":
    main()
