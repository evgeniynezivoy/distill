from pathlib import Path
from index_touch import update_timestamps


def test_update_timestamps_replaces_existing_line(tmp_path):
    idx = tmp_path / "INDEX.md"
    idx.write_text(
        "# Brain — Index\n\n"
        "**Last harvest:** 2026-05-17 09:00:01\n"
        "**Last weekly review:** [[logs/weekly/2026-W20]]\n"
        "\n## Hot\n- foo\n"
    )
    update_timestamps(idx, harvest_ts="2026-05-18 09:00:30", daily_ts="2026-05-18 09:03:12")
    text = idx.read_text()
    assert "**Last harvest:** 2026-05-18 09:00:30" in text
    assert "2026-05-17" not in text
    assert "**Last daily synthesis:** 2026-05-18 09:03:12" in text


def test_update_timestamps_inserts_daily_line_when_absent(tmp_path):
    idx = tmp_path / "INDEX.md"
    idx.write_text(
        "# Brain — Index\n\n"
        "**Last harvest:** 2026-05-17 09:00:01\n"
        "\n## Hot\n"
    )
    update_timestamps(idx, harvest_ts="2026-05-18 09:00:30", daily_ts="2026-05-18 09:03:12")
    text = idx.read_text()
    assert "**Last daily synthesis:** 2026-05-18 09:03:12" in text
    # Daily line should be near Last harvest
    harvest_idx = text.index("**Last harvest:**")
    daily_idx = text.index("**Last daily synthesis:**")
    assert daily_idx > harvest_idx
    assert daily_idx - harvest_idx < 100
