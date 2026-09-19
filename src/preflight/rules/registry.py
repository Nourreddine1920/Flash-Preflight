"""Rule discovery: the four built-ins plus third-party plugins.

Plugins register through the `preflight.rules` entry-point group, e.g. in a
plugin package's pyproject.toml:

    [project.entry-points."preflight.rules"]
    my_rule = "my_pkg.rules:MyRule"

Entry points (rather than scanning a directory) are what pytest, flake8 and
similar tools use: a plugin is an ordinary pip-installable package, nothing
has to be copied into Preflight's own tree.

Built-ins are listed here directly, not via entry points, so the tool works
identically from a source checkout or a broken/stale install. A broken
plugin is skipped with a warning; it can never take the built-ins down.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from importlib.metadata import entry_points

from preflight.rules.base import Rule
from preflight.rules.clock_baud import ClockBaudRule
from preflight.rules.nvic import NvicRule
from preflight.rules.pin_conflict import PinConflictRule
from preflight.rules.uninit_peripheral import UninitPeripheralRule

ENTRY_POINT_GROUP = "preflight.rules"

BUILTIN_RULE_CLASSES: tuple[type[Rule], ...] = (
    PinConflictRule,
    ClockBaudRule,
    UninitPeripheralRule,
    NvicRule,
)


def _plugin_entry_points():
    return entry_points(group=ENTRY_POINT_GROUP)


def _warn(message: str) -> None:
    print(f"preflight: warning: {message}", file=sys.stderr)


def load_rule_classes() -> list[tuple[type[Rule], str]]:
    """Returns (rule class, origin) pairs: built-ins in order, then valid
    plugins sorted by id. Origin is "built-in" or "plugin:<distribution>"."""
    found: list[tuple[type[Rule], str]] = [(cls, "built-in") for cls in BUILTIN_RULE_CLASSES]
    taken = {cls.id for cls, _ in found}
    plugins: list[tuple[type[Rule], str]] = []

    for ep in _plugin_entry_points():
        try:
            cls = ep.load()
            if not (isinstance(cls, type) and issubclass(cls, Rule)):
                raise TypeError("not a subclass of preflight.rules.base.Rule")
            for attr in ("id", "name", "description"):
                if not isinstance(getattr(cls, attr, None), str):
                    raise TypeError(f"missing string class attribute {attr!r}")
            if cls.id in taken:
                raise ValueError(f"rule id {cls.id} is already registered")
        except Exception as exc:  # third-party code: never let it break the run
            _warn(f"skipping plugin rule {ep.name!r}: {exc}")
            continue
        taken.add(cls.id)
        plugins.append((cls, f"plugin:{ep.value.split(':')[0].split('.')[0]}"))

    plugins.sort(key=lambda pair: pair[0].id)
    return found + plugins


def build_rules(options: Mapping[str, object], only: set[str] | None = None) -> list[Rule]:
    """Instantiate every registered rule via `Rule.from_options`, optionally
    restricted to the given rule ids."""
    rules: list[Rule] = []
    for cls, origin in load_rule_classes():
        if only is not None and cls.id not in only:
            continue
        try:
            rules.append(cls.from_options(options))
        except Exception as exc:
            if origin == "built-in":
                raise
            _warn(f"skipping plugin rule {cls.id}: {exc}")
    return rules
