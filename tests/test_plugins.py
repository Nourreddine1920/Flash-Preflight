from pathlib import Path

import pytest

from preflight import parsers
from preflight.cli import main
from preflight.clocks import ClockError, register_clock_solver, solve
from preflight.clocks import _SOLVERS
from preflight.findings import Finding, Severity
from preflight.model import ClockTree, Config, SourceKind
from preflight.rules import registry
from preflight.rules.base import Applicability, Rule

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEP:
    def __init__(self, name, obj, value="fake_pkg.mod:Thing", raises=None):
        self.name, self.value, self._obj, self._raises = name, value, obj, raises

    def load(self):
        if self._raises:
            raise self._raises
        return self._obj


class ExtraRule(Rule):
    id = "PF900"
    name = "Extra"
    description = "test plugin rule"
    docs = "# PF900\n\nplugin docs\n"

    def applies_to(self, cfg):
        return Applicability(True)

    def check(self, cfg):
        return [
            Finding(
                rule_id=self.id, severity=Severity.WARNING, title="t", detail="d",
                loc=cfg.pins[0].loc, remediation="r",
            )
        ]


class CrashingRule(ExtraRule):
    id = "PF901"

    def check(self, cfg):
        raise RuntimeError("boom")


def use_rule_plugins(monkeypatch, *eps):
    monkeypatch.setattr(registry, "_plugin_entry_points", lambda: list(eps))


def ids():
    return [cls.id for cls, _ in registry.load_rule_classes()]


# ---- rule discovery -------------------------------------------------------


def test_builtins_load_without_plugins(monkeypatch):
    use_rule_plugins(monkeypatch)
    assert ids() == ["PF001", "PF002", "PF003", "PF004"]


def test_valid_plugin_is_appended_with_origin(monkeypatch):
    use_rule_plugins(monkeypatch, FakeEP("extra", ExtraRule))
    pairs = registry.load_rule_classes()
    assert [c.id for c, _ in pairs][-1] == "PF900"
    assert pairs[-1][1] == "plugin:fake_pkg"


@pytest.mark.parametrize(
    "ep",
    [
        FakeEP("notrule", object),
        FakeEP("broken", None, raises=ImportError("no module")),
        FakeEP("dup", type("Dup", (ExtraRule,), {"id": "PF001"})),
    ],
)
def test_bad_plugin_is_skipped_with_warning(monkeypatch, capsys, ep):
    use_rule_plugins(monkeypatch, ep)
    assert ids() == ["PF001", "PF002", "PF003", "PF004"]
    assert "skipping plugin rule" in capsys.readouterr().err


def test_from_options_reaches_builtins(monkeypatch):
    use_rule_plugins(monkeypatch)
    rules = registry.build_rules({"baud_tolerance_pct": 0.25, "nvic_checks": frozenset({"b1"})})
    by_id = {r.id: r for r in rules}
    assert by_id["PF002"].baud_tolerance_pct == 0.25
    assert by_id["PF004"].checks == frozenset({"b1"})


def test_only_filter(monkeypatch):
    use_rule_plugins(monkeypatch, FakeEP("extra", ExtraRule))
    assert [r.id for r in registry.build_rules({}, {"PF900"})] == ["PF900"]


# ---- CLI integration ------------------------------------------------------


def test_plugin_rule_runs_from_cli(monkeypatch, capsys):
    use_rule_plugins(monkeypatch, FakeEP("extra", ExtraRule))
    code = main([str(FIXTURES / "pf001_clean.ioc"), "--no-color", "--format", "json"])
    out = capsys.readouterr().out
    assert code == 1  # the plugin's WARNING trips --fail-on warning
    assert '"PF900"' in out


def test_crashing_rule_is_isolated_and_exits_two(monkeypatch, capsys):
    use_rule_plugins(monkeypatch, FakeEP("crash", CrashingRule))
    code = main([str(FIXTURES / "pf001_clean.ioc"), "--no-color"])
    captured = capsys.readouterr()
    assert code == 2
    assert "rule crashed" in captured.out  # shown as SKIP reason
    assert "PF001" in captured.out  # other rules still reported


def test_list_rules(monkeypatch, capsys):
    use_rule_plugins(monkeypatch, FakeEP("extra", ExtraRule))
    assert main(["--list-rules"]) == 0
    out = capsys.readouterr().out
    assert "PF001" in out and "[built-in]" in out and "PF900" in out and "[plugin:" in out


def test_no_paths_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


# ---- explain ---------------------------------------------------------------


@pytest.mark.parametrize("rule_id", ["PF001", "PF002", "PF003", "PF004"])
def test_every_builtin_rule_has_structured_docs(rule_id, capsys):
    assert main(["--explain", rule_id.lower()]) == 0  # case-insensitive
    out = capsys.readouterr().out
    for section in ("## What goes wrong", "## Example", "## How to fix"):
        assert section in out, f"{rule_id} doc missing {section}"


def test_explain_unknown_rule(capsys):
    assert main(["--explain", "PF999"]) == 2
    assert "unknown rule" in capsys.readouterr().err


def test_explain_plugin_uses_docs_attribute(monkeypatch, capsys):
    use_rule_plugins(monkeypatch, FakeEP("extra", ExtraRule))
    assert main(["--explain", "PF900"]) == 0
    assert "plugin docs" in capsys.readouterr().out


# ---- parser plugins ---------------------------------------------------------


class XyzParser:
    name = "xyz"

    def can_parse(self, path):
        return path.suffix == ".xyz"

    def parse(self, path, *, mcu_override=None, hse_hz_override=None):
        return Config(source_path=str(path), source_kind=SourceKind.OTHER)


def use_parser_plugins(monkeypatch, *eps):
    monkeypatch.setattr(parsers, "_plugin_entry_points", lambda: list(eps))


def test_plugin_parser_handles_unknown_suffix(monkeypatch, tmp_path):
    use_parser_plugins(monkeypatch, FakeEP("xyz", XyzParser))
    f = tmp_path / "board.xyz"
    f.write_text("anything")
    assert parsers.parse(f).source_kind is SourceKind.OTHER


def test_builtin_suffixes_never_reach_plugins(monkeypatch):
    def boom():
        raise AssertionError("plugins must not be consulted for .ioc")

    monkeypatch.setattr(parsers, "_plugin_entry_points", boom)
    assert parsers.parse(FIXTURES / "pf001_clean.ioc").source_kind is SourceKind.IOC


def test_bad_parser_plugin_skipped(monkeypatch, capsys, tmp_path):
    use_parser_plugins(monkeypatch, FakeEP("bad", object()))
    f = tmp_path / "a.ioc"
    f.write_text("Mcu.Family=STM32F4\n")
    assert parsers.load_plugin_parsers() == []
    assert "skipping plugin parser" in capsys.readouterr().err


def test_plugin_parser_end_to_end_skips_inapplicable_rules(monkeypatch, capsys, tmp_path):
    use_parser_plugins(monkeypatch, FakeEP("xyz", XyzParser))
    f = tmp_path / "board.xyz"
    f.write_text("anything")
    assert main([str(f), "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "PF003" in out


# ---- clock solver registry ---------------------------------------------------


def test_register_clock_solver():
    register_clock_solver("TESTFAM", lambda tree: tree)
    try:
        tree = ClockTree()
        assert solve("TESTFAM", tree) is tree
    finally:
        _SOLVERS.pop("TESTFAM", None)


def test_unregistered_family_still_raises():
    with pytest.raises(ClockError):
        solve("NOPE", ClockTree())
    with pytest.raises(ClockError):
        solve(None, ClockTree())
