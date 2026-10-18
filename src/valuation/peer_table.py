"""Preliminary peer data table (data check only; valuation judgement is P3).

LTM at 2026 H1 = FY2025 + H1 2026 - H1 2025 (flows), balance sheet at 2026-06-30, market cap at 2026-09-30
(price_daily.mktcap, 한국거래소 통계정보).

    EBITDA      = operating income + depreciation + amortisation + ROU depreciation (fs_dna, LTM)
    net debt    = total debt (+ lease liabilities in the "incl. lease" version) - cash - short-term financial assets
                  (long-term financial assets are NOT deducted here; non-operating asset treatment is a P3 decision)
    EV          = market cap + net debt (incl. lease) + non-controlling interests (book)
    multiples   = EV/Sales, EV/EBITDA, PER (market cap / LTM NI to owners), PBR (market cap / equity to owners)
                  value <= 0 in the denominator -> "N/M"
Statistics: median of core, median of core + extended; RFHIC (reference) and the target shown separately.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from src.clean.fs_periods import ltm, to_wide
from src.db.build import DB_PATH
from src.market.beta_table import companies

AS_OF = "2026-09-30"


def dna_wide(con, corp: str, fs_div: str) -> pd.DataFrame:
    d = con.execute(
        """SELECT fiscal_year, period, item, amount FROM fs_dna WHERE corp_code=? AND fs_div=?""", [corp, fs_div]
    ).df()
    from src.clean.frames import pivot

    return pivot(d, ["fiscal_year", "period"], "item", "amount")  # P7-B5: no D&A rows -> empty frame


def basis(con, corp: str, year: int = 2026, period: str = "H1") -> str:
    r = con.execute(
        """SELECT count(*) FROM fs_std WHERE corp_code=? AND fs_div='CFS' AND fiscal_year=?
                       AND period=? AND is_default""",
        [corp, year, period],
    ).fetchone()[0]
    return "CFS" if r else "OFS"


def dna_ltm_checked(
    dw: pd.DataFrame, revenue_fy: float | None, rule: dict, ltm_year: int = 2026, ltm_period: str = "H1"
) -> tuple[float | None, str]:
    """P3-C2 rule (config relative.ebitda_rule): LTM D&A = FY + H1 − H1prev unless a half-year total looks like a
    3-month value (H1/FY outside [h1_lo, h1_hi]) -> FY D&A; N/M if depreciation is 0 or FY D&A / revenue is outside
    [ratio_lo, ratio_hi]."""

    def tot(y, p):
        try:
            r = dw.loc[(y, p)]
        except KeyError:
            return None, None
        dep = r.get("depreciation", 0)  # P7-B2 B2-F5: a missing depreciation (NaN in the pivot) counts as 0
        return float(r.fillna(0).sum()), 0.0 if dep is None or pd.isna(dep) else float(dep)

    fy, dep_fy = tot(ltm_year - 1, "FY")
    if fy is None or not dep_fy or revenue_fy is None or revenue_fy <= 0:
        return None, f"D&A FY{ltm_year - 1} 없음 또는 감가상각비 0"
    if not (rule["ratio_lo"] <= fy / revenue_fy <= rule["ratio_hi"]):
        return None, f"D&A/매출 {fy / revenue_fy:.1%} 범위 밖"
    h1c, dc = tot(ltm_year, ltm_period)
    h1p, dp = tot(ltm_year - 1, ltm_period)
    ok = all(v is not None and dv and rule["h1_lo"] <= v / fy <= rule["h1_hi"] for v, dv in ((h1c, dc), (h1p, dp)))
    return (fy + h1c - h1p, "LTM") if ok else (fy, f"반기 D&A 이상 → FY{ltm_year - 1} D&A")


def row_for(con, std: pd.DataFrame, c: dict, as_of: str = AS_OF, dna_rule: dict | None = None) -> dict:
    # LTM period: from dna_rule (company config meta, P3-C3), default 2026 H1 (RF P1/P3 tables)
    ly, lp = (dna_rule or {}).get("ltm_year", 2026), (dna_rule or {}).get("ltm_period", "H1")
    fs = basis(con, c["corp_code"], ly, lp)
    w = to_wide(std, c["corp_code"], fs)
    dw = dna_wide(con, c["corp_code"], fs)
    if (dna_rule or {}).get("fill"):  # P7-B2b auto drafts: 원문/XBRL → 보완 원문 per period (no estimate)
        from src.clean.dna_fill import wide as dna_fill_wide

        dw = dna_fill_wide(con, c["corp_code"], fs, estimate=False)

    def bs(a):
        try:
            v = w.loc[(ly, lp), a]
            return None if pd.isna(v) else int(v)
        except KeyError:
            return None

    rev, op = ltm(w, ly, lp, "revenue"), ltm(w, ly, lp, "operating_income")
    ni_acct = "net_income_parent" if fs == "CFS" else "net_income"
    ni = ltm(w, ly, lp, ni_acct)
    notes = []
    if ni is None and fs == "CFS" and not bs("nci"):
        # e.g. 아모그린텍 2026 H1 shows no profit attribution line; NCI is 0 -> owners' profit = net income
        ni = ltm(w, ly, lp, "net_income")
        notes.append("NI parent <- net income (NCI 0)")
    dna_parts, dna_note = {}, []
    for item in ("depreciation", "amortization", "rou_depreciation"):
        v = ltm(dw, ly, lp, item) if item in dw.columns else None
        dna_parts[item] = v
        if v is None:
            dna_note.append(item)
    dna = None if dna_parts["depreciation"] is None else sum(v or 0 for v in dna_parts.values())
    if dna_rule is not None:  # P3-C2: checked LTM D&A (RF peers keep the P1 rule)
        ly, lp = dna_rule.get("ltm_year", 2026), dna_rule.get("ltm_period", "H1")
        rev_fy = w.loc[(ly - 1, "FY"), "revenue"] if (ly - 1, "FY") in w.index and "revenue" in w else None
        rev_fy = None if rev_fy is None or pd.isna(rev_fy) else float(rev_fy)
        dna, why = dna_ltm_checked(dw, rev_fy, dna_rule, ly, lp)
        if dna is None and dna_rule.get("supplement"):  # P3-C3: supplementary extraction (FY total, flagged)
            from src.clean.dna_supplement import supplement_fy

            sv, src = supplement_fy(con, c["corp_code"], fs, ly - 1)
            if sv and rev_fy and dna_rule["ratio_lo"] <= sv / rev_fy <= dna_rule["ratio_hi"]:
                dna, why = sv, f"보완 FY{ly - 1}: {src}"
        dna_note = [why] if why != "LTM" else []
    ebitda = None if op is None or dna is None else op + dna
    debt, lease = bs("total_debt") or 0, bs("lease_liabilities") or 0
    cash, stf = bs("cash") or 0, bs("short_term_fin") or 0
    nci = (bs("nci") or 0) if fs == "CFS" else 0
    eq = bs("equity_parent") if fs == "CFS" else bs("total_equity")
    from src.market.provider import get as market_provider  # P7-B: market values through the provider

    mcap = market_provider().mktcap_at(c["stock_code"], as_of, con=con)
    nd_ex, nd_inc = debt - cash - stf, debt + lease - cash - stf
    ev = mcap + nd_inc + nci if mcap is not None else None

    def mult(num, den):
        return None if num is None or den is None or den <= 0 else num / den

    return {
        "name": c["name"],
        "tier": c["tier"],
        "fs_div": fs,
        "revenue": rev,
        "ebitda": ebitda,
        "op": op,
        "ni_parent": ni,
        "net_debt_ex_lease": nd_ex,
        "net_debt_inc_lease": nd_inc,
        "nci": nci,
        "mktcap": mcap,
        "ev": ev,
        "ev_sales": mult(ev, rev),
        "ev_ebitda": mult(ev, ebitda),
        "per": mult(mcap, ni),
        "pbr": mult(mcap, eq),
        "dna_missing": ",".join(dna_note),
        "notes": "; ".join(notes),
    }


def build() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH))
    std = con.sql("SELECT * FROM fs_std").df()
    df = pd.DataFrame([row_for(con, std, c) for c in companies()])
    con.execute("DROP TABLE IF EXISTS peer_prelim")
    con.execute("CREATE TABLE peer_prelim AS SELECT * FROM df")
    con.close()
    return df


def medians(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["ev_sales", "ev_ebitda", "per", "pbr"]
    out = {}
    for lab, tiers in (("core median", ["core"]), ("core+extended median", ["core", "extended"])):
        sub = df[df.tier.isin(tiers)]
        out[lab] = {c: sub[c].dropna().median() if sub[c].notna().any() else None for c in cols}
        out[lab].update({f"n_{c}": int(sub[c].notna().sum()) for c in cols})
    return pd.DataFrame(out).T


if __name__ == "__main__":
    d = build()
    print(len(d), "rows written to peer_prelim")
