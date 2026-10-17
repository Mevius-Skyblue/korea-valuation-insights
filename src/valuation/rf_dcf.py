"""P3-B: RF머트리얼즈 DCF and sum-of-the-parts (all assumptions in config/valuation_rf.yaml). No API calls.

Run: python -m src.valuation.rf_dcf      -> prints markdown, data/interim/p3b_tables.md, reports/figures/p3b_*.png

Structure (user decision D2, checked by src/valuation/structure.py)
    SOTP equity = parent package business EV (DCF, separate statements)
                + 30.91% x RF시스템즈 market cap at 2026-09-30 (shares listed that day)
                + parent net cash and non-operating assets at 2026-06-30 (separate BS; investment in the subsidiary
                  is a separate line and is not added - the subsidiary is counted once, at market)
    Cross-check   consolidated EV (parent DCF + RF시스템즈 simple DCF) − consolidated net debt + non-operating
                  − NCI at market (69.09% x market cap)
Timing (user correction): net cash is the 06-30 balance sheet, so cash flows start 2026-07-01 and are discounted to
06-30; the EV is then rolled to 09-30 with (1 + WACC)^(92/365). Net cash is not rolled.
Units: 억원 unless stated. Market data: 한국거래소 통계정보 (as-of single values only).
"""
from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd

from src.collect.core import ROOT
from src.db.build import DB_PATH
from src.valuation.assumptions import load_ledger, marginal_rate, progressive_tax, rf_code
from src.valuation.beta_p3 import peer_stats
from src.valuation.dcf import Period, roll_forward, run_dcf
from src.valuation.sotp import consolidated_equity, reconcile, sotp_equity
from src.valuation.structure import decide
from src.valuation.wacc import wacc

EOK = 1e8
SUB_CODE = "474610"
YEARS = list(range(2027, 2033))


# ---------------------------------------------------------------- inputs

def _wide(con, corp, fs):
    d = con.execute("""SELECT fiscal_year y, period p, std_account a, amount FROM fs_std
                       WHERE corp_code=? AND fs_div=? AND is_default""", [corp, fs]).df()
    return d.pivot_table(index=["y", "p"], columns="a", values="amount", aggfunc="first") / EOK


def _dna(con, corp, fs):
    d = con.execute("SELECT fiscal_year y, period p, item, amount FROM fs_dna WHERE corp_code=? AND fs_div=?",
                    [corp, fs]).df()
    return d.pivot_table(index=["y", "p"], columns="item", values="amount", aggfunc="first").sum(axis=1) / EOK


def _rate(con, code, d):
    return con.execute("""SELECT value FROM rates_daily WHERE rate_code=? AND freq='D' AND date<=?
                          ORDER BY date DESC LIMIT 1""", [code, d]).fetchone()[0] / 100


