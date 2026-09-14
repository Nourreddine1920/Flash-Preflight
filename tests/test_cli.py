import json
from pathlib import Path

import pytest

from preflight.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_file_exits_zero(capsys):
    code = main([str(FIXTURES / "pf001_clean.ioc"), "--no-color"])
    assert code == 0
    out = capsys.readouterr().out
    assert "PF001" in out
    assert "0 errors" in out


def test_broken_file_exits_one(capsys):
    code = main([str(FIXTURES / "pf001_broken_dup_signal.ioc"), "--no-color"])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "PA2" in out


def test_fail_on_never_always_exits_zero(capsys):
    code = main([str(FIXTURES / "pf001_broken_dup_signal.ioc"), "--no-color", "--fail-on", "never"])
    assert code == 0


def test_fail_on_error_ignores_warnings(capsys):
    # pf001_broken_stale_pin.ioc only produces WARNING-level findings
    code = main([str(FIXTURES / "pf001_broken_stale_pin.ioc"), "--no-color", "--fail-on", "error"])
    assert code == 0
    code_warn = main([str(FIXTURES / "pf001_broken_stale_pin.ioc"), "--no-color", "--fail-on", "warning"])
    assert code_warn == 1


def test_json_format_is_valid_json(capsys):
    code = main([str(FIXTURES / "pf002_broken_baud_error.ioc"), "--format", "json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema_version"] == "1.0"
    assert data["files"][0]["source"].endswith("pf002_broken_baud_error.ioc")
    assert data["summary"]["errors"] == 1
    assert data["findings"][0]["rule_id"] == "PF002"
    assert code == 1


def test_rule_filter_runs_only_selected_rule(capsys):
    code = main([str(FIXTURES / "pf001_broken_dup_signal.ioc"), "--no-color", "--rule", "PF002"])
    out = capsys.readouterr().out
    assert "PF001" not in out
    assert "PF002" in out


def test_missing_file_exits_two(capsys):
    code = main([str(FIXTURES / "does_not_exist.ioc")])
    assert code == 2


def test_all_four_rules_always_listed_for_ioc(capsys):
    main([str(FIXTURES / "pf001_clean.ioc"), "--no-color"])
    out = capsys.readouterr().out
    for rule_id in ["PF001", "PF002", "PF003", "PF004"]:
        assert rule_id in out


def test_nvic_checks_filter(capsys):
    code = main(
        [str(FIXTURES / "pf004_broken_systick.ioc"), "--no-color", "--nvic-checks", "b1,b2"]
    )
    out = capsys.readouterr().out
    assert code == 0  # b3 disabled, and this fixture has no b1/b2 issues


def test_verbose_shows_diagnostics(capsys):
    code = main([str(FIXTURES / "l476_unsupported.ioc"), "--no-color", "-v"])
    out = capsys.readouterr().out
    assert "diagnostics" in out.lower()


def test_nvic_checks_shorthand_a_expands_to_a1_a2():
    from preflight.cli import _expand_nvic_checks

    assert _expand_nvic_checks("a,b1") == frozenset({"a1", "a2", "b1"})
    assert _expand_nvic_checks(None) == frozenset({"a1", "a2", "b1", "b2", "b3"})
    assert _expand_nvic_checks("b3") == frozenset({"b3"})


# --------------------------------------------------------------------------
# Multi-file input (PLAN-PHASE2.md §2)
# --------------------------------------------------------------------------


def test_multiple_literal_paths_all_scanned(capsys):
    code = main(
        [
            str(FIXTURES / "pf001_clean.ioc"),
            str(FIXTURES / "pf001_broken_dup_signal.ioc"),
            "--no-color",
        ]
    )
    out = capsys.readouterr().out
    assert code == 1  # the second file has a finding
    assert out.count("pf001_clean.ioc") >= 1
    assert out.count("pf001_broken_dup_signal.ioc") >= 1
    assert "across 2 files" in out


def test_single_file_summary_wording_unchanged(capsys):
    # Single-file output must keep saying "across N rules", not "across 1 files".
    main([str(FIXTURES / "pf001_clean.ioc"), "--no-color"])
    out = capsys.readouterr().out
    assert "across 4 rules" in out
    assert "files" not in out.split("\n")[-2]  # the footer line


def test_glob_pattern_expanded(capsys):
    pattern = str(FIXTURES / "pf004_broken_*.ioc")
    code = main([pattern, "--no-color", "--rule", "PF004"])
    out = capsys.readouterr().out
    assert code == 1
    # all three pf004_broken_*.ioc fixtures should have been scanned
    assert out.count("preflight 0.1.0") == 3


def test_glob_matching_nothing_exits_two(capsys):
    code = main([str(FIXTURES / "no_such_prefix_*.ioc")])
    assert code == 2
    err = capsys.readouterr().err
    assert "no files matched" in err


def test_duplicate_paths_deduplicated(capsys):
    p = str(FIXTURES / "pf001_clean.ioc")
    main([p, p, "--no-color"])
    out = capsys.readouterr().out
    assert out.count("preflight 0.1.0") == 1


def test_one_missing_among_many_exits_two_but_reports_the_rest(capsys):
    code = main(
        [
            str(FIXTURES / "pf001_clean.ioc"),
            str(FIXTURES / "does_not_exist.ioc"),
            "--no-color",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "pf001_clean.ioc" in captured.out  # the good file was still scanned and reported
    assert "no such file" in captured.err or "does_not_exist" in captured.err
