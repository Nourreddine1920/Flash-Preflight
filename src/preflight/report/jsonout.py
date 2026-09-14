"""Machine-readable JSON report (PLAN.md §10.1)."""

from __future__ import annotations

import json

from preflight.findings import Finding, Loc, RuleResult, Severity, Status
from preflight.model import Config


def _loc_dict(loc: Loc) -> dict:
    d = {"file": loc.file, "line": loc.line}
    if loc.key is not None:
        d["key"] = loc.key
    return d


def _finding_dict(f: Finding) -> dict:
    return {
        "severity": f.severity.name.lower(),
        "title": f.title,
        "detail": f.detail,
        "loc": _loc_dict(f.loc),
        "evidence": f.evidence,
        "remediation": f.remediation,
    }


def build(cfg: Config, results: list[RuleResult], *, version: str = "0.1.0") -> dict:
    total_errors = 0
    total_warnings = 0
    rules_run = 0
    rules_skipped = 0

    result_dicts = []
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

        result_dicts.append(
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "status": r.status.value,
                "skip_reason": r.skip_reason,
                "findings": [_finding_dict(f) for f in r.findings],
            }
        )

    return {
        "preflight_version": version,
        "source": cfg.source_path,
        "mcu": {
            "family": cfg.mcu.family,
            "raw_name": cfg.mcu.raw_name,
            "core": cfg.mcu.core,
        },
        "results": result_dicts,
        "summary": {
            "errors": total_errors,
            "warnings": total_warnings,
            "rules_run": rules_run,
            "rules_skipped": rules_skipped,
        },
    }


def render(cfg: Config, results: list[RuleResult], *, version: str = "0.1.0") -> str:
    return json.dumps(build(cfg, results, version=version), indent=2)
