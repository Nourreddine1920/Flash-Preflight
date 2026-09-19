"""PF004 - NVIC / interrupt priority conflict.

Sub-checks (PLAN.md §9.3), individually selectable via `checks`:
  a1  .c only: HAL_NVIC_EnableIRQ with no matching HAL_NVIC_SetPriority anywhere.
  a2  .ioc: enabled entry whose priority fields could not be parsed.
  b1  priority value out of range for the configured NVIC_PRIORITYGROUP_*.
  b2  two enabled, non-core IRQs tied at the same non-(0,0) priority.
  b3  SysTick is not the least-urgent (numerically largest preempt) interrupt.

Only fields 1-3 of the `NVIC.<IRQn>` colon-separated value are used -- fields
4-9 encode CubeMX-version-specific code-generation flags whose meaning is not
confidently known (PLAN.md R1) and are not read.
"""

from __future__ import annotations

import re
from collections import defaultdict

from preflight.findings import Finding, Severity
from preflight.model import Config, SourceKind
from preflight.rules.base import Applicability, Rule

DEFAULT_NVIC_CHECKS = frozenset({"a1", "a2", "b1", "b2", "b3"})

_GROUP_RE = re.compile(r"PRIORITYGROUP_(\d+)")


class NvicRule(Rule):
    id = "PF004"
    name = "NVIC / interrupt priority conflict"
    description = "Interrupts enabled without a valid, non-conflicting NVIC priority"

    def __init__(self, *, checks: frozenset[str] = DEFAULT_NVIC_CHECKS):
        self.checks = checks

    @classmethod
    def from_options(cls, options):
        return cls(checks=options.get("nvic_checks", DEFAULT_NVIC_CHECKS))

    def applies_to(self, cfg: Config) -> Applicability:
        if not cfg.interrupts:
            return Applicability(False, "no NVIC interrupt configuration found")
        return Applicability(True)

    def check(self, cfg: Config) -> list[Finding]:
        findings: list[Finding] = []

        if "a2" in self.checks and cfg.source_kind is SourceKind.IOC:
            findings.extend(self._check_a2_missing_priority(cfg))
        if "a1" in self.checks and cfg.code is not None:
            findings.extend(self._check_a1_enable_without_set(cfg))

        bits = cfg.mcu.nvic_prio_bits
        group_n = self._group_number(cfg)
        if "b1" in self.checks and bits is not None and group_n is not None:
            findings.extend(self._check_b1_out_of_range(cfg, bits, group_n))
        if "b2" in self.checks:
            findings.extend(self._check_b2_ties(cfg))
        if "b3" in self.checks:
            findings.extend(self._check_b3_systick(cfg))

        return findings

    def _group_number(self, cfg: Config) -> int | None:
        if cfg.priority_group is None:
            return None
        m = _GROUP_RE.search(cfg.priority_group)
        return int(m.group(1)) if m else None

    def _check_a2_missing_priority(self, cfg: Config) -> list[Finding]:
        findings = []
        for irqn, intr in sorted(cfg.interrupts.items()):
            if intr.enabled and (intr.preempt is None or intr.sub is None):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=Severity.WARNING,
                        title=f"{irqn} is enabled but its priority could not be read",
                        detail=(
                            f"{irqn} is enabled in this file but its NVIC priority "
                            f"fields could not be parsed, so its effective priority "
                            f"is unknown."
                        ),
                        loc=intr.loc,
                        evidence={"irqn": irqn, "mechanism": "a2"},
                        remediation="Regenerate the file from CubeMX so NVIC priority fields are well-formed.",
                    )
                )
        return findings

    def _check_a1_enable_without_set(self, cfg: Config) -> list[Finding]:
        findings = []
        code = cfg.code
        assert code is not None
        set_irqns = {e.irqn for e in code.nvic_set}
        seen: set[str] = set()
        for e in code.nvic_enable:
            if e.irqn in set_irqns or e.irqn in seen:
                continue
            seen.add(e.irqn)
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=Severity.ERROR,
                    title=f"{e.irqn} is enabled without an NVIC priority ever being set",
                    detail=(
                        f"HAL_NVIC_EnableIRQ({e.irqn}) is called but no "
                        f"HAL_NVIC_SetPriority({e.irqn}, ...) call exists anywhere in "
                        f"this file. The IRQ will run at its reset priority, which is "
                        f"the highest urgency level (0) -- this will preempt "
                        f"everything, including SysTick."
                    ),
                    loc=e.loc,
                    evidence={"irqn": e.irqn, "mechanism": "a1"},
                    remediation=f"Call HAL_NVIC_SetPriority({e.irqn}, <preempt>, <sub>) before enabling it.",
                )
            )
        return findings

    def _check_b1_out_of_range(self, cfg: Config, bits: int, group_n: int) -> list[Finding]:
        findings = []
        no_grouping = bits == 2  # Cortex-M0/M0+: no PRIGROUP field in hardware
        if no_grouping:
            preempt_bits, sub_bits = bits, 0
        else:
            preempt_bits = min(group_n, bits)
            sub_bits = bits - preempt_bits
        max_preempt = 2**preempt_bits - 1
        max_sub = 2**sub_bits - 1

        for irqn, intr in sorted(cfg.interrupts.items()):
            if not intr.enabled or intr.preempt is None or intr.sub is None:
                continue
            if intr.preempt > max_preempt:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=Severity.ERROR,
                        title=f"{irqn} preempt priority {intr.preempt} is out of range for {cfg.priority_group}",
                        detail=(
                            f"{cfg.priority_group} on this {bits}-bit-priority core "
                            f"allows preempt priorities 0..{max_preempt}. {irqn} is "
                            f"configured at preempt={intr.preempt}, which "
                            f"HAL_NVIC_SetPriority would either assert on or silently "
                            f"truncate."
                        ),
                        loc=intr.loc,
                        evidence={
                            "irqn": irqn,
                            "preempt": intr.preempt,
                            "sub": intr.sub,
                            "max_preempt": max_preempt,
                            "max_sub": max_sub,
                            "mechanism": "b1",
                        },
                        remediation=f"Set a preempt priority within 0..{max_preempt}.",
                    )
                )
            elif intr.sub > max_sub:
                severity = Severity.WARNING if no_grouping else Severity.ERROR
                extra = (
                    " This core has no NVIC priority grouping (Cortex-M0/M0+); the "
                    "sub-priority field is ignored by hardware."
                    if no_grouping
                    else ""
                )
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=severity,
                        title=f"{irqn} sub-priority {intr.sub} is out of range for {cfg.priority_group}",
                        detail=(
                            f"{cfg.priority_group} on this {bits}-bit-priority core "
                            f"allows sub-priorities 0..{max_sub}. {irqn} is configured "
                            f"at sub={intr.sub}.{extra}"
                        ),
                        loc=intr.loc,
                        evidence={
                            "irqn": irqn,
                            "preempt": intr.preempt,
                            "sub": intr.sub,
                            "max_preempt": max_preempt,
                            "max_sub": max_sub,
                            "mechanism": "b1",
                        },
                        remediation=f"Set a sub-priority within 0..{max_sub}.",
                    )
                )
        return findings

    def _check_b2_ties(self, cfg: Config) -> list[Finding]:
        groups: dict[tuple[int, int], list[str]] = defaultdict(list)
        for irqn, intr in cfg.interrupts.items():
            if (
                intr.enabled
                and not intr.is_core
                and intr.preempt is not None
                and intr.sub is not None
                and (intr.preempt, intr.sub) != (0, 0)
            ):
                groups[(intr.preempt, intr.sub)].append(irqn)

        findings = []
        for (preempt, sub), irqns in sorted(groups.items()):
            if len(irqns) <= 1:
                continue
            irqns_sorted = sorted(irqns)
            first = cfg.interrupts[irqns_sorted[0]]
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=Severity.WARNING,
                    title=f"{', '.join(irqns_sorted)} share priority {preempt}:{sub}",
                    detail=(
                        f"{', '.join(irqns_sorted)} are all configured at "
                        f"preempt={preempt}, sub={sub}. Since a non-default priority "
                        f"was deliberately chosen, this tie is likely an oversight -- "
                        f"with equal priority neither interrupt can preempt the "
                        f"other, and arbitration falls back to IRQ number."
                    ),
                    loc=first.loc,
                    evidence={"irqns": irqns_sorted, "preempt": preempt, "sub": sub, "mechanism": "b2"},
                    remediation="Assign distinct priorities if these interrupts need deterministic arbitration.",
                )
            )
        return findings

    def _check_b3_systick(self, cfg: Config) -> list[Finding]:
        systick = cfg.interrupts.get("SysTick_IRQn")
        if systick is None or not systick.enabled or systick.preempt is None:
            return []

        others = [
            intr
            for irqn, intr in cfg.interrupts.items()
            if intr.enabled and not intr.is_core and intr.preempt is not None
        ]
        if not others:
            return []

        max_other_preempt = max(o.preempt for o in others)
        if systick.preempt > max_other_preempt:
            return []

        offenders = sorted(
            irqn
            for irqn, intr in cfg.interrupts.items()
            if intr.enabled and not intr.is_core and intr.preempt == max_other_preempt
        )
        return [
            Finding(
                rule_id=self.id,
                severity=Severity.WARNING,
                title="SysTick is not the least-urgent enabled interrupt",
                detail=(
                    f"SysTick_IRQn has preempt priority {systick.preempt}, but "
                    f"{', '.join(offenders)} has an equal-or-higher urgency preempt "
                    f"priority ({max_other_preempt}). HAL_Delay() spins on a counter "
                    f"that only advances inside SysTick_Handler; any ISR at this "
                    f"urgency level that calls HAL_Delay() will hang forever, "
                    f"because SysTick can never preempt it to advance the counter."
                ),
                loc=systick.loc,
                evidence={
                    "systick_preempt": systick.preempt,
                    "max_other_preempt": max_other_preempt,
                    "offenders": offenders,
                    "mechanism": "b3",
                },
                remediation=(
                    "Give SysTick the numerically largest (least urgent) preempt "
                    "priority, or avoid calling HAL_Delay() from higher-priority ISRs."
                ),
            )
        ]
