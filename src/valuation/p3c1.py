"""P3-C1: RF머트리얼즈 wrap-up - cleanup sensitivities, broker reference case, relative valuation, block premium,
football field (assumptions: config/valuation_rf.yaml `p3c1`). No API calls.

Run: python -m src.valuation.p3c1     -> prints markdown, data/interim/p3c1_tables.md, reports/figures/p3c1_football.png

Pure helpers (unit-tested): hp_unlever, best3_days, multiple_stats, sotp_from_multiple, block_range, football_rows.
Market data: 한국거래소 통계정보 (as-of single values: close, market caps, one 20-day VWAP).
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from src.collect.core import ROOT
from src.db.build import DB_PATH
from src.valuation.assumptions import load_ledger
from src.valuation.dcf import days_path
from src.valuation.rf_dcf import EOK, load_inputs, md, per_share, segments_from_filings
from src.valuation.rf_dcf2 import AFTER, value
from src.valuation.wacc import debt_beta

ORDER = ["pessimistic", "base", "optimistic"]
LAB = {"pessimistic": "비관", "base": "기본", "optimistic": "낙관", "broker": "증권사(참고)"}


# ---------------------------------------------------------------- pure helpers


def hp_unlever(beta_l: float, beta_d: float, de: float) -> float:
    """Inverse of Harris–Pringle: βu = (βL + βd × D/E) / (1 + D/E)."""
    return (beta_l + beta_d * de) / (1 + de)


def best3_days(hist: pd.DataFrame) -> dict:
    """Best three years per item: lowest DSO / DIO, highest DPO (mean of the three)."""
    return {
        "dso": float(hist.dso.nsmallest(3).mean()),
        "dio": float(hist.dio.nsmallest(3).mean()),
        "dpo": float(hist.dpo.nlargest(3).mean()),
    }


def multiple_stats(values: pd.Series, cap: float | None = None) -> dict:
    """Quartiles of positive multiples (N/M = None/NaN excluded); optional cap for the reference version."""
    v = pd.Series(values, dtype=float).dropna()
    v = v[v > 0]
    if cap is not None:
        v = v[v <= cap]
    if v.empty:
        return {"n": 0, "q25": np.nan, "median": np.nan, "q75": np.nan}
    return {"n": int(v.size), "q25": float(v.quantile(0.25)), "median": float(v.median()), "q75": float(v.quantile(0.75))}


def sotp_from_multiple(
    kind: str, multiple: float, metric: float, stake_value: float, net_cash: float, non_operating: float
) -> float:
    """Equity (억원) from one multiple applied to the parent business.
    ev:     EV = multiple × metric → + stake + net cash + non-operating
    equity: equity of the parent ex-subsidiary = multiple × metric (PER on parent net income, PBR on parent book
            equity ex investment) → + stake (net cash is already inside parent net income / book equity)"""
    if kind == "ev":
        return multiple * metric + stake_value + net_cash + non_operating
    if kind == "equity":
        return multiple * metric + stake_value
    raise ValueError(kind)


def block_range(base_price: float, quantiles: dict) -> dict:
    """Block price per share = base x (1 + premium) for each quantile (q25 / q50 / q75)."""
    return {k: base_price * (1 + q) for k, q in quantiles.items()}


def football_rows(items: list[dict]) -> pd.DataFrame:
    """items: {group, label, low, high, mid (optional), definition}. Sorted by group order of appearance; low<=high."""
    df = pd.DataFrame(items)
    bad = df[df.low > df.high]
    if len(bad):
        raise ValueError(f"low > high: {bad.label.tolist()}")
    df["group_order"] = pd.Categorical(df.group, categories=list(dict.fromkeys(df.group)), ordered=True).codes
    return df.sort_values(["group_order"], kind="stable").drop(columns="group_order").reset_index(drop=True)


# ---------------------------------------------------------------- RF pieces


def parent_metrics(con, led, inp, segs) -> dict:
    corp = led["meta"]["target"]["corp_code"]

    def q(acct, y, p):  # one parent (OFS) statement amount in 억원
        return (
            con.execute(
                """SELECT amount FROM fs_std WHERE corp_code=? AND fs_div='OFS' AND is_default
                              AND std_account=? AND fiscal_year=? AND period=?""",
                [corp, acct, y, p],
            ).fetchone()[0]
            / EOK
        )

    dna = con.execute(
        """SELECT fiscal_year, period, sum(amount) FROM fs_dna WHERE corp_code=? AND fs_div='OFS'
                         AND ((fiscal_year=2025 AND period IN ('FY','H1')) OR (fiscal_year=2026 AND period='H1'))
                         GROUP BY ALL""",
        [corp],
    ).fetchall()
    d = {(y, p): v / EOK for y, p, v in dna}
    ltm = lambda k: segs["FY2025_parent"][k] + segs["1H26_parent"][k] - segs["1H25_parent"][k]  # noqa: E731
    rev, op = ltm("revenue"), ltm("op")
    dna_ltm = d[(2025, "FY")] + d[(2026, "H1")] - d[(2025, "H1")]
    ni = q("net_income", 2025, "FY") + q("net_income", 2026, "H1") - q("net_income", 2025, "H1")
    eq = q("total_equity", 2026, "H1") - inp["parent"]["inv_subs_book"]
    return {"revenue": rev, "op": op, "ebitda": op + dna_ltm, "dna": dna_ltm, "ni": ni, "equity_ex_inv": eq}


def broker_case(led, inp, segs, variant: str = "main") -> tuple[dict, dict]:
    bc, sub = led["p3c1"]["broker_case"], led["subsidiary_simple"]
    cons = {k: v["value"] for k, v in bc["consolidated"].items()}
    if variant == "march":
        cons["op_2026"], cons["op_2027"] = bc["variant_march"]["op_2026"], bc["variant_march"]["op_2027"]
    g, m = sub["growth"], sub["margin"]
    sub_2h = (segs["FY2025"]["revenue"] - segs["1H25"]["revenue"]) * (1 + g)
    sub26_rev = segs["1H26"]["revenue"] + sub_2h
    sub26_op = segs["1H26"]["op"] + sub_2h * m
    sub27_rev, sub27_op = sub26_rev * (1 + g), sub26_rev * (1 + g) * m
    p26_rev, p27_rev = cons["rev_2026"] - sub26_rev, cons["rev_2027"] - sub27_rev
    p26_op, p27_op = cons["op_2026"] - sub26_op, cons["op_2027"] - sub27_op
    base = led["parent_scenarios"]["cases"]["base"]
    case = {
        "rev_2026": p26_rev,
        "g_2027": p27_rev / p26_rev - 1,
        "g_2028_2032": base["g_2028_2032"],
        "margin": p27_op / p27_rev,
        "g_terminal": base["g_terminal"],
        "op_2026": p26_op,
    }
    derived = {
        "연결 2026 매출": cons["rev_2026"],
        "연결 2026 영업이익": cons["op_2026"],
        "연결 2027 매출": cons["rev_2027"],
        "연결 2027 영업이익": cons["op_2027"],
        "RF시스템즈 2026 매출(단순)": sub26_rev,
        "RF시스템즈 2026 영업이익(단순)": sub26_op,
        "RF시스템즈 2027 매출": sub27_rev,
        "RF시스템즈 2027 영업이익": sub27_op,
        "모회사 2026 매출(파생)": p26_rev,
        "모회사 2026 영업이익(파생)": p26_op,
        "모회사 2H26 영업이익률(파생)": (p26_op - inp["parent"]["h1_op"]) / (p26_rev - inp["parent"]["h1_rev"]),
        "모회사 2027 매출(파생)": p27_rev,
        "모회사 2027 성장률(파생)": p27_rev / p26_rev - 1,
        "모회사 2027 이익률(파생, 정상)": p27_op / p27_rev,
    }
    return case, derived


def vwap20(con, stock_code: str, as_of: str) -> dict:
    """20 trading days ending on the valuation date (included), adjusted volumes if an event is inside."""
    from src.market.prices import vwap_last_n

    r = vwap_last_n(con, stock_code, as_of, 20, include_end=True)
    d = con.execute(
        """SELECT min(bas_dd), max(bas_dd) FROM (SELECT bas_dd FROM price_adj WHERE stock_code=? AND bas_dd<=?
                       ORDER BY bas_dd DESC LIMIT 20)""",
        [stock_code, as_of],
    ).fetchone()
    return {"vwap": float(r.vwap), "start": str(d[0]), "end": str(d[1]), "n": r.n_days, "events": int(r.event_in_window)}


def main() -> str:
    led = load_ledger()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    inp = load_inputs(con, led)
    segs = segments_from_filings()
    pm = parent_metrics(con, led, inp, segs)
    bt = con.execute("SELECT * FROM beta_p3 WHERE spec='weekly_2y' AND \"index\"='KOSDAQ'").df()
    peers = con.execute("SELECT * FROM peer_p3").df()
    code, as_of = led["meta"]["target"]["stock_code"], led["meta"]["as_of"]
    vw = vwap20(con, code, as_of)
    pcons = con.execute(
        """SELECT std_account, amount FROM fs_std WHERE corp_code=? AND fs_div='CFS' AND is_default
                           AND fiscal_year=2026 AND period='H1' AND std_account IN ('equity_parent')""",
        [led["meta"]["target"]["corp_code"]],
    ).fetchall()
    con.close()
    cases, srps, price = led["parent_scenarios"]["cases"], led["decisions"]["srp_columns"], inp["rf_close"]
    rf_ = inp["rates"]["KTB5Y"]
    mrp = led["mrp"]["value"]
    stake = led["nci"]["subsidiary"]["parent_stake"] * inp["sub_mc"]
    out = []

    # ---- 0-2 Harris–Pringle unlevered beta
    tiers = led["beta"]["peer_tiers"]
    p = bt[bt.tier.isin(tiers)].copy()
    rows = {"Hamada(βd 0, t 22%) — 기본": p.bu_avg.median()}
    hp = {}
    for lab, kd in (("Harris–Pringle, Kd BBB-", inp["rates"]["CB3Y_BBBm"]), ("Harris–Pringle, Kd AA-", inp["rates"]["CB3Y_AAm"])):
        bd = debt_beta(kd, rf_, mrp)
        p[lab] = [hp_unlever(b, bd, de) for b, de in zip(p.blume, p.de_avg)]
        hp[lab] = (kd, float(p[lab].median()))
        rows[lab] = p[lab].median()
    bt_tab = p.set_index("name")[["blume", "de_avg", "bu_avg"] + list(hp)]
    bt_tab.loc["중앙값"] = bt_tab.median()
    out.append(
        "## 0-2. 피어 βu: Hamada vs Harris–Pringle(부채 베타)\n\n" + md(bt_tab.rename_axis("피어(주간 2년 KOSDAQ)"), "{:.3f}")
    )
    sens = []
    base_after = value(led, inp, cases["base"], **AFTER)
    for lab, (kd, bu) in hp.items():
        old = value(led, inp, cases["base"], **AFTER, hp_kd=kd)
        inp2 = {**inp, "beta": inp["beta"].copy()}
        inp2["beta"]["median"] = bu
        new = value(led, inp2, cases["base"], **AFTER, hp_kd=kd)
        sens.append(
            {
                "민감도(D/E 0.253)": lab,
                "βu(Hamada) 사용": old["per_share"],
                "βu(HP) 사용": new["per_share"],
                "WACC(HP βu)": new["wacc"] * 100,
                "βu 중앙값 차이": bu - float(inp["beta"]["median"]),
            }
        )
    out.append("\n" + md(pd.DataFrame(sens).set_index("민감도(D/E 0.253)"), "{:,.3f}"))
    out.append(f"\n기본(D/E 0, Hamada βu {float(inp['beta']['median']):.3f}) 주당 {base_after['per_share']:,.0f}원 — 변화 없음\n")

    # ---- 0-3 NWC best-3
    import duckdb as _d

    con = _d.connect(str(DB_PATH), read_only=True)
    h = (
        con.execute(
            """SELECT fiscal_year y, std_account a, amount/1e8 v FROM fs_std WHERE corp_code=? AND fs_div='OFS'
                       AND is_default AND period='FY' AND fiscal_year BETWEEN ? AND ?
                       AND std_account IN ('revenue','cogs','receivables','inventories','trade_payables')""",
            [led["meta"]["target"]["corp_code"], min(led["p3c1"]["nwc_best3"]["years"]), max(led["p3c1"]["nwc_best3"]["years"])],
        )
        .df()
        .pivot_table(index="y", columns="a", values="v")
    )
    con.close()
    h["dso"], h["dio"], h["dpo"] = h.receivables / h.revenue * 365, h.inventories / h.cogs * 365, h.trade_payables / h.cogs * 365
    b3 = best3_days(h)
    hist_days = inp["days"].mean().to_dict()
    dp = days_path(hist_days, b3, 2026, 2030, list(range(2026, 2033)))
    v_b3 = value(led, inp, cases["base"], **AFTER, days_by_year=dp)
    from src.valuation.rf_dcf2 import peer_days

    con = _d.connect(str(DB_PATH), read_only=True)
    pdm = peer_days(con, led)["median"]
    con.close()
    v_pm = value(led, inp, cases["base"], **AFTER, days_by_year=days_path(hist_days, pdm, 2026, 2030, list(range(2026, 2033))))
    nwc = pd.DataFrame(
        {
            "과거 평균(기본)": {k: hist_days[k] for k in ("dso", "dio", "dpo")},
            "과거 최선 3개 연도(새 기준)": b3,
            "피어 중앙값(이전 기준)": pdm,
        }
    ).T
    nwc["주당(원)"] = [base_after["per_share"], v_b3["per_share"], v_pm["per_share"]]
    out.append(
        "## 0-3. 운전자본 개선 민감도 (기본 시나리오, SRP 0%, 2030년까지 직선)\n\n" + md(nwc.rename_axis("기준"), "{:,.1f}")
    )
    out.append("\n별도 회전일수(FY2019~2025)\n\n" + md(h[["dso", "dio", "dpo"]].rename_axis("연도"), "{:.1f}"))

    # ---- 1 broker case
    res = {}
    for nm in ORDER:
        res[nm] = {s: value(led, inp, cases[nm], srp=s, **AFTER)["per_share"] for s in srps}
    bcase, deriv = broker_case(led, inp, segs)
    bres = {s: value(led, inp, bcase, srp=s, **AFTER) for s in srps}
    res["broker"] = {s: r["per_share"] for s, r in bres.items()}
    vcase, vderiv = broker_case(led, inp, segs, "march")
    vres = {s: value(led, inp, vcase, srp=s, **AFTER)["per_share"] for s in srps}
    out.append(
        "\n## 1. 증권사 추정 시나리오(참고, P3-B2 구조)\n\n"
        + md(
            pd.DataFrame({"주요(2026-07 영업이익)": deriv, "변형(2026-03 영업이익)": vderiv}).rename_axis("억원·비율"), "{:,.3f}"
        )
    )
    tbl = pd.DataFrame(res).T.rename(index=LAB)
    tbl.columns = [f"SRP {c:.0%}" for c in tbl.columns]
    tbl.loc["증권사 변형(2026-03 영업이익)"] = list(vres.values())
    tbl.index.name = "주당(원)"
    out.append("\n" + md(tbl, "{:,.0f}"))
    b0 = bres[0.0]
    out.append(
        f"\n증권사(주요) SRP 0%: RONIC {b0['ronic']:.1%}, 영구가치 비중 {b0['tv_share']:.1%}, 종가 대비 {b0['per_share'] / price - 1:+.1%}\n"
    )

    # ---- 2 relative valuation
    pr = peers[peers.tier.isin(led["p3c1"]["relative"]["tiers"])]
    nwarn = led["p3c1"]["relative"]["n_warn"]
    pnet, pnonop = inp["parent"]["net_cash"], inp["parent"]["ltf"]
    cons_eq_parent = dict(pcons).get("equity_parent", np.nan) / EOK
    rows = []
    specs = [
        ("EV/Sales", "ev_sales", "ev", pm["revenue"]),
        ("EV/EBITDA", "ev_ebitda", "ev", pm["ebitda"]),
        ("PER", "per", "equity", pm["ni"]),
        ("PBR", "pbr", "equity", pm["equity_ex_inv"]),
    ]
    rf_row = peers[peers.tier == "target"].iloc[0]
    cons_metric = {"ev_sales": rf_row.revenue, "ev_ebitda": rf_row.ebitda, "per": rf_row.ni_parent, "pbr": cons_eq_parent * EOK}
    for name, col, kind, metric in specs:
        st = multiple_stats(pr[col])
        st100 = multiple_stats(pr[col], cap=100)
        ps = {q: per_share(led, sotp_from_multiple(kind, st[q], metric, stake, pnet, pnonop)) for q in ("q25", "median", "q75")}
        # consolidated reference
        cm = cons_metric[col] / EOK
        nd, nonop, nci = inp["cons"]["net_debt"], inp["cons"]["ltf"], inp["cons"]["nci"]
        cref = {
            q: per_share(led, (st[q] * cm - nd + nonop - nci) if kind == "ev" else st[q] * cm) for q in ("q25", "median", "q75")
        }
        rows.append(
            {
                "배수": name,
                "n": st["n"],
                "q25": st["q25"],
                "중앙값": st["median"],
                "q75": st["q75"],
                "모회사 지표(억원)": metric,
                "주당 q25": ps["q25"],
                "주당 중앙값": ps["median"],
                "주당 q75": ps["q75"],
                "연결 단순 중앙값(참고)": cref["median"],
                "100배 초과 제외 중앙값": st100["median"],
                "경고": f"n<{nwarn}" if st["n"] < nwarn else "",
            }
        )
    rel = pd.DataFrame(rows).set_index("배수")
    out.append("\n## 2. 상대가치 (SOTP 구조, 피어 core+extended LTM)\n\n" + md(rel, "{:,.2f}"))
    out.append(
        f"\n모회사 LTM(부문·별도): 매출 {pm['revenue']:.1f}, 영업이익 {pm['op']:.1f}, D&A {pm['dna']:.2f}, EBITDA {pm['ebitda']:.1f}, "
        f"별도 순이익 {pm['ni']:.1f}, 별도 자본 − 종속기업투자 {pm['equity_ex_inv']:.1f}억; 지분 시가 {stake:.1f}, 순현금 {pnet:.1f}, 비영업 {pnonop:.1f}억\n"
    )
    # implied multiples
    ev_mkt = float(rf_row.ev) / EOK
    mc = inp["rf_mc"]
    da_cons = float(rf_row.ebitda - rf_row.op) / EOK
    bcons = led["p3c1"]["broker_case"]["consolidated"]
    imp = []
    for lab, op, rev in (
        ("2026E(하나 2026-07 영업이익, 2026-03 매출)", bcons["op_2026"]["value"], bcons["rev_2026"]["value"]),
        ("2027E", bcons["op_2027"]["value"], bcons["rev_2027"]["value"]),
        ("LTM 실적(2026H1)", float(rf_row.op) / EOK, float(rf_row.revenue) / EOK),
    ):
        imp.append(
            {
                "기준": lab,
                "EV/Sales": ev_mkt / rev,
                "EV/EBIT": ev_mkt / op,
                "EV/EBITDA(D&A=LTM 연결)": ev_mkt / (op + da_cons),
                "시가총액 ÷ 영업이익×(1−22%) (PER 대용)": mc / (op * 0.78),
            }
        )
    imp.append(
        {
            "기준": "피어 LTM 중앙값",
            "EV/Sales": rel.loc["EV/Sales", "중앙값"],
            "EV/EBIT": np.nan,
            "EV/EBITDA(D&A=LTM 연결)": rel.loc["EV/EBITDA", "중앙값"],
            "시가총액 ÷ 영업이익×(1−22%) (PER 대용)": rel.loc["PER", "중앙값"],
        }
    )
    out.append(
        f"\n시장 함의 배수 (연결 시장 EV {ev_mkt:,.1f}억 = P3-A 정의, 시가총액 {mc:,.1f}억)\n\n"
        + md(pd.DataFrame(imp).set_index("기준"), "{:.1f}")
    )

    # ---- 3 block premium
    from src.premium.predict import mktcap_percentile, premium_range

    con = _d.connect(str(DB_PATH), read_only=True)
    pct = mktcap_percentile(con, as_of, "KOSDAQ", inp["rf_mc"] * EOK)
    con.close()
    prr = premium_range(pct["mktcap_pct"], stake_band="25to50", buyer_group="strategic", market="KOSDAQ", period="2015-2026")
    if prr.method != "neighbours":  # D6 (P4-A): KOSDAQ top band -> neighbours; RF values must not move
        raise ValueError(f"D6 rule gave {prr.method} ({prr.reason}) for RF, expected neighbours")
    nb = {"q25": prr.q25, "q50": prr.q50, "q75": prr.q75}
    br = block_range(vw["vwap"], nb)
    blk = pd.DataFrame({"프리미엄": nb, "블록 1주당(원)": br}).T
    out.append(
        f"\n## 3. 블록 프리미엄 (지배 블록 1주당 가격 범위 점검용)\n\n- 기준가: 20거래일 VWAP {vw['start']}~{vw['end']} "
        f"(n={vw['n']}, 수정 사건 {vw['events']}) = **{vw['vwap']:,.0f}원** (종가 {price:,.0f}원)\n"
        f"- 시총 백분위 {pct['mktcap_pct']:.1f}, 이웃 50건(백분위 {prr.neighbour['pct_range'][0]:.0f}~{prr.neighbour['pct_range'][1]:.0f})\n"
        f"- 회귀(채택 판정) 중앙값 {prr.regression['q50']:.1%} — 참고만. 경고: {'; '.join(prr.warnings)}\n\n"
        + md(blk.rename_axis("이웃 50건 분위"), "{:,.3f}")
    )
    out.append(
        f"\n상증법 최대주주 할증 비교(1주당): 할증 20% → {vw['vwap'] * 1.2:,.0f}원(기준가 기준) / {price * 1.2:,.0f}원(종가 기준); "
        f"할증 제외(중소·일정 중견기업) → {vw['vwap']:,.0f}원 / {price:,.0f}원. (세법 평가액은 평가기준일 전후 2개월 평균 종가가 원칙 — 여기서는 비교용 단순화)\n"
    )

    # ---- 4 football field
    items = []
    for nm in ORDER + ["broker"]:
        vals = list(res[nm].values())
        items.append(
            {
                "group": "DCF(SOTP, P3-B2)",
                "label": f"DCF {LAB[nm]}",
                "low": min(vals),
                "high": max(vals),
                "mid": res[nm][0.0],
                "definition": "SRP 2%~0% 범위, 막대 안 점 = SRP 0%. 3단계·가치동인·D/E 0"
                + (" · 증권사 추정 역산(대표 아님)" if nm == "broker" else ""),
            }
        )
    for name in ("EV/EBITDA", "PER", "EV/Sales", "PBR"):
        r = rel.loc[name]
        items.append(
            {
                "group": "상대가치(SOTP, 피어 LTM)",
                "label": f"{name} (n={int(r.n)})",
                "low": r["주당 q25"],
                "high": r["주당 q75"],
                "mid": r["주당 중앙값"],
                "definition": f"피어 사분위 {r.q25:.1f}~{r.q75:.1f}배 × 모회사 지표 + 지분 시가(+순현금)"
                + (" · n<5 경고" if r.n < nwarn else ""),
            }
        )
    items.append(
        {
            "group": "블록 거래 가격(참고)",
            "label": "지배 블록 1주당",
            "low": br["q25"],
            "high": br["q75"],
            "mid": br["q50"],
            "definition": f"20일 VWAP {vw['vwap']:,.0f}원 × (1 + 이웃 50건 프리미엄 {nb['q25']:.1%}~{nb['q75']:.1%}). 지분 전체 가치 아님",
        }
    )
    tp = led["p3c1"]["broker_target_prices"]
    items.append(
        {
            "group": "참고",
            "label": "증권사 목표주가",
            "low": tp["low"],
            "high": tp["high"],
            "mid": tp["consensus"],
            "definition": "2026-08~09 범위·컨센서스(문서 근거 🔸), 투자의견과 무관하게 범위만",
        }
    )
    ff = football_rows(items)
    out.append(
        f"\n## 4. 풋볼필드 (주당 원, 기준일 종가 {price:,.0f}원)\n\n"
        + md(ff.set_index("label")[["group", "low", "mid", "high", "definition"]], "{:,.0f}")
    )
    _football(ff, price)
    text = "\n".join(out)
    (ROOT / "data" / "interim" / "p3c1_tables.md").write_text(text, encoding="utf-8")
    ff.to_csv(ROOT / "data" / "interim" / "p3c1_football.csv", index=False)
    return text


def _football(ff: pd.DataFrame, price: float):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    colors = {
        "DCF(SOTP, P3-B2)": "#2a6f97",
        "상대가치(SOTP, 피어 LTM)": "#61a5c2",
        "블록 거래 가격(참고)": "#e09f3e",
        "참고": "#9e9e9e",
    }
    fig, ax = plt.subplots(figsize=(9, 5.6))
    y = np.arange(len(ff))[::-1]
    for yi, r in zip(y, ff.itertuples()):
        ax.barh(yi, r.high - r.low, left=r.low, color=colors.get(r.group, "#888"), height=0.6)
        if pd.notna(r.mid):
            ax.plot([r.mid], [yi], marker="|", color="black", ms=14)
        ax.text(r.high + 600, yi, f"{r.low:,.0f}~{r.high:,.0f}", va="center", fontsize=7)
    ax.axvline(price, color="#c1121f", ls="--", lw=1)
    ax.text(price + 500, -0.9, f"기준일 종가 {price:,.0f}원", color="#c1121f", fontsize=8, ha="left")
    ax.set_xlim(0, max(ff.high.max(), price) * 1.12)
    ax.set_ylim(-1.3, len(ff) - 0.4)
    ax.set_yticks(y, ff.label)
    ax.set_xlabel("주당 원 (가정 하 추정·참고 범위)")
    ax.set_title("RF머트리얼즈 풋볼필드 (초안, 기준일 2026-09-30)")
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=c, label=g) for g, c in colors.items()], fontsize=7, loc="upper right")
    fig.text(
        0.01,
        0.01,
        "가정 기반 계산·참고 범위(투자 권유 아님). 종가·VWAP·시가총액은 한국거래소 통계정보. 정의는 reports/p3c1_relative.md 표",
        fontsize=6.5,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(ROOT / "reports" / "figures" / "p3c1_football.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    print(main())