def load_inputs(con, led) -> dict:
    corp, code = led["meta"]["target"]["corp_code"], led["meta"]["target"]["stock_code"]
    as_of = led["meta"]["as_of"]
    po, pc = _wide(con, corp, "OFS"), _wide(con, corp, "CFS")
    dna_o = _dna(con, corp, "OFS")
    ps = led["parent_scenarios"]
    g = lambda w, k, y, p="FY": float(w.loc[(y, p), k]) if k in w and pd.notna(w.loc[(y, p), k]) else 0.0  # noqa: E731
    # historical ratios (separate statements)
    hist = pd.DataFrame({y: {"revenue": g(po, "revenue", y),
                             "capex": g(po, "capex_ppe", y) + g(po, "capex_intangibles", y),
                             "dna": float(dna_o.get((y, "FY"), np.nan))} for y in ps["hist_years"]}).T
    days = []
    for y in ps["nwc_days_years"]:
        rev, cogs = g(po, "revenue", y), g(po, "cogs", y)
        days.append({"dso": g(po, "receivables", y) / rev * 365, "dio": g(po, "inventories", y) / cogs * 365,
                     "dpo": g(po, "trade_payables", y) / cogs * 365,
                     "dcl": g(po, "contract_liabilities", y) / rev * 365})
    days = pd.DataFrame(days, index=ps["nwc_days_years"])
    ltm = lambda w, k: g(w, k, 2025) + g(w, k, 2026, "H1") - g(w, k, 2025, "H1")  # noqa: E731
    bs = lambda w, k: g(w, k, 2026, "H1")  # noqa: E731
    over = led["parent_bs_overrides"]["long_term_borrowings"] / EOK
    parent_debt = bs(po, "total_debt") + over
    parent = {"cash": bs(po, "cash"), "stf": bs(po, "short_term_fin"), "debt": parent_debt,
              "lease": bs(po, "lease_liabilities"), "ltf": bs(po, "long_term_fin"),
              "nwc": bs(po, "receivables") + bs(po, "inventories") - bs(po, "trade_payables")
              - bs(po, "contract_liabilities"),
              "h1_rev": g(po, "revenue", 2026, "H1"), "h1_op": g(po, "operating_income", 2026, "H1"),
              "cogs_ratio": ltm(po, "cogs") / ltm(po, "revenue"), "dna_2025": float(dna_o[(2025, "FY")]),
              "ppe": bs(po, "ppe"), "intangibles": bs(po, "intangibles"), "rou": bs(po, "rou_assets")}
    parent["net_cash"] = parent["cash"] + parent["stf"] - parent["debt"] - parent["lease"]
    inv = con.execute("""SELECT thstrm_amount FROM fs_raw WHERE corp_code=? AND fs_div='OFS' AND bsns_year=2026
                         AND reprt_code='11012' AND sj_div='BS' AND account_nm LIKE '종속기업투자%'""", [corp]).fetchone()
    parent["inv_subs_book"] = float(inv[0]) / EOK if inv else 0.0
    cons = {"cash": bs(pc, "cash"), "stf": bs(pc, "short_term_fin"), "debt": bs(pc, "total_debt"),
            "lease": bs(pc, "lease_liabilities"), "ltf": bs(pc, "long_term_fin"), "nci": bs(pc, "nci"),
            "nwc": bs(pc, "receivables") + bs(pc, "inventories") - bs(pc, "trade_payables")
            - bs(pc, "contract_liabilities")}
    cons["net_debt"] = cons["debt"] + cons["lease"] - cons["cash"] - cons["stf"]
    mc = lambda s: con.execute("""SELECT coalesce(f.mktcap_fix, d.mktcap), d.close FROM price_daily d
                                  LEFT JOIN mktcap_fix f ON f.stock_code=d.stock_code AND f.bas_dd=d.bas_dd
                                  WHERE d.stock_code=? AND d.bas_dd=?""", [s, as_of]).fetchone()  # noqa: E731
    sub_mc, _ = mc(SUB_CODE)
    rf_mc, rf_close = mc(code)
    bt = con.execute("SELECT * FROM beta_p3").df()
    ps_ = peer_stats(bt).set_index(["spec", "index"]).loc[("weekly_2y", "KOSDAQ")]
    rates = {k: _rate(con, k, as_of) for k in ("KTB5Y", "KTB10Y", "CB3Y_BBBm", "CB3Y_AAm")}
    return {"hist": hist, "days": days, "parent": parent, "cons": cons, "sub_mc": sub_mc / EOK, "rf_mc": rf_mc / EOK,
            "rf_close": float(rf_close), "beta": ps_, "rates": rates, "po": po, "pc": pc}


# ---------------------------------------------------------------- discount rate

def wacc_case(led, inp, srp: float, de: float | None = None, kd: float | None = None, t_kd: float = 0.22):
    b = inp["beta"]
    return wacc(inp["rates"][rf_code(led)], led["mrp"]["value"], float(b["median"]),
                float(b["de_avg_median"]) if de is None else de,
                inp["rates"]["CB3Y_BBBm"] if kd is None else kd, led["beta"]["tax_for_hamada"], t_kd, srp)


def tax_fn(led):
    br = led["corporate_tax"]["brackets"]
    return lambda base_eok: progressive_tax(base_eok * EOK, br) / EOK


# ---------------------------------------------------------------- parent business

