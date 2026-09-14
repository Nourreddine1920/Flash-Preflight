from __future__ import annotations

import argparse
import glob as glob_module
import os
import sys
from pathlib import Path

from preflight import __version__
from preflight.findings import RuleResult, Severity
from preflight.model import Config
from preflight.parsers import parse
from preflight.report import jsonout, text
from preflight.rules.base import Rule
from preflight.rules.clock_baud import ClockBaudRule
from preflight.rules.nvic import DEFAULT_NVIC_CHECKS, NvicRule
from preflight.rules.pin_conflict import PinConflictRule
from preflight.rules.uninit_peripheral import UninitPeripheralRule

_SEVERITY_BY_NAME = {"info": Severity.INFO, "warning": Severity.WARNING, "error": Severity.ERROR}
_GLOB_CHARS = frozenset("*?[")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preflight",
        description="Offline static analyzer for STM32 firmware configuration bugs.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="path",
        help="One or more .ioc/.c files or glob patterns (e.g. '**/*.ioc') to scan",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on", choices=["info", "warning", "error", "never"], default="warning"
    )
    parser.add_argument(
        "--rule",
        action="append",
        dest="rules",
        metavar="PFxxx",
        help="Run only this rule (may be given multiple times)",
    )
    parser.add_argument(
        "--nvic-checks",
        default=None,
        help="Comma-separated PF004 sub-checks to run: a,b1,b2,b3 (default: all)",
    )
    parser.add_argument("--baud-tolerance-pct", type=float, default=1.0)
    parser.add_argument("--baud-error-pct", type=float, default=2.0)
    parser.add_argument("--mcu", default=None, help="Override MCU/family detection for .c files")
    parser.add_argument(
        "--hse-hz", type=int, default=None, help="Override/supply HSE frequency for .c files"
    )
    trust = parser.add_mutually_exclusive_group()
    trust.add_argument(
        "--trust-declared-clocks", dest="trust_declared_clocks", action="store_true", default=True
    )
    trust.add_argument(
        "--no-trust-declared-clocks", dest="trust_declared_clocks", action="store_false"
    )
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"preflight {__version__}")
    return parser


def _expand_nvic_checks(raw: str | None) -> frozenset[str]:
    if raw is None:
        return DEFAULT_NVIC_CHECKS
    checks: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token == "a":
            checks.update({"a1", "a2"})
        else:
            checks.add(token)
    return frozenset(checks)


def _is_glob(pattern: str) -> bool:
    return any(c in pattern for c in _GLOB_CHARS)


def _resolve_paths(raw_paths: list[str]) -> tuple[list[Path], list[str]]:
    """Expand globs (Windows shells don't) and literal paths.

    Returns (resolved_paths, error_messages). A literal path that doesn't
    exist, or a glob that matches nothing, is reported as an error rather
    than silently dropped -- a typo'd glob passing CI with zero files
    scanned is worse than a hard failure.
    """
    resolved: list[Path] = []
    errors: list[str] = []
    seen: set[str] = set()

    for raw in raw_paths:
        if _is_glob(raw):
            matches = sorted(glob_module.glob(raw, recursive=True))
            if not matches:
                errors.append(f"no files matched: {raw}")
                continue
            candidates = [Path(m) for m in matches if Path(m).is_file()]
        else:
            p = Path(raw)
            if not p.exists():
                errors.append(f"{raw}: no such file")
                continue
            candidates = [p]

        for p in candidates:
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                resolved.append(p)

    return resolved, errors


def _build_rules(args: argparse.Namespace) -> list[Rule]:
    rules: list[Rule] = [
        PinConflictRule(),
        ClockBaudRule(
            baud_tolerance_pct=args.baud_tolerance_pct,
            baud_error_pct=args.baud_error_pct,
            trust_declared_clocks=args.trust_declared_clocks,
        ),
        UninitPeripheralRule(),
        NvicRule(checks=_expand_nvic_checks(args.nvic_checks)),
    ]
    if args.rules:
        wanted = {r.upper() for r in args.rules}
        rules = [r for r in rules if r.id in wanted]
    return rules


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    # encode the box-drawing/arrow characters in the text report.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    parser = _build_parser()
    args = parser.parse_args(argv)

    resolved_paths, resolve_errors = _resolve_paths(args.paths)
    for msg in resolve_errors:
        print(f"preflight: error: {msg}", file=sys.stderr)

    if not resolved_paths:
        return 2

    rules = _build_rules(args)
    files_results: list[tuple[Config, list[RuleResult]]] = []
    had_parse_error = bool(resolve_errors)

    for path in resolved_paths:
        try:
            cfg = parse(path, mcu_override=args.mcu, hse_hz_override=args.hse_hz)
        except Exception as exc:  # CLI boundary: never crash the process on bad input
            print(f"preflight: error: could not parse {path}: {exc}", file=sys.stderr)
            had_parse_error = True
            continue
        results = [rule.run(cfg) for rule in rules]
        files_results.append((cfg, results))

    if not files_results:
        return 2

    use_color = not args.no_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ

    if args.format == "json":
        output = jsonout.render(files_results, version=__version__)
    else:
        output = text.render(
            files_results, use_color=use_color, verbose=args.verbose, version=__version__
        )
    print(output, end="")

    if had_parse_error:
        return 2

    if args.fail_on == "never":
        return 0
    threshold = _SEVERITY_BY_NAME[args.fail_on]
    for _cfg, results in files_results:
        for r in results:
            for f in r.findings:
                if f.severity >= threshold:
                    return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
