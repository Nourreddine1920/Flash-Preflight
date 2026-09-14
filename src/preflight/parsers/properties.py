"""Hand-rolled reader for Java `Properties.load()` format, which is what
CubeMX `.ioc` files actually are: flat key=value text with backslash escaping
and line continuations. No sections, so `configparser` does not apply.

Diverges from Java on one point deliberately: duplicate keys are preserved in
file order rather than last-wins, because a duplicated key in an `.ioc` file
is itself evidence of a configuration conflict (see PF001).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_WS = " \t\f"
_UNESCAPE_SIMPLE = {"n": "\n", "r": "\r", "t": "\t", "f": "\f"}


def _count_trailing_backslashes(s: str) -> int:
    n = 0
    for ch in reversed(s):
        if ch == "\\":
            n += 1
        else:
            break
    return n


def _iter_logical_lines(text: str) -> Iterator[tuple[str, int]]:
    physical = text.split("\n")
    physical = [ln[:-1] if ln.endswith("\r") else ln for ln in physical]
    n = len(physical)
    i = 0
    while i < n:
        line_no = i + 1
        stripped = physical[i].lstrip(_WS)
        i += 1
        if stripped == "" or stripped[0] in "#!":
            continue

        logical = stripped
        while _count_trailing_backslashes(logical) % 2 == 1:
            logical = logical[:-1]
            if i >= n:
                break
            logical += physical[i].lstrip(_WS)
            i += 1
        yield logical, line_no


def _split_key_value(logical: str) -> tuple[str, str]:
    i = 0
    n = len(logical)
    key_chars: list[str] = []
    while i < n:
        ch = logical[i]
        if ch == "\\" and i + 1 < n:
            key_chars.append(ch)
            key_chars.append(logical[i + 1])
            i += 2
            continue
        if ch in "=:" or ch in _WS:
            break
        key_chars.append(ch)
        i += 1

    while i < n and logical[i] in _WS:
        i += 1
    if i < n and logical[i] in "=:":
        i += 1
        while i < n and logical[i] in _WS:
            i += 1

    return "".join(key_chars), logical[i:]


def _unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "u" and i + 6 <= n:
                hex_digits = s[i + 2 : i + 6]
                try:
                    out.append(chr(int(hex_digits, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(_UNESCAPE_SIMPLE.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class PropEntry:
    key: str
    value: str
    line: int


class PropertyFile:
    def __init__(self, entries: list[PropEntry]):
        self.entries = entries
        self._by_key: dict[str, list[PropEntry]] = {}
        self._by_key_lower: dict[str, list[PropEntry]] = {}
        for e in entries:
            self._by_key.setdefault(e.key, []).append(e)
            self._by_key_lower.setdefault(e.key.lower(), []).append(e)

    def get(self, key: str) -> str | None:
        lst = self._by_key.get(key)
        return lst[-1].value if lst else None

    def get_entry(self, key: str) -> PropEntry | None:
        lst = self._by_key.get(key)
        return lst[-1] if lst else None

    def get_all(self, key: str) -> list[PropEntry]:
        return list(self._by_key.get(key, []))

    def get_ci(self, key: str) -> str | None:
        lst = self._by_key_lower.get(key.lower())
        return lst[-1].value if lst else None

    def get_ci_entry(self, key: str) -> PropEntry | None:
        lst = self._by_key_lower.get(key.lower())
        return lst[-1] if lst else None

    def keys_with_prefix(self, prefix: str) -> list[PropEntry]:
        return [e for e in self.entries if e.key.startswith(prefix)]

    def duplicates(self) -> dict[str, list[PropEntry]]:
        return {k: v for k, v in self._by_key.items() if len(v) > 1}


def load(text: str) -> PropertyFile:
    entries = [
        PropEntry(key=_unescape(key_raw), value=_unescape(value_raw), line=line_no)
        for logical, line_no in _iter_logical_lines(text)
        for key_raw, value_raw in [_split_key_value(logical)]
    ]
    return PropertyFile(entries)


def load_file(path: str | Path) -> PropertyFile:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return load(text)
