"""P3-B2: DCF structure fixes for RF머트리얼즈, as pre-registered in config/valuation_rf.yaml `p3b2` (commit 19b03c4).

Run: python -m src.valuation.rf_dcf2     -> prints markdown, data/interim/p3b2_tables.md, reports/figures/p3b2_*.png

Three fixes (textbook consistency), switched on one at a time for the decomposition:
    1 three-stage DCF   explicit 2H26~2032 (unchanged), fade 2033~2040 (growth falls by equal steps to g), TV from 2041
    2 value drivers     fade-stage and terminal FCF = NOPAT x (1 − g / RONIC); RONIC = incremental ROIC of 2027~2032
                        (ΔNOPAT from FY2026 to 2032 ÷ cumulative CAPEX − D&A + ΔNWC of 2027~2032)
    3 WACC D/E = 0      Rf + βu x MRP + SRP (RF holds net cash). D/E 0.253 with a debt beta (Harris–Pringle) is a
                        sensitivity
Scenario numbers (v2) are unchanged. The P3-B value is reproduced as step 0 (src/valuation/rf_dcf.parent_value).
Units 억원; market data 한국거래소 통계정보 (as-of values only).
"""

from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd

from src.collect.core import ROOT
from src.db.build import DB_PATH
from src.market.beta_table import companies
from src.valuation.assumptions import load_ledger, marginal_rate, rf_code
from src.valuation.dcf import Period, days_path, fade_path, roll_forward, run_dcf
from src.valuation.rf_dcf import EOK, YEARS, load_inputs, md, parent_case, parent_value, per_share, sotp_for, tax_fn, wacc_case
from src.valuation.wacc import wacc_hp

FADE = list(range(2033, 2041))


def eff(led, ebit: float) -> float:
    tx = tax_fn(led)
    return tx(ebit) / ebit if ebit > 0 else 0.0


def ronic_incremental(led, fc: dict, start: str = "mixed") -> float:
    """Pre-registered rule: (NOPAT_2032 − NOPAT_FY2026) / Σ_{2027..2032}(CAPEX − D&A + ΔNWC).
    start = "mixed" (P3-B2: FY2026 EBIT = 1H actual + 2H normal) / "normal" (P3-C3 common rule: FY2026 revenue x normal
    margin)."""
    t = fc["table"].set_index("label")
    fy26 = t.loc["2H26", "fy_ebit"]
    if start == "normal":
        e26 = fc["rev_fy"][2026] * fc["margin"]
        n26 = e26 * (1 - eff(led, e26))
    else:
        n26 = fy26 * (1 - eff(led, fy26))
    n32 = t.loc["2032", "ebit"] * (1 - eff(led, t.loc["2032", "ebit"]))
    yrs = [str(y) for y in YEARS]
    reinv = float((t.loc[yrs, "capex"] - t.loc[yrs, "dna"] + t.loc[yrs, "dnwc"]).sum())
    return (n32 - n26) / reinv if reinv > 0 else float("nan")


def roic_path(led, inp, fc: dict) -> pd.DataFrame:
    """ROIC_t = NOPAT_t / opening invested capital; IC(06-30) = NWC + PPE + intangibles + ROU (separate BS)."""
    p = inp["parent"]
    ic = p["nwc"] + p["ppe"] + p["intangibles"] + p["rou"]
    rows = []
    for r in fc["table"].itertuples():
        nopat = r.ebit * (1 - eff(led, r.fy_ebit))
        rows.append({"label": r.label, "opening_ic": ic, "nopat": nopat, "roic": nopat / ic})
        ic = ic + r.capex - r.dna + r.dnwc
    out = pd.DataFrame(rows).set_index("label")
    out.loc["2H26", "roic"] = out.loc["2H26", "nopat"] * 365 / 184 / out.loc["2H26", "opening_ic"]  # annualised
    return out


