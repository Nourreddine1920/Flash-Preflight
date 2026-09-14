from __future__ import annotations

from pathlib import Path

from preflight.model import Config, SourceKind


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


def parse(path: Path, *, mcu_override: str | None = None, hse_hz_override: int | None = None) -> Config:
    kind = detect_source_kind(path)
    if kind is SourceKind.IOC:
        from preflight.parsers.ioc import parse_ioc

        return parse_ioc(path)
    from preflight.parsers.cfile import parse_cfile

    return parse_cfile(path, mcu_override=mcu_override, hse_hz_override=hse_hz_override)
