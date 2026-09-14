"""Which USART IP generation (BRR register layout) a family uses.

F1/F2/F4/L1 use the "old" IP with a fractional DIV_Mantissa/DIV_Fraction BRR
split. Every other family (F0/F3/F7/G0/G4/H7/L0/L4/L5/U5/C0/WB/WL/H5/WBA...)
uses the "new" flat-BRR IP. See PLAN.md §6.4 for the exact bit math that
depends on this classification.
"""

from __future__ import annotations

OLD_IP_FAMILIES = {"STM32F1", "STM32F2", "STM32F4", "STM32L1"}


def usart_ip_for_family(family: str | None) -> str | None:
    if family is None:
        return None
    return "old" if family in OLD_IP_FAMILIES else "new"