def value(
    led,
    inp,
    case: dict,
    *,
    stage3: bool,
    vd: bool,
    de0: bool,
    srp: float = 0.0,
    ronic=None,
    growth_override: list[float] | None = None,
    days_by_year: dict | None = None,
    wacc_override=None,
    g_override=None,
    hp_kd: float | None = None,
    ronic_start: str = "mixed",
) -> dict:
    fc = parent_case(led, inp, case, growth_override=growth_override, days_by_year=days_by_year)
    t = fc["table"]
    last = t.iloc[-1]
    t_kd = marginal_rate(last.ebit * EOK, led["corporate_tax"]["brackets"])
    if wacc_override is not None:
        w = wacc_override
    elif hp_kd is not None:
        w = wacc_hp(
            inp["rates"][rf_code(led)],
            led["mrp"]["value"],
            float(inp["beta"]["median"]),
            led["p3b2"]["wacc"]["sensitivity"]["de"],
            hp_kd,
            t_kd,
            srp,
        ).wacc
    elif de0:  # P3-B2 default: config p3b2.wacc.base_de (= 0)
        w = wacc_case(led, inp, srp, de=led["p3b2"]["wacc"]["base_de"], t_kd=t_kd).wacc  # = Rf + βu MRP + SRP
    else:
        w = wacc_case(led, inp, srp, t_kd=t_kd).wacc  # P3-B: D/E 0.253 Hamada, Kd BBB-
    g = case["g_terminal"] if g_override is None else g_override
    tx, m = tax_fn(led), case["margin"]
    # RONIC
    r_calc = ronic_incremental(led, fc, ronic_start)
    flag = None
    if ronic is None:
        R = r_calc
        if not np.isfinite(R) or R <= 0 or R <= g:
            R, flag = w, "RONIC ≤ 0 또는 ≤ g → WACC로 대체"
    elif ronic == "wacc":
        R = w
    elif ronic == "1.5wacc":
        R = 1.5 * w
    else:
        R = float(ronic)
    periods = [Period(r.label, r.start, r.end, r.ebit, r.dna, r.capex, r.dnwc, tax_base=r.fy_ebit) for r in t.itertuples()]
    rev32, dna32, nwc32 = last.revenue, last.dna, last.nwc
    g32 = (growth_override or [case["g_2027"], *case["g_2028_2032"]])[-1]
    cap_k = led["dcf"]["terminal_capex_to_dna"]
    if stage3:
        prev = rev32
        for y, gy in zip(FADE, fade_path(g32, g, len(FADE))):
            rev = prev * (1 + gy)
            ebit = rev * m
            nopat = ebit * (1 - eff(led, ebit))
            if vd:
                periods.append(Period(str(y), date(y, 1, 1), date(y, 12, 31), ebit, 0.0, nopat * gy / R, 0.0, tax_base=ebit))
            else:
                dna = dna32 * rev / rev32
                periods.append(
                    Period(
                        str(y),
                        date(y, 1, 1),
                        date(y, 12, 31),
                        ebit,
                        dna,
                        dna * cap_k,
                        nwc32 / rev32 * (rev - prev),
                        tax_base=ebit,
                    )
                )
            prev = rev
        rev_n, ebit_n = prev, prev * m
    else:
        rev_n, ebit_n = rev32, last.ebit
    rev_next = rev_n * (1 + g)
    ebit_next = rev_next * m
    nopat_next = ebit_next * (1 - eff(led, ebit_next))
    if vd:
        fcf_norm = nopat_next * (1 - g / R) / (1 + g)
    elif stage3:
        dna_next = dna32 * rev_next / rev32
        fcf_next = nopat_next + dna_next - dna_next * cap_k - nwc32 / rev32 * (rev_next - rev_n)
        fcf_norm = fcf_next / (1 + g)
    else:
        rate = eff(led, last.ebit)
        fcf_norm = last.ebit * (1 - rate) + last.dna - last.dna * cap_k - last.nwc * g  # P3-B rule
    dna_n = dna32 * rev_n / rev32
    r = run_dcf(
        periods,
        tx,
        w,
        date.fromisoformat(led["dcf"]["discount_date"]),
        g=g,
        exit_multiple=led["dcf"]["exit_multiple"]["value"],
        mid_year=led["dcf"]["mid_year"],
        fcf_norm=fcf_norm,
        ebitda_final=ebit_n + dna_n,
    )
    days = (date.fromisoformat(led["meta"]["as_of"]) - date.fromisoformat(led["dcf"]["discount_date"])).days
    ev930 = roll_forward(r.ev_gordon, w, days)
    eq = sotp_for(led, inp, ev930).equity
    return {
        "wacc": w,
        "ronic": R,
        "ronic_calc": r_calc,
        "ronic_flag": flag,
        "ev630": r.ev_gordon,
        "ev930": ev930,
        "equity": eq,
        "per_share": per_share(led, eq),
        "tv_share": r.tv_share_gordon,
        "implied_multiple": r.implied_multiple,
        "pv_explicit": r.pv_explicit,
        "pv_tv": r.pv_tv_gordon,
        "r": r,
        "fc": fc,
        "g": g,
    }


