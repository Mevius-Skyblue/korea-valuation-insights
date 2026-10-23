"""Collect every number an Excel model needs from the company config, the DB and the P3 engine inputs (no API calls).

load_model_data(cfg_path) -> dict
    The company config (e.g. config/valuation_rf.yaml) names the forecast type in `excel.forecast_type`.
    P4-A implements `scenario_capex` (the rf_dcf2 engine: scenario revenue path + normal margin, maintenance / growth
    CAPEX depreciation, working-capital days, explicit -> fade -> value-driver terminal). P4-B adds the mechanical
    consolidated engine (company_dcf) under its own type.
Units: amounts in 백만원 (the engine works in 억원: x 100), per-share values in 원, rates as decimals.
Every value carries a source string so the Inputs sheet can show it next to the number.
Market data (한국거래소 통계정보) only as single as-of values or aggregates: close, market caps, one 20-day VWAP,
beta regression results, the market-cap percentile and premium-DB quantiles. No price series.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src import yamlio
from src.collect.core import ROOT
from src.db.build import DB_PATH
from src.valuation.assumptions import load_ledger
from src.workbench.snapdata import seam

EOK_TO_MN = 100.0  # 억원 -> 백만원
MN = 1e6
KRX = "한국거래소 통계정보"


def _ledger_text(led: dict) -> dict:
    """Source texts of the discount ledger shown in Inputs (config/valuation_rf.yaml risk_free.value_series / options,
    mrp.as_of)."""
    vs = led["risk_free"]["value_series"]
    o10 = next((o for o in led["risk_free"].get("options") or [] if o.get("code") == "KTB10Y"), {})
    return {
        "rf_series": f"ECOS {vs['stat']} {vs['item']} ({vs['code']})",
        "rf10_series": f"ECOS {vs['stat']} {o10.get('item', '')} ({o10.get('code', 'KTB10Y')})",
        "mrp_asof": str(led["mrp"].get("as_of", "")),
    }


def load_model_data(cfg_path: str = "config/valuation_rf.yaml", with_engine: bool = True) -> dict:
    from src.db.ro import shared_readonly

    with shared_readonly():  # P7-C1 speed: one read-only DB connection for the whole read
        return _load_model_data(cfg_path, with_engine)


def _load_model_data(cfg_path: str, with_engine: bool) -> dict:
    raw = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
    ftype = raw["excel"]["forecast_type"]
    led = load_ledger(ROOT / cfg_path) if ftype == "scenario_capex" else None
    if ftype == "scenario_capex":
        data = scenario_capex_data(led)
    elif ftype == "mechanical":
        data = mechanical_data(cfg_path)
    else:
        raise NotImplementedError(f"forecast_type {ftype!r}")
    data["type"] = ftype
    data["cfg_path"] = cfg_path
    from src.report.engagement import engagement

    data["engagement"] = engagement(raw)  # P7-X2b: purpose / premise / evaluator (defaults = the earlier texts)
    from src.report.engagement import example_label

    data["example_label"] = example_label(raw)  # P7-D: round example prices of the public screen
    from src.valuation.company_dcf import _close, _con
    from src.workbench.public_deploy import p5b_excel_data  # P6-A: P5-B reference aggregates (display only)

    con = _con()  # P7-C3: None in the public snapshot (seam replays)
    try:
        data["p5b_ref"] = p5b_excel_data(con)
    finally:
        _close(con)
    if with_engine:
        from src.excel import engine_ref

        data["engine"] = (
            engine_ref.scenario_capex_reference(led) if ftype == "scenario_capex" else engine_ref.mechanical_reference(cfg_path)
        )
        if raw.get("public_mode"):  # P7-C1 public mode: per-peer / per-date KRX rows -> aggregates
            from src.workbench.public import transform

            data = transform(data)
    return data


def _rf_choice(led: dict, rates: dict) -> dict:
    """P6-A Rf tenor choice: the selected tenor (default 5) and the 국고채 10년 value of the same date (DB rates_daily)."""
    rf = led["risk_free"]
    return {"rf_tenor": int(rf.get("tenor", 5)), "rf10": rates["KTB10Y"], "rf_tenor_basis": rf["tenor_basis"]}


@seam("mode_rcept", key=lambda con, corp, fs, year, period: (corp, fs, year, period))
def _mode_rcept(con, corp: str, fs: str, year: int, period: str) -> tuple[str, list[str]]:
    rows = con.execute(
        """SELECT rcept_no FROM fs_std WHERE corp_code=? AND fs_div=? AND fiscal_year=? AND period=?
                          AND is_default""",
        [corp, fs, year, period],
    ).fetchall()
    c = Counter(r[0] for r in rows if r[0])
    if not c:
        return "", []
    main = c.most_common(1)[0][0]
    return main, sorted(k for k in c if k != main)


def scenario_capex_data(led: dict) -> dict:
    from src.market.beta_table import companies
    from src.premium.predict import mktcap_percentile, premium_range
    from src.valuation.p3c1 import vwap20
    from src.valuation.peer_p3 import _bs
    from src.valuation.rf_dcf import _dna, load_inputs, segments_from_filings
    from src.valuation.structure import load_rules

    meta = led["meta"]
    corp, code = meta["target"]["corp_code"], meta["target"]["stock_code"]
    as_of = meta["as_of"]
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        inp = load_inputs(con, led)
        segs = segments_from_filings()
        ps = led["parent_scenarios"]
        ly = int(meta["ltm"]["year"])

        # ---- historical statements used by the engine (separate = OFS for the parent, CFS for the cross-check)
        po, pc = inp["po"], inp["pc"]
        dna_o = _dna(con, corp, "OFS")

        def val(w, k, y, p):
            return float(w.loc[(y, p), k]) * EOK_TO_MN if k in w and (y, p) in w.index and pd.notna(w.loc[(y, p), k]) else 0.0

        ofs_cols = [(y, "FY") for y in ps["hist_years"]] + [(ly - 1, "H1"), (ly, "H1")]
        ofs_accts = [
            "revenue",
            "cogs",
            "operating_income",
            "net_income",
            "capex_ppe",
            "capex_intangibles",
            "dna",
            "receivables",
            "inventories",
            "trade_payables",
            "contract_liabilities",
            "cash",
            "short_term_fin",
            "total_debt",
            "lease_liabilities",
            "long_term_fin",
            "total_equity",
            "ppe",
            "intangibles",
            "rou_assets",
        ]
        fs = {"OFS": {}, "CFS": {}}
        for y, p in ofs_cols:
            colv = {}
            for a in ofs_accts:
                if a == "dna":
                    v = dna_o.get((y, p), np.nan)
                    colv[a] = float(v) * EOK_TO_MN if pd.notna(v) else 0.0
                else:
                    colv[a] = val(po, a, y, p)
            main, other = _mode_rcept(con, corp, "OFS", y, p)
            fs["OFS"][f"{p}{y}"] = {"year": y, "period": p, "values": colv, "rcept": main, "rcept_other": other}
        cfs_accts = [
            "cash",
            "short_term_fin",
            "total_debt",
            "lease_liabilities",
            "long_term_fin",
            "nci",
            "receivables",
            "inventories",
            "trade_payables",
            "contract_liabilities",
            "equity_parent",
        ]
        main, other = _mode_rcept(con, corp, "CFS", ly, "H1")
        fs["CFS"][f"H1{ly}"] = {
            "year": ly,
            "period": "H1",
            "values": {a: val(pc, a, ly, "H1") for a in cfs_accts},
            "rcept": main,
            "rcept_other": other,
        }

        # ---- segment note (천원 in the filing -> 억 in rf_dcf -> 백만원 here)
        seg_src = {"FY2025": "20260318001224 주석 34", "1H25": "20260814001631 주석 31(전기)", "1H26": "20260814001631 주석 31"}
        segments = {}
        for lab in ("FY2025", "1H25", "1H26"):
            segments[lab] = {
                "sub": {k: float(v) * EOK_TO_MN for k, v in segs[lab].items()},
                "parent": {k: float(v) * EOK_TO_MN for k, v in segs[lab + "_parent"].items()},
                "source": seg_src[lab],
            }

        # ---- market single values (한국거래소 통계정보)
        sub_code = "474610"
        vw = vwap20(con, code, as_of)
        pct = mktcap_percentile(con, as_of, meta["target"]["market"], inp["rf_mc"] * 1e8)

        # ---- beta table (weekly 2y, the listing market index) - regression results only
        bcfg = led["beta"]
        bt = con.execute("SELECT * FROM beta_p3 WHERE spec='weekly_2y' AND \"index\"=?", [bcfg["regression"]["index"]]).df()
        beta_rows = [
            {
                "name": r.name,
                "tier": r.tier,
                "include": int(r.tier in bcfg["peer_tiers"]),
                "raw": float(r.raw),
                "se": float(r.se),
                "r2": float(r.r2),
                "n": int(r.n),
                "de_avg": float(r.de_avg),
                "blume_engine": float(r.blume),
                "bu_engine": float(r.bu_avg),
            }
            for r in bt.itertuples()
            if r.tier != "target"
        ]

        # ---- peer multiples inputs (LTM flows, 2026-06-30 balance sheet, as-of market cap)
        rel = led["p3c1"]["relative"]
        pp = con.execute("SELECT * FROM peer_p3").df().set_index("name")
        peers = []
        for c in companies():
            if c["tier"] == "target":
                continue
            r = pp.loc[c["name"]]
            eq_acct = "equity_parent" if r.fs_div == "CFS" else "total_equity"
            eq = _bs(con, c["corp_code"], r.fs_div, eq_acct, ly, meta["ltm"]["period"])
            f = lambda x: None if x is None or pd.isna(x) else float(x) / MN  # noqa: E731
            peers.append(
                {
                    "name": c["name"],
                    "tier": c["tier"],
                    "include": int(c["tier"] in rel["tiers"]),
                    "fs_div": r.fs_div,
                    "mktcap": f(r.mktcap),
                    "debt": f(r.total_debt_inc_lease),
                    "cash_like": f(r.cash_like),
                    "non_operating": f(r.non_operating),
                    "nci": f(r.nci),
                    "revenue": f(r.revenue),
                    "ebitda": f(r.ebitda),
                    "ni": f(r.ni_parent),
                    "equity": f(eq),
                    "note": "; ".join(x for x in (r.dna_missing or "", r.notes or "") if x),
                    "engine": {k: (None if pd.isna(r[k]) else float(r[k])) for k in ("ev_sales", "ev_ebitda", "per", "pbr")},
                }
            )
    finally:
        con.close()

    # ---- premium (D6 application rule, aggregates only)
    pm_cfg = dict(led["excel"]["premium"])  # same conditions as the p3c1 block call
    prr = premium_range(pct["mktcap_pct"], market=meta["target"]["market"], **pm_cfg)
    from src.premium.predict import ADOPT_THRESHOLD, GAP_WARN, application_rule

    premium = {
        "pct": pct["mktcap_pct"],
        "n_universe": pct["n_universe"],
        "market": meta["target"]["market"],
        **pm_cfg,
        "method": prr.method,
        "reason": prr.reason,
        "cv_improvement": prr.cv_improvement_q50,
        "adopt_threshold": ADOPT_THRESHOLD,
        "gap_warn": GAP_WARN,
        "top_band_pct": application_rule()["top_band_pct"],
        "neighbour": {k: prr.neighbour[k] for k in ("q25", "q50", "q75", "n")},
        "regression": dict(prr.regression),
        "band": dict(prr.band),
        "warnings": list(prr.warnings),
        "primary": {"q25": prr.q25, "q50": prr.q50, "q75": prr.q75},
        "vwap": vw["vwap"],
        "vwap_start": vw["start"],
        "vwap_end": vw["end"],
        "vwap_n": vw["n"],
        "tax_premium": led["p3c1"]["block"]["tax_premium"]["general"],
    }

    sc = led["excel"]
    cases = ps["cases"]
    bc = led["p3c1"]["broker_case"]
    return {
        "meta": {
            "name": meta["target"]["name"],
            "stock_code": code,
            "corp_code": corp,
            "market": meta["target"]["market"],
            "beta_index": led["beta"]["regression"]["index"],  # P7-D2: the beta table title
            "as_of": as_of,
            "bs_date": meta["bs_date"],
            "cf_start": led["dcf"]["cash_flow_start"],
            "discount_date": led["dcf"]["discount_date"],
            "ltm_year": ly,
            "structure": led["decisions"]["structure"],
            "fs_div": meta["fs_div"],
        },
        "excel": sc,
        "rates": {
            "rf": inp["rates"]["KTB5Y"],
            "rf_src": led["risk_free"]["source"],
            "rf_status": led["risk_free"]["status"],
            **_rf_choice(led, inp["rates"]),
            "kd_bbb": inp["rates"]["CB3Y_BBBm"],
            "kd_aa": inp["rates"]["CB3Y_AAm"],
            "mrp": led["mrp"]["value"],
            "mrp_src": led["mrp"]["source"],
            **_ledger_text(led),  # P7-X2b: Rf series codes and the MRP as-of date from the ledger (were typed in the sheet)
            "mrp_status": led["mrp"]["status"],
            "srp_list": list(led["decisions"]["srp_columns"]),
            "srp_src": led["srp"]["source"],
            "t_hamada": bcfg["tax_for_hamada"],
            "blume_w": bcfg["blume"]["weight_raw"],
            "blume_c": bcfg["blume"]["constant"],
            "de_target": led["p3b2"]["wacc"]["base_de"],
            "rating": None,
            "kd_actual": None,
        },
        "common": _common_rules(),
        "tax": [
            {"from": b["from"] / MN, "to": None if b["to"] is None else b["to"] / MN, "rate": b["rate"]}
            for b in led["corporate_tax"]["brackets"]
        ],
        "tax_src": led["corporate_tax"]["source"],
        "shares": {
            "common_issued": led["shares"]["issued_as_of"],
            "common_treasury": led["shares"]["treasury_as_of"],
            "pref_issued": 0,
            "pref_treasury": 0,
            "listed_pref": [],
            "src": f"{led['shares']['source']} (주식소각결정 20260908900177)",
            "status": led["shares"]["status"],
            "basis": "무상증자·자기주식 소각 반영. 우선주 없음",
        },
        "borrowings": [
            {"label": f"{b['lender']} {b['kind']}", "rate": b["rate"], "amount": b["amount"] / MN}
            for b in led["cost_of_debt"]["actual_borrowings"]
        ],
        "borrowings_src": "반기보고서 20260814001631 주석 16",
        "de": {
            "rule": "fixed",
            "value": led["p3b2"]["wacc"]["base_de"],
            "src": "p3b2.wacc.base_de",
            "basis": "RF는 순현금 → D/E 0(P3-B2, 사용자 승인). 0.253은 민감도",
        },
        "kd_tax_base": sc["kd_tax_base"],
        "market": {
            "close": inp["rf_close"],
            "rf_mc": inp["rf_mc"] * EOK_TO_MN,
            "sub_mc": inp["sub_mc"] * EOK_TO_MN,
            "sub_name": led["nci"]["subsidiary"]["name"],
            "sub_code": sub_code,
            "stake": led["nci"]["subsidiary"]["parent_stake"],
        },
        "fs": fs,
        "segments": segments,
        "inv_subs_book": inp["parent"]["inv_subs_book"] * EOK_TO_MN,
        "lt_borrowings_override": led["parent_bs_overrides"]["long_term_borrowings"] / MN,
        "scenarios": {k: {**cases[k], "rev_2026": cases[k]["rev_2026"] * EOK_TO_MN} for k in sc["scenarios"] if k in cases},
        "broker": {
            "cons": {k: v["value"] * EOK_TO_MN for k, v in bc["consolidated"].items()},
            "src": {k: v["source"] for k, v in bc["consolidated"].items()},
        },
        "sub_simple": dict(led["subsidiary_simple"]),
        "growth_capex": [
            {**g, "year": 2026 if g["period"] == "2H26" else int(g["period"]), "amount": g["amount"] * EOK_TO_MN}
            for g in ps["growth_capex"]
        ],
        "lives": {
            "maint": ps["maintenance_capex_life_years"],
            "growth": ps["growth_capex_life_years"],
            "bldg_start": int(sc["growth_capex_dep_start"]),
        },
        "dcf": {
            "explicit_end": led["dcf"]["explicit_end"],
            "fade_years": len(led["p3b2"]["stages"]["fade_years"]),
            "mid_year": int(bool(led["dcf"]["mid_year"])),
            "exit_multiple": led["dcf"]["exit_multiple"]["value"],
            "exit_src": led["dcf"]["exit_multiple"]["basis"],
            "days": 365,
            "unallocated_hq_pv": 0.0,
        },
        "nwc_years": list(ps["nwc_days_years"]),
        "hist_years": list(ps["hist_years"]),
        "beta": beta_rows,
        "peers": peers,
        "relative": rel,
        "premium": premium,
        "structure_rules": load_rules(),
        "broker_targets": led["p3c1"]["broker_target_prices"],
        "affiliate": None,
        "bs_lines": None,
        "rating_src": "무등급(cost_of_debt.method rating_curve)",
    }


def _common_rules() -> dict:
    from src.valuation.common_rules import load_common

    c = load_common()
    return {"r2_warn": c["beta"]["warn_r2_median_below"], "rating_scale": c["kd"]["rating_scale"]}


def withheld_premium(market: str, pm_cfg: dict, vw: dict, led: dict) -> dict:
    """P7-C3 public deployment (config/p7c3.yaml decisions.premium_public = false): no premium aggregates, no market-cap
    percentile. The Excel model and the report show '비공개' and leave the block price out (no formula on missing inputs)."""
    return {
        "withheld": True,
        "market": market,
        **pm_cfg,
        "method": None,
        "reason": None,
        "warnings": [],
        "note": "경영권 프리미엄 집계는 한국거래소 서면 확인 뒤 공개(공개 배포에서는 계산하지 않음)",
        "vwap": vw.get("vwap"),
        "vwap_start": vw.get("start"),
        "vwap_end": vw.get("end"),
        "vwap_n": vw.get("n"),
        "tax_premium": led["p3c1"]["block"]["tax_premium"]["general"],
    }


def output_path(data: dict) -> Path:
    return ROOT / data["excel"]["output"].format(as_of=data["meta"]["as_of"])


# ---------------------------------------------------------------- mechanical (company_dcf engine, e.g. JW중외제약)


def _relax_note(cfg: dict) -> str | None:
    ps = cfg.get("peer_screen") or {}
    rs = ps.get("relax_step") or 0
    if not rs:
        return None
    last = (ps.get("levels") or [{}])[-1]
    return (
        f"피어 완화 {rs}단계(config/p7b5.yaml peer_relax): 시총 대상의 {last.get('band', ['', ''])[0]}~{last.get('band', ['', ''])[1]}배, "
        f"KSIC 앞 {last.get('ksic_digits')}자리 — 피어 적합성 사람 확인"
    )


def mechanical_data(cfg_path: str) -> dict:
    """Inputs of src/valuation/company_dcf (P3-C3 rules) for one company config. Consolidated statements only."""
    import re
    from datetime import date, timedelta

    from src.market.beta_table import companies
    from src.market.provider import get as market_provider
    from src.premium.predict import ADOPT_THRESHOLD, GAP_WARN, application_rule
    from src.valuation.common_rules import load_common
    from src.valuation.company_dcf import explicit_end, fade_years, fs_div, load_company, val
    from src.valuation.peer_p3 import CASH_LIKE, DERIV, NON_OP, _bs
    from src.valuation.structure import load_rules

    c = load_company(cfg_path)
    cfg, led, mk = c.cfg, c.led, c.market
    xl = cfg["excel"]
    pr_ = cfg["params"]
    corp, code, as_of = cfg["target"]["corp_code"], cfg["target"]["stock_code"], cfg["meta"]["as_of"]
    y0, y1 = pr_["cagr_years"]
    years = sorted(
        set(range(y0, y1 + 1)) | {min(pr_["avg_years"]) - 1} | (set(range(c.FY - 4, c.FY + 1)) if c.v2 else set())
    )  # P7-B2b v2: 5-year margin median needs FY(Y−5)~FY(Y−1) (P7-X2b: from the config's LTM year)
    accts = [
        "revenue",
        "cogs",
        "operating_income",
        "pretax_income",
        "net_income",
        "net_income_parent",
        "capex_ppe",
        "capex_intangibles",
        "dna",
        "dna_dep",
        "receivables",
        "inventories",
        "trade_payables",
        "ppe",
        "intangibles",
        "rou_assets",
        "total_debt",
        "lease_liabilities",
        "nci",
        "equity_parent",
        "total_equity",
    ]
    fsd = fs_div(cfg)  # P7-B: statement basis from config meta (JW: CFS)
    base_name = Path(cfg_path).stem.replace("valuation_", "")
    draft = "draft_meta" in cfg  # P7-B auto draft: generic labels instead of the JW texts
    from src.valuation.company_dcf import _close, _con, dna_wide_of, draft_dna
    from src.workbench import pubagg, pubcut
    from src.workbench import snapdata as SD
    from src.workbench.public_deploy import premium_range as premium_range_pub
    from src.workbench.public_deploy import premium_withheld

    replay = SD.replaying()  # P7-C3 public snapshot: peer aggregates instead of the rows
    con = _con()
    try:
        if draft:  # P7-B2b: filled D&A (원문 → 보완 → 추정), same as the engine
            dw = draft_dna(con, cfg)[0]
        else:
            dw = dna_wide_of(con, corp, fsd)

        def colvals(y, p):
            if draft and (y, p) not in c.w.index:  # P7-X2b X7: no statements for the period -> blank cells, not 0
                return {a: None for a in accts}
            out = {}
            for a in accts:
                if a == "dna":  # P7-B2 B2-F5: no D&A for the period -> blank (the engine skips it)
                    out[a] = float(dw.loc[(y, p)].fillna(0).sum()) / MN if (y, p) in dw.index else None
                elif a == "dna_dep":  # P7-B2 B2-F3: a NaN depreciation cell is 0 (was NaN -> Excel error)
                    dep = dw.loc[(y, p)].get("depreciation", 0) if (y, p) in dw.index else 0
                    out[a] = 0.0 if dep is None or pd.isna(dep) else float(dep) / MN
                else:
                    out[a] = val(c, a, y, p) * EOK_TO_MN
            return out

        fs = {"CFS": {}}  # key kept for the sheet code; values on the config basis
        for y, p in [(y, "FY") for y in years] + [(c.Y - 1, c.P), (c.Y, c.P)]:
            main, other = _mode_rcept(con, corp, fsd, y, p)
            fs["CFS"][f"{p}{y}"] = {"year": y, "period": p, "values": colvals(y, p), "rcept": main, "rcept_other": other}
            if draft and (y, p) not in c.w.index:
                fs["CFS"][f"{p}{y}"]["blank"] = True
        # balance-sheet lines with the peer_p3 classification (cash-like / non-operating)
        lines = []
        if c.sotp:
            from src.valuation.company_dcf import sotp_book_all, sub_line_mask

            sub_mask = sub_line_mask(c.bs_lines, sotp_book_all(c.sotp["rows"])).tolist()
        for i, r in enumerate(c.bs_lines.itertuples()):
            nm = r.account_nm.replace(" ", "")
            deriv = bool(re.search(DERIV, nm))
            cls = ""
            if c.sotp and sub_mask[i]:  # P7-B3: replaced by the SOTP subsidiary values
                cls = "sub_inv"
            elif r.section == "CA" and re.search(CASH_LIKE, nm) and not deriv and "매출채권" not in nm:
                cls = "cash_like"
            elif r.section == "NCA" and re.search(NON_OP, nm) and not deriv and "매출채권" not in nm:
                cls = "non_operating"
            if cls == "non_operating" and c.assoc and not (c.sotp and sub_mask[i]):
                from src.valuation.associates import is_assoc_line

                if is_assoc_line(nm):  # P7-X2b: the associates line the listed associates replace (Bridge rows)
                    cls = "nonop_assoc"
            if cls:
                lines.append({"section": r.section, "name": r.account_nm, "amount": r.amount / MN, "class": cls})
        bs_rcept = _mode_rcept(con, corp, fsd, c.Y, c.P)[0]
    finally:
        _close(con)
    if replay:
        tiers = cfg["beta"]["peer_tiers"]
        beta_rows, peers = [], []
        vw = market_provider().vwap20(code, as_of)
        pct = None if premium_withheld() else market_provider().mktcap_percentile(as_of, cfg["target"]["market"])
    else:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            # beta (config spec / index) and peers (C3 table with the supplementary D&A, C2 table for EBITDA before it)
            bt = con.execute(
                f'SELECT * FROM beta_{base_name} WHERE spec=? AND "index"=?', [cfg["beta"]["spec"], cfg["beta"]["index"]]
            ).df()
            tiers = cfg["beta"]["peer_tiers"]
            beta_rows = [
                {
                    "name": r.name,
                    "tier": r.tier,
                    "include": int(r.tier in tiers),
                    "raw": float(r.raw),
                    "se": float(r.se),
                    "r2": float(r.r2),
                    "n": int(r.n),
                    "de_avg": float(r.de_avg),
                    "blume_engine": float(r.blume),
                    "bu_engine": float(r.bu_avg),
                }
                for r in bt.itertuples()
                if r.tier != "target"
            ]
            p3 = con.execute(f"SELECT * FROM peer_{base_name}_c3").df().set_index("name")
            p2 = con.execute(f"SELECT * FROM peer_{base_name}").df().set_index("name")
            peers = []
            for pc in companies(cfg_path):
                if pc["tier"] == "target":
                    continue
                r = p3.loc[pc["name"]]
                eq = _bs(con, pc["corp_code"], r.fs_div, "equity_parent" if r.fs_div == "CFS" else "total_equity", c.Y, c.P)
                f = lambda x: None if x is None or pd.isna(x) else float(x) / MN  # noqa: E731
                e2 = p2.loc[pc["name"], "ebitda"] if pc["name"] in p2.index else None
                peers.append(
                    {
                        "name": pc["name"],
                        "tier": pc["tier"],
                        "include": int(pc["tier"] in tiers),
                        "fs_div": r.fs_div,
                        "mktcap": f(r.mktcap),
                        "debt": f(r.total_debt_inc_lease),
                        "cash_like": f(r.cash_like),
                        "non_operating": f(r.non_operating),
                        "nci": f(r.nci),
                        "revenue": f(r.revenue),
                        "ebitda": f(r.ebitda),
                        "ebitda_pre": f(e2) if e2 is not None and pd.notna(e2) and float(e2) > 0 else None,
                        "ni": f(r.ni_parent),
                        "equity": f(eq),
                        "note": "; ".join(x for x in (r.dna_missing or "", r.notes or "") if x),
                        "engine": {k: (None if pd.isna(r[k]) else float(r[k])) for k in ("ev_sales", "ev_ebitda", "per", "pbr")},
                    }
                )
            vw = market_provider().vwap20(code, as_of, con=con)
            pct = (
                None
                if premium_withheld()
                else market_provider().mktcap_percentile(as_of, cfg["target"]["market"], mk["mktcap_common"] * 1e8, con=con)
            )
        finally:
            con.close()
        if SD.mode() == "record":  # P7-C3: what public.transform needs, as aggregates
            from src.workbench.public import public_aggregates

            pubagg.record("public", cfg_path, cfg, public_aggregates(beta_rows, peers))
    pm_cfg = dict(pr_["premium"])
    if premium_withheld():  # P7-C3 decisions.premium_public = false
        premium = withheld_premium(cfg["target"]["market"], pm_cfg, vw, led)
    else:
        prr = premium_range_pub(
            pct["mktcap_pct"], market=cfg["target"]["market"], public=pubcut.public_scope(cfg), **pm_cfg
        )  # P7-X2a
        premium = {
            "pct": pct["mktcap_pct"],
            "n_universe": pct["n_universe"],
            "pct_fixed": bool(pct.get("fixed")),
            "vwap_user": vw.get("source") == "사용자 입력",
            "market": cfg["target"]["market"],
            **pm_cfg,
            "method": prr.method,
            "reason": prr.reason,
            "cv_improvement": prr.cv_improvement_q50,
            "adopt_threshold": ADOPT_THRESHOLD,
            "gap_warn": GAP_WARN,
            "top_band_pct": application_rule()["top_band_pct"],
            "neighbour": {k: prr.neighbour[k] for k in ("q25", "q50", "q75", "n")},
            "regression": dict(prr.regression),
            "band": dict(prr.band),
            "warnings": list(prr.warnings),
            "primary": {"q25": prr.q25, "q50": prr.q50, "q75": prr.q75},
            "vwap": vw["vwap"],
            "vwap_start": vw["start"],
            "vwap_end": vw["end"],
            "vwap_n": vw["n"],
            "tax_premium": led["p3c1"]["block"]["tax_premium"]["general"],
        }
    sh = cfg["shares"]
    listed_pref = [
        {"code": cd, "close": float(p[0]), "listed": int(p[2])}
        for cd, p in zip(sh.get("listed_pref_codes", []), mk["listed_pref"])
    ]
    bs_date = cfg["meta"]["bs_date"]
    cs = load_common()
    return {
        "meta": {
            "name": cfg["target"]["name"],
            "stock_code": code,
            "corp_code": corp,
            "market": cfg["target"]["market"],
            "beta_index": (cfg.get("beta") or {}).get("index"),  # P7-D2: the beta table title (PC table only)
            "as_of": as_of,
            "bs_date": bs_date,
            "cf_start": (date.fromisoformat(bs_date) + timedelta(days=1)).isoformat(),
            "discount_date": bs_date,
            "ltm_year": c.Y,
            "structure": "consolidated",
            "fs_div": fsd,
            "bs_rcept": bs_rcept,
            "draft": draft,
        },
        "excel": xl,
        "rates": {
            "rf": c.rates["KTB5Y"],
            "rf_src": led["risk_free"]["source"],
            "rf_status": led["risk_free"]["status"],
            **_rf_choice(led, c.rates),
            "kd_bbb": c.rates["CB3Y_BBBm"],
            "kd_aa": c.rates["CB3Y_AAm"],
            "mrp": led["mrp"]["value"],
            "mrp_src": led["mrp"]["source"],
            **_ledger_text(led),  # P7-X2b: Rf series codes and the MRP as-of date from the ledger (were typed in the sheet)
            "mrp_status": led["mrp"]["status"],
            "srp_list": list(led["decisions"]["srp_columns"]),
            "srp_src": led["srp"]["source"],
            "t_hamada": cfg["beta"]["tax"],
            "blume_w": led["beta"]["blume"]["weight_raw"],
            "blume_c": led["beta"]["blume"]["constant"],
            "rating": cfg["kd"].get("rating"),
        },
        "rating_src": cfg["kd"].get("rating_source", ""),
        "common": {"r2_warn": cs["beta"]["warn_r2_median_below"], "rating_scale": cs["kd"]["rating_scale"]},
        "tax": [
            {"from": b["from"] / MN, "to": None if b["to"] is None else b["to"] / MN, "rate": b["rate"]}
            for b in led["corporate_tax"]["brackets"]
        ],
        "tax_src": led["corporate_tax"]["source"],
        "shares": {
            "common_issued": sh["common_issued"],
            "common_treasury": sh["common_treasury"],
            "pref_issued": sh["pref_issued"],
            "pref_treasury": sh["pref_treasury"],
            "listed_pref": listed_pref,
            "src": sh["source"],
            "status": sh["status"],
            "basis": sh["per_share_rule"],
        },
        "market": {
            "close": mk["close"],
            "rf_mc": mk["mktcap_common"] * EOK_TO_MN,
            "sub_mc": 0.0,
            "sub_name": "",
            "sub_code": "",
            "stake": 0.0,
        },
        "fs": fs,
        "segments": None,
        "bs_lines": lines,
        "bs_lines_src": f"{bs_rcept} 연결 재무상태표 줄(peer_p3.classify 규칙)",
        "borrowings": [{"label": b["kind"], "rate": b["rate"], "amount": b["amount"] / MN} for b in cfg["kd"]["actual"]],
        "borrowings_src": cfg["kd"]["source"],
        "de": {
            "rule": "points",
            "points": []
            if replay or mk.get("de_cut")
            else [
                {"date": r.date, "debt": r.debt * EOK_TO_MN, "lease": r.lease * EOK_TO_MN, "mktcap": r.mktcap * EOK_TO_MN}
                for r in mk["de_points"].itertuples()
            ],
            "n": mk.get("de_n", len(mk["de_points"])),
            **({"public_cut": True} if mk.get("de_cut") else {}),
            "src": cfg["capital_structure"]["rule"],
            "basis": "자체 3년 평균 D/E(P7-B 초안 규칙)" if draft else "자체 3년 평균 D/E(사전 고정 370efdb)",
        },
        "kd_tax_base": xl["kd_tax_base"],
        "scenarios": {k: dict(v) for k, v in cfg["scenarios"]["human"].items()},
        "mech": {
            "cagr_years": list(pr_["cagr_years"]),
            "avg_years": list(pr_["avg_years"]),
            "fade_to": pr_["fade_to_terminal_by"],
            "g_terminal": cfg["forecast"]["human"]["g_terminal"],
            "ebitda_rule": dict(pr_["ebitda_rule"]),
        },
        "dcf": {
            "explicit_end": explicit_end(c),
            "fade_years": len(fade_years(c)),
            "mid_year": int(bool(cfg["forecast"]["mid_year"])),
            "exit_multiple": None,
            "exit_src": "피어 EV/EBITDA 중앙값(Peers 시트, 병행 표시용 ⚠️ — 엔진은 Exit 미계산)",
            "days": 365,
            "unallocated_hq_pv": 0.0,
        },
        "beta": beta_rows,
        "peers": peers,
        "relative": {"n_warn": cfg["relative"]["n_warn"], "tiers": tiers},
        "premium": premium,
        "structure_rules": load_rules(),
        "broker_targets": None,
        "affiliate": xl.get("affiliate_loans"),
        "convergence_rule": cfg["convergence_test"]["rule"],
        "kd_method": cfg["kd"].get("method", "rating"),
        "v2": None if not c.v2 else {k: v for k, v in c.v2.items() if k != "peers"},  # P7-B2b mechanical_v2 inputs
        "nci_path": bool(cfg["structure"].get("nci_path")),  # P7-B2 consolidated DCF − NCI (book) path
        "debt_reclass": (cfg.get("bridge") or {}).get("debt_reclass") or [],  # P7-B3b mistag.text_rule
        "peer_relax": _relax_note(cfg),  # P7-B5 peer_relax
        "overrides": dict(cfg.get("overrides") or {}),  # P7-C1 workbench confirmed assumptions
        "workbench": cfg.get("workbench"),  # P7-C1 session record (changes table)
        "associates": None  # P7-X2b listed associates at market value
        if not c.assoc
        else {
            "rows": c.assoc["rows"],
            "basis": c.assoc["basis"],
            "discount": c.assoc["discount"],
            "sensitivities": c.assoc["sensitivities"],
            "equity_income": {f"{y}|{p}": v for (y, p), v in c.assoc["equity_income"].items()},
        },
        "sotp": None
        if not c.sotp
        else {
            "rows": c.sotp["rows"],
            "discount": c.sotp["discount"],  # P7-B3 general SOTP
            "sensitivities": c.sotp["sensitivities"],
            "dividends": c.sotp["dividends"],
        },
        "labels": (
            {
                "rule_tag": "P7-B 자동 초안 규칙",
                "de_basis": "자체 3년 평균 D/E(P7-B 초안 규칙)",
                "seg_note": "단일 부문(자동 초안: 부문 미수집)",
                "conv_note": None,
            }
            if draft
            else {
                "rule_tag": "사전 고정 370efdb · P3-C3",
                "de_basis": "자체 3년 평균 D/E(사전 고정 370efdb)",
                "seg_note": "단일 보고부문(제약)",
                "conv_note": "미수렴 원인(P3-C2·C3 보고서): KOSPI 기준 피어 베타의 설명력이 낮다(R² 중앙값 약 0.02) → βu 0.354 → WACC 낮음. "
                "결과를 본 뒤 지수·SRP를 바꾸지 않았다(사전 고정)",
            }
        ),
        "inv_subs_book": 0.0,
        "lt_borrowings_override": 0.0,
        "hist_years": [],
        "nwc_years": [],
    }
