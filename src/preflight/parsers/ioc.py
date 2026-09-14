"""Turn a parsed `.ioc` PropertyFile into a source-agnostic `Config`.

Two CubeMX quirks drive most of this module (PLAN.md §2.2):

  Gotcha A: a key absent from the file means "at its CubeMX/hardware default",
  never "unknown" or "disabled". Every RCC/NVIC field read here has an
  explicit default applied when absent.

  Gotcha B: `<PERIPH>.IPParameters` is the authoritative list of which
  parameters were explicitly set; a parameter not listed is at its default.
  We still fall back to scanning `<PERIPH>.*` keys when IPParameters itself
  is missing (older CubeMX exports).
"""

from __future__ import annotations

import re
from pathlib import Path

from preflight.findings import Diagnostic, Loc, Severity
from preflight.knowledge.families import (
    core_for_family,
    hsi_hz_for_family,
    nvic_prio_bits_for_family,
)
from preflight.knowledge.usart_ip import usart_ip_for_family
from preflight.model import (
    ClockTree,
    Config,
    Interrupt,
    McuInfo,
    Peripheral,
    PinAssignment,
    PllConfig,
    SourceKind,
)
from preflight.parsers.properties import PropertyFile, load_file

PIN_RE = re.compile(r"^P(?P<port>[A-Z])(?P<num>\d{1,2})(?![0-9])")

_NON_PERIPHERAL_IPS = {"RCC", "NVIC", "SYS", "CORTEX_M"}

_SYSCLK_SRC_MAP = {
    "RCC_SYSCLKSOURCE_HSI": "HSI",
    "RCC_SYSCLKSOURCE_HSE": "HSE",
    "RCC_SYSCLKSOURCE_PLLCLK": "PLLCLK",
}

_TRAILING_INT_RE = re.compile(r"(\d+)\s*$")
_PERIPH_NAME_RE = re.compile(r"^(?P<kind>[A-Za-z]+)(?P<num>\d*)$")


def parse_ioc(path: str | Path) -> Config:
    pf = load_file(path)
    diagnostics: list[Diagnostic] = []
    filename = str(path)

    mcu = _parse_mcu(pf)
    pins = _parse_pins(pf, filename)
    clocks = _parse_clocks(pf, mcu.family, filename, diagnostics)
    peripherals = _parse_peripherals(pf, filename)
    interrupts, priority_group = _parse_nvic(pf, filename, diagnostics)

    return Config(
        source_path=filename,
        source_kind=SourceKind.IOC,
        mcu=mcu,
        pins=pins,
        clocks=clocks,
        peripherals=peripherals,
        interrupts=interrupts,
        priority_group=priority_group,
        code=None,
        raw=pf,
        diagnostics=diagnostics,
    )


def _parse_mcu(pf: PropertyFile) -> McuInfo:
    family = pf.get("Mcu.Family")
    raw_name = pf.get("Mcu.UserName") or pf.get("Mcu.Name")
    cpn = pf.get("Mcu.CPN")
    core = core_for_family(family)
    return McuInfo(
        raw_name=raw_name,
        cpn=cpn,
        family=family,
        core=core,
        nvic_prio_bits=nvic_prio_bits_for_family(family),
        hsi_hz=hsi_hz_for_family(family),
        usart_ip=usart_ip_for_family(family),
    )


def _pin_prefixes(pf: PropertyFile) -> set[str]:
    prefixes: set[str] = set()
    for e in pf.entries:
        prefix, sep, _attr = e.key.partition(".")
        if sep and PIN_RE.match(prefix):
            prefixes.add(prefix)
    return prefixes