def parent_case(led, inp, case: dict, growth_override: list[float] | None = None,
                days_by_year: dict[int, dict] | None = None) -> dict:
    """Forecast table (2H26, 2027..2032) for one scenario dict (rev_2026, g_2027, g_2028_2032, margin, g_terminal)."""
    ps, p = led["parent_scenarios"], inp["parent"]
    hist, days = inp["hist"], inp["days"].mean()
    capex_ratio = float((hist.capex / hist.revenue).median())
    life_m, life_b = ps["maintenance_capex_life_years"], ps["growth_capex_life_years"]
    growth = growth_override or [case["g_2027"], *case["g_2028_2032"]]
    rev_fy = {2026: case["rev_2026"]}
    for y, gr in zip(YEARS, growth):
        rev_fy[y] = rev_fy[y - 1] * (1 + gr)
    m = case["margin"]
    gcap = {"2H26": 0.0, 2027: 0.0}
    bldg = 0.0
    for gc in ps["growth_capex"]:
        key = gc["period"] if gc["period"] == "2H26" else int(gc["period"])
        gcap[key] += gc["amount"]
        bldg += gc["amount"] if gc["kind"] == "building" else 0.0
    rows, maint_hist = [], []                 # (year, amount) of maintenance capex for depreciation

    def nwc(y):
        r = rev_fy[y]
        cogs = r * p["cogs_ratio"]
        d = days_by_year[y] if days_by_year and y in days_by_year else days    # P3-B2 NWC sensitivity path
        return r * d["dso"] / 365 + cogs * d["dio"] / 365 - cogs * d["dpo"] / 365 - r * d["dcl"] / 365
    prev_nwc = p["nwc"]
    for lab, y, start in [("2H26", 2026, date(2026, 7, 1))] + [(str(y), y, date(y, 1, 1)) for y in YEARS]:
        end = date(y, 12, 31)
        rev = rev_fy[2026] - p["h1_rev"] if lab == "2H26" else rev_fy[y]
        ebit = rev * m
        if lab == "2H26" and case.get("op_2026") is not None:   # P3-C1 broker case: FY2026 OP given -> 2H = FY − H1
            ebit = case["op_2026"] - p["h1_op"]
        fy_ebit = p["h1_op"] + ebit if lab == "2H26" else ebit
        f = ((end - start).days + 1) / 365
        maint = capex_ratio * rev
        # straight line: earlier maintenance capex a full period, this period's capex half of it (spent evenly)
        dep_m = (sum(a for (_, a) in maint_hist) / life_m) * f + maint / life_m * f / 2
        maint_hist.append((y, maint))
        dep_b = bldg / life_b if y >= 2028 else 0.0           # new plant from 2028 (completion end-2027)
        dna = p["dna_2025"] * f + dep_m + dep_b               # existing assets held at the FY2025 level
        capex = maint + gcap.get(lab if lab == "2H26" else y, 0.0)
        cur_nwc = nwc(y)
        rows.append({"label": lab, "start": start, "end": end, "revenue": rev, "ebit": ebit, "fy_ebit": fy_ebit,
                     "dna": dna, "capex": capex, "maint_capex": maint, "growth_capex": capex - maint,
                     "nwc": cur_nwc, "dnwc": cur_nwc - prev_nwc})
        prev_nwc = cur_nwc
    t = pd.DataFrame(rows)
    return {"table": t, "rev_fy": rev_fy, "capex_ratio": capex_ratio, "days": days, "margin": m,
            "g_terminal": case["g_terminal"]}


def parent_value(led, inp, fc: dict, w: float, g: float | None = None, exit_multiple: float | None = None):
    t = fc["table"]
    tx = tax_fn(led)
    periods = [Period(r.label, r.start, r.end, r.ebit, r.dna, r.capex, r.dnwc, tax_base=r.fy_ebit)
               for r in t.itertuples()]
    g = fc["g_terminal"] if g is None else g
    last = t.iloc[-1]
    rate = tx(last.ebit) / last.ebit if last.ebit > 0 else 0.0
    capex_n = last.dna * led["dcf"]["terminal_capex_to_dna"]
    fcf_norm = last.ebit * (1 - rate) + last.dna - capex_n - last.nwc * g
    r = run_dcf(periods, tx, w, date.fromisoformat(led["dcf"]["discount_date"]), g=g,
                exit_multiple=exit_multiple if exit_multiple is not None else led["dcf"]["exit_multiple"]["value"],
                mid_year=led["dcf"]["mid_year"], fcf_norm=fcf_norm, ebitda_final=last.ebit + last.dna)
    days = (date.fromisoformat(led["meta"]["as_of"]) - date.fromisoformat(led["dcf"]["discount_date"])).days
    return r, roll_forward(r.ev_gordon, w, days), roll_forward(r.ev_exit, w, days), days


