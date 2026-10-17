"""Number formats of the work screen, in one place (config/p7c2.yaml wording.numbers).

    won(v)      per-share and price values: whole 원 with thousands separators ("62,394원")
    eok(v)      amounts in 억원: 100억 or more whole, below that one decimal ("1,234억원", "56.7억원")
    mn_eok(v)   백만원 amounts shown as 억원
    pct(v, d)   ratios as % with d decimals (default 2) ("6.86%")
    pp(v, d)    differences in %p
    beta(v)     3 decimals; times(v) multiples ("1.23배"); shares(n) share counts ("24,157,223주")
Missing values (None, NaN, inf) show as "—" (never 0).
"""
from __future__ import annotations

import math

NA = "—"


def ok(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def won(v, unit: bool = True, sign: bool = False) -> str:
    if not ok(v):
        return NA
    s = f"{float(v):+,.0f}" if sign else f"{float(v):,.0f}"
    return s + ("원" if unit else "")


def eok(v, unit: bool = True) -> str:
    if not ok(v):
        return NA
    v = float(v)
    if abs(v) < 0.05:
        v = 0.0
    s = f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"
    return s + ("억원" if unit else "")


def mn_eok(v, unit: bool = True) -> str:
    return eok(float(v) / 100 if ok(v) else None, unit)


def pct(v, d: int = 2, sign: bool = False) -> str:
    if not ok(v):
        return NA
    return (f"{float(v) * 100:+.{d}f}" if sign else f"{float(v) * 100:.{d}f}") + "%"


def pp(v, d: int = 1) -> str:
    if not ok(v):
        return NA
    return f"{float(v) * 100:+.{d}f}%p"


def beta(v) -> str:
    return f"{float(v):.3f}" if ok(v) else NA


def times(v, d: int = 2) -> str:
    return f"{float(v):,.{d}f}배" if ok(v) else NA


def multiple(v, d: int = 1) -> str:
    """A valuation multiple: ≤ 0 (negative EBITDA, earnings or EV) is N/M, as in the engine."""
    if not ok(v):
        return NA
    return f"{float(v):,.{d}f}배" if float(v) > 0 else "N/M"


def shares(n) -> str:
    return f"{int(n):,}주" if ok(n) else NA


def days(v) -> str:
    return f"{float(v):,.1f}일" if ok(v) else NA


def ratio_text(v) -> str:
    """DCF ÷ market price as '×1.23'."""
    return f"×{float(v):,.2f}" if ok(v) else NA
