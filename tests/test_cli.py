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
    assert data["source"].endswith("pf002_broken_baud_error.ioc")
    assert data["summary"]["errors"] == 1
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
