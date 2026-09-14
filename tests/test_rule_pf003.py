from pathlib import Path

from preflight.findings import Severity, Status
from preflight.parsers.cfile import parse_cfile
from preflight.parsers.ioc import parse_ioc
from preflight.rules.uninit_peripheral import UninitPeripheralRule

FIXTURES = Path(__file__).parent / "fixtures"


def _run(fixture_name):
    cfg = parse_cfile(FIXTURES / fixture_name)
    return UninitPeripheralRule().run(cfg)


def test_clean_passes_with_wrapper_init_resolution():
    result = _run("pf003_clean.c")
    assert result.status is Status.PASS
    assert result.findings == []


def test_never_called_init_is_flagged_never_initialized():
    result = _run("pf003_broken_never_init.c")
    assert result.status is Status.FAIL
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.severity is Severity.ERROR
    assert "never initialized" in f.title
    assert f.evidence["handle"] == "hspi1"


def test_use_before_init_is_flagged():
    result = _run("pf003_broken_use_before_init.c")
    assert result.status is Status.FAIL
    assert len(result.findings) == 1
    f = result.findings[0]
    assert "before it is initialized" in f.title
    assert f.evidence["handle"] == "huart2"


def test_if0_block_init_does_not_count():
    result = _run("pf003_conditional.c")
    assert result.status is Status.FAIL
    assert len(result.findings) == 1
    assert "never initialized" in result.findings[0].title


def test_lexer_traps_produce_no_findings():
    result = _run("pf003_lexer_traps.c")
    assert result.status is Status.PASS


def test_skipped_for_ioc_source():
    cfg = parse_ioc(FIXTURES / "pf001_clean.ioc")
    result = UninitPeripheralRule().run(cfg)
    assert result.status is Status.SKIPPED
    assert "ioc" in result.skip_reason.lower() or ".ioc" in result.skip_reason


def test_diagnostic_added_when_findings_present():
    cfg = parse_cfile(FIXTURES / "pf003_broken_never_init.c")
    UninitPeripheralRule().run(cfg)
    assert any("linear" in d.message.lower() for d in cfg.diagnostics)
