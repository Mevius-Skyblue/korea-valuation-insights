"""Forecast sheet of the Excel model (split out of sheets_calc.py in P7-C4): the history base, the forecast rows of every
engine type (scenario_capex / mechanical / mechanical_v2), the parameter blocks and the business-plan check.
"""

from __future__ import annotations

from src.excel.context import Ctx
from src.excel.sheets_input import SCEN_PARAMS
from src.excel.sheets_layout import (
    ACC_KO,
    C_FIRST,
    C_OPEN,
    FC_ROWS,
    FC_ROWS_MECH,
    FC_TAIL_MAIN,
    FC_TAIL_SCEN,
    _row_range,
    _vlist,
    eff_of,
    n_periods,
    tax_of,
)
from src.excel.writer import a1


def forecast_rows(c: Ctx, s, top: int, P: dict, main: bool) -> dict:
    """Write the period rows from `top`. P: formula refs rev26, gvec, glast, margin, gt, opflag, op26."""
    n = n_periods(c.d)
    mech = c.d["type"] == "mechanical"
    P = {**{k: "NA()" for k in ("rev26", "gvec", "opflag", "op26", "g0", "gtx")}, **P}  # keys of the other engine type
    rows = (FC_ROWS_MECH if mech else FC_ROWS) + (FC_TAIL_MAIN if main else FC_TAIL_SCEN)
    R = {k: top + i for i, (k, *_r) in enumerate(rows)}

    def X(k, j):
        return a1(R[k], j) if k in R else "NA()"

    def W(k, j):
        return a1(R[k], j - 1) if k in R else "NA()"

    for _i, (k, lab, unit, _kind) in enumerate(rows):
        s.text(R[k], 0, lab)
        if unit:
            s.text(R[k], 1, unit, "note")
    # opening column
    s.const(R["k"], C_OPEN, 0, "int")
    if not mech:
        s.const(R["maint"], C_OPEN, 0, "mn")
        s.const(R["cum_maint"], C_OPEN, 0, "mn")
    s.fx(R["nwc"], C_OPEN, "=NWC_Open", "mn")
    for j in range(C_FIRST, C_FIRST + n):
        f = {
            "k": f"={W('k', j)}+1",
            "year": f"=YEAR(CfStart)+{X('k', j)}-1",
            "stage": f'=IF({X("explicit", j)}=1,"명시","체감")',
            "start": f"=MAX(DATE({X('year', j)},1,1),CfStart)",
            "end": f"=DATE({X('year', j)},12,31)",
            "f": f"=({X('end', j)}-{X('start', j)}+1)/DaysYr",
            "explicit": f"=IF({X('year', j)}<=ExplicitEnd,1,0)",
            # explicit: scenario path; fade: g_t = g_last − (year − ExplicitEnd) × (g_last − g) / FadeYears
            "g": (
                f"=IF({X('k', j)}=1,0,IF({X('explicit', j)}=1,INDEX({P['gvec']},{X('year', j)}-YEAR(CfStart)),"
                f"{P['glast']}-({X('year', j)}-ExplicitEnd)*({P['glast']}-{P['gt']})/FadeYears))"
            ),
            "rev_fy": f"=IF({X('k', j)}=1,{P['rev26']},{W('rev_fy', j)}*(1+{X('g', j)}))",
            "rev": f"=IF({X('k', j)}=1,{X('rev_fy', j)}-H1Rev,{X('rev_fy', j)})",
            "ebit": f"=IF(AND({X('k', j)}=1,{P['opflag']}=1),{P['op26']}-H1Op,{X('rev', j)}*{P['margin']})",
            "fy_ebit": f"=IF({X('k', j)}=1,H1Op+{X('ebit', j)},{X('ebit', j)})",
            "maint": f"=IF({X('explicit', j)}=1,CapexRatio*{X('rev', j)},0)",
            "cum_maint": f"={W('cum_maint', j)}+{W('maint', j)}",
            # straight line: earlier maintenance CAPEX a full period, this period's half (spent evenly)
            "dep_m": f"=IF({X('explicit', j)}=1,{X('cum_maint', j)}/LifeM*{X('f', j)}+{X('maint', j)}/LifeM*{X('f', j)}/2,0)",
            "dep_b": f"=IF(AND({X('explicit', j)}=1,{X('year', j)}>=BldgStart),BldgTotal/LifeB,0)",
            "dep_old": f"=IF({X('explicit', j)}=1,DNA_FY25*{X('f', j)},0)",
            "dna": f"={X('dep_m', j)}+{X('dep_b', j)}+{X('dep_old', j)}",
            "gcapex": f"=IF({X('explicit', j)}=1,SUMIFS(GcAmt,GcYear,{X('year', j)}),0)",
            "capex": f"={X('maint', j)}+{X('gcapex', j)}",
            # days on FULL-year revenue (also for 2H26), COGS = revenue × LTM COGS ratio
            "nwc": (
                f"=IF({X('explicit', j)}=1,{X('rev_fy', j)}*DSO/DaysYr+{X('rev_fy', j)}*COGSR*DIO/DaysYr"
                f"-{X('rev_fy', j)}*COGSR*DPO/DaysYr-{X('rev_fy', j)}*DCL/DaysYr,{W('nwc', j)})"
            ),
            "dnwc": f"=IF({X('explicit', j)}=1,{X('nwc', j)}-{W('nwc', j)},0)",
            "tax_rate": f"={eff_of(X('fy_ebit', j))}",
            "tax": f"=MAX({X('ebit', j)},0)*{X('tax_rate', j)}",
            "nopat": f"={X('ebit', j)}-{X('tax', j)}",
            "reinv_rate": f"=IF({X('explicit', j)}=1,0,{X('g', j)}/RONIC)",
            "reinv": f"={X('nopat', j)}*{X('reinv_rate', j)}",
            "fcff": f"={X('nopat', j)}+{X('dna', j)}-{X('capex', j)}-{X('dnwc', j)}-{X('reinv', j)}",
            "ebitda": f"={X('ebit', j)}+{X('dna', j)}",
            "fcff_pre": f"={X('nopat', j)}+{X('dna', j)}-{X('capex', j)}-{X('dnwc', j)}",
        }
        if mech:  # company_dcf.forecast: growth_path to g by FadeTo, ratios of the average years
            y0 = "YEAR(CfStart)"
            # P7-X2b: a confirmed year the margin path reaches its end value (default the explicit end)
            conv_end = "ConvEndOverride" if (c.d.get("overrides") or {}).get("conv_end") is not None else "ExplicitEnd"
            f.update(
                {
                    "g": (
                        f"=IF({X('explicit', j)}=1,{P['g0']}+({P['gtx']}-{P['g0']})*MIN({X('year', j)}-{y0},FadeTo-{y0})/(FadeTo-{y0}),"
                        f"{P['glast']}-({X('year', j)}-ExplicitEnd)*({P['glast']}-{P['gt']})/FadeYears)"
                    ),
                    "rev_fy": f"=IF({X('k', j)}=1,RevFY_Last*(1+{X('g', j)}),{W('rev_fy', j)}*(1+{X('g', j)}))",
                    "ebit": (
                        f"={X('rev', j)}*({P['margin']}+MarginConvAmt*MIN(({X('year', j)}-YEAR(CfStart))/({conv_end}-YEAR(CfStart)),1))"
                        if c.d.get("v2")
                        else f"={X('rev', j)}*{P['margin']}"
                    ),
                    "dna": f"=IF({X('explicit', j)}=1,{X('rev', j)}*DnaRatio,0)",
                    "capex": f"=IF({X('explicit', j)}=1,{X('rev', j)}*CapexRatio,0)",
                    "nwc": (
                        f"=IF({X('explicit', j)}=1,{X('rev_fy', j)}*DSO/DaysYr+{X('rev_fy', j)}*COGSR*DIO/DaysYr"
                        f"-{X('rev_fy', j)}*COGSR*DPO/DaysYr,{W('nwc', j)})"
                    ),
                }
            )
        for k, _lab, _unit, kind in rows:
            s.fx(R[k], j, f[k], kind)
    return R


