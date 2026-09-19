"""Source detection and parsing.

Built-in parsers cover CubeMX `.ioc` and generated HAL `.c`. Another MCU
family plugs in through the `preflight.parsers` entry-point group (see
docs/adding-mcu-support.md): a parser turns its native config format into the
same `Config` the rules already consume.

Plugin parsers are only consulted for file types the built-ins don't claim,
so `.ioc`/`.c`/`.h` handling is identical with or without plugins installed.
"""

from __future__ import annotations

import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol

from preflight.model import Config, SourceKind

PARSER_ENTRY_POINT_GROUP = "preflight.parsers"
_BUILTIN_SUFFIXES = {".ioc", ".c", ".h"}


class Parser(Protocol):
    """What a plugin parser must provide (a class or an instance)."""

    name: str

    def can_parse(self, path: Path) -> bool: ...

    def parse(
        self, path: Path, *, mcu_override: str | None = None, hse_hz_override: int | None = None
    ) -> Config: ...


def detect_source_kind(path: Path) -> SourceKind:
    suffix = path.suffix.lower()
    if suffix == ".ioc":
        return SourceKind.IOC
    if suffix in (".c", ".h"):
        return SourceKind.CFILE

    head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    if "#MicroXplorer" in head or "\nMcu." in head or head.startswith("Mcu."):
        return SourceKind.IOC
    return SourceKind.CFILE


def _plugin_entry_points():
    return entry_points(group=PARSER_ENTRY_POINT_GROUP)


def load_plugin_parsers() -> list[Parser]:
    parsers: list[Parser] = []
    for ep in _plugin_entry_points():
        try:
            obj = ep.load()
            parser = obj() if isinstance(obj, type) else obj
            if not (
                isinstance(getattr(parser, "name", None), str)
                and callable(getattr(parser, "can_parse", None))
                and callable(getattr(parser, "parse", None))
            ):
                raise TypeError("expected an object with name, can_parse() and parse()")
        except Exception as exc:  # third-party code: never let it break the run
            print(f"preflight: warning: skipping plugin parser {ep.name!r}: {exc}", file=sys.stderr)
            continue
        parsers.append(parser)
    return sorted(parsers, key=lambda p: p.name)


def parse(
    path: Path, *, mcu_override: str | None = None, hse_hz_override: int | None = None
) -> Config:
    path = Path(path)
    if path.suffix.lower() not in _BUILTIN_SUFFIXES:
        for parser in load_plugin_parsers():
            if parser.can_parse(path):
                return parser.parse(
                    path, mcu_override=mcu_override, hse_hz_override=hse_hz_override
                )

    kind = detect_source_kind(path)
    if kind is SourceKind.IOC:
        from preflight.parsers.ioc import parse_ioc

        return parse_ioc(path)
    from preflight.parsers.cfile import parse_cfile

    return parse_cfile(path, mcu_override=mcu_override, hse_hz_override=hse_hz_override)
