from __future__ import annotations

from preflight.rules.base import Applicability, Rule
from preflight.rules.registry import BUILTIN_RULE_CLASSES

# Default-configured instances of the built-in rules. The CLI does not use
# this list -- it goes through preflight.rules.registry so plugins and CLI
# options are honoured. Kept for programmatic use and tests.
ALL_RULES: list[Rule] = [cls() for cls in BUILTIN_RULE_CLASSES]

__all__ = ["ALL_RULES", "Rule", "Applicability"]
