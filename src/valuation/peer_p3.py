"""P3-A preliminary peer multiples with the P3 net-debt / non-operating definitions (data check; judgement is P3-C).

Run: python -m src.valuation.peer_p3      -> DB table peer_p3

Flows (LTM 2026 H1, CFS else OFS) come from src/valuation/peer_table.row_for (P1-B). Balance sheet at 2026-06-30 is
re-read line by line from fs_raw because the peers' financial-asset lines are mostly not standard accounts:
    current section     cash line + 단기금융상품/자산, 공정가치 financial assets, 기타 (유동) 금융자산  -> cash-like
    non-current section 공정가치 financial assets, 장기금융상품/자산, 기타 비유동 금융자산, 관계기업, 투자부동산
                                                                                          -> non-operating
    derivatives (파생상품자산/부채) are neither; shown in a flag column
    EV = market cap (2026-09-30, 한국거래소 통계정보) + total debt incl. lease − cash-like − non-operating + NCI (book)
"기타 금융자산" may hold deposits or loans as well as securities -> treated as cash-like / non-operating here and
flagged (project assumption for a preliminary table).
"""

from __future__ import annotations

import re

import duckdb
import pandas as pd

from src.db.build import DB_PATH
from src.market.beta_table import companies
from src.valuation.peer_table import AS_OF, row_for

CASH_LIKE = re.compile(r"^현금및현금성자산$|단기금융(?:상품|자산)|공정가치|기타\s*(?:유동\s*)?금융자산|단기기타금융자산")
NON_OP = re.compile(r"공정가치|장기금융(?:상품|자산)|비유동\s*금융자산|기타금융자산|장기기타금융자산|관계기업|투자부동산")
DERIV = re.compile(r"파생")
SECTION_IDS = {
    "ifrs-full_CurrentAssets": "CA",
    "ifrs-full_NoncurrentAssets": "NCA",
    "ifrs-full_Liabilities": "L",
    "ifrs-full_CurrentLiabilities": "L",
    "ifrs-full_NoncurrentLiabilities": "L",
    "ifrs-full_Equity": "E",
    "ifrs-full_EquityAndLiabilities": "E",
}


def bs_lines(con, corp: str, fs_div: str, year: int = 2026, reprt: str = "11012") -> pd.DataFrame:
    """2026 H1 balance-sheet lines with the section (CA / NCA / L / E) each line sits under (by `ord`)."""
    d = con.execute(
        """SELECT ord, account_id, account_nm, thstrm_amount FROM fs_raw
                       WHERE corp_code=? AND fs_div=? AND bsns_year=? AND reprt_code=? AND sj_div='BS'
                       ORDER BY ord""",
        [corp, fs_div, year, reprt],
    ).df()
    sec, out = None, []
    for r in d.itertuples(index=False):
        if r.account_id in SECTION_IDS:
            sec = SECTION_IDS[r.account_id]
            continue
        amt = pd.to_numeric(r.thstrm_amount, errors="coerce")
        out.append(
            {"section": sec, "account_nm": re.sub(r"\s+", " ", r.account_nm).strip(), "amount": 0 if pd.isna(amt) else int(amt)}
        )
    from src.clean.frames import frame

    return frame(out, ["section", "account_nm", "amount"])  # P7-B5: no lines -> empty table with the columns


def classify(lines: pd.DataFrame) -> dict:
    nm = lines.account_nm.str.replace(" ", "")
    deriv = nm.str.contains(DERIV)
    ca = (lines.section == "CA") & nm.str.contains(CASH_LIKE) & ~deriv & ~nm.str.contains("매출채권")
    nca = (lines.section == "NCA") & nm.str.contains(NON_OP) & ~deriv & ~nm.str.contains("매출채권")
    dl = lines.section.isin(["L"]) & deriv
    da = lines.section.isin(["CA", "NCA"]) & deriv

    def detail(m):
        return "; ".join(f"{a} {v / 1e8:,.1f}" for a, v in zip(lines.account_nm[m], lines.amount[m]) if v)

    return {
        "cash_like": int(lines.amount[ca].sum()),
        "non_operating": int(lines.amount[nca].sum()),
        "deriv_assets": int(lines.amount[da].sum()),
        "deriv_liab": int(lines.amount[dl].sum()),
        "cash_like_detail": detail(ca),
        "non_op_detail": detail(nca),
        "other_fin_flag": bool(nm[ca | nca].str.contains("기타").any()),
    }


