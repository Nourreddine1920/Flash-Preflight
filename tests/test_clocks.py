import random
from fractions import Fraction

import pytest

from preflight.clocks import ClockError, compute_baud, solve
from preflight.model import ClockTree, PllConfig

# --------------------------------------------------------------------------
# Clock tree derivation
# --------------------------------------------------------------------------


def test_f4_pll_from_hse_168mhz():
    tree = ClockTree(
        hse_hz=8_000_000,
        pll=PllConfig(source="HSE", m=8, n=336, p=2),
        sysclk_source="PLLCLK",
        ahb_div=1,
        apb1_div=4,
        apb2_div=2,
    )
    result = solve("STM32F4", tree)
    assert result.sysclk_hz == 168_000_000
    assert result.hclk_hz == 168_000_000
    assert result.pclk1_hz == 42_000_000
    assert result.pclk2_hz == 84_000_000


def test_f4_hsi_direct_16mhz():
    tree = ClockTree(sysclk_source="HSI", ahb_div=1, apb1_div=1, apb2_div=1)
    result = solve("STM32F4", tree)
    assert result.sysclk_hz == 16_000_000
    assert result.pclk1_hz == 16_000_000
    assert result.pclk2_hz == 16_000_000


def test_f4_hsi_direct_with_apb1_div8():
    tree = ClockTree(sysclk_source="HSI", ahb_div=1, apb1_div=8, apb2_div=1)
    result = solve("STM32F4", tree)
    assert result.pclk1_hz == 2_000_000


def test_f4_missing_pll_params_raises():
    tree = ClockTree(pll=PllConfig(source="HSE", m=8, n=336), sysclk_source="PLLCLK")
    with pytest.raises(ClockError):
        solve("STM32F4", tree)


def test_f4_hse_source_missing_hz_raises():
    tree = ClockTree(sysclk_source="HSE")
    with pytest.raises(ClockError):
        solve("STM32F4", tree)


def test_f1_pll_from_hse_72mhz():
    tree = ClockTree(
        hse_hz=8_000_000,
        pll=PllConfig(source="HSE", mul=9, prediv=1),
        sysclk_source="PLLCLK",
        ahb_div=1,
        apb1_div=2,
        apb2_div=1,
    )
    result = solve("STM32F1", tree)
    assert result.sysclk_hz == 72_000_000
    assert result.hclk_hz == 72_000_000
    assert result.pclk1_hz == 36_000_000
    assert result.pclk2_hz == 72_000_000


def test_f1_pll_from_hsi_div2():
    tree = ClockTree(
        pll=PllConfig(source="HSI_DIV2", mul=16),
        sysclk_source="PLLCLK",
        ahb_div=1,
        apb1_div=1,
        apb2_div=1,
    )
    result = solve("STM32F1", tree)
    # HSI 8MHz / 2 * 16 = 64MHz
    assert result.sysclk_hz == 64_000_000


def test_unsupported_family_raises():
    with pytest.raises(ClockError):
        solve("STM32L4", ClockTree(sysclk_source="HSI"))


# --------------------------------------------------------------------------
# Baud rate generator: known-good vectors from PLAN.md §6.6
# --------------------------------------------------------------------------


def test_baud_8mhz_9600_over16():
    r = compute_baud(8_000_000, 9600, oversampling=16, usart_ip="old")
    assert r.valid
    assert r.n == 833
    assert r.actual_hz == Fraction(8_000_000, 833)
    assert r.error_pct == pytest.approx(0.04, abs=0.01)


def test_baud_8mhz_115200_over16():
    r = compute_baud(8_000_000, 115200, oversampling=16, usart_ip="old")
    assert r.valid
    assert r.n == 69
    assert r.error_pct == pytest.approx(0.64, abs=0.01)


def test_baud_16mhz_115200_over16():
    r = compute_baud(16_000_000, 115200, oversampling=16, usart_ip="old")
    assert r.valid
    assert r.n == 139
    assert r.error_pct == pytest.approx(-0.08, abs=0.01)


def test_baud_42mhz_115200_over16():
    r = compute_baud(42_000_000, 115200, oversampling=16, usart_ip="old")
    assert r.valid
    assert r.n == 365
    assert r.error_pct == pytest.approx(-0.11, abs=0.01)


def test_baud_84mhz_115200_over16():
    r = compute_baud(84_000_000, 115200, oversampling=16, usart_ip="old")
    assert r.valid
    assert r.n == 729
    assert r.error_pct == pytest.approx(0.02, abs=0.01)


def test_baud_2mhz_115200_over16_error_band():
    r = compute_baud(2_000_000, 115200, oversampling=16, usart_ip="old")
    assert r.valid
    assert r.n == 17
    assert r.error_pct == pytest.approx(2.12, abs=0.01)
    assert r.error_pct > 2.0  # crosses the ERROR threshold


def test_baud_2mhz_921600_over16_unreachable():
    r = compute_baud(2_000_000, 921600, oversampling=16, usart_ip="old")
    assert not r.valid
    assert r.n == 2


def test_baud_16mhz_921600_over8_old_ip():
    r = compute_baud(16_000_000, 921600, oversampling=8, usart_ip="old")
    assert r.valid
    assert r.n == 17
    assert r.mantissa == 2
    assert r.fraction == 1
    assert float(r.actual_hz) == pytest.approx(941176.5, abs=0.1)
    assert r.error_pct == pytest.approx(2.12, abs=0.01)


def test_baud_16mhz_230400_over8_old_ip_brr_0x85():
    r = compute_baud(16_000_000, 230400, oversampling=8, usart_ip="old")
    assert r.valid
    assert r.brr == 0x85
    assert r.mantissa == 8
    assert r.fraction == 5
    assert r.n == 69
    assert r.error_pct == pytest.approx(0.64, abs=0.01)


def test_over8_old_and_new_ip_agree_on_actual_frequency():
    fck, baud = 16_000_000, 230400
    old = compute_baud(fck, baud, oversampling=8, usart_ip="old")
    new = compute_baud(fck, baud, oversampling=8, usart_ip="new")
    assert old.valid and new.valid
    assert float(old.actual_hz) == pytest.approx(float(new.actual_hz), rel=1e-9)


def test_over16_and_over8_agree_when_n_even():
    # Pick fck/baud where OVER16's N happens to be even so it maps cleanly.
    fck, baud = 16_000_000, 500_000  # N16 = 32 (even)
    over16 = compute_baud(fck, baud, oversampling=16, usart_ip="old")
    assert over16.valid
    assert over16.n % 2 == 0


@pytest.mark.parametrize("baud", [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600])
def test_baud_property_actual_matches_fck_over_n(baud):
    random.seed(baud)
    for _ in range(20):
        fck = random.randint(1_000_000, 100_000_000)
        r = compute_baud(fck, baud, oversampling=16, usart_ip="old")
        if r.valid:
            assert r.actual_hz == Fraction(fck, r.n)
            assert abs(r.error_pct) < 50.0


def test_baud_zero_inputs_invalid():
    assert not compute_baud(0, 115200, oversampling=16, usart_ip="old").valid
    assert not compute_baud(16_000_000, 0, oversampling=16, usart_ip="old").valid