def peer_days(con, led) -> dict:
    """Pre-registered: median DSO / DIO / DPO of core+extended peers, FY2025 annual (CFS, else OFS)."""
    rows = []
    for c in companies():
        if c["tier"] not in led["beta"]["peer_tiers"]:
            continue
        d = con.execute(
            """SELECT fs_div, std_account, amount FROM fs_std WHERE corp_code=? AND fiscal_year=2025
                           AND period='FY' AND is_default AND std_account IN
                           ('revenue','cogs','receivables','inventories','trade_payables')""",
            [c["corp_code"]],
        ).df()
        fs = "CFS" if (d.fs_div == "CFS").any() else "OFS"
        v = d[d.fs_div == fs].set_index("std_account").amount
        rows.append(
            {
                "name": c["name"],
                "dso": v.receivables / v.revenue * 365,
                "dio": v.inventories / v.cogs * 365,
                "dpo": v.trade_payables / v.cogs * 365,
            }
        )
    df = pd.DataFrame(rows).set_index("name")
    return {"table": df, "median": df.median().to_dict()}


def solve_gu(led, inp, base_case: dict, margin: float, target_ps: float, **kw) -> float | None:
    def f(gu):
        res = value(led, inp, {**base_case, "margin": margin}, growth_override=[gu] * len(YEARS), **kw)
        return res["per_share"] - target_ps

    lo, hi = -0.15, 1.5
    try:
        if f(lo) > 0 or f(hi) < 0:
            return None
    except ValueError:
        return None
    for _ in range(70):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


AFTER = {"stage3": True, "vd": True, "de0": True}
BEFORE = {"stage3": False, "vd": False, "de0": False}