def build(cfg_path: str | None = None, table: str = "peer_p3", as_of: str = AS_OF, dna_rule: dict | None = None) -> pd.DataFrame:
    """cfg_path: company config (default RF); table: output table (P3-C2: peer_jw); dna_rule: checked LTM D&A."""
    con = duckdb.connect(str(DB_PATH))
    std = con.sql("SELECT * FROM fs_std").df()
    rows = []
    ly, lp = (dna_rule or {}).get("ltm_year", 2026), (dna_rule or {}).get("ltm_period", "H1")  # config meta (P3-C3)
    rep = {"H1": "11012", "FY": "11011", "Q1": "11013", "Q3": "11014"}[lp]
    for c in companies(cfg_path):
        base = row_for(con, std, c, as_of, dna_rule)
        cl = classify(bs_lines(con, c["corp_code"], base["fs_div"], ly, rep))
        debt_inc = base["net_debt_inc_lease"] + _cash_std(con, c, base["fs_div"], ly, lp)  # back out P1 cash
        net_debt = debt_inc - cl["cash_like"]
        mc = base["mktcap"]
        ev = mc + net_debt - cl["non_operating"] + base["nci"] if mc is not None else None
        eq = _bs(con, c["corp_code"], base["fs_div"], "equity_parent" if base["fs_div"] == "CFS" else "total_equity", ly, lp)

        def mult(n, d):
            return None if n is None or d is None or d <= 0 else n / d

        rows.append(
            {
                **{
                    k: base[k]
                    for k in (
                        "name",
                        "tier",
                        "fs_div",
                        "revenue",
                        "ebitda",
                        "op",
                        "ni_parent",
                        "nci",
                        "mktcap",
                        "dna_missing",
                        "notes",
                    )
                },
                "total_debt_inc_lease": debt_inc,
                **cl,
                "net_debt": net_debt,
                "ev": ev,
                "ev_p1": base["ev"],
                "ev_sales": mult(ev, base["revenue"]),
                "ev_ebitda": mult(ev, base["ebitda"]),
                "per": mult(mc, base["ni_parent"]),
                "pbr": mult(mc, eq),
                "as_of": as_of,
            }
        )
    df = pd.DataFrame(rows)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
    con.close()
    return df


def _bs(con, corp, fs, acct, year: int = 2026, period: str = "H1"):
    r = con.execute(
        """SELECT amount FROM fs_std WHERE corp_code=? AND fs_div=? AND fiscal_year=? AND period=?
                       AND std_account=? AND is_default""",
        [corp, fs, year, period, acct],
    ).fetchone()
    return int(r[0]) if r and r[0] is not None else None


def _cash_std(con, c, fs, year: int = 2026, period: str = "H1") -> int:
    """cash + short_term_fin as P1 used them (to recover total debt incl. lease from P1's net debt)."""
    return (_bs(con, c["corp_code"], fs, "cash", year, period) or 0) + (
        _bs(con, c["corp_code"], fs, "short_term_fin", year, period) or 0
    )


def medians(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["ev_sales", "ev_ebitda", "per", "pbr"]
    out = {}
    for lab, tiers in (("core", ["core"]), ("core+extended", ["core", "extended"])):
        sub = df[df.tier.isin(tiers)]
        for col in cols:
            v = sub[col].dropna()
            out[(lab, col)] = {
                "n": len(v),
                "q25": v.quantile(0.25) if len(v) else None,
                "median": v.median() if len(v) else None,
                "q75": v.quantile(0.75) if len(v) else None,
            }
    return pd.DataFrame(out).T


if __name__ == "__main__":
    d = build()
    print(len(d), "rows written to peer_p3")
