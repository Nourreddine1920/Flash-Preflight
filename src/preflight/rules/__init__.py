from __future__ import annotations

from preflight.rules.base import Applicability, Rule
from preflight.rules.clock_baud import ClockBaudRule
from preflight.rules.nvic import NvicRule
from preflight.rules.pin_conflict import PinConflictRule
from preflight.rules.uninit_peripheral import UninitPeripheralRule

# Explicit, ordered list -- no plugin discovery, no importlib scanning.
# cli.py iterates this (optionally filtered by --rule) and always reports
# on all four, including ones that end up SKIPPED.
ALL_RULES: list[Rule] = [
    PinConflictRule(),
    ClockBaudRule(),
    UninitPeripheralRule(),
    NvicRule(),
]

__all__ = ["ALL_RULES", "Rule", "Applicability"]