# ---------------------------------------------------------------- subsidiary (cross-check only)

def sub_value(led, inp, w: float, segs: dict):
    s = led["subsidiary_simple"]
    gr, m = s["growth"], s["margin"]
    rev_2h25 = segs["FY2025"]["revenue"] - segs["1H25"]["revenue"]
    rev_2h = rev_2h25 * (1 + gr)
    fy26 = segs["1H26"]["revenue"] + rev_2h
    ltm_rev = segs["FY2025"]["revenue"] + segs["1H26"]["revenue"] - segs["1H25"]["revenue"]
    ltm_dep = segs["FY2025"]["depreciation"] + segs["1H26"]["depreciation"] - segs["1H25"]["depreciation"]
    da_ratio = ltm_dep / ltm_rev
    nwc0 = inp["cons"]["nwc"] - inp["parent"]["nwc"]
    periods, rev, prev = [], None, fy26
    for lab, y in [("2H26", 2026)] + [(str(y), y) for y in YEARS]:
        if lab == "2H26":
            rev, start = rev_2h, date(2026, 7, 1)
            fy_ebit = segs["1H26"]["op"] + rev * m
            dnwc = nwc0 * gr * 0.5
        else:
            prev = prev * (1 + gr)
            rev, start, fy_ebit, dnwc = prev, date(y, 1, 1), prev * m, nwc0 * (1 + gr) ** (y - 2026) * gr
        dna = rev * da_ratio
        periods.append(Period(lab, start, date(y, 12, 31), rev * m, dna, dna * s["capex_to_dna"], dnwc, tax_base=fy_ebit))
    tx = tax_fn(led)
    r = run_dcf(periods, tx, w, date.fromisoformat(led["dcf"]["discount_date"]), g=s["g_terminal"],
                mid_year=led["dcf"]["mid_year"])
    days = (date.fromisoformat(led["meta"]["as_of"]) - date.fromisoformat(led["dcf"]["discount_date"])).days
    return r, roll_forward(r.ev_gordon, w, days), {"da_ratio": da_ratio, "nwc0": nwc0, "rev_2h26": rev_2h}


# ---------------------------------------------------------------- equity

def sotp_for(led, inp, ev_parent_930: float):
    stake = led["nci"]["subsidiary"]["parent_stake"]
    p = inp["parent"]
    return sotp_equity({"모회사 패키지 사업": ev_parent_930}, {"RF시스템즈": (stake, inp["sub_mc"])}, p["net_cash"],
                       p["ltf"], investment_in_subs_book=0.0, unallocated_hq_pv=0.0)


def per_share(led, equity_eok: float) -> float:
    return equity_eok * EOK / led["shares"]["outstanding_as_of"]


def solve_growth(led, inp, base_case: dict, margin: float, w: float, target_ps: float) -> float | None:
    """Uniform 2027..2032 growth that makes the SOTP per-share value equal target_ps (bisection)."""
    def f(gu):
        fc = parent_case(led, inp, {**base_case, "margin": margin}, growth_override=[gu] * len(YEARS))
        _, ev, _, _ = parent_value(led, inp, fc, w)
        return per_share(led, sotp_for(led, inp, ev).equity) - target_ps
    lo, hi = -0.2, 1.5
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def segments_from_filings() -> dict:
    from src.valuation.rf_disclosure import segments
    out = {}
    for lab, rc, per in (("FY2025", "20260318001224", "current"), ("1H25", "20260814001631", "comparative"),
                         ("1H26", "20260814001631", "current")):
        s = segments(rc)
        s = s[(s.period == per)].set_index("entity")
        out[lab] = {"revenue": s.loc["subsidiary", "revenue"] / 1e5, "op": s.loc["subsidiary", "operating_income"] / 1e5,
                    "depreciation": s.loc["subsidiary", "depreciation"] / 1e5}
        out[lab + "_parent"] = {"revenue": s.loc["parent", "revenue"] / 1e5, "op": s.loc["parent", "operating_income"] / 1e5}
    return out


# ---------------------------------------------------------------- report

