from pathlib import Path

from preflight.findings import Severity, Status
from preflight.parsers.cfile import parse_cfile
from preflight.parsers.ioc import parse_ioc
from preflight.rules.clock_baud import ClockBaudRule

FIXTURES = Path(__file__).parent / "fixtures"


def _run(fixture_name, **kwargs):
    cfg = parse_ioc(FIXTURES / fixture_name)
    return ClockBaudRule(**kwargs).run(cfg)


def test_c_source_clean_with_hse_override():
    cfg = parse_cfile(FIXTURES / "pf002_clean.c", hse_hz_override=8_000_000)
    result = ClockBaudRule().run(cfg)
    assert result.status is Status.PASS


def test_c_source_skips_without_hse_value():
    cfg = parse_cfile(FIXTURES / "pf002_clean.c")
    result = ClockBaudRule().run(cfg)
    assert result.status is Status.SKIPPED


def test_clean_passes():
    result = _run("pf002_clean.ioc")
    assert result.status is Status.PASS
    assert result.findings == []


def test_baud_error_flagged():
    result = _run("pf002_broken_baud_error.ioc")
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].evidence["pclk_hz"] == 2_000_000
    assert errors[0].evidence["error_pct"] > 2.0


def test_unreachable_baud_flagged():
    result = _run("pf002_broken_unreachable.ioc")
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert "unreachable" in errors[0].title


def test_stale_declared_frequency_is_warning_but_baud_still_passes():
    result = _run("pf002_broken_stale_declared.ioc")
    assert result.status is Status.FAIL
    assert len(result.findings) == 1
    assert result.findings[0].severity is Severity.WARNING
    assert result.findings[0].evidence["derived_hz"] == 42_000_000
    assert result.findings[0].evidence["declared_hz"] == 84_000_000


def test_over8_clean_within_tolerance():
    result = _run("pf002_clean_over8.ioc")
    assert result.status is Status.PASS


def test_f103_usart1_clean():
    result = _run("f103_blinky.ioc")
    assert result.status is Status.PASS


def test_unsupported_family_falls_back_to_declared():
    result = _run("l476_unsupported.ioc")
    # PCLK1=80MHz declared, baud 115200: N = round(80e6/115200) = 694 -> actual 115273.7
    assert result.status is Status.PASS
    assert result.skip_reason is None


def test_unsupported_family_skips_when_declared_not_trusted():
    result = _run("l476_unsupported.ioc", trust_declared_clocks=False)
    assert result.status is Status.SKIPPED
    assert "STM32L4" in result.skip_reason


def test_no_usart_peripherals_skips():
    from preflight.model import Config, SourceKind

    cfg = Config(source_path="empty.ioc", source_kind=SourceKind.IOC)
    result = ClockBaudRule().run(cfg)
    assert result.status is Status.SKIPPED
