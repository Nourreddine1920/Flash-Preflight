"""STM32 clock-tree derivation and UART baud-rate-generator math.

Clock tree derivation (SYSCLK -> HCLK -> PCLKx) is implemented from first
principles for STM32F1 and STM32F4 only (PLAN.md §6.1) using exact
`fractions.Fraction` arithmetic so results are never approximated. Other
families must use the declared-frequency fallback (see rules/clock_baud.py).

Baud math (§6.4) implements both USART IP generations bit-for-bit against
the HAL driver's own BRR computation (`UART_DIV_SAMPLING16`,
`UART_BRR_SAMPLING8`), not an approximation of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction

from preflight.model import ClockTree

HSI_F1_HZ = 8_000_000
HSI_F4_HZ = 16_000_000


class ClockError(Exception):
    """Raised when a clock tree cannot be derived from the given inputs."""


_SOLVERS: dict[str, Callable[[ClockTree], ClockTree]] = {}


def register_clock_solver(family: str, solver: Callable[[ClockTree], ClockTree]) -> None:
    """Register a clock-tree solver for an MCU family. A solver takes a
    ClockTree with sources/dividers filled in and returns it with the derived
    sysclk_hz/hclk_hz/pclk1_hz/pclk2_hz set (raise ClockError if it can't)."""
    _SOLVERS[family] = solver


def solve(family: str | None, tree: ClockTree) -> ClockTree:
    """Return a copy of `tree` with sysclk_hz/hclk_hz/pclk1_hz/pclk2_hz filled in."""
    solver = _SOLVERS.get(family) if family else None
    if solver is None:
        raise ClockError(f"clock derivation not implemented for family {family!r}")
    return solver(tree)


def _pll_source_hz_f4(tree: ClockTree) -> Fraction:
    src = tree.pll.source
    if src == "HSE":
        if tree.hse_hz is None:
            raise ClockError("PLL source is HSE but HSE frequency is unknown")
        return Fraction(tree.hse_hz)
    if src in ("HSI", None):
        hsi = tree.hsi_hz if tree.hsi_hz is not None else HSI_F4_HZ
        return Fraction(hsi)
    raise ClockError(f"unrecognized PLL source {src!r}")


def _solve_f4(tree: ClockTree) -> ClockTree:
    hsi = tree.hsi_hz if tree.hsi_hz is not None else HSI_F4_HZ

    if tree.sysclk_source == "PLLCLK":
        pll = tree.pll
        if pll.m is None or pll.n is None or pll.p is None:
            raise ClockError("PLL selected as SYSCLK source but PLLM/PLLN/PLLP incomplete")
        if pll.m == 0 or pll.p == 0:
            raise ClockError("PLLM or PLLP is zero")
        vco_in = _pll_source_hz_f4(tree) / pll.m
        vco_out = vco_in * pll.n
        sysclk = vco_out / pll.p
    elif tree.sysclk_source == "HSE":
        if tree.hse_hz is None:
            raise ClockError("SYSCLK source is HSE but HSE frequency is unknown")
        sysclk = Fraction(tree.hse_hz)
    elif tree.sysclk_source == "HSI":
        sysclk = Fraction(hsi)
    else:
        raise ClockError(f"unrecognized or missing SYSCLK source {tree.sysclk_source!r}")

    return _finish(tree, sysclk, hsi_used=hsi)


def _solve_f1(tree: ClockTree) -> ClockTree:
    hsi = tree.hsi_hz if tree.hsi_hz is not None else HSI_F1_HZ

    if tree.sysclk_source == "PLLCLK":
        pll = tree.pll
        if pll.mul is None:
            raise ClockError("PLL selected as SYSCLK source but PLLMUL is missing")
        if pll.source == "HSE":
            if tree.hse_hz is None:
                raise ClockError("PLL source is HSE but HSE frequency is unknown")
            prediv = pll.prediv if pll.prediv is not None else 1
            if prediv == 0:
                raise ClockError("PLL prediv is zero")
            pll_in = Fraction(tree.hse_hz, prediv)
        elif pll.source in ("HSI_DIV2", "HSI", None):
            pll_in = Fraction(hsi, 2)
        else:
            raise ClockError(f"unrecognized F1 PLL source {pll.source!r}")
        sysclk = pll_in * pll.mul
    elif tree.sysclk_source == "HSE":
        if tree.hse_hz is None:
            raise ClockError("SYSCLK source is HSE but HSE frequency is unknown")
        sysclk = Fraction(tree.hse_hz)
    elif tree.sysclk_source == "HSI":
        sysclk = Fraction(hsi)
    else:
        raise ClockError(f"unrecognized or missing SYSCLK source {tree.sysclk_source!r}")

    return _finish(tree, sysclk, hsi_used=hsi)


def _finish(tree: ClockTree, sysclk: Fraction, *, hsi_used: int) -> ClockTree:
    ahb_div = tree.ahb_div if tree.ahb_div is not None else 1
    apb1_div = tree.apb1_div if tree.apb1_div is not None else 1
    apb2_div = tree.apb2_div if tree.apb2_div is not None else 1

    hclk = sysclk / ahb_div
    pclk1 = hclk / apb1_div
    pclk2 = hclk / apb2_div

    return replace(
        tree,
        hsi_hz=hsi_used,
        sysclk_hz=_to_int_hz(sysclk),
        hclk_hz=_to_int_hz(hclk),
        pclk1_hz=_to_int_hz(pclk1),
        pclk2_hz=_to_int_hz(pclk2),
    )


def _to_int_hz(value: Fraction) -> int:
    return round(value)


register_clock_solver("STM32F4", _solve_f4)
register_clock_solver("STM32F1", _solve_f1)


# --------------------------------------------------------------------------
# UART baud-rate generator math (PLAN.md §6.4)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BaudResult:
    valid: bool
    n: int | None = None  # effective divisor, in f_CK ticks
    actual_hz: Fraction | None = None
    error_pct: float | None = None
    brr: int | None = None
    mantissa: int | None = None
    fraction: int | None = None
    reason: str | None = None


def compute_baud(fck_hz: int, baud: int, *, oversampling: int, usart_ip: str) -> BaudResult:
    if fck_hz <= 0:
        return BaudResult(valid=False, reason="peripheral clock is zero or negative")
    if baud <= 0:
        return BaudResult(valid=False, reason="baud rate is zero or negative")

    if oversampling == 16:
        return _compute_baud_over16(fck_hz, baud)
    if oversampling == 8:
        if usart_ip == "old":
            return _compute_baud_over8_old(fck_hz, baud)
        if usart_ip == "new":
            return _compute_baud_over8_new(fck_hz, baud)
        raise ClockError(f"unrecognized usart_ip {usart_ip!r}")
    raise ClockError(f"unsupported oversampling value {oversampling!r} (expected 8 or 16)")


def _round_div(numerator: int, denominator: int) -> int:
    """Integer round-half-up division, matching HAL's `(x + y/2) / y` idiom."""
    return (numerator + denominator // 2) // denominator


def _result_from_n(n: int, fck_hz: int, baud: int, *, brr: int | None = None,
                    mantissa: int | None = None, fraction: int | None = None) -> BaudResult:
    actual = Fraction(fck_hz, n)
    error_pct = float((actual - baud) / baud * 100)
    return BaudResult(valid=True, n=n, actual_hz=actual, error_pct=error_pct,
                       brr=brr, mantissa=mantissa, fraction=fraction)


def _compute_baud_over16(fck_hz: int, baud: int) -> BaudResult:
    n = _round_div(fck_hz, baud)
    if not (16 <= n <= 0xFFFF):
        return BaudResult(valid=False, n=n, brr=n,
                           reason=f"divisor {n} out of the valid 16..65535 range")
    return _result_from_n(n, fck_hz, baud, brr=n)


def _compute_baud_over8_old(fck_hz: int, baud: int) -> BaudResult:
    d = _round_div(2 * fck_hz, baud)
    brr = (d & 0xFFF0) | ((d & 0x000F) >> 1)
    mantissa = brr >> 4
    fraction = brr & 0x07
    n = mantissa * 8 + fraction
    if not (1 <= mantissa <= 0xFFF) or n < 8:
        return BaudResult(valid=False, brr=brr, mantissa=mantissa, fraction=fraction,
                           reason="baud rate is unreachable from this clock")
    return _result_from_n(n, fck_hz, baud, brr=brr, mantissa=mantissa, fraction=fraction)


def _compute_baud_over8_new(fck_hz: int, baud: int) -> BaudResult:
    d = _round_div(2 * fck_hz, baud)
    if d < 16:
        return BaudResult(valid=False, brr=d,
                           reason="baud rate is unreachable from this clock")
    brr = (d & 0xFFF0) | ((d & 0x000F) >> 1)
    eff = (brr & 0xFFF0) | ((brr & 0x0007) << 1)
    if eff == 0:
        return BaudResult(valid=False, brr=brr,
                           reason="baud rate is unreachable from this clock")
    actual = Fraction(2 * fck_hz, eff)
    error_pct = float((actual - baud) / baud * 100)
    return BaudResult(valid=True, n=eff, actual_hz=actual, error_pct=error_pct, brr=brr)
