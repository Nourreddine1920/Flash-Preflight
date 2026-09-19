from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from preflight.findings import Finding, RuleResult, Status
from preflight.model import Config


@dataclass(frozen=True)
class Applicability:
    runnable: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.runnable and self.reason is None:
            raise ValueError("reason is required when runnable is False")


class Rule(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]

    @classmethod
    def from_options(cls, options: Mapping[str, object]) -> Rule:
        """Factory the CLI uses to build a rule. Override to read CLI-driven
        options (thresholds etc.); the default ignores them, so a rule that
        needs no configuration only has to define `check` and `applies_to`."""
        return cls()

    @abstractmethod
    def applies_to(self, cfg: Config) -> Applicability: ...

    @abstractmethod
    def check(self, cfg: Config) -> list[Finding]: ...

    def run(self, cfg: Config) -> RuleResult:
        app = self.applies_to(cfg)
        if not app.runnable:
            return RuleResult(self.id, self.name, Status.SKIPPED, [], app.reason)
        findings = self.check(cfg)
        status = Status.FAIL if findings else Status.PASS
        return RuleResult(self.id, self.name, status, findings, None)
