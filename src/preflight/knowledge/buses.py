"""Which APB bus feeds each USART/UART instance.

F1 and F4 (and F2/F3/L1, which share the same simple topology) have no
per-USART clock mux -- the APB clock is the only source. Families with a
`RCC.USARTxClockSelection` mux (F0/F3/F7/L4/G0/G4/H7/...) are out of scope
for clock derivation (PLAN.md §6.3, §13 future work).
"""

from __future__ import annotations

F4_USART_BUS: dict[str, str] = {
    "USART1": "APB2",
    "USART6": "APB2",
    "USART2": "APB1",
    "USART3": "APB1",
    "UART4": "APB1",
    "UART5": "APB1",
    "UART7": "APB1",
    "UART8": "APB1",
}

F1_USART_BUS: dict[str, str] = {
    "USART1": "APB2",
    "USART2": "APB1",
    "USART3": "APB1",
    "UART4": "APB1",
    "UART5": "APB1",
}

BUS_BY_FAMILY: dict[str, dict[str, str]] = {
    "STM32F4": F4_USART_BUS,
    "STM32F2": F4_USART_BUS,
    "STM32F1": F1_USART_BUS,
    "STM32L1": F1_USART_BUS,
}

# Bus *placement* (which APB bus a USART/UART instance is wired to) is a
# fixed hardware fact shared by most STM32 families following the "USART1 on
# APB2, everything else on APB1" convention -- true even for families whose
# exact PCLK *frequency* we cannot derive from first principles (they may
# have a `RCC.USARTxClockSelection` mux, but its default is still PCLK).
# Used only for the declared-frequency fallback (PLAN.md §6.5); never for
# PLL-based derivation, which stays restricted to DERIVABLE_FAMILIES.
_GENERIC_USART_BUS = {
    "USART1": "APB2",
    "USART6": "APB2",
    "USART2": "APB1",
    "USART3": "APB1",
    "USART4": "APB1",
    "USART5": "APB1",
    "UART4": "APB1",
    "UART5": "APB1",
    "UART7": "APB1",
    "UART8": "APB1",
}


def bus_for_usart(family: str | None, peripheral_name: str) -> str | None:
    if family is None:
        return None
    table = BUS_BY_FAMILY.get(family)
    if table is not None:
        return table.get(peripheral_name.upper())
    return _GENERIC_USART_BUS.get(peripheral_name.upper())
