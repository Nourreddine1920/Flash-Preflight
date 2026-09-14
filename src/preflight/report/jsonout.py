"""Machine-readable JSON report (PLAN-PHASE2.md §1).

`findings[]` is flat and self-contained (each entry carries its own
`rule_id`) so `jq '.findings[]'` works without walking a nested structure.
`files[]` separately carries per-rule PASS/FAIL/SKIPPED status -- "PF003 was
skipped because this is a .ioc file" is information a flat findings list has
no place for, and it's part of Preflight's product promise that all four
rules are always reported.

Field names are chosen to make a future SARIF exporter a rename, not a
rewrite -- see PLAN-PHASE2.md §1.3 for the mapping table.
"""

from __future__ import annotations

import json

from preflight.findings import Finding, Loc, RuleResult, Severity, Status
from preflight.model import Config

SCHEMA_VERSION = "1.0"


def _location_dict(loc: Loc) -> dict:
    d: dict = {"file": loc.file, "line": loc.line}
    if loc.key is not None:
        d["key"] = loc.key
    return d


def _finding_dict(rule_id: str, rule_name: str, f: Finding) -> dict:
    return {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "severity": f.severity.name.lower(),
        "title": f.title,
        "detail": f.detail,
        "location": _location_dict(f.loc),
        "evidence": f.evidence,
        "remediation": f.remediation,
    }


def build(files: list[tuple[Config, list[RuleResult]]], *, version: str = "0.1.0") -> dict:
    all_findings: list[dict] = []
    file_dicts: list[dict] = []

    total_errors = 0
    total_warnings = 0
    total_info = 0
    rules_run = 0
    rules_skipped = 0

    for cfg, results in files:
        rule_summaries = []
        for r in results:
            if r.status is Status.SKIPPED:
                rules_skipped += 1
            else:
                rules_run += 1
                for f in r.findings:
                    if f.severity is Severity.ERROR:
                        total_errors += 1
                    elif f.severity is Severity.WARNING:
                        total_warnings += 1
                    elif f.severity is Severity.INFO:
                        total_info += 1
                    all_findings.append(_finding_dict(r.rule_id, r.rule_name, f))

            rule_summaries.append(
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "status": r.status.value,
                    "skip_reason": r.skip_reason,
                    "finding_count": len(r.findings),
                }
            )

        file_dicts.append(
            {
                "source": cfg.source_path,
                "mcu": {
                    "family": cfg.mcu.family,
                    "raw_name": cfg.mcu.raw_name,
                    "core": cfg.mcu.core,
                },
                "rules": rule_summaries,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "preflight", "version": version},
        "findings": all_findings,
        "files": file_dicts,
        "summary": {
            "files_scanned": len(files),
            "errors": total_errors,
            "warnings": total_warnings,
            "info": total_info,
            "rules_run": rules_run,
            "rules_skipped": rules_skipped,
        },
    }


def render(files: list[tuple[Config, list[RuleResult]]], *, version: str = "0.1.0") -> str:
    return json.dumps(build(files, version=version), indent=2)
