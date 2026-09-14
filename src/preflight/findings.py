from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    ERROR = 30


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Loc:
    file: str
    line: int
    key: str | None = None


@dataclass(frozen=True)
class Diagnostic:
    level: Severity
    message: str
    loc: Loc | None = None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    title: str
    detail: str
    loc: Loc
    evidence: dict[str, object] = field(default_factory=dict)
    remediation: str = ""


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    rule_name: str
    status: Status
    findings: list[Finding] = field(default_factory=list)
    skip_reason: str | None = None
