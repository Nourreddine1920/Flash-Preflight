from pathlib import Path

from preflight.findings import Severity, Status
from preflight.parsers.cfile import parse_cfile
from preflight.parsers.ioc import parse_ioc
from preflight.rules.nvic import NvicRule

FIXTURES = Path(__file__).parent / "fixtures"


def _run(fixture_name, **kwargs):
    cfg = parse_ioc(FIXTURES / fixture_name)
    return NvicRule(**kwargs).run(cfg)


def _run_c(fixture_name, **kwargs):
    cfg = parse_cfile(FIXTURES / fixture_name)
    return NvicRule(**kwargs).run(cfg)


def test_c_source_enable_without_priority_mechanism_a1():
    result = _run_c("pf004_broken_no_priority.c")
    assert result.status is Status.FAIL
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.severity is Severity.ERROR
    assert f.evidence["mechanism"] == "a1"
    assert f.evidence["irqn"] == "TIM2_IRQn"


def test_c_source_clean_passes():
    result = _run_c("pf004_clean.c")
    assert result.status is Status.PASS


def test_clean_passes():
    result = _run("pf004_clean.ioc")
    assert result.status is Status.PASS
    assert result.findings == []


def test_out_of_range_group2():
    result = _run("pf004_broken_out_of_range.ioc")
    assert result.status is Status.FAIL
    errors = [f for f in result.findings if f.severity is Severity.ERROR]
    assert len(errors) == 3
    irqns = {f.evidence["irqn"] for f in errors}
    assert irqns == {"USART2_IRQn", "TIM2_IRQn", "SysTick_IRQn"}
    assert all(f.evidence["mechanism"] == "b1" for f in errors)


def test_priority_tie_mechanism_b2():
    result = _run("pf004_broken_tie.ioc")
    assert result.status is Status.FAIL
    warnings = [f for f in result.findings if f.severity is Severity.WARNING]
    assert len(warnings) == 1
    assert warnings[0].evidence["mechanism"] == "b2"
    assert set(warnings[0].evidence["irqns"]) == {"USART2_IRQn", "TIM2_IRQn"}


def test_systick_not_least_urgent_mechanism_b3():
    result = _run("pf004_broken_systick.ioc")
    assert result.status is Status.FAIL
    b3 = [f for f in result.findings if f.evidence.get("mechanism") == "b3"]
    assert len(b3) == 1
    assert b3[0].severity is Severity.WARNING


def test_b3_can_be_disabled():
    from preflight.rules.nvic import DEFAULT_NVIC_CHECKS

    checks = DEFAULT_NVIC_CHECKS - {"b3"}
    result = _run("pf004_broken_systick.ioc", checks=frozenset(checks))
    mechanisms = {f.evidence.get("mechanism") for f in result.findings}
    assert "b3" not in mechanisms


def test_no_interrupts_skips():
    from preflight.model import Config, SourceKind

    cfg = Config(source_path="x.ioc", source_kind=SourceKind.IOC)
    result = NvicRule().run(cfg)
    assert result.status is Status.SKIPPED


def test_a2_missing_priority_fields():
    cfg = parse_ioc(FIXTURES / "pf004_clean.ioc")
    from dataclasses import replace

    from preflight.model import Interrupt

    broken = replace(
        cfg.interrupts["TIM2_IRQn"],
        preempt=None,
        sub=None,
    )
    new_interrupts = dict(cfg.interrupts)
    new_interrupts["TIM2_IRQn"] = broken
    cfg2 = replace(cfg, interrupts=new_interrupts)
    result = NvicRule().run(cfg2)
    a2 = [f for f in result.findings if f.evidence.get("mechanism") == "a2"]
    assert len(a2) == 1
    assert a2[0].severity is Severity.WARNING
