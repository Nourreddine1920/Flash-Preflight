"""PF002 - Clock / baud mismatch.

For each USART/UART with a configured baud rate: find which APB bus feeds it
(knowledge/buses.py), derive that bus's real frequency from the PLL/prescaler
settings (clocks.solve), and check whether the baud-rate generator can
actually produce the configured baud within tolerance (clocks.compute_baud).

Falls back to CubeMX's own declared frequency (`RCC.APB*Freq_Value`) when the
family isn't one clocks.py can derive from first principles (PLAN.md §6.5).
When derivation *does* succeed, the declared value is used only as a
cross-check -- a mismatch means the .ioc is stale or hand-edited.
"""

from __future__ import annotations

from preflight.clocks import ClockError, compute_baud, solve
from preflight.findings import Finding, Loc, Severity
from preflight.knowledge.buses import bus_for_usart
from preflight.knowledge.usart_ip import usart_ip_for_family
from preflight.model import Config, Peripheral
from preflight.rules.base import Applicability, Rule

BAUD_WARN_PCT = 1.0
BAUD_ERR_PCT = 2.0

_USART_KINDS = {"USART", "UART"}


def _fallback_loc(cfg: Config) -> Loc:
    return Loc(file=cfg.source_path, line=1)


class ClockBaudRule(Rule):
    id = "PF002"
    name = "Clock / baud mismatch"
    description = "UART/USART baud rate that the configured clock tree cannot actually produce"

    def __init__(
        self,
        *,
        baud_tolerance_pct: float = BAUD_WARN_PCT,
        baud_error_pct: float = BAUD_ERR_PCT,
        trust_declared_clocks: bool = True,
    ):
        self.baud_tolerance_pct = baud_tolerance_pct
        self.baud_error_pct = baud_error_pct
        self.trust_declared_clocks = trust_declared_clocks

    def _candidates(self, cfg: Config) -> list[Peripheral]:
        return [
            p
            for p in cfg.peripherals.values()
            if p.kind in _USART_KINDS and "BaudRate" in p.params
        ]

    def _pclk_for(self, cfg: Config, peripheral: Peripheral) -> tuple[int, str] | None:
        bus = bus_for_usart(cfg.mcu.family, peripheral.name)
        if bus is None:
            return None
        label = "PCLK1" if bus == "APB1" else "PCLK2"

        try:
            resolved = solve(cfg.mcu.family, cfg.clocks)
            pclk = resolved.pclk1_hz if bus == "APB1" else resolved.pclk2_hz
            if pclk is not None:
                return pclk, "derived"
        except ClockError:
            pass

        if self.trust_declared_clocks:
            declared = cfg.clocks.declared.get(label)
            if declared is not None:
                return declared, "declared-by-cubemx"
        return None

    def applies_to(self, cfg: Config) -> Applicability:
        candidates = self._candidates(cfg)
        if not candidates:
            return Applicability(False, "no USART/UART peripherals with a configured baud rate were found")
        for p in candidates:
            if self._pclk_for(cfg, p) is not None:
                return Applicability(True)
        return Applicability(
            False,
            f"clock derivation not implemented for family {cfg.mcu.family!r} and no "
            f"declared peripheral clock frequencies were available",
        )

    def check(self, cfg: Config) -> list[Finding]:
        findings: list[Finding] = []
        for peripheral in self._candidates(cfg):
            findings.extend(self._check_peripheral(cfg, peripheral))
        return findings

    def _check_peripheral(self, cfg: Config, peripheral: Peripheral) -> list[Finding]:
        bus = bus_for_usart(cfg.mcu.family, peripheral.name)
        if bus is None:
            return []
        label = "PCLK1" if bus == "APB1" else "PCLK2"

        pclk_info = self._pclk_for(cfg, peripheral)
        if pclk_info is None:
            return []
        pclk_hz, source = pclk_info

        findings: list[Finding] = []
        loc = peripheral.locs.get("BaudRate", _fallback_loc(cfg))

        if source == "derived":
            declared = cfg.clocks.declared.get(label)
            if declared is not None and declared != pclk_hz:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity=Severity.WARNING,
                        title=f"{label} recorded in the file does not match the derived clock tree",
                        detail=(
                            f"The PLL and prescaler settings in this file produce "
                            f"{label} = {pclk_hz:,} Hz, but the file separately records "
                            f"{label} = {declared:,} Hz. This usually means the file was "
                            f"hand-edited or is stale. The baud check below uses the "
                            f"derived value ({pclk_hz:,} Hz), which reflects what the "
                            f"hardware will actually produce."
                        ),
                        loc=cfg.clocks.locs.get(label, loc),
                        evidence={"derived_hz": pclk_hz, "declared_hz": declared, "clock": label},
                        remediation="Regenerate the file from CubeMX so the declared frequency matches the PLL settings.",
                    )
                )

        try:
            baud = int(peripheral.params["BaudRate"])
        except ValueError:
            return findings

        oversampling = 8 if "8" in peripheral.params.get("OverSampling", "") else 16
        usart_ip = usart_ip_for_family(cfg.mcu.family) or "old"
        result = compute_baud(pclk_hz, baud, oversampling=oversampling, usart_ip=usart_ip)

        source_note = (
            "Using the peripheral clock frequency recorded by CubeMX (not independently "
            "derived from the PLL settings): "
            if source == "declared-by-cubemx"
            else ""
        )

        if not result.valid:
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=Severity.ERROR,
                    title=f"{peripheral.name} baud rate {baud} is unreachable from its clock",
                    detail=(
                        f"{source_note}{peripheral.name}'s clock ({label}) is {pclk_hz:,} Hz. "
                        f"{result.reason or 'The requested baud rate cannot be generated from this clock.'}"
                    ),
                    loc=loc,
                    evidence={
                        "peripheral": peripheral.name,
                        "pclk_hz": pclk_hz,
                        "baud": baud,
                        "pclk_source": source,
                    },
                    remediation="Raise the peripheral clock, lower the baud rate, or change the oversampling mode.",
                )
            )
            return findings

        error_pct = result.error_pct if result.error_pct is not None else 0.0
        if abs(error_pct) > self.baud_error_pct:
            severity: Severity | None = Severity.ERROR
        elif abs(error_pct) > self.baud_tolerance_pct:
            severity = Severity.WARNING
        else:
            severity = None

        if severity is not None:
            actual = float(result.actual_hz) if result.actual_hz is not None else 0.0
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity=severity,
                    title=f"{peripheral.name} baud rate is off by {error_pct:+.2f}%",
                    detail=(
                        f"{source_note}{peripheral.name} is configured for {baud} baud, "
                        f"but its clock ({label}) is {pclk_hz:,} Hz. The baud rate "
                        f"generator can only produce {actual:,.1f} baud from that clock "
                        f"({error_pct:+.2f}% off). UART links typically tolerate about "
                        f"{self.baud_error_pct:.0f}% total error, so this link "
                        f"{'will very likely drop bytes' if severity is Severity.ERROR else 'may drop bytes on marginal wiring'}."
                    ),
                    loc=loc,
                    evidence={
                        "peripheral": peripheral.name,
                        "pclk_hz": pclk_hz,
                        "baud_nominal": baud,
                        "baud_actual": actual,
                        "error_pct": error_pct,
                        "pclk_source": source,
                    },
                    remediation=(
                        f"Raise {label} (currently {pclk_hz:,} Hz), lower the baud rate, "
                        f"or accept the drift if the receiver tolerates it."
                    ),
                )
            )

        return findings