def _parse_pins(pf: PropertyFile, filename: str) -> list[PinAssignment]:
    pins: list[PinAssignment] = []
    for raw_name in sorted(_pin_prefixes(pf)):
        m = PIN_RE.match(raw_name)
        assert m is not None
        port, number = m.group("port"), int(m.group("num"))

        signal_entries = pf.get_all(f"{raw_name}.Signal")
        if not signal_entries:
            continue

        mode = pf.get(f"{raw_name}.Mode")
        label = pf.get(f"{raw_name}.GPIO_Label")

        for entry in signal_entries:
            pins.append(
                PinAssignment(
                    raw_name=raw_name,
                    port=port,
                    number=number,
                    signal=entry.value,
                    mode=mode,
                    label=label,
                    alternate=None,
                    owner=None,
                    loc=Loc(file=filename, line=entry.line, key=entry.key),
                )
            )
    return pins


def _div_from_enum(value: str | None) -> int | None:
    if value is None:
        return None
    m = _TRAILING_INT_RE.search(value)
    return int(m.group(1)) if m else None


def _parse_pll_f4(pf: PropertyFile) -> PllConfig:
    src_raw = pf.get_ci("RCC.PLLSourceVirtual")
    source = "HSE" if src_raw and "HSE" in src_raw.upper() else ("HSI" if src_raw else None)
    m_val = pf.get_ci("RCC.PLLM")
    n_val = pf.get_ci("RCC.PLLN")
    p_val = pf.get_ci("RCC.PLLP")
    q_val = pf.get_ci("RCC.PLLQ")
    return PllConfig(
        source=source,
        m=int(m_val) if m_val is not None else None,
        n=int(n_val) if n_val is not None else None,
        p=_div_from_enum(p_val),
        q=int(q_val) if q_val is not None else None,
    )


def _parse_pll_f1(pf: PropertyFile) -> PllConfig:
    src_raw = pf.get_ci("RCC.PLLSourceVirtual")
    prediv = None
    if src_raw and "HSI" in src_raw.upper():
        source = "HSI_DIV2"
    elif src_raw and "HSE" in src_raw.upper():
        source = "HSE"
        xtpre = pf.get_ci("RCC.PLLXTPRE")
        prediv = 2 if xtpre and "DIV2" in xtpre.upper() else 1
    else:
        source = None
    mul_val = pf.get_ci("RCC.PLLMUL")
    return PllConfig(source=source, mul=_div_from_enum(mul_val), prediv=prediv)


def _parse_clocks(
    pf: PropertyFile,
    family: str | None,
    filename: str,
    diagnostics: list[Diagnostic],
) -> ClockTree:
    hse_val = pf.get_ci("RCC.HSE_VALUE")
    hsi_val = pf.get_ci("RCC.HSI_VALUE")
    lse_val = pf.get_ci("RCC.LSE_VALUE")

    sysclk_src_raw = pf.get_ci("RCC.SYSCLKSource")
    sysclk_source = _SYSCLK_SRC_MAP.get(sysclk_src_raw, "HSI") if sysclk_src_raw else "HSI"

    ahb_div = _div_from_enum(pf.get_ci("RCC.AHBCLKDivider")) or 1
    apb1_div = _div_from_enum(pf.get_ci("RCC.APB1CLKDivider")) or 1
    apb2_div = _div_from_enum(pf.get_ci("RCC.APB2CLKDivider")) or 1

    if family == "STM32F4":
        pll = _parse_pll_f4(pf)
    elif family == "STM32F1":
        pll = _parse_pll_f1(pf)
    else:
        pll = PllConfig()
        diagnostics.append(
            Diagnostic(
                level=Severity.INFO,
                message=f"clock derivation not implemented for family {family!r}; "
                f"PF002 will use declared frequencies if available",
            )
        )

    declared: dict[str, int] = {}
    locs: dict[str, Loc] = {}
    for label, key in [
        ("SYSCLK", "RCC.SYSCLKFreq_VALUE"),
        ("HCLK", "RCC.HCLKFreq_Value"),
        ("PCLK1", "RCC.APB1Freq_Value"),
        ("PCLK2", "RCC.APB2Freq_Value"),
        ("AHB", "RCC.AHBFreq_Value"),
    ]:
        entry = pf.get_ci_entry(key)
        if entry is not None:
            try:
                declared[label] = int(entry.value)
                locs[label] = Loc(file=filename, line=entry.line, key=entry.key)
            except ValueError:
                diagnostics.append(
                    Diagnostic(
                        level=Severity.WARNING,
                        message=f"could not parse {entry.key}={entry.value!r} as an integer",
                        loc=Loc(file=filename, line=entry.line, key=entry.key),
                    )
                )

    return ClockTree(
        hse_hz=int(hse_val) if hse_val is not None else None,
        hsi_hz=int(hsi_val) if hsi_val is not None else None,
        lse_hz=int(lse_val) if lse_val is not None else None,
        pll=pll,
        sysclk_source=sysclk_source,
        ahb_div=ahb_div,
        apb1_div=apb1_div,
        apb2_div=apb2_div,
        declared=declared,
        locs=locs,
    )


