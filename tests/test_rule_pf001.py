from pathlib import Path

from preflight.findings import Severity, Status
from preflight.parsers.cfile import parse_cfile
from preflight.parsers.ioc import parse_ioc
from preflight.rules.pin_conflict import PinConflictRule

FIXTURES = Path(__file__).parent / "fixtures"


def _run(fixture_name):
    cfg = parse_ioc(FIXTURES / fixture_name)
    return PinConflictRule().run(cfg)


def test_c_source_msp_init_alternate_conflict():
    cfg = parse_cfile(FIXTURES / "pf001_broken_msp_af.c")
    result = PinConflictRule().run(cfg)
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].evidence["canonical_pin"] == "PA2"
    values = {a["value"] for a in errors[0].evidence["assignments"]}
    assert values == {"GPIO_AF7_USART2", "GPIO_AF1_TIM2"}


def test_clean_passes():
    result = _run("pf001_clean.ioc")
    assert result.status is Status.PASS
    assert result.findings == []


def test_duplicate_signal_key_mechanism_a():
    result = _run("pf001_broken_dup_signal.ioc")
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].evidence["mechanism"] == "a"
    assert errors[0].evidence["canonical_pin"] == "PA2"


def test_alias_collision_mechanism_b():
    result = _run("pf001_broken_alias_collision.ioc")
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].evidence["mechanism"] == "b"
    assert errors[0].evidence["canonical_pin"] == "PC14"


def test_signal_two_pins_mechanism_c():
    result = _run("pf001_broken_signal_two_pins.ioc")
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].evidence["mechanism"] == "c"
    assert errors[0].evidence["signal"] == "USART2_TX"
    assert set(p["canonical"] for p in errors[0].evidence["pins"]) == {"PA2", "PD5"}


def test_stale_pin_mechanism_d_is_warning_only():
    result = _run("pf001_broken_stale_pin.ioc")
    assert result.status is Status.FAIL
    assert all(f.severity is Severity.WARNING for f in result.findings)
    mechanisms = {f.evidence["mechanism"] for f in result.findings}
    assert mechanisms == {"d"}
    # both the PinsNb mismatch and the PE0 stale entry should be flagged
    assert len(result.findings) == 2


def test_gpio_signals_do_not_trigger_mechanism_c():
    # pf001_clean.ioc has GPIO_Output on PD12 only, no collision expected;
    # verify that a shared GPIO_ prefixed signal across pins is not flagged.
    cfg = parse_ioc(FIXTURES / "pf001_clean.ioc")
    from preflight.model import PinAssignment
    from dataclasses import replace

    extra_pin = PinAssignment(
        raw_name="PD13", port="D", number=13, signal="GPIO_Output", mode=None,
        label=None, alternate=None, owner=None,
        loc=cfg.pins[0].loc,
    )
    cfg2 = replace(cfg, pins=cfg.pins + [extra_pin])
    result = PinConflictRule().run(cfg2)
    # PD13 isn't enumerated in Mcu.Pin* so mechanism (d) still fires, but the
    # shared GPIO_Output signal itself must not trigger mechanism (c).
    mechanisms = {f.evidence["mechanism"] for f in result.findings}
    assert "c" not in mechanisms
