"""Discount rate (P3-A preview; the valuation judgement is P3-B).

    levered beta  βL = βu × (1 + (1 − t) × D/E)                  (Hamada; same D/E rule as the unlever step)
    cost of equity Ke = Rf + βL × MRP + SRP                        (CAPM + size premium)
    after-tax Kd       = Kd × (1 − t_marginal)
    weights            D/V = (D/E) / (1 + D/E),  E/V = 1 / (1 + D/E)
    WACC               = E/V × Ke + D/V × Kd × (1 − t)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product

import pandas as pd

from src.valuation.levering import relever


@dataclass
class WaccResult:
    beta_u: float
    de: float
    beta_l: float
    ke: float
    kd_after_tax: float
    wd: float
    wacc: float


def cost_of_equity(rf: float, beta_l: float, mrp: float, srp: float = 0.0) -> float:
    return rf + beta_l * mrp + srp


def wacc(rf: float, mrp: float, beta_u: float, de: float, kd: float, t_hamada: float, t_kd: float,
         srp: float = 0.0) -> WaccResult:
    """WACC at a target D/E. t_hamada relevers the beta, t_kd is the marginal rate for the tax shield."""
    bl = relever(beta_u, t_hamada, de)
    ke = cost_of_equity(rf, bl, mrp, srp)
    wd = de / (1 + de)
    kd_at = kd * (1 - t_kd)
    return WaccResult(beta_u, de, bl, ke, kd_at, wd, (1 - wd) * ke + wd * kd_at)


def wacc_grid(rf: float, kd: float, t_hamada: float, t_kd: float, mrps: dict, betas: dict, des: dict,
              srp: float = 0.0) -> pd.DataFrame:
    """Every combination of the labelled MRP / βu / D/E values (dicts label -> value)."""
    rows = []
    for (ml, m), (bl, b), (dl, d) in product(mrps.items(), betas.items(), des.items()):
        r = wacc(rf, m, b, d, kd, t_hamada, t_kd, srp)
        rows.append({"mrp_case": ml, "beta_case": bl, "de_case": dl, "mrp": m, **asdict(r)})
    return pd.DataFrame(rows)


def debt_beta(kd: float, rf: float, mrp: float) -> float:
    """Debt beta implied by the CAPM: βd = (Kd − Rf) / MRP (P3-B2 sensitivity)."""
    return (kd - rf) / mrp


def harris_pringle(beta_u: float, beta_d: float, de: float) -> float:
    """βL = βu + (βu − βd) × D/E (no tax term; with βd = 0 it equals Hamada at t = 0)."""
    return beta_u + (beta_u - beta_d) * de


def wacc_hp(rf: float, mrp: float, beta_u: float, de: float, kd: float, t_kd: float, srp: float = 0.0) -> WaccResult:
    """WACC with a risky-debt beta (Harris–Pringle relever, βd from Kd)."""
    bd = debt_beta(kd, rf, mrp)
    bl = harris_pringle(beta_u, bd, de)
    ke = cost_of_equity(rf, bl, mrp, srp)
    wd = de / (1 + de)
    kd_at = kd * (1 - t_kd)
    return WaccResult(beta_u, de, bl, ke, kd_at, wd, (1 - wd) * ke + wd * kd_at)