def forecast(c: Ctx):
    d, s = c.d, c.sheet("Forecast")
    n = n_periods(d)
    s.widths({0: 36, 1: 9, 2: 13, **{C_FIRST + j: 12 for j in range(n)}})
    s.text(
        0,
        0,
        "Forecast — "
        + ("모회사 사업 예측" if d["type"] == "scenario_capex" else "연결 예측(기계적 경로)")
        + " (선택한 시나리오, 백만원)",
        "title",
    )
    s.fx(1, 0, '="선택 시나리오: "&ScenSel&"   (2H26~"&ExplicitEnd&" 명시, 이후 "&FadeYears&"년 체감 → 영구)"', "gen")
    r = 3
    # ---- tax delta table (from Inputs table 1)
    s.text(r, 0, "세율표(누진) — Inputs 표 1 연결, 한계세율 차이", "subtitle")
    for j, h in enumerate(["하한", "상한", "세율", "세율 증분"]):
        s.text(r + 1, 2 + j, h, "header")
    t0, t1 = c.layout["tax_rows"]
    for i in range(t1 - t0 + 1):
        rr = r + 2 + i
        s.text(rr, 0, f"구간 {i + 1}")
        s.fx(rr, 2, f"=Inputs!{a1(t0 + i, 1)}", "mn")
        s.fx(rr, 3, f'=IF(ISBLANK(Inputs!{a1(t0 + i, 2)}),"",Inputs!{a1(t0 + i, 2)})', "mn")
        s.fx(rr, 4, f"=Inputs!{a1(t0 + i, 3)}", "pct1")
        s.fx(rr, 5, f"={a1(rr, 4)}-N({a1(rr - 1, 4)})" if i else f"={a1(rr, 4)}", "pct1")
    c.range_name("TaxDRate", "Forecast", a1(r + 2, 5), a1(r + 2 + t1 - t0, 5))
    r = r + 3 + (t1 - t0) + 1

    if d["type"] == "mechanical":
        r = _base_mech(c, s, r)
        r = _params_mech(c, s, r)
        P = {"g0": "G0_Sel", "gtx": "GTermCfg", "glast": "GLast_Sel", "margin": "Margin_Sel", "gt": "GEff"}
    else:
        r = _base_capex(c, s, r)
        r = _params_capex(c, s, r)
        P = {
            "rev26": "Rev26_Sel",
            "gvec": "GVec_Sel",
            "glast": "GLast_Sel",
            "margin": "Margin_Sel",
            "gt": "GEff",
            "opflag": "OpFlag_Sel",
            "op26": "Op26_Sel",
        }

    # ---- timeline
    s.text(r, 0, f"예측 (기초 열 = {d['meta']['bs_date']} 재무상태표)", "subtitle")
    s.text(r, C_OPEN, "기초", "header")
    s.ws.freeze_panes(r + 1, 3)
    R = forecast_rows(c, s, r + 1, P, main=True)
    for j in range(C_FIRST, C_FIRST + n):
        s.fx(r, j, f'=IF({a1(R["k"], j)}=1,"2H"&RIGHT({a1(R["year"], j)},2),""&{a1(R["year"], j)})', "gen")
    c.layout["fc_rows"] = R
    c.layout["n"] = n
    lp = (d.get("v2") or {}).get("start") == "ltm"
    if lp:  # P7-B3b loss path: cumulative explicit FCF vs cash-like (funding check)
        rc = max(R.values()) + 1
        s.text(rc, 0, "누적 FCF(명시 기간, 적자 경로 자금 점검)")
        s.text(rc, 1, "백만원", "note")
        for j in range(C_FIRST, C_FIRST + n):
            prev = f"N({a1(rc, j - 1)})" if j > C_FIRST else "0"
            s.fx(rc, j, f'=IF({a1(R["explicit"], j)}=1,{prev}+{a1(R["fcff"], j)},"")', "mn")
        _vlist(
            s,
            rc + 1,
            "누적 FCF 최저(0 이하)",
            f"=MIN(0,MIN({a1(rc, C_FIRST)}:{a1(rc, C_FIRST + n - 1)}))",
            "mn",
            "백만원",
            "FundTrough",
            "Checks: −최저 > 현금성이면 WARN(추가 자금 필요)",
        )
        c.layout["fund_row"] = rc
    _plan_check(c, s, max(R.values()) + (5 if lp else 3))


