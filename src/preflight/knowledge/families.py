"""MCU family facts: Cortex-M core, NVIC priority bits, default HSI frequency.

Clock-tree derivation (clocks.py) only supports STM32F1 and STM32F4 (see
PLAN.md §6.1) — the tables here are broader because PF004's NVIC range check
and PF001's pin logic are family-agnostic and should work for any family
CubeMX supports, even when PF002 has to skip or fall back to declared values.
"""

from __future__ import annotations

import re

# Cortex-M core per STM32 family. Not exhaustive of every STM32 line ever
# released; families absent here yield core=None and callers must degrade
# gracefully (see PF004 §9.2 in PLAN.md — unrecognized family -> SKIPPED).
CORE_BY_FAMILY: dict[str, str] = {
    "STM32F0": "CM0",
    "STM32G0": "CM0PLUS",
    "STM32C0": "CM0PLUS",
    "STM32L0": "CM0PLUS",
    "STM32F1": "CM3",
    "STM32F2": "CM3",
    "STM32L1": "CM3",
    "STM32F3": "CM4",
    "STM32F4": "CM4",
    "STM32L4": "CM4",
    "STM32G4": "CM4",
    "STM32WB": "CM4",
    "STM32F7": "CM7",
    "STM32H7": "CM7",
    "STM32L5": "CM33",
    "STM32U5": "CM33",
    "STM32H5": "CM33",
    "STM32WBA": "CM33",
    "STM32WL": "CM4",
}

# Cortex-M0 / M0+ implement 2 NVIC priority bits; M3/M4/M7/M33 implement 4.
# This is the coarse split PLAN.md §9.2 flags as [CONFIRM] for less-common
# lines (U5/H5/WBA) -- default to 4 and special-case the M0 cores.
_TWO_BIT_CORES = {"CM0", "CM0PLUS"}


def nvic_prio_bits_for_core(core: str | None) -> int | None:
    if core is None:
        return None
    return 2 if core in _TWO_BIT_CORES else 4


def nvic_prio_bits_for_family(family: str | None) -> int | None:
    return nvic_prio_bits_for_core(core_for_family(family))


def core_for_family(family: str | None) -> str | None:
    if family is None:
        return None
    return CORE_BY_FAMILY.get(family)


# Default HSI frequency per family, in Hz. Only STM32F1 (8 MHz) and STM32F4
# (16 MHz) are load-bearing for clock derivation; the rest are informational.
HSI_HZ_BY_FAMILY: dict[str, int] = {
    "STM32F0": 8_000_000,
    "STM32F1": 8_000_000,
    "STM32F2": 16_000_000,
    "STM32F3": 8_000_000,
    "STM32F4": 16_000_000,
    "STM32F7": 16_000_000,
    "STM32L0": 16_000_000,
    "STM32L1": 16_000_000,
    "STM32L4": 16_000_000,
    "STM32G0": 16_000_000,
    "STM32G4": 16_000_000,
    "STM32H7": 64_000_000,
    "STM32L5": 16_000_000,
    "STM32U5": 16_000_000,
    "STM32H5": 16_000_000,
    "STM32WB": 16_000_000,
    "STM32WL": 16_000_000,
}


def hsi_hz_for_family(family: str | None) -> int | None:
    if family is None:
        return None
    return HSI_HZ_BY_FAMILY.get(family)


# Families whose clock tree clocks.py can actually derive from PLL settings.
DERIVABLE_FAMILIES = {"STM32F1", "STM32F4"}

# Core exception IRQns that are always present regardless of family and must
# never be treated as ordinary peripheral interrupts by PF004.
CORE_IRQNS = {
    "NonMaskableInt_IRQn",
    "HardFault_IRQn",
    "MemoryManagement_IRQn",
    "BusFault_IRQn",
    "UsageFault_IRQn",
    "SVCall_IRQn",
    "DebugMonitor_IRQn",
    "PendSV_IRQn",
    "SysTick_IRQn",
}

_HEADER_RE = re.compile(r'#include\s*[<"]stm32(?P<fam>[a-z]\d)xx_hal\.h[>"]', re.IGNORECASE)


def family_from_header_include(text: str) -> str | None:
    m = _HEADER_RE.search(text)
    if not m:
        return None
    return "STM32" + m.group("fam").upper()


_MCU_NAME_RE = re.compile(r"STM32(?P<fam>[A-Za-z]\d)")


def family_from_mcu_name(name: str | None) -> str | None:
    if not name:
        return None
    m = _MCU_NAME_RE.search(name)
    if not m:
        return None
    return "STM32" + m.group("fam").upper()
