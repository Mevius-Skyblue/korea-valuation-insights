"""FCFF discounted cash flow engine (P3-B, general - nothing company-specific here).

Per period (dates, so a partial first year is natural):
    FCFF   = EBIT x (1 - t) + D&A - CAPEX - ΔNWC
    t      = effective rate of the progressive tax on the fiscal year's taxable base (tax_base, default = EBIT
             annualised); a loss year pays 0 (no carry-forward in this engine)
    time   = years (days / 365, leap day counts) from `discount_date` (end of that day) to the period midpoint (mid_year=True, default) or to the period end
    PV     = FCFF / (1 + WACC)^time

Terminal value at the end of the last period (time T):
    Gordon   TV = FCF_norm x (1 + g) / (WACC - g)        FCF_norm = normalised final-year FCFF (default: last FCFF
                                                           annualised); with mid_year the flows after T also arrive
                                                           mid-year -> TV x (1 + WACC)^0.5
    Exit     TV = multiple x EBITDA_final (annualised)    a market value at T, no mid-year adjustment
    Each implies the other: implied multiple = TV_gordon / EBITDA_final, implied g solves Gordon(g) = TV_exit.

EV at the discount date = sum PV(FCFF) + PV(TV). roll_forward(ev, wacc, days) moves it to a later valuation date
(used when the balance sheet / cash-flow start precedes the valuation date, e.g. BS 06-30, valuation 09-30).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

DAYS = 365.0


@dataclass
class Period:
    label: str
    start: date  # first day of the period
    end: date  # last day of the period
    ebit: float
    dna: float
    capex: float
    dnwc: float  # increase in net working capital (positive = cash outflow)
    tax_base: float | None = None  # fiscal-year taxable base for the rate (default: EBIT annualised)

    @property
    def fraction(self) -> float:
        return ((self.end - self.start).days + 1) / DAYS


@dataclass
class DcfResult:
    table: pd.DataFrame
    pv_explicit: float
    tv_gordon: float | None
    tv_exit: float | None
    pv_tv_gordon: float | None
    pv_tv_exit: float | None
    ev_gordon: float | None
    ev_exit: float | None
    implied_multiple: float | None  # from Gordon TV
    implied_g: float | None  # from exit TV
    tv_share_gordon: float | None  # PV(TV) / EV
    tv_share_exit: float | None
    inputs: dict = field(default_factory=dict)


def flat_tax(rate: float) -> Callable[[float], float]:
    """A tax function with one rate (tests and simple cases; real runs use the progressive table)."""
    return lambda base: max(base, 0.0) * rate


def year_frac(a: date, b: date) -> float:
    """Years between two dates as days / 365 (the discounting clock of this engine)."""
    return (b - a).days / DAYS


def fcff_rows(
    periods: list[Period], tax_fn: Callable[[float], float], wacc: float, discount_date: date, mid_year: bool = True
) -> pd.DataFrame:
    """One row per period: tax, NOPAT, FCFF = EBIT(1-t) + D&A - CAPEX - ΔNWC, discount time and present value."""
    rows = []
    for p in periods:
        f = p.fraction
        base = p.tax_base if p.tax_base is not None else p.ebit / f
        rate = tax_fn(base) / base if base > 0 else 0.0
        tax = max(p.ebit, 0.0) * rate if base > 0 else 0.0
        fcff = p.ebit - tax + p.dna - p.capex - p.dnwc
        t_end = year_frac(discount_date, p.end)  # both dates mean 'end of that day' (BS date -> period end)
        t = t_end - f / 2 if mid_year else t_end
        df = (1 + wacc) ** -t
        rows.append(
            {
                "label": p.label,
                "fraction": f,
                "ebit": p.ebit,
                "tax_rate": rate,
                "tax": tax,
                "nopat": p.ebit - tax,
                "dna": p.dna,
                "capex": p.capex,
                "dnwc": p.dnwc,
                "fcff": fcff,
                "ebitda": p.ebit + p.dna,
                "t": t,
                "t_end": t_end,
                "discount_factor": df,
                "pv": fcff * df,
            }
        )
    return pd.DataFrame(rows)


def gordon_tv(fcf_norm: float, wacc: float, g: float, mid_year: bool = True) -> float:
    """Gordon terminal value FCF x (1+g) / (WACC-g); with mid-year flows also x (1+WACC)^0.5."""
    if wacc <= g:
        raise ValueError("WACC must exceed g")
    return fcf_norm * (1 + g) / (wacc - g) * ((1 + wacc) ** 0.5 if mid_year else 1.0)


def implied_g(tv: float, fcf_norm: float, wacc: float, mid_year: bool = True) -> float:
    """g such that gordon_tv(fcf_norm, wacc, g, mid_year) == tv."""
    x = tv / ((1 + wacc) ** 0.5 if mid_year else 1.0)
    return (x * wacc - fcf_norm) / (x + fcf_norm)


def run_dcf(
    periods: list[Period],
    tax_fn: Callable[[float], float],
    wacc: float,
    discount_date: date,
    g: float | None = None,
    exit_multiple: float | None = None,
    mid_year: bool = True,
    fcf_norm: float | None = None,
    ebitda_final: float | None = None,
) -> DcfResult:
    """EV = PV of the explicit FCFF + PV of the terminal value (Gordon and/or exit multiple), with the cross checks."""
    tab = fcff_rows(periods, tax_fn, wacc, discount_date, mid_year)
    last = tab.iloc[-1]
    t_n = float(last.t_end)
    dfn = (1 + wacc) ** -t_n
    fcf_n = fcf_norm if fcf_norm is not None else last.fcff / last.fraction
    ebitda_n = ebitda_final if ebitda_final is not None else last.ebitda / last.fraction
    pv_exp = float(tab.pv.sum())
    tvg = gordon_tv(fcf_n, wacc, g, mid_year) if g is not None else None
    tve = exit_multiple * ebitda_n if exit_multiple is not None else None
    pvg = tvg * dfn if tvg is not None else None
    pve = tve * dfn if tve is not None else None
    evg = pv_exp + pvg if pvg is not None else None
    eve = pv_exp + pve if pve is not None else None
    return DcfResult(
        table=tab,
        pv_explicit=pv_exp,
        tv_gordon=tvg,
        tv_exit=tve,
        pv_tv_gordon=pvg,
        pv_tv_exit=pve,
        ev_gordon=evg,
        ev_exit=eve,
        implied_multiple=tvg / ebitda_n if tvg is not None and ebitda_n > 0 else None,
        implied_g=implied_g(tve, fcf_n, wacc, mid_year) if tve is not None else None,
        tv_share_gordon=pvg / evg if evg else None,
        tv_share_exit=pve / eve if eve else None,
        inputs={
            "wacc": wacc,
            "g": g,
            "exit_multiple": exit_multiple,
            "mid_year": mid_year,
            "fcf_norm": fcf_n,
            "ebitda_final": ebitda_n,
            "t_n": t_n,
            "discount_date": discount_date,
        },
    )


def roll_forward(value: float, wacc: float, days: int) -> float:
    """Move a value from its date to `days` later at the WACC (e.g. EV at the BS date -> valuation date)."""
    return value * (1 + wacc) ** (days / DAYS)


# ---------------------------------------------------------------- P3-B2: three-stage DCF and value drivers


def fade_path(g_start: float, g_end: float, n: int) -> list[float]:
    """Growth falling by the same step each year: g_k = g_start − k (g_start − g_end) / n, k = 1..n (last = g_end)."""
    return [g_start - k * (g_start - g_end) / n for k in range(1, n + 1)]


def value_driver_fcf(nopat: float, g: float, ronic: float) -> float:
    """FCF = NOPAT x (1 − g / RONIC): growth g needs reinvestment g / RONIC of NOPAT (McKinsey value driver)."""
    return nopat * (1 - g / ronic)


def value_driver_tv(nopat_next: float, g: float, ronic: float, wacc: float, mid_year: bool = True) -> float:
    """TV = NOPAT_{N+1} x (1 − g / RONIC) / (WACC − g). With RONIC = WACC this equals NOPAT_{N+1} / WACC for any g."""
    if wacc <= g:
        raise ValueError("WACC must exceed g")
    return value_driver_fcf(nopat_next, g, ronic) / (wacc - g) * ((1 + wacc) ** 0.5 if mid_year else 1.0)


def days_path(start: dict, target: dict, first_year: int, target_year: int, years: list[int]) -> dict[int, dict]:
    """Working-capital days moving by equal steps from `start` (value in first_year) to `target` (reached in
    target_year), flat afterwards. Keys of start/target are e.g. dso, dio, dpo; missing keys stay at start."""
    out = {}
    n = target_year - first_year
    for y in years:
        k = min(max(y - first_year, 0), n)
        out[y] = {key: start[key] + (target.get(key, start[key]) - start[key]) * k / n for key in start}
    return out


# ---------------------------------------------------------------- P5-A: external projections (an opinion's FCFF as given)


@dataclass
class ExternalDcf:
    pv: list[float]  # PV of each period's FCFF
    pv_explicit: float
    pv_tv: float
    ev_operating: float  # pv_explicit + pv_tv


def discount_external(
    fcff: list[float], t: list[float], wacc: float, fcf_next: float, g: float, t_tv: float | None = None
) -> ExternalDcf:
    """Discount cash flows that someone else projected, with their timing.

        PV_i     = FCFF_i x (1 + WACC)^(-t_i)              t_i as given (e.g. mid-year 0.5, 1.5, ...)
        PV(TV)   = FCF_{N+1} / (WACC − g) x (1 + WACC)^(-t_tv)
    t_tv defaults to the last t_i: the Korean opinion convention 1/(1+WACC)^4.5 for a mid-year 5-year forecast. That equals
    run_dcf's mid-year Gordon value (TV x (1+WACC)^0.5 discounted from the period end) when FCF_{N+1} = FCF_N x (1 + g)."""
    if wacc <= g:
        raise ValueError("WACC must exceed g")
    if len(fcff) != len(t):
        raise ValueError("fcff and t differ in length")
    pv = [f * (1 + wacc) ** -ti for f, ti in zip(fcff, t)]
    t_tv = t[-1] if t_tv is None else t_tv
    pv_tv = fcf_next / (wacc - g) * (1 + wacc) ** -t_tv
    return ExternalDcf(pv, float(sum(pv)), pv_tv, float(sum(pv)) + pv_tv)
