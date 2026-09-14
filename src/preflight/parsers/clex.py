"""Stage 1/2 of the C parsing pipeline (PLAN.md §2.3).

Stage 1 (`strip_and_index`) is a real character-by-character scanner, not a
regex: it walks the source tracking whether it is inside code, a line
comment, a block comment, a string literal, or a char literal, and replaces
everything but code with spaces -- same length output, so offsets (and thus
line numbers) never shift. Regex cannot safely do this (it can't tell
whether a `/*` inside a string starts a comment, or a `"` inside a comment
starts a string); this scanner can, because it tracks state honestly.

It also blanks the bodies of literal `#if 0 ... #endif` blocks. Any other
conditional compilation (`#ifdef`, `#elif <cond>`, `#if <cond other than 0>`)
is left alone -- its branches are assumed live, and the caller is told how
many such conditionals it did not evaluate so it can surface that as an
INFO diagnostic.

Stage 2 (`split_functions`) finds function definitions with a regex anchored
at column 0 over the now-safe stripped text, then brace-matches from each
`{` to find the body end.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from preflight.model import CFunction

_CODE, _LINE_COMMENT, _BLOCK_COMMENT, _STRING, _CHAR = range(5)

_DIRECTIVE_RE = re.compile(r"^([ \t]*)#[ \t]*(if|ifdef|ifndef|elif|else|endif)\b(.*)$")

FUNC_HEADER = re.compile(
    r"^[ \t]*(?:(?:static|inline|__weak|extern|const|volatile|unsigned|signed)\s+)*"
    r"(?P<ret>[A-Za-z_]\w*)(?:[\s*]+)"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<params>[^;{)]*)\)\s*"
    r"(?:__attribute__\s*\(\([^)]*\)\)\s*)?"
    r"\{",
    re.MULTILINE,
)


@dataclass(frozen=True)
class StrippedSource:
    original: str
    stripped: str
    newline_offsets: list[int]
    conditionals_not_evaluated: int

    def line_for_offset(self, offset: int) -> int:
        return bisect.bisect_left(self.newline_offsets, offset) + 1


def _strip_comments_and_strings(src: str) -> str:
    out = list(src)
    n = len(src)
    state = _CODE
    i = 0
    while i < n:
        c = src[i]

        if state == _CODE:
            if c == "/" and i + 1 < n and src[i + 1] == "/":
                out[i] = " "
                out[i + 1] = " "
                state = _LINE_COMMENT
                i += 2
                continue
            if c == "/" and i + 1 < n and src[i + 1] == "*":
                out[i] = " "
                out[i + 1] = " "
                state = _BLOCK_COMMENT
                i += 2
                continue
            if c == '"':
                out[i] = " "
                state = _STRING
                i += 1
                continue
            if c == "'":
                out[i] = " "
                state = _CHAR
                i += 1
                continue
            i += 1
            continue

        if state == _LINE_COMMENT:
            if c == "\\" and i + 1 < n and src[i + 1] == "\n":
                out[i] = " "
                i += 2  # consume backslash + newline together; stay in LINE_COMMENT
                continue
            if c == "\n":
                state = _CODE
                i += 1
                continue
            out[i] = " "
            i += 1
            continue

        if state == _BLOCK_COMMENT:
            if c == "*" and i + 1 < n and src[i + 1] == "/":
                out[i] = " "
                out[i + 1] = " "
                state = _CODE
                i += 2
                continue
            if c == "\n":
                i += 1  # keep newline for line counting
                continue
            out[i] = " "
            i += 1
            continue

        if state in (_STRING, _CHAR):
            closing = '"' if state == _STRING else "'"
            if c == "\\" and i + 1 < n:
                out[i] = " "
                out[i + 1] = src[i + 1] if src[i + 1] == "\n" else " "
                i += 2
                continue
            if c == closing:
                out[i] = " "
                state = _CODE
                i += 1
                continue
            if c == "\n":
                # Unterminated literal reaching EOL: bail out defensively.
                state = _CODE
                i += 1
                continue
            out[i] = " "
            i += 1
            continue

    return "".join(out)


def _blank_if0_blocks(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    out_lines = list(lines)
    stack: list[dict] = []
    current_blank = False
    not_evaluated = 0

    for idx, line in enumerate(lines):
        m = _DIRECTIVE_RE.match(line)
        if m:
            directive = m.group(2)
            rest = m.group(3).strip()

            if directive == "if":
                is_if0 = rest == "0"
                if not is_if0:
                    not_evaluated += 1
                stack.append({"is_if0": is_if0, "parent_blank": current_blank, "toggled": False})
                current_blank = current_blank or is_if0
            elif directive in ("ifdef", "ifndef"):
                not_evaluated += 1
                stack.append({"is_if0": False, "parent_blank": current_blank, "toggled": False})
            elif directive == "elif":
                not_evaluated += 1
                if stack:
                    frame = stack[-1]
                    frame["is_if0"] = False
                    current_blank = frame["parent_blank"]
            elif directive == "else":
                if stack:
                    frame = stack[-1]
                    current_blank = frame["parent_blank"]
                    frame["toggled"] = True
            elif directive == "endif":
                if stack:
                    frame = stack.pop()
                    current_blank = frame["parent_blank"]
            continue

        if current_blank and line.strip():
            out_lines[idx] = " " * len(line)

    return "\n".join(out_lines), not_evaluated


def strip_and_index(src: str) -> StrippedSource:
    stage1 = _strip_comments_and_strings(src)
    stage2, not_evaluated = _blank_if0_blocks(stage1)
    newline_offsets = [i for i, c in enumerate(stage2) if c == "\n"]
    return StrippedSource(
        original=src,
        stripped=stage2,
        newline_offsets=newline_offsets,
        conditionals_not_evaluated=not_evaluated,
    )


def _find_matching_brace(text: str, open_pos: int) -> int:
    depth = 1
    i = open_pos + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def split_functions(stripped: StrippedSource) -> list[CFunction]:
    text = stripped.stripped
    functions: list[CFunction] = []
    for m in FUNC_HEADER.finditer(text):
        open_brace_pos = m.end() - 1
        close_brace_pos = _find_matching_brace(text, open_brace_pos)
        functions.append(
            CFunction(
                name=m.group("name"),
                start_offset=m.start(),
                body_start=open_brace_pos + 1,
                body_end=close_brace_pos,
                start_line=stripped.line_for_offset(m.start()),
            )
        )
    return functions
