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


# ---------------------------------------------------------------- P7-U1 table formats (config/p7u.yaml number_format)
MINUS = "−"


def amt(v, mn: bool = False, paren: bool = True) -> str:
    """An amount in 억원 (mn=True: 백만원, x 100) as a whole number; negatives in parentheses."""
    if not ok(v):
        return NA
    x = float(v) * (100 if mn else 1)
    s = f"{abs(x):,.0f}"
    if s == "0":
        return "0"
    return (f"({s})" if paren else MINUS + s) if x < 0 else s


def unit(mn: bool = False) -> str:
    return "백만원" if mn else "억원"


def amt_u(v, mn: bool = False) -> str:
    """amt with its unit (억 or 백만 after the number)."""
    return NA if not ok(v) else amt(v, mn) + ("백만" if mn else "억")


def won0(v, paren: bool = False) -> str:
    """Per-share and price values: whole 원 without the unit."""
    if not ok(v):
        return NA
    x = float(v)
    s = f"{abs(x):,.0f}"
    if x < 0 and s != "0":
        return f"({s})" if paren else MINUS + s
    return s


def x_(v) -> str:
    """A multiple: 1 decimal + 'x' (below 1x: 2 decimals); <= 0 or missing -> '계산 불가'."""
    if not ok(v) or float(v) <= 0:
        return "계산 불가"
    return f"{float(v):,.2f}x" if float(v) < 1 else f"{float(v):,.1f}x"


def p1(v, d: int = 1, paren: bool = False) -> str:
    """A ratio as % with d decimals (table default 1); negatives in parentheses when paren."""
    if not ok(v):
        return NA
    x = float(v) * 100
    s = f"{abs(x):.{d}f}%"
    if x < 0 and float(f"{abs(x):.{d}f}") != 0:
        return f"({s})" if paren else MINUS + s
    return s


def signed(d, zero: str = "±0") -> str:
    """A per-share difference with its sign, '±0' when |d| < 0.5."""
    if not ok(d):
        return NA
    if abs(float(d)) < 0.5:
        return zero
    return ("+" if float(d) > 0 else MINUS) + f"{abs(float(d)):,.0f}"


def pct_signed(v, d: int = 1) -> str:
    """A premium with its sign and one decimal."""
    if not ok(v):
        return NA
    x = float(v) * 100
    return ("+" if x >= 0 else MINUS) + f"{abs(x):.{d}f}%"


def kst(at, clock: bool = False) -> str:
    """P7-U3 U3-2c: a time written by the server ('YYYY-MM-DDTHH:MM:SS', naive = the server's local clock, UTC on the
    public deployment) as Korean time: 'YYYY-MM-DD HH:MM', or 'HH:MM' with clock=True."""
    from datetime import datetime, timedelta, timezone

    if not at:
        return ""
    try:
        d = datetime.fromisoformat(str(at))
    except ValueError:
        return str(at)
    d = (d if d.tzinfo else d.astimezone()).astimezone(timezone(timedelta(hours=9)))
    return d.strftime("%H:%M" if clock else "%Y-%m-%d %H:%M")