def main() -> str:
    led = load_ledger()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    inp = load_inputs(con, led)
    pdays = peer_days(con, led)
    con.close()
    cases, srps, price = led["parent_scenarios"]["cases"], led["decisions"]["srp_columns"], inp["rf_close"]
    order = ["pessimistic", "base", "optimistic"]
    out = []

    # 0. check: step 0 reproduces P3-B
    b0 = value(led, inp, cases["base"], **BEFORE)
    fc = parent_case(led, inp, cases["base"])
    t_kd = marginal_rate(fc["table"].iloc[-1].ebit * EOK, led["corporate_tax"]["brackets"])
    _, ev_ref, _, _ = parent_value(led, inp, fc, wacc_case(led, inp, 0.0, t_kd=t_kd).wacc)
    out.append(f"check: 0단계 = P3-B 값 {abs(b0['ev930'] - ev_ref) < 1e-9} (EV {b0['ev930']:,.2f} vs {ev_ref:,.2f})\n")

    # 1. before / after table
    rows = []
    for s in srps:
        for nm in order:
            bf = value(led, inp, cases[nm], srp=s, **BEFORE)
            af = value(led, inp, cases[nm], srp=s, **AFTER)
            rows.append(
                {
                    "scenario": nm,
                    "srp": s,
                    "before": bf["per_share"],
                    "after": af["per_share"],
                    "wacc_before": bf["wacc"],
                    "wacc_after": af["wacc"],
                    "ronic": af["ronic"],
                    "ronic_flag": af["ronic_flag"],
                    "tv_before": bf["tv_share"],
                    "tv_after": af["tv_share"],
                    "mult_before": bf["implied_multiple"],
                    "mult_after": af["implied_multiple"],
                    "ev_after": af["ev930"],
                    "eq_after": af["equity"],
                }
            )
    R = pd.DataFrame(rows)
    out.append("## 1. 전/후 (Gordon, 주당 원)\n")
    tab = pd.DataFrame(index=order)
    for s in srps:
        sub = R[R.srp == s].set_index("scenario").loc[order]
        tab[f"전 SRP {s:.0%}"] = sub.before
        tab[f"후 SRP {s:.0%}"] = sub.after
    tab.index.name = "시나리오"
    out.append(md(tab, "{:,.0f}"))
    vs = pd.DataFrame({f"후 SRP {s:.0%}": R[R.srp == s].set_index("scenario").loc[order].after / price - 1 for s in srps})
    vs.index.name = f"종가 {price:,.0f}원 대비(후)"
    out.append("\n" + md(vs, "{:+.1%}"))
    for col, lab, f in (
        ("wacc_after", "WACC(후)", "{:.2%}"),
        ("ronic", "RONIC(후, 기본 규칙)", "{:.1%}"),
        ("tv_after", "영구가치 비중(후)", "{:.1%}"),
        ("tv_before", "영구가치 비중(전)", "{:.1%}"),
        ("mult_after", "Gordon 함의 EV/EBITDA(후, 2040 EBITDA)", "{:.1f}"),
        ("mult_before", "Gordon 함의 EV/EBITDA(전, 2032 EBITDA)", "{:.1f}"),
        ("ev_after", "모회사 사업 EV(9/30, 후)", "{:,.1f}"),
    ):
        pv = R.pivot(index="scenario", columns="srp", values=col).loc[order]
        pv.columns = [f"SRP {c:.0%}" for c in pv.columns]
        pv.index.name = lab
        out.append("\n" + md(pv, f))
    flags = R[R.ronic_flag.notna()]
    out.append("\nRONIC 대체: " + ("; ".join(f"{r.scenario} SRP {r.srp:.0%}" for r in flags.itertuples()) or "없음") + "\n")

    # 2. decomposition (base, SRP 0)
    steps = [
        ("0. P3-B 기본", BEFORE),
        ("1. + 3단계(체감 구간, P3-B 정규화)", {"stage3": True, "vd": False, "de0": False}),
        ("2. + 가치동인 영구가치(RONIC 기본)", {"stage3": True, "vd": True, "de0": False}),
        ("3. + WACC D/E 0", AFTER),
    ]
    dec, prev = [], None
    for lab, kw in steps:
        v = value(led, inp, cases["base"], **kw)
        dec.append(
            {
                "단계": lab,
                "WACC": v["wacc"] * 100,
                "RONIC": v["ronic"] * 100 if kw["vd"] else np.nan,
                "모회사 EV(9/30)": v["ev930"],
                "주당(원)": v["per_share"],
                "변화(원)": v["per_share"] - prev if prev is not None else np.nan,
                "영구가치 비중": v["tv_share"] * 100,
            }
        )
        prev = v["per_share"]
    out.append("\n## 2. 분해 (기본 시나리오, SRP 0%)\n\n" + md(pd.DataFrame(dec).set_index("단계"), "{:,.2f}"))
    # reverse order check (contribution depends on order)
    alt = []
    for lab, kw in (
        ("D/E 0만", {"stage3": False, "vd": False, "de0": True}),
        ("3단계만", {"stage3": True, "vd": False, "de0": False}),
        ("가치동인만(2단계 없이 2032 뒤 바로)", {"stage3": False, "vd": True, "de0": False}),
    ):
        alt.append({"하나만 켬": lab, "주당(원)": value(led, inp, cases["base"], **kw)["per_share"]})
    out.append("\n" + md(pd.DataFrame(alt).set_index("하나만 켬"), "{:,.0f}"))

    # 3. sensitivities (base, SRP 0, after)
    base = value(led, inp, cases["base"], **AFTER)
    w0 = base["wacc"]
    sr = []
    for lab, kw in (
        ("RONIC 기본(증분 ROIC)", {}),
        ("RONIC = WACC", {"ronic": "wacc"}),
        ("RONIC = 1.5 × WACC", {"ronic": "1.5wacc"}),
    ):
        v = value(led, inp, cases["base"], **AFTER, **kw)
        sr.append(
            {
                "경우": lab,
                "RONIC": v["ronic"] * 100,
                "WACC": v["wacc"] * 100,
                "주당(원)": v["per_share"],
                "영구가치 비중": v["tv_share"] * 100,
            }
        )
    for lab, kw in (
        ("D/E 0.253, βd·Harris–Pringle, Kd BBB-", {"hp_kd": inp["rates"]["CB3Y_BBBm"]}),
        ("D/E 0.253, βd·Harris–Pringle, Kd AA-", {"hp_kd": inp["rates"]["CB3Y_AAm"]}),
        ("참고: P3-B WACC(D/E 0.253 Hamada, Kd BBB-)", {"de0": False}),
    ):
        kk = {**AFTER, **kw} if "hp_kd" in kw else {**AFTER, "de0": False}
        v = value(led, inp, cases["base"], **kk)
        sr.append(
            {
                "경우": lab,
                "RONIC": v["ronic"] * 100,
                "WACC": v["wacc"] * 100,
                "주당(원)": v["per_share"],
                "영구가치 비중": v["tv_share"] * 100,
            }
        )
    hist_days = inp["days"].mean().to_dict()
    dp = days_path(hist_days, pdays["median"], 2026, 2030, list(range(2026, 2033)))
    v = value(led, inp, cases["base"], **AFTER, days_by_year=dp)
    sr.append(
        {
            "경우": "운전자본 회전일수 → 피어 중앙값(2030)",
            "RONIC": v["ronic"] * 100,
            "WACC": v["wacc"] * 100,
            "주당(원)": v["per_share"],
            "영구가치 비중": v["tv_share"] * 100,
        }
    )
    out.append("\n## 3. 민감도 (기본 시나리오, SRP 0%, 수정 후)\n\n" + md(pd.DataFrame(sr).set_index("경우"), "{:,.2f}"))
    pdt = pdays["table"].copy()
    pdt.loc["중앙값"] = pdays["median"]
    pdt.loc["RF 모회사 과거 평균"] = {k: hist_days[k] for k in ("dso", "dio", "dpo")}
    out.append("\n피어 회전일수(FY2025)\n\n" + md(pdt.rename_axis("회사"), "{:.1f}"))
    grid = {}
    R0 = base["ronic"]
    for dw in (-0.02, -0.01, 0.0, 0.01, 0.02):
        for g in (0.01, 0.015, 0.02, 0.025, 0.03):
            vv = value(led, inp, cases["base"], **AFTER, wacc_override=w0 + dw, g_override=g, ronic=R0)
            grid[(f"{w0 + dw:.2%}", f"g {g:.1%}")] = vv["per_share"]
    gs = pd.Series(grid).unstack()
    gs = gs.loc[sorted(gs.index, key=lambda x: float(x.strip("%")))]
    gs.index.name = f"WACC \\ g (RONIC {R0:.1%} 고정)"
    out.append("\n" + md(gs, "{:,.0f}"))

    # 4. reverse DCF before/after
    from src.valuation.rf_dcf import solve_growth

    wb = wacc_case(led, inp, 0.0, t_kd=t_kd).wacc
    rv = []
    for mgn in (0.15, 0.18, 0.21, 0.24, 0.27, 0.30):
        b = solve_growth(led, inp, cases["base"], mgn, wb, price)
        a = solve_gu(led, inp, cases["base"], mgn, price, **AFTER)
        rv.append(
            {
                "정상 이익률": f"{mgn:.0%}",
                "전(P3-B)": b,
                "후(P3-B2)": a,
                "후 2032 매출(억원)": 500 * (1 + a) ** 6 if a is not None else np.nan,
            }
        )
    rvt = pd.DataFrame(rv).set_index("정상 이익률")
    out.append(
        f"\n## 4. 역DCF (종가 {price:,.0f}원, 2026 매출 500억, 2027~2032 같은 성장률)\n\n"
        + md(rvt[["전(P3-B)", "후(P3-B2)"]], "{:.1%}")
        + "\n\n"
        + md(rvt[["후 2032 매출(억원)"]], "{:,.0f}")
    )

    # 5. ROIC path and RONIC (base)
    rp = roic_path(led, inp, base["fc"])
    rp_show = rp.T
    rp_show.index.name = "기본 시나리오(억원, ROIC는 연환산)"
    out.append("\n## 5. 명시 기간 ROIC와 RONIC\n\n" + md(rp_show.astype(float), "{:,.3f}"))
    out.append(
        f"\nRONIC 기본값(증분 ROIC 2027~2032): 비관 {R[(R.scenario == 'pessimistic') & (R.srp == 0)].ronic.iloc[0]:.1%}, "
        f"기본 {R0:.1%}, 낙관 {R[(R.scenario == 'optimistic') & (R.srp == 0)].ronic.iloc[0]:.1%}\n"
    )
    fade = fade_path(cases["base"]["g_2028_2032"][-1], cases["base"]["g_terminal"], 8)
    out.append("체감 구간 성장률(기본): " + ", ".join(f"{y} {g:.2%}" for y, g in zip(FADE, fade)))

    _figures(R, order, srps, price, rvt)
    text = "\n".join(out)
    (ROOT / "data" / "interim" / "p3b2_tables.md").write_text(text, encoding="utf-8")
    R.to_csv(ROOT / "data" / "interim" / "p3b2_results.csv", index=False)
    return text