def _plan_check(c: Ctx, s, r):
    """Business-plan check (03 문서 3-3 #4): forecast growth and margin next to history. Display only - no warning
    threshold is set (a threshold is a judgement left to the reviewer)."""
    d = c.d
    fs, L = c.layout["fs_refs"], d["meta"]["ltm_year"]
    F, n = c.layout["fc_rows"], c.layout["n"]
    if d["type"] == "scenario_capex":
        o = lambda a, k: fs[("OFS", k, a)]  # noqa: E731
        y0, y1 = d["hist_years"][0], d["hist_years"][-1]
        hist_cagr = f"=({o('revenue', f'FY{y1}')}/{o('revenue', f'FY{y0}')})^(1/({y1}-{y0}))-1"
        ny = d["nwc_years"]
        hist_m = "=AVERAGE(" + ",".join(f"{o('operating_income', f'FY{y}')}/{o('revenue', f'FY{y}')}" for y in ny) + ")"
        rev_last = o("revenue", f"FY{L - 1}")
        lab_h = f"과거 매출 CAGR(별도 FY{y0} → FY{y1})"
        lab_m = f"과거 영업이익률 평균(별도 FY{ny[0]}~FY{ny[-1]})"
    else:
        mc = d["mech"]
        hist_cagr, hist_m, rev_last = "=CAGR", "=HistMargin", "RevFY_Last"
        lab_h = f"과거 매출 CAGR(연결 FY{mc['cagr_years'][0]} → FY{mc['cagr_years'][1]})"
        lab_m = f"과거 영업이익률 평균(연결 FY{mc['avg_years'][0]}~FY{mc['avg_years'][-1]})"
    fr = lambda k: _row_range("Forecast", F[k], n)  # noqa: E731
    s.text(r, 0, "사업계획 검증 — 예측(선택 시나리오) vs 과거 (표시만, 괴리 경고 기준은 사람 판단)", "subtitle")
    rows = [
        (lab_h, hist_cagr, "PlanHistCAGR"),
        (f"예측 FY{L} 매출 성장률(직전 회계연도 대비)", f"=Forecast!{a1(F['rev_fy'], C_FIRST)}/{rev_last}-1", "PlanG26"),
        (
            f"예측 매출 CAGR(FY{L} → 명시 마지막 연도)",
            f"=(INDEX({fr('rev_fy')},MATCH(ExplicitEnd,{fr('year')},0))/Forecast!{a1(F['rev_fy'], C_FIRST)})^(1/(ExplicitEnd-YEAR(CfStart)))-1",
            "PlanFcCAGR",
        ),
        ("  차이(예측 CAGR − 과거 CAGR)", "=PlanFcCAGR-PlanHistCAGR", "PlanGapCAGR"),
        (lab_m, hist_m, "PlanHistMargin"),
        ("예측 정상 영업이익률", "=Margin_Sel", "PlanMargin"),
        ("  차이(예측 − 과거)", "=PlanMargin-PlanHistMargin", "PlanGapMargin"),
    ]
    for i, (lab, f, nm) in enumerate(rows):
        _vlist(s, r + 1 + i, lab, f, "pct", "%", nm)
    c.range_name("PlanCheck", "Forecast", a1(r + 1, 0), a1(r + len(rows), 2))
    _plan_reference(c, s, r, fr)


