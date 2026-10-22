"""Listed associates at market value (P7-X2b, config/p7x2b.yaml associates). Pure pieces + the rule parameters.

Consolidated operating FCF leaves out the share of profit of associates (K-IFRS 1001.82(c)), so the associates sit outside
EV as a non-operating asset. The bridge used to add the balance-sheet line (equity-method book) only; for associates that
are listed, the observable price is used instead (shares held x close x (1 − discount)) and their book is taken out of the
associates line (no double count):

    params()                                  config/p7x2b.yaml params (cached per process)
    is_assoc_line(name)                       an associates / joint-venture / equity-method line name
    assoc_bridge(lines, rows, discount, ...)  market value, the book replaced, the line total (원)
    equity_income_rows(rows)                  equity-method income lines above the operating-income line, by report

Amounts in 원, shares in 주. The engine (company_dcf) and the Excel Bridge rows use the same rule.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from src import yamlio
from src.collect.core import ROOT


@lru_cache(maxsize=1)
def params() -> dict:
    """The P7-X2b rule numbers (config/p7x2b.yaml params).
    Audit switch (not for normal runs): environment variable KVI_X2B_OFF = comma list of rules turned off for the
    attribution of changed results (ronic, guard_b, assoc, events, judge) - scripts/audit/inv_p7x2b.py."""
    import os

    p = yamlio.load((ROOT / "config" / "p7x2b.yaml").read_text(encoding="utf-8"))["params"]
    off = {x.strip() for x in os.environ.get("KVI_X2B_OFF", "").split(",") if x.strip()}
    if off:
        p = {**p, "off": sorted(off)}
        if "ronic" in off:
            p["ronic_floor"] = False
        if "guard_b" in off:
            p["guard_b_abs"] = False
    return p


def off(rule: str) -> bool:
    """True when an audit run turned the rule off (KVI_X2B_OFF)."""
    return rule in (params().get("off") or [])


def is_assoc_line(name: str) -> bool:
    return bool(re.search(params()["associates"]["line_regex"], str(name).replace(" ", "")))


def carrying(row: dict, basis: str) -> float:
    """Book of one associate the bridge takes out: consolidated = estimated equity-method book (stake x the associate's
    owners' equity), else the separate book of the investee list (exact for the separate statements)."""
    if basis == "CFS" and row.get("est_carrying") is not None:
        return float(row["est_carrying"])
    return float(row.get("book") or 0.0)


def assoc_bridge(lines: pd.DataFrame, rows: list[dict], discount: float, basis: str, remainder: float = 0.0) -> dict:
    """Bridge pieces of the listed associates (원).
    lines: the balance-sheet lines the bridge classifies (peer_p3.classify input, '종속' lines already out for SOTP).
    L = associate lines counted as non-operating; the book replaced = min(L, Σ carrying); when L is 0 and the associates
    sit in the SOTP replaced line, min(remainder, Σ carrying)."""
    from src.valuation.peer_p3 import DERIV, NON_OP

    nm = lines.account_nm.astype(str).str.replace(" ", "") if len(lines) else pd.Series(dtype=str)
    m = (
        (lines.section == "NCA")
        & nm.str.contains(NON_OP)
        & ~nm.str.contains(DERIV)
        & ~nm.str.contains("매출채권")
        & nm.map(is_assoc_line)
        if len(lines)
        else pd.Series(dtype=bool)
    )
    L = float(lines.amount[m].sum()) if len(lines) else 0.0
    held = [x for x in rows if x.get("shares")]
    est = sum(carrying(x, basis) for x in held)
    listed = sum(float(x["shares"]) * float(x["close"] or 0) for x in held)
    missing = [x["name"] for x in held if not x.get("close")]
    if L > 0:
        replaced, where = min(L, est), "lines"
    elif remainder > 0:
        replaced, where = min(remainder, est), "sotp_remainder"
    else:
        replaced, where = 0.0, "none"
    return {
        "lines": L,
        "est": est,
        "replaced": replaced,
        "replaced_from": where,
        "listed": listed,
        "discount": discount,
        "value": listed * (1 - discount),
        "add": listed * (1 - discount) - replaced,
        "missing_close": missing,
    }


def equity_income_rows(rows: pd.DataFrame) -> dict:
    """{(year, period): {'amount': 원, 'in_revenue': bool, 'labels': [...]}} of '지분법' lines above the operating-income
    line (IS / CIS, FY = 11011 current, H1 = 11012 year-to-date). in_revenue: the line comes before the first expense line
    (매출원가 / 영업비용 / 판매비), i.e. inside operating revenue."""
    out = {}
    if rows is None or not len(rows):
        return out
    rx = params()["associates"]["equity_regex"]
    # X2b-F2: one statement at a time (a separate IS and CIS each number their lines from 1, so a CIS line could sit
    # 'above' the IS operating-income line), the IS first; aggregate / OCI / adjustment lines are not equity income
    # ('수익(매출과지분법손익)' is the revenue total, '지분법자본변동' and '…기타포괄손익…' are OCI)
    rows = rows.assign(sj_div=rows["sj_div"] if "sj_div" in rows.columns else "IS")
    not_income = params()["associates"].get("equity_exclude_regex", "매출|수익[(]|자본변동|기타포괄|조정")
    for (y, rep, _sj), g in sorted(
        rows.groupby(["bsns_year", "reprt_code", "sj_div"]), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] != "IS")
    ):
        if (int(y), "FY" if rep == "11011" else "H1") in out:
            continue  # the IS already gave this period
        nm = g.account_nm.astype(str).str.replace(" ", "")
        op = g[(g.account_id == "dart_OperatingIncomeLoss") | nm.str.startswith("영업이익") | nm.str.startswith("영업손실")]
        if op.empty:
            continue
        cut = op.ord.min()
        ex = g[nm.str.contains("매출원가|영업비용|판매비") & (g.ord < cut)]
        first_exp = ex.ord.min() if len(ex) else None
        hit = g[nm.str.contains(rx) & (g.ord < cut) & ~nm.str.contains("관계기업투자|투자주식") & ~nm.str.contains(not_income)]
        if hit.empty:
            continue
        col = "thstrm_num" if rep == "11011" else "thstrm_add_num"
        v = pd.to_numeric(hit[col], errors="coerce").fillna(pd.to_numeric(hit.thstrm_num, errors="coerce")).fillna(0.0)
        hn = hit.account_nm.astype(str).str.replace(" ", "")
        loss = hn.str.contains("손실") & ~hn.str.contains("이익|손익")  # a '지분법손실' line shows the loss as a positive amount
        amt = float((v.where(~loss, -v)).sum())
        if amt:
            out[(int(y), "FY" if rep == "11011" else "H1")] = {
                "amount": amt,
                "in_revenue": first_exp is not None and bool((hit.ord < first_exp).all()),
                "labels": sorted(set(hit.account_nm.astype(str))),
            }
    return out
