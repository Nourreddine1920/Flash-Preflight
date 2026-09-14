"""Human-readable terminal report (PLAN.md §10.1)."""

from __future__ import annotations

import os
import shutil
import textwrap

from preflight.findings import RuleResult, Severity, Status
from preflight.model import Config

_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_SUMMARY_COL = 58


def _c(text: str, code: str, use_color: bool) -> str:
    return f"{code}{text}{_RESET}" if use_color else text


def _status_label(result: RuleResult, use_color: bool) -> str:
    if result.status is Status.PASS:
        return _c("PASS", _GREEN, use_color)
    if result.status is Status.SKIPPED:
        return _c("SKIP", _DIM, use_color)
    return _c("FAIL", _RED, use_color)


def _severity_label(sev: Severity, use_color: bool) -> str:
    if sev is Severity.ERROR:
        return _c("ERROR", _RED, use_color)
    if sev is Severity.WARNING:
        return _c("WARNING", _YELLOW, use_color)
    return _c("INFO", _DIM, use_color)


def render(
    cfg: Config,
    results: list[RuleResult],
    *,
    use_color: bool = True,
    width: int | None = None,
    verbose: bool = False,
    version: str = "0.1.0",
) -> str:
    term_width = width or min(shutil.get_terminal_size(fallback=(100, 24)).columns, 100)
    lines: list[str] = []

    mcu_desc = cfg.mcu.raw_name or cfg.mcu.family or "unknown MCU"
    family_note = f" ({cfg.mcu.family})" if cfg.mcu.family and cfg.mcu.family != mcu_desc else ""
    source_name = os.path.basename(cfg.source_path)
    lines.append(f"preflight {version} — {mcu_desc}{family_note} — {source_name}")
    lines.append("")

    for r in results:
        left = f"  {r.rule_id}  {r.rule_name} "
        dots_needed = max(_SUMMARY_COL - len(left), 3)
        summary_line = left + ("." * dots_needed) + " " + _status_label(r, use_color)
        if r.status is Status.FAIL:
            n = len(r.findings)
            summary_line += f"  {n} issue{'s' if n != 1 else ''}"
        elif r.status is Status.SKIPPED:
            summary_line += f"  ({r.skip_reason})"
        lines.append(summary_line)

    total_errors = 0
    total_warnings = 0
    rules_run = 0
    rules_skipped = 0

    for r in results:
        if r.status is Status.SKIPPED:
            rules_skipped += 1
            continue
        rules_run += 1
        for f in r.findings:
            if f.severity is Severity.ERROR:
                total_errors += 1
            elif f.severity is Severity.WARNING:
                total_warnings += 1

        if not r.findings:
            continue

        lines.append("")
        header = f"─── {r.rule_id}  {r.rule_name} "
        header += "─" * max(term_width - len(header), 0)
        lines.append(header)

        for f in r.findings:
            lines.append("")
            lines.append(f"  {_severity_label(f.severity, use_color)}  {f.title}")
            loc_str = f"{f.loc.file}:{f.loc.line}"
            if f.loc.key:
                loc_str += f"  ({f.loc.key})"
            lines.append(f"    {loc_str}")
            wrapped = textwrap.wrap(f.detail, width=max(term_width - 4, 40))
            for w in wrapped:
                lines.append(f"    {w}")
            if f.remediation:
                remediation_wrapped = textwrap.wrap(
                    f"→ {f.remediation}", width=max(term_width - 4, 40)
                )
                for w in remediation_wrapped:
                    lines.append(f"    {w}")

    if verbose and cfg.diagnostics:
        lines.append("")
        lines.append("─── diagnostics ─" + "─" * max(term_width - 16, 0))
        for d in cfg.diagnostics:
            loc_str = f"  ({d.loc.file}:{d.loc.line})" if d.loc else ""
            lines.append(f"  [{d.level.name}] {d.message}{loc_str}")

    lines.append("")
    error_word = "error" if total_errors == 1 else "errors"
    warning_word = "warning" if total_warnings == 1 else "warnings"
    summary = (
        f"{total_errors} {error_word}, {total_warnings} {warning_word} across "
        f"{len(results)} rules.  {rules_run} rules run, {rules_skipped} skipped."
    )
    lines.append(summary)

    return "\n".join(lines) + "\n"