def _figures(R, order, srps, price, rvt):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    fig_dir = ROOT / "reports" / "figures"
    lab = {"pessimistic": "비관", "base": "기본", "optimistic": "낙관"}
    fig, ax = plt.subplots(figsize=(8, 4.2))
    wbar = 0.13
    cols_b = ["#bbbbbb", "#999999", "#777777"]
    cols_a = ["#2a6f97", "#61a5c2", "#a9d6e5"]
    for i, s in enumerate(srps):
        sub = R[R.srp == s].set_index("scenario").loc[order]
        ax.bar(np.arange(3) + (i - 2.5) * wbar, sub.before, wbar, color=cols_b[i], label=f"전 SRP {s:.0%}")
        ax.bar(np.arange(3) + (i + 0.5) * wbar, sub.after, wbar, color=cols_a[i], label=f"후 SRP {s:.0%}")
    ax.axhline(price, color="#c1121f", ls="--", lw=1)
    ax.text(2.45, price, f"기준일 종가 {price:,.0f}원", color="#c1121f", va="bottom", ha="right", fontsize=8)
    ax.set_xticks(range(3), [lab[o] for o in order])
    ax.set_ylabel("주당 가치(원, 가정 하 추정)")
    ax.set_title("RF머트리얼즈 SOTP 주당 가치: P3-B(전) vs P3-B2(후) (초안)")
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    fig.text(0.01, 0.01, "가정 기반 계산(투자 권유 아님). 기준일 2026-09-30, 종가는 한국거래소 통계정보", fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(fig_dir / "p3b2_per_share_before_after.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 4))
    x = [float(i.strip("%")) for i in rvt.index]
    for col, c, lb in (("전(P3-B)", "#999999", "전(P3-B)"), ("후(P3-B2)", "#2a6f97", "후(P3-B2)")):
        y = rvt[col].astype(float) * 100
        ax.plot(x, y, marker="o", color=c, label=lb)
        for xi, yi in zip(x, y):
            ax.annotate(f"{yi:.0f}%", (xi, yi), textcoords="offset points", xytext=(4, 4), fontsize=7, color=c)
    ax.set_xlabel("모회사 정상 영업이익률(%)")
    ax.set_ylabel("2027~2032 연평균 매출 성장률(%)")
    ax.set_title("역DCF: 기준일 종가를 맞추는 조합, 전/후 (초안)")
    ax.legend(fontsize=8)
    fig.text(0.01, 0.01, "2026 매출 500억, 나머지 가정은 기본 시나리오. 후 = 3단계·가치동인·D/E 0", fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(fig_dir / "p3b2_reverse_dcf.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    print(main())