def _plan_reference(c: Ctx, s, r, fr):
    """P6-A: next to the business-plan check, the P5-B reference distribution (SPAC merger opinions: actual / forecast)
    and the revenue achievement by forecast-CAGR quartile band, with the band of this model's forecast CAGR.
    Display only: no haircut, no warning verdict. Values are aggregates from DB p5b_* (grey = not formulas)."""
    ref = c.d["p5b_ref"]
    F = c.layout["fc_rows"]
    c0 = 5
    s.text(r, c0, "참고: P5-B 스팩 합병 외부평가 추정의 실제 달성률(실적 ÷ 예측, 표시만) " + ref["status"], "subtitle")
    for j, h in enumerate(["계정", "차연도 h", "n", "달성률 중앙값", "Q1", "Q3"]):
        s.text(r + 1, c0 + j, h, "header")
    ach = ref["achievement"]
    for i, x in enumerate(ach):
        rr = r + 2 + i
        s.eng(rr, c0, ACC_KO[x["account"]])
        s.eng(rr, c0 + 1, x["h"], "int")
        s.eng(rr, c0 + 2, x["n"], "int")
        for j, k in enumerate(("median", "q1", "q3")):
            s.eng(rr, c0 + 3 + j, x[k], "pct1")
    s.engine_range(r + 2, c0, r + 1 + len(ach), c0 + 5)
    c.range_name("P5bAchTable", "Forecast", a1(r + 2, c0), a1(r + 1 + len(ach), c0 + 5))
    rr = r + 2 + len(ach)
    s.text(rr, c0, ref["note"], "note")
    s.text(rr + 1, c0, "출처: " + ref["source"] + ". 거래 목록은 넣지 않음(집계값만)", "note")
    # ---- forecast revenue CAGR bands
    cg = ref["cagr"]
    r2 = rr + 3
    s.text(r2, c0, f"예측 매출 CAGR 구간별 매출 달성률 중앙값(스팩, 사분위 4구간, 기준 {cg['n_base']}건)", "subtitle")
    hdr = ["구간", "CAGR 하한", "CAGR 상한", "거래 수", "1차 중앙값", "1차 n", "2차 중앙값", "2차 n", "3차 중앙값", "3차 n"]
    for j, h in enumerate(hdr):
        s.text(r2 + 1, c0 + j, h, "header")
    names = ["1구간(하위 25%)", "2구간", "3구간", "4구간(상위 25%)"]
    for i, b in enumerate(cg["bands"]):
        q = r2 + 2 + i
        s.eng(q, c0, names[i])
        s.eng(q, c0 + 1, b["lo"], "pct1")
        s.eng(q, c0 + 2, b["hi"], "pct1")
        s.eng(q, c0 + 3, b["n_deals"], "int")
        for j, h in enumerate((1, 2, 3)):
            s.eng(q, c0 + 4 + 2 * j, b[f"h{h}_median"], "pct1")
            s.eng(q, c0 + 5 + 2 * j, b[f"h{h}_n"], "int")
    q0, q3 = r2 + 2, r2 + 5
    s.engine_range(q0, c0, q3, c0 + 9)
    c.range_name("P5bCagrTable", "Forecast", a1(q0, c0), a1(q3, c0 + 9))
    lo = lambda i: a1(q0 + i, c0 + 1, True)  # noqa: E731      lower edge of band i (0-based)
    # ---- this model's forecast CAGR on the opinions' horizon (first forecast year + N - 1 years)
    t = q3 + 2
    s.text(t, c0, "비교 기준 추정 연수(의견서 추정 기간 중앙값)")
    s.eng(t, c0 + 4, ref["target_cagr_years"], "int")
    s.engine_range(t, c0 + 4, t, c0 + 4)
    yrs = a1(t, c0 + 4, True)
    first = f"Forecast!{a1(F['rev_fy'], C_FIRST, True)}"
    s.text(t + 1, c0, "대상 회사 예측 매출 CAGR(첫 추정 회계연도부터 N개 연도, 선택 시나리오)")
    s.fx(
        t + 1,
        c0 + 4,
        f"=(INDEX({fr('rev_fy')},MATCH(YEAR(CfStart)+{yrs}-1,{fr('year')},0))/{first})^(1/({yrs}-1))-1",
        "pct1",
        name="PlanFcCAGR5",
    )
    s.text(t + 2, c0, "해당 구간(1~4)")
    s.fx(
        t + 2,
        c0 + 4,
        f"=IF(PlanFcCAGR5>={lo(3)},4,IF(PlanFcCAGR5>={lo(2)},3,IF(PlanFcCAGR5>={lo(1)},2,1)))",
        "int",
        name="PlanBand",
    )
    s.fx(
        t + 2,
        c0 + 5,
        f'=IF(OR(PlanFcCAGR5<{lo(0)},PlanFcCAGR5>{a1(q3, c0 + 2, True)}),"표본 범위 밖(참고만)","표본 범위 안")',
        "gen",
        name="PlanBandRange",
    )
    s.text(t + 3, c0, "그 구간 매출 달성률 중앙값 1차 / 2차 / 3차")
    for j in range(3):
        col_rng = f"{a1(q0, c0 + 4 + 2 * j, True)}:{a1(q3, c0 + 4 + 2 * j, True)}"
        s.fx(t + 3, c0 + 4 + j, f"=INDEX({col_rng},PlanBand)", "pct1", name=f"PlanBandH{j + 1}")
    s.text(
        t + 4,
        c0,
        "표시만: 예측을 자동으로 깎거나 경고 판정하지 않는다. 비교 기준이 다름(스팩 합병 의견서 5년 추정 vs 이 모델)",
        "note",
    )


def _geff(c: Ctx, s, r):
    _vlist(
        s,
        r,
        "영구·체감 구간 g(데이터 표 입력 칸이 비면 시나리오 값)",
        "=IF(ISNUMBER(GOvr),GOvr,GTerm_Sel)",
        "pct",
        "%",
        "GEff",
        "Scenarios 시트의 데이터 표가 GOvr 칸에 값을 넣어 계산한다",
    )
    return r + 1


