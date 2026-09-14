"""PF001 - Pin conflict.

Operates on `Config.pins`, which both parsers populate the same way, so the
four mechanisms below run identically regardless of source. Mechanisms (a)
and (b) collapse into one grouping check: `.ioc` pins carry a `signal`, `.c`
pins (from MspInit GPIO_Init calls) carry an `alternate` -- either one is the
"what is routed here" value, and two different values on one physical pin is
always a contradiction. Mechanism (c) is inherently `.ioc`-shaped (it needs a
named peripheral signal, which `.c` pins don't carry) and mechanism (d) is
`.ioc`-only by construction (it checks the `Mcu.PinN` enumeration).
"""

from __future__ import annotations

from collections import defaultdict

from preflight.findings import Finding, Loc, Severity
from preflight.model import Config, PinAssignment, SourceKind
from preflight.rules.base import Applicability, Rule

NON_EXCLUSIVE_SIGNAL_PREFIXES = ("GPIO_",)


def _is_exclusive_signal(signal: str | None) -> bool:
    if signal is None:
        return False
    return not any(signal.startswith(p) for p in NON_EXCLUSIVE_SIGNAL_PREFIXES)


def _conflict_value(pin: PinAssignment) -> str | None:
    return pin.alternate if pin.alternate is not None else pin.signal


class PinConflictRule(Rule):
    id = "PF001"
    name = "Pin conflict"
    description = "Two peripheral signals assigned to the same physical pin"

    def applies_to(self, cfg: Config) -> Applicability:
        return Applicability(runnable=True)

    def check(self, cfg: Config) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._check_same_pin_conflicts(cfg))
        findings.extend(self._check_same_signal_two_pins(cfg))
        if cfg.source_kind is SourceKind.IOC and cfg.raw is not None:
            findings.extend(self._check_stale_pins(cfg))
        return findings

    def _check_same_pin_conflicts(self, cfg: Config) -> list[Finding]:
        by_canonical: dict[str, list[PinAssignment]] = defaultdict(list)
        for pin in cfg.pins:
            by_canonical[pin.canonical].append(pin)

        findings: list[Finding] = []
        for canonical, group in sorted(by_canonical.items()):
            values = {_conflict_value(p) for p in group if _conflict_value(p) is not None}
            if len(values) <= 1:
                continue

            raw_names = {p.raw_name for p in group}
            mechanism = "a" if len(raw_names) == 1 else "b"
            group_sorted = sorted(group, key=lambda p: p.loc.line)
            evidence = {
                "canonical_pin": canonical,
                "assignments": [
                    {"raw_name": p.raw_name, "value": _conflict_value(p), "line": p.loc.line}
                    for p in group_sorted
                ],
                "mechanism": mechanism,
            }
            value_list = ", ".join(sorted(str(v) for v in values))
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=Severity.ERROR,
                    title=f"{canonical} is assigned to two different signals",
                    detail=(
                        f"Pin {canonical} has conflicting assignments in this file: "
                        f"{value_list}. A physical pin can only carry one signal or "
                        f"alternate function at a time, so whichever assignment is "
                        f"applied last will silently override the other(s)."
                    ),
                    loc=group_sorted[0].loc,
                    evidence=evidence,
                    remediation=(
                        "Remove or move one of these assignments so only one signal "
                        "is routed to this pin."
                    ),
                )
            )
        return findings

    def _check_same_signal_two_pins(self, cfg: Config) -> list[Finding]:
        by_signal: dict[str, list[PinAssignment]] = defaultdict(list)
        for pin in cfg.pins:
            if pin.signal is not None and _is_exclusive_signal(pin.signal):
                by_signal[pin.signal].append(pin)

        findings: list[Finding] = []
        for signal, group in sorted(by_signal.items()):
            canonicals = sorted({p.canonical for p in group})
            if len(canonicals) <= 1:
                continue

            group_sorted = sorted(group, key=lambda p: p.loc.line)
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=Severity.ERROR,
                    title=f"Signal {signal} is routed to multiple pins",
                    detail=(
                        f"{signal} is assigned to pins {', '.join(canonicals)} in this "
                        f"file. A peripheral signal can only be routed to one physical "
                        f"pin at a time, so this is a contradiction."
                    ),
                    loc=group_sorted[0].loc,
                    evidence={
                        "signal": signal,
                        "pins": [
                            {"canonical": p.canonical, "raw_name": p.raw_name, "line": p.loc.line}
                            for p in group_sorted
                        ],
                        "mechanism": "c",
                    },
                    remediation="Route this signal to a single pin; reassign or remove the others.",
                )
            )
        return findings

    def _check_stale_pins(self, cfg: Config) -> list[Finding]:
        pf = cfg.raw
        findings: list[Finding] = []

        pin_entries = [e for e in pf.keys_with_prefix("Mcu.Pin") if e.key != "Mcu.PinsNb"]
        enumerated_raw_names = {e.value for e in pin_entries}

        pins_nb_entry = pf.get_entry("Mcu.PinsNb")
        if pins_nb_entry is not None:
            try:
                declared_count = int(pins_nb_entry.value)
                if declared_count != len(pin_entries):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            severity=Severity.WARNING,
                            title="Mcu.PinsNb does not match the number of enumerated pins",
                            detail=(
                                f"Mcu.PinsNb declares {declared_count} pins but "
                                f"{len(pin_entries)} Mcu.PinN entries are present in the "
                                f"file. This indicates an inconsistent or hand-edited "
                                f".ioc file."
                            ),
                            loc=Loc(file=cfg.source_path, line=pins_nb_entry.line, key="Mcu.PinsNb"),
                            evidence={
                                "declared_pins_nb": declared_count,
                                "actual_pin_entries": len(pin_entries),
                                "mechanism": "d",
                            },
                            remediation="Regenerate the .ioc from CubeMX, or correct Mcu.PinsNb by hand.",
                        )
                    )
            except ValueError:
                pass

        seen_stale: set[str] = set()
        for pin in cfg.pins:
            if pin.raw_name in enumerated_raw_names or pin.raw_name in seen_stale:
                continue
            seen_stale.add(pin.raw_name)
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=Severity.WARNING,
                    title=f"{pin.raw_name} is configured but not listed in Mcu.Pin*",
                    detail=(
                        f"{pin.raw_name} has a Signal assignment ({pin.signal}) but does "
                        f"not appear in the Mcu.Pin0..Mcu.Pin{{N-1}} enumeration. CubeMX "
                        f"normally keeps these in sync; this usually means the file was "
                        f"hand-edited or merged."
                    ),
                    loc=pin.loc,
                    evidence={"raw_name": pin.raw_name, "signal": pin.signal, "mechanism": "d"},
                    remediation="Regenerate the .ioc from CubeMX, or add the pin to the Mcu.Pin enumeration.",
                )
            )
        return findings
