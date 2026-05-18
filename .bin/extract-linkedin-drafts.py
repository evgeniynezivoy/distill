#!/usr/bin/env python3
"""extract-linkedin-drafts.py — после weekly-synthesis извлекает блоки ### из секции
## LinkedIn drafts текущего weekly-файла и сохраняет каждый как отдельный markdown
в ~/brain/linkedin/drafts/<YYYY-Www>-N-<slug>.md.

Idempotent: если файл уже существует, перезаписывает (assumes synthesis is canonical).
"""

from __future__ import annotations
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BRAIN = Path(os.environ.get("BRAIN_ROOT", str(Path.home() / "brain")))
DRAFTS = BRAIN / "linkedin" / "drafts"

WEEK = datetime.now().strftime("%G-W%V")
WEEKLY = BRAIN / "logs" / "weekly" / f"{WEEK}.md"


def slugify(text: str, maxlen: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", "-", text).lower()
    return text[:maxlen].rstrip("-") or "post"


def main() -> int:
    if not WEEKLY.exists():
        print(f"no weekly file: {WEEKLY}", file=sys.stderr)
        return 0

    text = WEEKLY.read_text()
    m = re.search(r"## LinkedIn drafts\n+(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if not m:
        print("no '## LinkedIn drafts' section в weekly")
        return 0

    section = m.group(1).strip()
    posts = [p.strip() for p in re.split(r"\n(?=###\s)", section) if p.strip().startswith("###")]

    if not posts:
        print("0 posts found в LinkedIn drafts section")
        return 0

    DRAFTS.mkdir(parents=True, exist_ok=True)
    count = 0
    for i, post in enumerate(posts, 1):
        head = post.split("\n", 1)[0]
        hook = re.sub(r"^###\s+", "", head).strip()
        slug = slugify(hook)
        out = DRAFTS / f"{WEEK}-{i}-{slug}.md"
        out.write_text(post + "\n")
        count += 1
        print(f"  ✓ {out.name}")

    print(f"extract-linkedin-drafts.py: {count} draft(s) → {DRAFTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