def _base_capex(c: Ctx, s, r):
    """rf_dcf.load_inputs / parent_case: separate (OFS) history of the parent."""
    d = c.d
    fs, L = c.layout["fs_refs"], d["meta"]["ltm_year"]
    o = lambda a, k: fs[("OFS", k, a)]  # noqa: E731
    s.text(r, 0, "기초 비율 — 모회사 별도 과거 값(FS_Hist)", "subtitle")
    r += 1
    hy = d["hist_years"]
    for j, y in enumerate(hy):
        s.text(r, 2 + j, f"FY{y}", "header")
    s.text(r, 2 + len(hy), "값", "header")
    r += 1
    s.text(r, 0, "CAPEX ÷ 매출 (유형 + 무형 취득)")
    for j, y in enumerate(hy):
        k = f"FY{y}"
        s.fx(r, 2 + j, f"=({o('capex_ppe', k)}+{o('capex_intangibles', k)})/{o('revenue', k)}", "pct")
    s.fx(r, 2 + len(hy), f"=MEDIAN({a1(r, 2)}:{a1(r, 1 + len(hy))})", "pct", name="CapexRatio")
    s.text(r, 3 + len(hy), "유지 CAPEX 비율 = 과거 중앙값", "note")
    r += 2
    ny = d["nwc_years"]
    for j, y in enumerate(ny):
        s.text(r, 2 + j, f"FY{y}", "header")
    s.text(r, 2 + len(ny), "평균", "header")
    r += 1
    days = [
        ("DSO", "매출채권 회전일수(매출 기준)", "receivables", "revenue"),
        ("DIO", "재고 회전일수(매출원가 기준)", "inventories", "cogs"),
        ("DPO", "매입채무 회전일수(매출원가 기준)", "trade_payables", "cogs"),
        ("DCL", "계약부채 일수(매출 기준)", "contract_liabilities", "revenue"),
    ]
    for nm, lab, num, den in days:
        s.text(r, 0, lab)
        s.text(r, 1, "일", "note")
        for j, y in enumerate(ny):
            k = f"FY{y}"
            s.fx(r, 2 + j, f"={o(num, k)}/{o(den, k)}*DaysYr", "days")
        s.fx(r, 2 + len(ny), f"=AVERAGE({a1(r, 2)}:{a1(r, 1 + len(ny))})", "days", name=nm)
        r += 1
    r += 1
    fy, h1, h0 = f"FY{L - 1}", f"H1{L}", f"H1{L - 1}"
    _vlist(
        s,
        r,
        "매출원가율(LTM = FY + 당기 1H − 전기 1H)",
        f"=({o('cogs', fy)}+{o('cogs', h1)}-{o('cogs', h0)})/({o('revenue', fy)}+{o('revenue', h1)}-{o('revenue', h0)})",
        "pct",
        "%",
        "COGSR",
    )
    _vlist(
        s,
        r + 1,
        "순운전자본(기초, 2026-06-30)",
        f"={o('receivables', h1)}+{o('inventories', h1)}-{o('trade_payables', h1)}-{o('contract_liabilities', h1)}",
        "mn",
        "백만원",
        "NWC_Open",
        "매출채권 + 재고 − 매입채무 − 계약부채",
    )
    _vlist(s, r + 2, "2026 상반기 매출(별도)", f"={o('revenue', h1)}", "mn", "백만원", "H1Rev")
    _vlist(s, r + 3, "2026 상반기 영업이익(별도)", f"={o('operating_income', h1)}", "mn", "백만원", "H1Op")
    _vlist(s, r + 4, "기존 자산 D&A(FY2025, 연간)", f"={o('dna', fy)}", "mn", "백만원", "DNA_FY25")
    _vlist(s, r + 5, "신규 공장(building) 투자 합계", '=SUMIFS(GcAmt,GcKind,"building")', "mn", "백만원", "BldgTotal")
    return r + 7


