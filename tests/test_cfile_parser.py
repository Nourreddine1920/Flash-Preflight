from pathlib import Path

from preflight.model import SourceKind
from preflight.parsers.cfile import parse_cfile

FIXTURES = Path(__file__).parent / "fixtures"


def test_family_detected_from_include():
    cfg = parse_cfile(FIXTURES / "pf003_clean.c")
    assert cfg.source_kind is SourceKind.CFILE
    assert cfg.mcu.family == "STM32F4"
    assert cfg.mcu.core == "CM4"


def test_mcu_override_takes_precedence():
    cfg = parse_cfile(FIXTURES / "pf004_broken_no_priority.c", mcu_override="STM32F1")
    assert cfg.mcu.family == "STM32F1"


def test_handles_and_instances_parsed():
    cfg = parse_cfile(FIXTURES / "pf003_clean.c")
    assert cfg.code.handles["huart2"].kind == "UART"
    assert cfg.code.handles["hspi1"].kind == "SPI"
    assert cfg.peripherals["USART2"].kind == "USART"
    assert cfg.peripherals["USART2"].instance == 2
    assert cfg.peripherals["SPI1"].instance == 1


def test_call_graph_resolves_wrapper_init():
    cfg = parse_cfile(FIXTURES / "pf003_clean.c")
    assert "MX_USART2_UART_Init" in cfg.code.call_graph["main"]
    assert "MX_SPI1_Init" in cfg.code.call_graph["main"]
    init_events = cfg.code.events["MX_USART2_UART_Init"]
    assert any(e.kind == "init" and e.handle == "huart2" for e in init_events)


def test_use_events_recorded():
    cfg = parse_cfile(FIXTURES / "pf003_clean.c")
    main_events = cfg.code.events["main"]
    use_handles = {e.handle for e in main_events if e.kind == "use"}
    assert use_handles == {"huart2", "hspi1"}


def test_msp_init_never_counts_as_init():
    cfg = parse_cfile(FIXTURES / "pf003_clean.c")
    msp_events = cfg.code.events.get("HAL_UART_MspInit", [])
    assert all(e.kind != "init" for e in msp_events)


def test_gpio_pins_parsed_with_alternate_and_owner():
    cfg = parse_cfile(FIXTURES / "pf001_broken_msp_af.c")
    pa2_pins = [p for p in cfg.pins if p.canonical == "PA2"]
    alternates = {p.alternate for p in pa2_pins}
    assert alternates == {"GPIO_AF7_USART2", "GPIO_AF1_TIM2"}
    owners = {p.owner for p in pa2_pins}
    assert owners == {"HAL_UART_MspInit", "HAL_TIM_MspPostInit"}


def test_gpio_pin_bitmask_expansion():
    cfg = parse_cfile(FIXTURES / "pf001_broken_msp_af.c")
    # GPIO_PIN_2|GPIO_PIN_3 in HAL_UART_MspInit should expand to both PA2 and PA3
    canonicals = {p.canonical for p in cfg.pins if p.owner == "HAL_UART_MspInit"}
    assert canonicals == {"PA2", "PA3"}


def test_clock_tree_fields_parsed_from_system_clock_config():
    cfg = parse_cfile(FIXTURES / "pf002_clean.c", hse_hz_override=8_000_000)
    assert cfg.clocks.pll.source == "HSE"
    assert cfg.clocks.pll.m == 8
    assert cfg.clocks.pll.n == 336
    assert cfg.clocks.pll.p == 2
    assert cfg.clocks.sysclk_source == "PLLCLK"
    assert cfg.clocks.apb1_div == 4
    assert cfg.clocks.apb2_div == 2


def test_clock_tree_end_to_end_derivation():
    from preflight.clocks import solve

    cfg = parse_cfile(FIXTURES / "pf002_clean.c", hse_hz_override=8_000_000)
    resolved = solve(cfg.mcu.family, cfg.clocks)
    assert resolved.sysclk_hz == 168_000_000
    assert resolved.pclk1_hz == 42_000_000
    assert resolved.pclk2_hz == 84_000_000


def test_hse_define_is_read_when_present():
    from preflight.parsers.cfile import _HSE_DEFINE_RE

    assert _HSE_DEFINE_RE.search("#define HSE_VALUE ((uint32_t)8000000U)").group("value") == "8000000"
    assert _HSE_DEFINE_RE.search("#define HSE_VALUE 25000000").group("value") == "25000000"


def test_nvic_calls_parsed():
    cfg = parse_cfile(FIXTURES / "pf004_clean.c")
    assert cfg.priority_group == "NVIC_PRIORITYGROUP_4"
    assert cfg.interrupts["USART2_IRQn"].enabled
    assert cfg.interrupts["USART2_IRQn"].preempt == 5
    assert cfg.interrupts["TIM2_IRQn"].preempt == 6


def test_enable_without_set_priority_recorded():
    cfg = parse_cfile(FIXTURES / "pf004_broken_no_priority.c")
    tim2 = cfg.interrupts["TIM2_IRQn"]
    assert tim2.enabled
    assert tim2.preempt is None
    assert tim2.sub is None


def test_no_family_detected_without_include_or_override(tmp_path):
    from preflight.findings import Severity

    src = tmp_path / "no_include.c"
    src.write_text("void foo(void) {\n}\n")
    cfg = parse_cfile(src)
    assert cfg.mcu.family is None
    assert any(d.level is Severity.INFO and "family" in d.message for d in cfg.diagnostics)
