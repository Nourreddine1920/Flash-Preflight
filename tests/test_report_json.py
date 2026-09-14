from pathlib import Path

from preflight.findings import Status
from preflight.parsers.ioc import parse_ioc
from preflight.report import jsonout
from preflight.rules import ALL_RULES

FIXTURES = Path(__file__).parent / "fixtures"


def _run_all(fixture_name):
    cfg = parse_ioc(FIXTURES / fixture_name)
    results = [rule.run(cfg) for rule in ALL_RULES]
    return cfg, results


def test_schema_version_present():
    doc = jsonout.build([_run_all("pf001_broken_dup_signal.ioc")])
    assert doc["schema_version"] == "1.0"
    assert doc["tool"]["name"] == "preflight"


def test_findings_are_flat_and_self_contained():
    doc = jsonout.build([_run_all("pf001_broken_dup_signal.ioc")])
    assert len(doc["findings"]) == 1
    f = doc["findings"][0]
    assert f["rule_id"] == "PF001"
    assert f["rule_name"] == "Pin conflict"
    assert f["severity"] == "error"
    assert "location" in f and "file" in f["location"] and "line" in f["location"]
    assert "loc" not in f  # renamed at serialization boundary, not left as an alias


def test_skipped_rule_appears_in_files_with_reason():
    doc = jsonout.build([_run_all("pf001_clean.ioc")])
    rules = {r["rule_id"]: r for r in doc["files"][0]["rules"]}
    assert rules["PF003"]["status"] == "skipped"
    assert rules["PF003"]["skip_reason"]
    assert rules["PF003"]["finding_count"] == 0


def test_all_four_rules_always_listed_per_file():
    doc = jsonout.build([_run_all("pf001_clean.ioc")])
    rule_ids = {r["rule_id"] for r in doc["files"][0]["rules"]}
    assert rule_ids == {"PF001", "PF002", "PF003", "PF004"}


def test_summary_counts_match_findings():
    cfg, results = _run_all("pf002_broken_baud_error.ioc")
    doc = jsonout.build([(cfg, results)])
    errors_in_findings = sum(1 for f in doc["findings"] if f["severity"] == "error")
    warnings_in_findings = sum(1 for f in doc["findings"] if f["severity"] == "warning")
    assert doc["summary"]["errors"] == errors_in_findings
    assert doc["summary"]["warnings"] == warnings_in_findings


def test_multi_file_document_has_one_entry_per_file():
    doc = jsonout.build([_run_all("pf001_clean.ioc"), _run_all("pf001_broken_dup_signal.ioc")])
    assert doc["summary"]["files_scanned"] == 2
    assert len(doc["files"]) == 2
    sources = {f["source"] for f in doc["files"]}
    assert any(s.endswith("pf001_clean.ioc") for s in sources)
    assert any(s.endswith("pf001_broken_dup_signal.ioc") for s in sources)
    # findings from both files land in one flat list, disambiguated by location.file
    assert len(doc["findings"]) == 1


def test_mcu_info_present_per_file():
    doc = jsonout.build([_run_all("pf001_clean.ioc")])
    mcu = doc["files"][0]["mcu"]
    assert mcu["family"] == "STM32F4"
    assert mcu["core"] == "CM4"


def test_render_produces_valid_json_string():
    import json

    text = jsonout.render([_run_all("pf001_clean.ioc")])
    doc = json.loads(text)
    assert doc["schema_version"] == "1.0"