def _base_mech(c: Ctx, s, r):
    """company_dcf.history / hist_roic: consolidated history (CAGR, 3-year averages, ROIC cap)."""
    d = c.d
    fs, L = c.layout["fs_refs"], d["meta"]["ltm_year"]
    o = lambda a, k: fs[("CFS", k, a)]  # noqa: E731
    mc = d["mech"]
    y0, y1 = mc["cagr_years"]
    av = mc["avg_years"]
    s.text(r, 0, "기초 비율 — 연결 과거 값(FS_Hist), 과거 3년 평균", "subtitle")
    r += 1
    for j, y in enumerate(av):
        s.text(r, 2 + j, f"FY{y}", "header")
    s.text(r, 2 + len(av), "평균", "header")
    r += 1
    # P7-B2 B2-F5: a year without D&A is text -> AVERAGE skips it, as the engine's mean skips NaN
    items = [
        ("HistMargin", "영업이익률", "=({op})/({rev})"),
        ("DnaRatio", "D&A ÷ 매출", '=IF(ISNUMBER({dna}),({dna})/({rev}),"n/a")'),
        ("CapexRatio", "CAPEX ÷ 매출(유형 + 무형)", "=({cx1}+{cx2})/({rev})"),
        ("COGSR", "매출원가율", "=({cogs})/({rev})"),
        ("DSO", "매출채권 회전일수(매출 기준)", '=IF(({rev})=0,"n/a",({rec})/({rev})*DaysYr)'),
        ("DIO", "재고 회전일수(매출원가 기준)", '=IF(({cogs})=0,"n/a",({inv})/({cogs})*DaysYr)'),
        ("DPO", "매입채무 회전일수(매출원가 기준)", '=IF(({cogs})=0,"n/a",({pay})/({cogs})*DaysYr)'),
    ]
    for nm, lab, tpl in items:
        s.text(r, 0, lab)
        for j, y in enumerate(av):
            k = f"FY{y}"
            s.fx(
                r,
                2 + j,
                tpl.format(
                    op=o("operating_income", k),
                    rev=o("revenue", k),
                    dna=o("dna", k),
                    cx1=o("capex_ppe", k),
                    cx2=o("capex_intangibles", k),
                    cogs=o("cogs", k),
                    rec=o("receivables", k),
                    inv=o("inventories", k),
                    pay=o("trade_payables", k),
                ),
                "days" if nm in ("DSO", "DIO", "DPO") else "pct",
            )
        rg = f"{a1(r, 2)}:{a1(r, 1 + len(av))}"
        avg = (
            f"=IF(COUNT({rg})=0,0,AVERAGE({rg}))" if nm in ("DSO", "DIO", "DPO") else f"=AVERAGE({rg})"
        )  # no year with a non-zero denominator -> 0 days, as the engine (B3-F5)
        ovr_ = d.get("overrides") or {}  # P7-X2b: a confirmed ratio replaces the 3-year average (the row above stays)
        okey = {"DnaRatio": "dna_ratio", "CapexRatio": "capex_ratio"}.get(nm)
        if okey and ovr_.get(okey) is not None:
            avg = f"={nm}Override"
        elif nm in ("DSO", "DIO", "DPO") and ovr_.get("nwc_days") is not None:
            avg = f"={nm[0] + nm[1:].lower()}Override"
        s.fx(r, 2 + len(av), avg, "days" if nm in ("DSO", "DIO", "DPO") else "pct", name=nm)
        r += 1
    # historical ROIC (RONIC cap): NOPAT_y / opening invested capital (NWC + PPE + intangibles + ROU at FY y−1)
    s.text(r, 0, "기초 투하자본(전년 말)")
    for j, y in enumerate(av):
        k = f"FY{y - 1}"
        s.fx(
            r,
            2 + j,
            f"={o('receivables', k)}+{o('inventories', k)}-{o('trade_payables', k)}+{o('ppe', k)}+{o('intangibles', k)}+{o('rou_assets', k)}",
            "mn",
        )
    ic = r
    r += 1
    s.text(r, 0, "NOPAT = 영업이익 − 누진 세금")
    for j, y in enumerate(av):
        op = o("operating_income", f"FY{y}")
        s.fx(r, 2 + j, f"={op}-{tax_of(op)}", "mn")
    nop = r
    r += 1
    s.text(r, 0, "ROIC(기초 투하자본 > 0일 때)")
    for j in range(len(av)):
        s.fx(r, 2 + j, f'=IF({a1(ic, 2 + j)}>0,{a1(nop, 2 + j)}/{a1(ic, 2 + j)},"")', "pct")
    s.fx(r, 2 + len(av), f"=AVERAGE({a1(r, 2)}:{a1(r, 1 + len(av))})", "pct", name="RonicCap")
    s.text(r, 3 + len(av), "RONIC 상한(사전 고정)", "note")
    r += 2
    fy, h1, h0 = f"FY{L - 1}", f"H1{L}", f"H1{L - 1}"
    _vlist(
        s,
        r,
        f"매출 5년 CAGR(FY{y0} → FY{y1})",
        f"=({o('revenue', f'FY{y1}')}/{o('revenue', f'FY{y0}')})^(1/({y1}-{y0}))-1",
        "pct",
        "%",
        "CAGR",
    )
    _vlist(
        s,
        r + 1,
        f"순운전자본(기초, {d['meta']['bs_date']})",
        f"={o('receivables', h1)}+{o('inventories', h1)}-{o('trade_payables', h1)}",
        "mn",
        "백만원",
        "NWC_Open",
        "매출채권 + 재고 − 매입채무",
    )
    _vlist(s, r + 2, f"{L} 상반기 매출(연결)", f"={o('revenue', h1)}", "mn", "백만원", "H1Rev")
    _vlist(s, r + 3, f"{L} 상반기 영업이익(연결)", f"={o('operating_income', h1)}", "mn", "백만원", "H1Op")
    _vlist(s, r + 4, f"FY{L - 1} 매출(연결)", f"={o('revenue', fy)}", "mn", "백만원", "RevFY_Last")
    _vlist(
        s,
        r + 5,
        "LTM 세전이익(세후 Kd 한계세율 기준)",
        f"={o('pretax_income', fy)}+{o('pretax_income', h1)}-{o('pretax_income', h0)}",
        "mn",
        "백만원",
        "PretaxLTM",
    )
    r += 7
    if d.get("v2"):  # P7-B2b mechanical_v2 (auto drafts): config/p7b2b.yaml, company_dcf.v2_inputs
        s.text(r, 0, "기본 경로 v2 — 5년 이익률 중앙값, 피어 쪽 수렴, 성장률 혼합(사전 고정 91a84dd)", "subtitle")
        r += 1
        hy = list(range(L - 5, L))  # P7-X2b: FY(Y−5)~FY(Y−1), the engine's v2 window (was typed 2021~2025)
        s.text(r, 0, f"영업이익률 FY{hy[0]}~{hy[-1]}(매출 > 0인 해)")
        for j, y in enumerate(hy):
            k = f"FY{y}"
            f = (
                f'=IF({o("revenue", k)}>0,{o("operating_income", k)}/{o("revenue", k)},"n/a")'
                if ("CFS", k, "revenue") in fs and ("CFS", k, "operating_income") in fs
                else '="n/a"'
            )
            s.fx(r, 2 + j, f, "pct")
        mrow = f"{a1(r, 2)}:{a1(r, 6)}"
        ovr = d.get("overrides") or {}
        if ovr.get("normal_margin") is not None:  # P7-C1: confirmed normal margin (Inputs '사람 확정값')
            _vlist(
                s, r + 1, "출발 정상 이익률 = 사람 확정값(평가 세션)", "=M0Override", "pct", "%", "M0V2", "자동값은 Diagnostics I"
            )
        elif d["v2"].get("start") == "ltm":  # P7-B3b loss path: start = LTM margin (config/p7b3b.yaml b_transition_dcf)
            ltm_m = (
                f"=({o('operating_income', fy)}+{o('operating_income', h1)}-{o('operating_income', h0)})"
                f"/({o('revenue', fy)}+{o('revenue', h1)}-{o('revenue', h0)})"
            )
            _vlist(
                s,
                r + 1,
                "출발 이익률(적자 경로) = LTM 영업이익률(FY + 당기 1H − 전기 1H)",
                ltm_m,
                "pct",
                "%",
                "M0V2",
                f"{d['dcf']['explicit_end']}년에 피어 중앙값 도달(수렴 비율 1.0) — 위 5년 값은 참고",
            )
        else:
            _vlist(
                s,
                r + 1,
                "출발 정상 이익률 v2 = 중앙값(3년 이상), 아니면 3년 평균",
                f"=IF(COUNT({mrow})>=3,MEDIAN({mrow}),HistMargin)",
                "pct",
                "%",
                "M0V2",
            )
        _vlist(
            s,
            r + 2,
            f"{d['dcf']['explicit_end']}년까지 피어 쪽 이동 폭 = 수렴 비율 × (피어 중앙값 − 출발)",
            "=IF(ISNUMBER(PeerMarginV2),"
            + ("ConvShareOverride" if ovr.get("conv_share") is not None else "ConvShare")
            + "*(PeerMarginV2-M0V2),0)",
            "pct",
            "%",
            "MarginConvAmt",
            "체감·영구 구간 = 출발 + 이동 폭",
        )
        if ovr.get("g_start") is not None:  # P7-C1: confirmed start growth
            _vlist(s, r + 3, "출발 성장률 = 사람 확정값(평가 세션)", "=G0Override", "pct", "%", "G0Base")
        else:
            _vlist(
                s,
                r + 3,
                "출발 성장률 v2 = clip(가중 × CAGR + (1 − 가중) × 피어 성장률)",
                "=MAX(ClipLo,MIN(ClipHi,IF(ISNUMBER(PeerGrowthV2),WOwn*CAGR+(1-WOwn)*PeerGrowthV2,CAGR)))",
                "pct",
                "%",
                "G0Base",
            )
        r += 5
    return r