def md(df: pd.DataFrame, fmt: str = "{:,.1f}") -> str:
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else fmt.format(v))
    head = "| " + " | ".join(map(str, [d.index.name or ""] + list(d.columns))) + " |"
    return "\n".join([head, "|" + "---|" * (len(d.columns) + 1)] +
                     ["| " + " | ".join(map(str, [i] + list(r))) + " |" for i, r in zip(d.index, d.values)])


def main() -> str:
    led = load_ledger()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    inp = load_inputs(con, led)
    con.close()
    segs = segments_from_filings()
    out, price = [], inp["rf_close"]
    cases = led["parent_scenarios"]["cases"]
    srps = led["decisions"]["srp_columns"]
    p = inp["parent"]

    # structure rule
    stake = led["nci"]["subsidiary"]["parent_stake"]
    nci_mv = (1 - stake) * inp["sub_mc"]
    def ltm(k, item):                       # LTM = FY2025 + 1H26 - 1H25 (segment note)
        return segs[f"FY2025{k}"][item] + segs[f"1H26{k}"][item] - segs[f"1H25{k}"][item]
    seg_rows = [{"name": nm, "margin": 100 * ltm(k, "op") / ltm(k, "revenue"),
                 "growth": 100 * (segs[f"1H26{k}"]["revenue"] / segs[f"1H25{k}"]["revenue"] - 1)}
                for nm, k in (("모회사", "_parent"), ("RF시스템즈", ""))]
    dec = decide(nci_mv, inp["rf_mc"], True, seg_rows)
    out.append("## 2. 구조 판단\n")
    out.append(f"- 판정: **{dec.method}** — " + "; ".join(dec.reasons))
    out.append("- 점검값: " + "; ".join(f"{k} {v[0]:.3f} (기준 {v[1]}) → {v[2]}" if isinstance(v[0], float)
                                     else f"{k} {v[0]} → {v[2]}" for k, v in dec.checks.items()))
    out.append("- 부문 입력: " + "; ".join(f"{s['name']} LTM 이익률 {s['margin']:.1f}%·1H 매출 성장 {s['growth']:.1f}%"
                                      for s in seg_rows))
    out.append(f"- 사용자 결정(D2)과 일치: {dec.method == led['decisions']['structure']}\n")
    out.append(f"- 본사 공통비: 부문 주석 모회사 영업이익(1H26 {segs['1H26_parent']['op']:.2f}억)과 별도 손익계산서 "
               f"영업이익({p['h1_op']:.2f}억)이 같다 → 미배분 공통비 없음(0)\n")

    # inputs
    out.append("## 4.0 입력\n")
    hist = inp["hist"].assign(capex_ratio=lambda d: d.capex / d.revenue * 100, dna_ratio=lambda d: d.dna / d.revenue * 100)
    hist.index.name = "모회사 별도"
    out.append(md(hist))
    out.append("\n회전일수(별도 FY2023~2025)\n\n" + md(inp["days"].assign(**{}).rename_axis("연도")))
    out.append(f"\n평균 DSO {inp['days'].dso.mean():.1f} / DIO {inp['days'].dio.mean():.1f} / DPO {inp['days'].dpo.mean():.1f}"
               f" / 계약부채 {inp['days'].dcl.mean():.1f}일, 매출원가율(LTM) {p['cogs_ratio']:.1%}\n")
    out.append(md(pd.DataFrame({"억원": [p["cash"], p["stf"], p["debt"], p["lease"], p["net_cash"], p["ltf"],
                                       p["inv_subs_book"], p["nwc"], inp["sub_mc"], stake * inp["sub_mc"], nci_mv,
                                       inp["rf_mc"]]},
                              index=["모회사 현금", "모회사 단기금융자산", "모회사 차입금(보정 포함)", "모회사 리스부채",
                                     "모회사 순현금", "모회사 장기금융자산(비영업)", "종속기업투자(장부, 더하지 않음)",
                                     "모회사 순운전자본(6/30)", "RF시스템즈 시가총액(9/30)", "지분 30.91% 시가",
                                     "비지배 69.09% 시가", "RF 시가총액(9/30)"]).rename_axis("2026-06-30 / 09-30")))

    # WACC per SRP
    res, waccs = [], {}
    for s in srps:
        for name, case in cases.items():
            fc = parent_case(led, inp, case)
            t_kd = marginal_rate(fc["table"].iloc[-1].ebit * EOK, led["corporate_tax"]["brackets"])
            wr = wacc_case(led, inp, s, t_kd=t_kd)
            waccs[(name, s)] = wr
            r, evg, eve, days = parent_value(led, inp, fc, wr.wacc)
            sg, se = sotp_for(led, inp, evg), sotp_for(led, inp, eve)
            res.append({"scenario": name, "srp": s, "wacc": wr.wacc, "ke": wr.ke, "ev_parent_630": r.ev_gordon,
                        "ev_parent": evg, "equity": sg.equity, "per_share": per_share(led, sg.equity),
                        "vs_price": per_share(led, sg.equity) / price - 1,
                        "per_share_exit": per_share(led, se.equity), "tv_share": r.tv_share_gordon,
                        "tv_share_exit": r.tv_share_exit, "implied_multiple": r.implied_multiple,
                        "implied_g": r.implied_g, "pv_explicit": r.pv_explicit, "fc": fc, "r": r})
    R = pd.DataFrame(res)
    order = ["pessimistic", "base", "optimistic"]
    out.append("\n## 4.1 시나리오 × SRP\n")
    for col, lab, f in (("per_share", "주당 가치(원, Gordon)", "{:,.0f}"), ("vs_price", "기준일 종가 대비", "{:+.1%}"),
                        ("wacc", "WACC", "{:.2%}"), ("ev_parent", "모회사 사업 EV(9/30, 억원)", "{:,.1f}"),
                        ("equity", "SOTP 주식가치(억원)", "{:,.1f}"), ("tv_share", "영구가치 비중(Gordon)", "{:.1%}"),
                        ("implied_multiple", "Gordon 함의 EV/EBITDA", "{:.1f}"), ("per_share_exit", "주당 가치(원, Exit 14.57배)", "{:,.0f}"),
                        ("implied_g", "Exit 함의 g", "{:.2%}"), ("tv_share_exit", "영구가치 비중(Exit)", "{:.1%}")):
        pv = R.pivot(index="scenario", columns="srp", values=col).loc[order]
        pv.columns = [f"SRP {c:.0%}" for c in pv.columns]
        pv.index.name = lab
        out.append(md(pv, f) + "\n")
    # SOTP breakdown, base SRP 0
    b0 = R[(R.scenario == "base") & (R.srp == 0)].iloc[0]
    sg = sotp_for(led, inp, b0.ev_parent)
    bd = pd.DataFrame({"억원": list(sg.parts.values())}, index=list(sg.parts.keys()))
    bd.loc["= SOTP 주식가치"] = sg.equity
    bd.loc["주당(원)"] = per_share(led, sg.equity)
    bd.index.name = "기본 시나리오, SRP 0%"
    out.append(md(bd))
    # forecast table base
    ft = b0.fc["table"].set_index("label")[["revenue", "ebit", "dna", "capex", "growth_capex", "dnwc", "nwc"]].T
    tab = b0.r.table.set_index("label")[["tax_rate", "fcff", "t", "pv"]].T
    ft = pd.concat([ft, tab])
    ft.index.name = "기본 시나리오(억원)"
    out.append("\n" + md(ft.astype(float), "{:,.2f}"))
    out.append(f"\nTV(Gordon, 2032 말) {b0.r.tv_gordon:,.1f}억, PV {b0.r.pv_tv_gordon:,.1f}억, 명시기간 PV {b0.r.pv_explicit:,.1f}억, "
               f"6/30 EV {b0.ev_parent_630:,.1f}억 → 9/30 이월(×(1+{b0.wacc:.4f})^(92/365)) {b0.ev_parent:,.1f}억; "
               f"유지 CAPEX/매출 {b0.fc['capex_ratio']:.2%}\n")
    for name in order:
        fcx = R[(R.scenario == name) & (R.srp == 0)].iloc[0].fc
        rv = fcx["rev_fy"]
        out.append(f"- {name}: 매출 " + ", ".join(f"{y} {v:,.0f}" for y, v in rv.items()) +
                   f"; 이익률 {fcx['margin']:.0%}, g {fcx['g_terminal']:.1%}")

    # sensitivity: WACC x g (base, SRP 0)
    fcb = parent_case(led, inp, cases["base"])
    wb = waccs[("base", 0.0)].wacc
    sens = {}
    for dw in (-0.02, -0.01, 0.0, 0.01, 0.02):
        for g in (0.01, 0.015, 0.02, 0.025, 0.03):
            _, ev, _, _ = parent_value(led, inp, fcb, wb + dw, g=g)
            sens[(f"{wb + dw:.2%}", f"g {g:.1%}")] = per_share(led, sotp_for(led, inp, ev).equity)
    s1 = pd.Series(sens).unstack()
    s1.index.name = "WACC \\ g (주당 원)"
    out.append("\n## 4.2 민감도\n\n" + md(s1, "{:,.0f}"))
    # sensitivity: 2027-2030 growth x margin
    base_path = [cases["base"]["g_2027"], *cases["base"]["g_2028_2032"]]
    sens2 = {}
    for gx in (0.10, 0.20, 0.30, 0.40, 0.50):
        for m in (0.15, 0.18, 0.21, 0.24, 0.27):
            path = [gx] * 4 + base_path[4:]
            fc = parent_case(led, inp, {**cases["base"], "margin": m}, growth_override=path)
            _, ev, _, _ = parent_value(led, inp, fc, wb)
            sens2[(f"{gx:.0%}", f"이익률 {m:.0%}")] = per_share(led, sotp_for(led, inp, ev).equity)
    s2 = pd.Series(sens2).unstack()
    s2.index.name = "2027~2030 성장률 \\ 정상 이익률"
    out.append("\n" + md(s2, "{:,.0f}"))
    # D/E 0 and Kd AA- (base, SRP 0)
    alt = {}
    for lab, kw in (("기본(D/E 0.253, Kd BBB-)", {}), ("D/E 0", {"de": 0.0}),
                    ("Kd AA- 4.703%", {"kd": inp["rates"]["CB3Y_AAm"]})):
        t_kd = marginal_rate(fcb["table"].iloc[-1].ebit * EOK, led["corporate_tax"]["brackets"])
        wr = wacc_case(led, inp, 0.0, t_kd=t_kd, **kw)
        _, ev, _, _ = parent_value(led, inp, fcb, wr.wacc)
        alt[lab] = {"WACC": wr.wacc * 100, "주당(원)": per_share(led, sotp_for(led, inp, ev).equity)}
    out.append("\n" + md(pd.DataFrame(alt).T.rename_axis("기본 시나리오, SRP 0%"), "{:,.2f}"))

    # reverse DCF
    rev_pts = {}
    for m in (0.15, 0.18, 0.21, 0.24, 0.27, 0.30):
        rev_pts[m] = solve_growth(led, inp, cases["base"], m, wb, price)
    rp = pd.DataFrame({"필요 성장률(2027~2032 연평균)": rev_pts}).rename_axis("정상 이익률")
    rp.index = [f"{m:.0%}" for m in rp.index]
    rp.index.name = "정상 이익률"
    out.append(f"\n## 4.3 역DCF (기본 WACC {wb:.2%}, g 2.0%, 2026 매출 500억, 종가 {price:,.0f}원)\n\n" + md(rp, "{:.1%}"))
    rev2032 = {m: 500 * (1 + g) ** 6 if g is not None else None for m, g in rev_pts.items()}
    out.append("\n2032 매출 함의(억원): " + ", ".join(f"이익률 {m:.0%} → {v:,.0f}" for m, v in rev2032.items() if v))

    # cross-check: consolidated DCF − NCI at market
    rs, ev_sub, meta = sub_value(led, inp, wb, segs)
    evp = b0.ev_parent
    cons_eq = consolidated_equity(evp + ev_sub, inp["cons"]["net_debt"], inp["cons"]["ltf"], nci_mv)
    sub_nc = (inp["cons"]["cash"] + inp["cons"]["stf"] - inp["cons"]["debt"] - inp["cons"]["lease"]) - p["net_cash"]
    sub_nonop = inp["cons"]["ltf"] - p["ltf"]
    sub_intr = ev_sub + sub_nc + sub_nonop
    rec = reconcile(sg, cons_eq, stake, inp["sub_mc"], sub_intr)
    book_eq = consolidated_equity(evp + ev_sub, inp["cons"]["net_debt"], inp["cons"]["ltf"], inp["cons"]["nci"])
    cc = pd.DataFrame({"억원": [evp, ev_sub, inp["cons"]["net_debt"], inp["cons"]["ltf"], nci_mv, cons_eq,
                              per_share(led, cons_eq), sg.equity, per_share(led, sg.equity), rec["difference"],
                              sub_intr, inp["sub_mc"], rec["subsidiary_market_vs_intrinsic"], rec["other"],
                              book_eq, per_share(led, book_eq)]},
                      index=["모회사 EV(9/30)", "RF시스템즈 EV(9/30, 단순 DCF)", "연결 순차입금(6/30)",
                             "연결 비영업자산", "비지배지분 시가", "연결 주식가치(비지배 시가)", "  주당(원)",
                             "SOTP 주식가치", "  주당(원)", "차이(SOTP − 연결)", "RF시스템즈 내재 주식가치(DCF+순현금+비영업)",
                             "RF시스템즈 시가총액", "  차이 중 RF시스템즈 시가 − 내재(100%)", "  나머지",
                             "참고: 연결 − 비지배 장부", "  주당(원)"]).rename_axis("기본 시나리오, SRP 0%")
    out.append("\n## 4.4 교차 확인\n\n" + md(cc))
    out.append(f"\nRF시스템즈 단순 DCF: 2H26 매출 {meta['rev_2h26']:.1f}억, D&A/매출 {meta['da_ratio']:.2%}, 순운전자본(연결−모회사) "
               f"{meta['nwc0']:.1f}억, 순현금 {sub_nc:.1f}억, 비영업 {sub_nonop:.1f}억, 영구가치 비중 {rs.tv_share_gordon:.1%}\n")

    # figures
    _figures(R, order, srps, price, rp)
    text = "\n".join(out)
    (ROOT / "data" / "interim" / "p3b_tables.md").write_text(text, encoding="utf-8")
    R.drop(columns=["fc", "r"]).to_csv(ROOT / "data" / "interim" / "p3b_results.csv", index=False)
    return text


