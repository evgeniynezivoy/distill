"""Update **Last harvest:** and **Last daily synthesis:** lines in INDEX.md."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


HARVEST_RE = re.compile(r"^\*\*Last harvest:\*\*.*$", re.MULTILINE)
DAILY_RE = re.compile(r"^\*\*Last daily synthesis:\*\*.*$", re.MULTILINE)


def update_timestamps(index_path: Path, harvest_ts: str, daily_ts: str) -> None:
    text = index_path.read_text()

    new_harvest = f"**Last harvest:** {harvest_ts}"
    new_daily = f"**Last daily synthesis:** {daily_ts}"

    if HARVEST_RE.search(text):
        text = HARVEST_RE.sub(new_harvest, text, count=1)
    else:
        text = new_harvest + "\n" + text

    if DAILY_RE.search(text):
        text = DAILY_RE.sub(new_daily, text, count=1)
    else:
        # Insert daily line immediately after harvest line
        text = HARVEST_RE.sub(lambda m: m.group(0) + "\n" + new_daily, text, count=1)

    tmp = index_path.with_suffix(".md.tmp")
    tmp.write_text(text)
    os.replace(tmp, index_path)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", required=True, type=Path)
    parser.add_argument("--harvest-ts", default=None)
    parser.add_argument("--daily-ts", default=None)
    args = parser.parse_args(argv)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_timestamps(
        args.brain_root / "INDEX.md",
        harvest_ts=args.harvest_ts or now,
        daily_ts=args.daily_ts or now,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