def _params_capex(c: Ctx, s, r):
    d = c.d
    keys = d["excel"]["scenarios"]
    labels = d["excel"]["scenario_labels"]
    st = c.layout["scen_table"]
    gy = d["excel"]["grids"].get("growth_years", [2027, 2030])
    ovr_rows = {f"g_{y}" for y in range(gy[0], gy[1] + 1)}
    s.text(r, 0, "시나리오 파라미터 — Inputs 표 3 연결, 증권사 열은 아래 파생, '선택' 열 = INDEX(…, 선택 순번)", "subtitle")
    r += 1
    for j, k in enumerate(keys):
        s.text(r, 2 + j, labels[k], "header")
    sel_c = 2 + len(keys)
    s.text(r, sel_c, "선택", "header")
    s.text(r, 0, "선택 순번", "bold")
    s.fx(r, 1, "=MATCH(ScenSel,ScenNames,0)", "int", name="ScenIdx")
    r += 1
    prow = {}
    bk_col = keys.index("broker") if "broker" in keys else None
    base_j = keys.index("base")
    der0 = r + len(SCEN_PARAMS) + 4
    der = {
        k: der0 + 1 + i
        for i, k in enumerate(
            ["sub_2h", "sub26_rev", "sub26_op", "sub27_rev", "sub27_op", "p26_rev", "p26_op", "p27_rev", "p27_op"]
        )
    }
    for i, (pk, lab, kind) in enumerate(SCEN_PARAMS):
        rr = r + i
        prow[pk] = rr
        s.text(rr, 0, lab)
        for j, _k in enumerate(keys):
            if j == bk_col:
                bc = a1(rr, 2 + base_j)
                f = {
                    "rev_2026": f"={a1(der['p26_rev'], 2)}",
                    "g_2027": f"={a1(der['p27_rev'], 2)}/{a1(der['p26_rev'], 2)}-1",
                    "margin": f"={a1(der['p27_op'], 2)}/{a1(der['p27_rev'], 2)}",
                    "op_2026": f"={a1(der['p26_op'], 2)}",
                }.get(pk, f"={bc}")
                if pk == "op_flag":
                    s.const(rr, 2 + j, 1, "int")
                else:
                    s.fx(rr, 2 + j, f, kind)
            else:
                src = a1(st["rows"][pk], st["col0"] + j)
                s.fx(rr, 2 + j, f"=N(Inputs!{src})" if pk == "op_2026" else f"=Inputs!{src}", kind)
        sel = f"INDEX({a1(rr, 2)}:{a1(rr, 1 + len(keys))},ScenIdx)"
        if pk in ovr_rows:  # sensitivity data table: growth override
            sel = f"IF(ISNUMBER(GrowthOvr),GrowthOvr,{sel})"
        elif pk == "margin":  # sensitivity data table: margin override
            sel = f"IF(ISNUMBER(MarginOvr),MarginOvr,{sel})"
        s.fx(rr, sel_c, f"={sel}", kind)
    c.range_name("GVec_Sel", "Forecast", a1(prow["g_2027"], sel_c), a1(prow["g_2032"], sel_c))
    for pk, nm in (
        ("rev_2026", "Rev26_Sel"),
        ("margin", "Margin_Sel"),
        ("g_terminal", "GTerm_Sel"),
        ("op_flag", "OpFlag_Sel"),
        ("op_2026", "Op26_Sel"),
    ):
        c.book.name(nm, "Forecast", a1(prow[pk], sel_c))
        c.R[nm] = nm
    rr = r + len(SCEN_PARAMS)
    _vlist(s, rr, "명시 마지막 연도 성장률(선택)", "=INDEX(GVec_Sel,ExplicitEnd-YEAR(CfStart))", "pct", "%", "GLast_Sel")
    _geff(c, s, rr + 1)
    c.layout["param_rows"] = prow
    c.layout["param_cols"] = {k: 2 + j for j, k in enumerate(keys)}
    # broker derivation (p3c1.broker_case): parent = consolidated broker estimate − 알에프시스템즈 simple
    seg = c.layout["seg_refs"]
    s.text(der0, 0, "증권사 참고 시나리오 파생 — 모회사 = 연결(증권사) − 종속회사(단순 가정)", "subtitle")
    fd = {
        "sub_2h": ("종속회사 2H26 매출", f"=({seg[('sub', 'revenue', 'FY2025')]}-{seg[('sub', 'revenue', '1H25')]})*(1+SubG)"),
        "sub26_rev": ("종속회사 2026 매출", f"={seg[('sub', 'revenue', '1H26')]}+{a1(der['sub_2h'], 2)}"),
        "sub26_op": ("종속회사 2026 영업이익", f"={seg[('sub', 'op', '1H26')]}+{a1(der['sub_2h'], 2)}*SubM"),
        "sub27_rev": ("종속회사 2027 매출", f"={a1(der['sub26_rev'], 2)}*(1+SubG)"),
        "sub27_op": ("종속회사 2027 영업이익", f"={a1(der['sub27_rev'], 2)}*SubM"),
        "p26_rev": ("모회사 2026 매출(파생)", f"=BK_rev_2026-{a1(der['sub26_rev'], 2)}"),
        "p26_op": ("모회사 2026 영업이익(파생)", f"=BK_op_2026-{a1(der['sub26_op'], 2)}"),
        "p27_rev": ("모회사 2027 매출(파생)", f"=BK_rev_2027-{a1(der['sub27_rev'], 2)}"),
        "p27_op": ("모회사 2027 영업이익(파생)", f"=BK_op_2027-{a1(der['sub27_op'], 2)}"),
    }
    for k, rr in der.items():
        lab, f = fd[k]
        _vlist(s, rr, lab, f, "mn", "백만원")
    r = der["p27_op"] + 2
    s.text(r, 0, "2028~2032 성장률·영구성장률은 기본 시나리오 경로, 2026 영업이익은 연간 지정(2H = 연간 − 1H 실적)", "note")
    return r + 2


