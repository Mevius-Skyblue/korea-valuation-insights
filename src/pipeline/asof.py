"""Periods that follow the as-of date (P7-X2b config/p7x2b.yaml config_constants.as_of).

Every year the automatic draft collects, averages or writes is computed from the config meta (as_of, bs_date, ltm) instead
of a typed constant, so a new as-of date moves them together. For meta {ltm: {year: 2026, period: H1}} every value equals
the constants used up to P7-X2a (tests/test_p7x2b.py).

    Y, P        LTM year / period of the balance sheet (2026, 'H1');  FY = Y − 1 (last full year before the LTM period)
    hist        FY(Y−5)~FY(Y−1)            five-year window (v2 margin median, signals)              2021~2025
    cagr_from   FY(Y−6)~FY(Y−2)            CAGR start candidates                                      2020~2024
    target      FY(Y−6)~FY(Y−1) + (FY, P) + (Y, P)                                                    2020~2025 + 2025H1 + 2026H1
    target_doc  FY(Y−5)~FY(Y−1) + (FY, P) + (Y, P)
    peers       FY(Y−2), FY(Y−1), (FY, P), (Y, P);  peers_doc  FY(Y−1), (FY, P), (Y, P)
    required    FY(Y−2), FY(Y−1), (FY, P), (Y, P)  (G7 short-history rule)
    avg         FY(Y−3)~FY(Y−1)            3-year averages                                            2023~2025
    de_points   FY(Y−3), FY(Y−2), H1(Y−1), FY(Y−1), (Y, P)
    fade_to     Y + 4                      start growth reaches g                                     2030
"""

from __future__ import annotations

REPRT = {"FY": "11011", "H1": "11012", "Q1": "11013", "Q3": "11014"}


def ltm(meta: dict) -> tuple[int, str]:
    return int(meta["ltm"]["year"]), str(meta["ltm"]["period"])


def periods(meta: dict) -> dict:
    """All as-of dependent years of the draft rules for one config meta."""
    from src.valuation.associates import params

    Y, P = ltm(meta)
    FY = Y - 1
    st = params()["structure"]
    cur = (Y, P)

    def u(xs):  # an annual LTM period (P = FY) repeats a year: keep the first
        return list(dict.fromkeys(xs))

    return {
        "Y": Y,
        "P": P,
        "FY": FY,
        "reprt": REPRT[P],
        "hist": list(range(FY - 4, FY + 1)),
        "cagr_from": list(range(FY - 5, FY)),
        "target": u([(y, "FY") for y in range(FY - 5, FY + 1)] + [(FY, P), cur]),
        "target_doc": u([(y, "FY") for y in range(FY - 4, FY + 1)] + [(FY, P), cur]),
        "peers": u([(FY - 1, "FY"), (FY, "FY"), (FY, P), cur]),
        "peers_doc": u([(FY, "FY"), (FY, P), cur]),
        "required": u([(FY - 1, "FY"), (FY, "FY"), (FY, P), cur]),
        "avg": [FY - 2, FY - 1, FY],
        "de_points": [[FY - 2, "FY"], [FY - 1, "FY"], [FY, "H1"], [FY, "FY"], [Y, P]],
        "fade_to": Y + int(st["fade_to_offset"]),
        "explicit_end": Y + int(st["explicit_years"]),
        "fade_end": Y + int(st["explicit_years"]) + int(st["fade_years"]),
    }


def default() -> dict:
    """periods() of the draft rules' meta (config/p7b.yaml meta)."""
    from src.pipeline.draft_common import load_rules

    return periods(load_rules()["meta"])


def short(y: int, p: str) -> str:
    """'2H26'-style label of the partial first forecast period after an LTM period (H1 -> 2H)."""
    return f"2H{str(y)[2:]}" if p == "H1" else f"{y}"
