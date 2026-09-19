import re
from pathlib import Path

import pytest

FINDINGS_DIR = Path(__file__).parent.parent / "docs" / "findings"
NOT_ENTRIES = {"README.md", "_template.md"}
REQUIRED = {
    "project", "repo_url", "analyzed_commit", "preflight_version",
    "rule_id", "verdict", "summary",
}
VERDICTS = {"confirmed-bug", "false-positive", "undetermined"}


def _front_matter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", "entry must start with a --- block"
    end = lines.index("---", 1) if "---" in lines[1:] else -1
    assert end > 0, "front matter block is not closed with ---"
    fields = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        assert sep, f"malformed line: {line!r}"
        fields[key.strip()] = value.strip()
    return fields


def _entries():
    return sorted(p for p in FINDINGS_DIR.glob("*.md") if p.name not in NOT_ENTRIES)


def test_log_infrastructure_exists():
    assert (FINDINGS_DIR / "README.md").is_file()
    assert (FINDINGS_DIR / "_template.md").is_file()


def test_template_lists_every_required_field():
    assert REQUIRED <= set(_front_matter(FINDINGS_DIR / "_template.md"))


@pytest.mark.parametrize("entry", _entries(), ids=lambda p: p.name)
def test_entry_is_well_formed(entry):
    f = _front_matter(entry)
    assert REQUIRED <= set(f), f"missing: {REQUIRED - set(f)}"
    assert f["repo_url"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{7,40}", f["analyzed_commit"])
    assert re.fullmatch(r"PF\d{3}", f["rule_id"])
    assert f["verdict"] in VERDICTS
    if "fix_url" in f:
        assert f["fix_url"].startswith("https://")
    assert re.match(r"\d{4}-\d{2}-", entry.name), "name must start with YYYY-MM-"