def _params_mech(c: Ctx, s, r):
    d = c.d
    keys = d["excel"]["scenarios"]
    labels = d["excel"]["scenario_labels"]
    st = c.layout["scen_table"]
    s.text(r, 0, "시나리오 파라미터 — Inputs 표 3 연결, '선택' 열 = INDEX(…, 선택 순번)", "subtitle")
    r += 1
    for j, k in enumerate(keys):
        s.text(r, 2 + j, labels[k], "header")
    sel_c = 2 + len(keys)
    s.text(r, sel_c, "선택", "header")
    s.text(r, 0, "선택 순번", "bold")
    s.fx(r, 1, "=MATCH(ScenSel,ScenNames,0)", "int", name="ScenIdx")
    r += 1
    prow = {}
    rows = [("growth_shift", "출발 성장률 이동", "GrowthShiftOvr"), ("margin_shift", "정상 이익률 이동", "MarginShiftOvr")]
    for i, (pk, lab, ovr) in enumerate(rows):
        rr = r + i
        prow[pk] = rr
        s.text(rr, 0, lab)
        for j in range(len(keys)):
            s.fx(rr, 2 + j, f"=Inputs!{a1(st['rows'][pk], st['col0'] + j)}", "pct")
        s.fx(rr, sel_c, f"=IF(ISNUMBER({ovr}),{ovr},INDEX({a1(rr, 2)}:{a1(rr, 1 + len(keys))},ScenIdx))", "pct")
    r += len(rows)
    v2 = bool(d.get("v2"))  # P7-B2b: v2 base values (auto drafts)
    der = [
        (
            "g0",
            "출발 성장률 = v2 출발 성장률 + 이동" if v2 else f"출발 성장률 g_{d['meta']['ltm_year']} = CAGR + 이동",
            "=G0Base+{gs}" if v2 else "=CAGR+{gs}",
            "G0_Sel",
        ),
        (
            "margin",
            "출발 정상 영업이익률 = v2 중앙값 + 이동" if v2 else "정상 영업이익률 = 3년 평균 + 이동",
            "=M0V2+{ms}" if v2 else "=HistMargin+{ms}",
            "Margin_Sel",
        ),
        (
            "glast",
            "명시 마지막 연도 성장률",
            "={g0}+(GTermCfg-{g0})*MIN(ExplicitEnd-YEAR(CfStart),FadeTo-YEAR(CfStart))/(FadeTo-YEAR(CfStart))",
            "GLast_Sel",
        ),
    ]
    for i, (pk, lab, tpl, nm) in enumerate(der):
        rr = r + i
        prow[pk] = rr
        s.text(rr, 0, lab)
        for j in range(len(keys) + 1):
            cc = 2 + j
            f = tpl.format(gs=a1(prow["growth_shift"], cc), ms=a1(prow["margin_shift"], cc), g0=a1(prow.get("g0", rr), cc))
            s.fx(rr, cc, f, "pct", name=nm if j == len(keys) else None)
    r += len(der)
    _vlist(s, r, "영구성장률(설정)", "=GTermCfg", "pct", "%", "GTerm_Sel")
    _geff(c, s, r + 1)
    c.layout["param_rows"] = prow
    c.layout["param_cols"] = {k: 2 + j for j, k in enumerate(keys)}
    return r + 3
