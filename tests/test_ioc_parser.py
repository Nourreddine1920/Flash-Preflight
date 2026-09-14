from pathlib import Path

from preflight.clocks import solve
from preflight.model import SourceKind
from preflight.parsers.ioc import parse_ioc

FIXTURES = Path(__file__).parent / "fixtures"


def test_mcu_info_parsed():
    cfg = parse_ioc(FIXTURES / "pf001_clean.ioc")
    assert cfg.source_kind is SourceKind.IOC
    assert cfg.mcu.family == "STM32F4"
    assert cfg.mcu.raw_name == "STM32F407VGTx"
    assert cfg.mcu.cpn == "STM32F407VGT6"
    assert cfg.mcu.core == "CM4"
    assert cfg.mcu.nvic_prio_bits == 4
    assert cfg.mcu.hsi_hz == 16_000_000
    assert cfg.mcu.usart_ip == "old"


def test_clean_pins_no_conflict_shape():
    cfg = parse_ioc(FIXTURES / "pf001_clean.ioc")
    canon = {p.canonical: p.signal for p in cfg.pins}
    assert canon["PA2"] == "USART2_TX"
    assert canon["PA3"] == "USART2_RX"
    assert canon["PD12"] == "GPIO_Output"
    # VP_SYS_VS_Systick is a virtual pin, not a physical one
    assert "VP_SYS_VS_Systick" not in {p.raw_name for p in cfg.pins}


def test_duplicate_signal_key_produces_two_pin_assignments():
    cfg = parse_ioc(FIXTURES / "pf001_broken_dup_signal.ioc")
    pa2_entries = [p for p in cfg.pins if p.canonical == "PA2"]
    assert len(pa2_entries) == 2
    assert {p.signal for p in pa2_entries} == {"USART2_TX", "S_TIM2_CH3"}
    assert {p.loc.line for p in pa2_entries} == {25, 29}


def test_alias_collision_same_canonical_different_raw_name():
    cfg = parse_ioc(FIXTURES / "pf001_broken_alias_collision.ioc")
    pc14_entries = [p for p in cfg.pins if p.canonical == "PC14"]
    raw_names = {p.raw_name for p in pc14_entries}
    assert raw_names == {"PC14-OSC32_IN", "PC14"}
    signals = {p.signal for p in pc14_entries}
    assert signals == {"RCC_OSC32_IN", "GPIO_Output"}


def test_signal_on_two_different_pins():
    cfg = parse_ioc(FIXTURES / "pf001_broken_signal_two_pins.ioc")
    tx_pins = {p.canonical for p in cfg.pins if p.signal == "USART2_TX"}
    assert tx_pins == {"PA2", "PD5"}


def test_stale_pin_raw_access():
    cfg = parse_ioc(FIXTURES / "pf001_broken_stale_pin.ioc")
    assert cfg.raw is not None
    assert cfg.raw.get("Mcu.PinsNb") == "3"
    pin_keys = cfg.raw.keys_with_prefix("Mcu.Pin")
    # Pin0..Pin3 (4 entries) plus PinsNb itself
    pin_entries = [e for e in pin_keys if e.key != "Mcu.PinsNb"]
    assert len(pin_entries) == 4
    assert any(p.canonical == "PE0" for p in cfg.pins)


def test_peripherals_parsed_with_ipparameters():
    cfg = parse_ioc(FIXTURES / "pf001_clean.ioc")
    usart2 = cfg.peripherals["USART2"]
    assert usart2.kind == "USART"
    assert usart2.instance == 2
    assert usart2.params["BaudRate"] == "115200"
    assert usart2.params["Mode"] == "MODE_TX_RX"
    assert "RCC" not in cfg.peripherals
    assert "NVIC" not in cfg.peripherals
    assert "SYS" not in cfg.peripherals


def test_clock_tree_f4_derivation_end_to_end():
    cfg = parse_ioc(FIXTURES / "pf002_clean.ioc")
    resolved = solve(cfg.mcu.family, cfg.clocks)
    assert resolved.sysclk_hz == 16_000_000
    assert resolved.pclk1_hz == 16_000_000
    assert resolved.declared["PCLK1"] == 16_000_000


def test_clock_tree_f4_pll_derivation_with_stale_declared():
    cfg = parse_ioc(FIXTURES / "pf002_broken_stale_declared.ioc")
    resolved = solve(cfg.mcu.family, cfg.clocks)
    assert resolved.pclk1_hz == 42_000_000  # derived, correct
    assert resolved.declared["PCLK1"] == 84_000_000  # stale, as recorded by CubeMX
    assert resolved.sysclk_hz == 168_000_000


def test_f103_clock_tree_and_bus():
    from preflight.knowledge.buses import bus_for_usart

    cfg = parse_ioc(FIXTURES / "f103_blinky.ioc")
    resolved = solve(cfg.mcu.family, cfg.clocks)
    assert resolved.sysclk_hz == 72_000_000
    assert resolved.pclk1_hz == 36_000_000
    assert resolved.pclk2_hz == 72_000_000
    assert bus_for_usart(cfg.mcu.family, "USART1") == "APB2"


def test_nvic_parsing_basic_fields():
    cfg = parse_ioc(FIXTURES / "pf004_clean.ioc")
    usart2_irq = cfg.interrupts["USART2_IRQn"]
    assert usart2_irq.enabled is True
    assert usart2_irq.preempt == 5
    assert usart2_irq.sub == 0
    assert usart2_irq.is_core is False
    systick = cfg.interrupts["SysTick_IRQn"]
    assert systick.is_core is True
    assert systick.preempt == 15
    assert cfg.priority_group == "NVIC_PRIORITYGROUP_4"


def test_l4_unsupported_family_raises_on_solve_but_declared_available():
    from preflight.clocks import ClockError

    cfg = parse_ioc(FIXTURES / "l476_unsupported.ioc")
    assert cfg.mcu.family == "STM32L4"
    try:
        solve(cfg.mcu.family, cfg.clocks)
        assert False, "expected ClockError for unsupported family"
    except ClockError:
        pass
    assert cfg.clocks.declared["PCLK1"] == 80_000_000


def test_empty_ioc_parses_without_pins_or_peripherals():
    cfg = parse_ioc(FIXTURES / "empty.ioc")
    assert cfg.pins == []
    assert cfg.peripherals == {}
    assert cfg.mcu.family == "STM32F4"


def test_malformed_ioc_does_not_raise():
    cfg = parse_ioc(FIXTURES / "malformed.ioc")
    assert cfg.mcu.family == "STM32F4"