def _parse_peripherals(pf: PropertyFile, filename: str) -> dict[str, Peripheral]:
    peripherals: dict[str, Peripheral] = {}
    ip_nb_val = pf.get("Mcu.IPNb")
    if ip_nb_val is None:
        return peripherals
    try:
        ip_nb = int(ip_nb_val)
    except ValueError:
        return peripherals

    names: list[str] = []
    for i in range(ip_nb):
        name = pf.get(f"Mcu.IP{i}")
        if name:
            names.append(name)

    for name in names:
        if name in _NON_PERIPHERAL_IPS:
            continue
        m = _PERIPH_NAME_RE.match(name)
        kind = m.group("kind") if m else name
        instance_str = m.group("num") if m else ""
        instance = int(instance_str) if instance_str else 0

        params: dict[str, str] = {}
        locs: dict[str, Loc] = {}
        ip_params_entry = pf.get_entry(f"{name}.IPParameters")
        if ip_params_entry is not None:
            param_names = [p.strip() for p in ip_params_entry.value.split(",") if p.strip()]
            for p in param_names:
                entry = pf.get_entry(f"{name}.{p}")
                if entry is not None:
                    params[p] = entry.value
                    locs[p] = Loc(file=filename, line=entry.line, key=entry.key)
        else:
            prefix = f"{name}."
            for e in pf.keys_with_prefix(prefix):
                attr = e.key[len(prefix) :]
                if attr == "IPParameters":
                    continue
                params[attr] = e.value
                locs[attr] = Loc(file=filename, line=e.line, key=e.key)

        peripherals[name] = Peripheral(name=name, kind=kind, instance=instance, params=params, locs=locs)

    return peripherals


def _parse_nvic(
    pf: PropertyFile, filename: str, diagnostics: list[Diagnostic]
) -> tuple[dict[str, Interrupt], str | None]:
    from preflight.knowledge.families import CORE_IRQNS

    interrupts: dict[str, Interrupt] = {}
    priority_group = pf.get("NVIC.PriorityGroup")

    for e in pf.keys_with_prefix("NVIC."):
        irqn = e.key[len("NVIC.") :]
        if not irqn.endswith("_IRQn"):
            continue

        fields = e.value.split(":")
        if len(fields) < 3 or fields[0] not in ("true", "false"):
            diagnostics.append(
                Diagnostic(
                    level=Severity.WARNING,
                    message=f"unparseable NVIC entry {e.key}={e.value!r}",
                    loc=Loc(file=filename, line=e.line, key=e.key),
                )
            )
            continue
        preempt: int | None
        sub: int | None
        try:
            preempt = int(fields[1])
            sub = int(fields[2])
        except ValueError:
            diagnostics.append(
                Diagnostic(
                    level=Severity.WARNING,
                    message=f"unparseable NVIC priority fields in {e.key}={e.value!r}",
                    loc=Loc(file=filename, line=e.line, key=e.key),
                )
            )
            preempt = None
            sub = None

        interrupts[irqn] = Interrupt(
            irqn=irqn,
            enabled=fields[0] == "true",
            preempt=preempt,
            sub=sub,
            is_core=irqn in CORE_IRQNS,
            loc=Loc(file=filename, line=e.line, key=e.key),
        )

    return interrupts, priority_group