def _figures(R, order, srps, price, rp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    fig_dir = ROOT / "reports" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    lab = {"pessimistic": "비관", "base": "기본", "optimistic": "낙관"}
    fig, ax = plt.subplots(figsize=(7, 4))
    wbar = 0.25
    colors = ["#2a6f97", "#61a5c2", "#a9d6e5"]
    for i, s in enumerate(srps):
        vals = [R[(R.scenario == o) & (R.srp == s)].per_share.iloc[0] for o in order]
        ax.bar(np.arange(3) + (i - 1) * wbar, vals, wbar, label=f"SRP {s:.0%}", color=colors[i])
    ax.axhline(price, color="#c1121f", ls="--", lw=1)
    ax.text(2.45, price, f"기준일 종가 {price:,.0f}원", color="#c1121f", va="bottom", ha="right", fontsize=8)
    ax.set_xticks(range(3), [lab[o] for o in order])
    ax.set_ylabel("주당 가치(원, 가정 하 추정)")
    ax.set_title("RF머트리얼즈 SOTP 주당 가치: 시나리오 × SRP (초안)")
    ax.legend(fontsize=8)
    fig.text(0.01, 0.01, "가정 기반 계산(투자 권유 아님). 기준일 2026-09-30, 종가는 한국거래소 통계정보", fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(fig_dir / "p3b_per_share_scenarios.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 4))
    pts = rp.iloc[:, 0].dropna()
    ax.plot([float(i.strip("%")) for i in pts.index], pts.values * 100, marker="o", color="#2a6f97")
    for x, y in zip(pts.index, pts.values):
        ax.annotate(f"{y:.1%}", (float(x.strip('%')), y * 100), textcoords="offset points", xytext=(4, 4), fontsize=8)
    ax.set_xlabel("모회사 정상 영업이익률(%)")
    ax.set_ylabel("2027~2032 연평균 매출 성장률(%)")
    ax.set_title("역DCF: 기준일 종가를 맞추는 성장률·이익률 조합 (초안)")
    fig.text(0.01, 0.01, "기본 WACC·g 2.0%·2026 매출 500억, 나머지 가정은 기본 시나리오", fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(fig_dir / "p3b_reverse_dcf.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    print(main())
