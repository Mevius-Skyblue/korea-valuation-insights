"""Calculation sheets for the scenario_capex engine: Forecast, WACC, DCF, Bridge, Scen_Calc.

Every row has one formula across its period columns (FAST rule); the opening column (기초, 2026-06-30) holds links or
structural zeros so the first period needs no special formula. Formulas mirror src/valuation/rf_dcf.parent_case,
rf_dcf2.value (three stages, value drivers, RONIC rule), dcf.fcff_rows / run_dcf (mid-year, partial first period,
roll-forward), wacc.wacc and sotp.sotp_equity - see the comments next to each block.
"""
from __future__ import annotations

from src.excel.context import Ctx
from src.excel.sheets_input import SCEN_PARAMS
from src.excel.writer import a1, col

C_OPEN, C_FIRST = 2, 3          # opening column C, first period column D


def tax_of(x: str) -> str:
    """Progressive tax on base x (delta-rate trick: Σ max(x − from_i, 0) × (rate_i − rate_{i−1}))."""
    return f"IF({x}>0,SUMPRODUCT(({x}>TaxFrom)*({x}-TaxFrom)*TaxDRate),0)"


def eff_of(x: str) -> str:
    return f"IF({x}>0,{tax_of(x)}/{x},0)"


def ronic_formula(d: dict, reinv: str, rc: str, w: str, g: str) -> str:
    """RF (rf_dcf2): calc <= 0 or <= g -> WACC. Mechanical (company_dcf.bounded_ronic): reinvestment <= 0 -> WACC,
    else clip to [WACC, historical ROIC cap]."""
    if d["type"] == "mechanical":
        return f"=IF({reinv}<=0,{w},IF({rc}<{w},{w},IF({rc}>RonicCap,RonicCap,{rc})))"
    return f"=IF(OR({reinv}<=0,{rc}<=0,{rc}<={g}),{w},{rc})"


def ronic_flag(d: dict, reinv: str, rc: str, w: str, g: str) -> str:
    if d["type"] == "mechanical":
        return (f'=IF({reinv}<=0,"재투자 ≤ 0 → WACC",IF({rc}<{w},"계산값 < WACC → 하한",'
                f'IF({rc}>RonicCap,"계산값 > 상한(과거 ROIC)","계산값 사용")))')
    return f'=IF(OR({reinv}<=0,{rc}<=0,{rc}<={g}),"RONIC ≤ 0 또는 ≤ g → WACC로 대체","계산값 사용")'


def n_periods(d: dict) -> int:
    return 1 + (d["dcf"]["explicit_end"] - int(d["meta"]["cf_start"][:4])) + d["dcf"]["fade_years"]


def _vlist(s, r, label, formula, kind, unit="", name=None, note="", bold=False):
    s.text(r, 0, label, "bold" if bold else "label")
    if unit:
        s.text(r, 1, unit, "note")
    ref = s.fx(r, 2, formula, kind, name=name, bold=bold)
    if note:
        s.text(r, 3, note, "note")
    return ref


# ---------------------------------------------------------------- Forecast

FC_ROWS = [  # key, label, unit, kind
    ("k", "기간 순번", "", "int"), ("year", "연도", "", "year"), ("stage", "구간", "", "gen"),
    ("start", "시작일", "", "date"), ("end", "종료일", "", "date"), ("f", "기간 비율(일수 ÷ 365)", "", "ratio"),
    ("explicit", "명시 구간(1/0)", "", "int"), ("g", "매출 성장률", "%", "pct"), ("rev_fy", "회계연도 매출", "백만원", "mn"),
    ("rev", "기간 매출", "백만원", "mn"), ("ebit", "영업이익(EBIT)", "백만원", "mn"), ("fy_ebit", "회계연도 영업이익(과세표준)", "백만원", "mn"),
    ("maint", "유지 CAPEX", "백만원", "mn"), ("cum_maint", "기초 누적 유지 CAPEX", "백만원", "mn"),
    ("dep_m", "유지 CAPEX 상각", "백만원", "mn"), ("dep_b", "신규 공장 상각", "백만원", "mn"), ("dep_old", "기존 자산 D&A(FY2025 수준)", "백만원", "mn"),
    ("dna", "D&A 합계", "백만원", "mn"), ("gcapex", "성장 CAPEX(시설자금)", "백만원", "mn"), ("capex", "CAPEX 합계", "백만원", "mn"),
    ("nwc", "순운전자본(기말)", "백만원", "mn"), ("dnwc", "ΔNWC(증가 = 유출)", "백만원", "mn"),
    ("tax_rate", "실효세율(누진, 회계연도 과세표준)", "%", "pct"), ("tax", "법인세", "백만원", "mn"), ("nopat", "NOPAT", "백만원", "mn"),
]
FC_ROWS_MECH = [r for r in FC_ROWS if r[0] not in ("maint", "cum_maint", "dep_m", "dep_b", "dep_old", "gcapex")]
FC_ROWS_MECH = [(k, "D&A = 매출 × 과거 3년 D&A/매출", u, kd) if k == "dna" else
                (k, "CAPEX = 매출 × 과거 3년 CAPEX/매출", u, kd) if k == "capex" else (k, lab, u, kd) for k, lab, u, kd in FC_ROWS_MECH]
FC_TAIL_MAIN = [("reinv_rate", "체감 구간 재투자율 g ÷ RONIC", "%", "pct"), ("reinv", "체감 구간 재투자", "백만원", "mn"),
                ("fcff", "FCFF", "백만원", "mn"), ("ebitda", "EBITDA", "백만원", "mn")]
FC_TAIL_SCEN = [("fcff_pre", "FCFF(체감 재투자 전)", "백만원", "mn")]


def forecast_rows(c: Ctx, s, top: int, P: dict, main: bool) -> dict:
    """Write the period rows from `top`. P: formula refs rev26, gvec, glast, margin, gt, opflag, op26."""
    n = n_periods(c.d)
    mech = c.d["type"] == "mechanical"
    P = {**{k: "NA()" for k in ("rev26", "gvec", "opflag", "op26", "g0", "gtx")}, **P}     # keys of the other engine type
    rows = (FC_ROWS_MECH if mech else FC_ROWS) + (FC_TAIL_MAIN if main else FC_TAIL_SCEN)
    R = {k: top + i for i, (k, *_r) in enumerate(rows)}

    def X(k, j):
        return a1(R[k], j) if k in R else "NA()"

    def W(k, j):
        return a1(R[k], j - 1) if k in R else "NA()"
    for i, (k, lab, unit, kind) in enumerate(rows):
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
            "g": (f"=IF({X('k', j)}=1,0,IF({X('explicit', j)}=1,INDEX({P['gvec']},{X('year', j)}-YEAR(CfStart)),"
                  f"{P['glast']}-({X('year', j)}-ExplicitEnd)*({P['glast']}-{P['gt']})/FadeYears))"),
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
            "nwc": (f"=IF({X('explicit', j)}=1,{X('rev_fy', j)}*DSO/DaysYr+{X('rev_fy', j)}*COGSR*DIO/DaysYr"
                    f"-{X('rev_fy', j)}*COGSR*DPO/DaysYr-{X('rev_fy', j)}*DCL/DaysYr,{W('nwc', j)})"),
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
        if mech:      # company_dcf.forecast: growth_path to g by FadeTo, ratios of the average years
            y0 = "YEAR(CfStart)"
            f.update({
                "g": (f"=IF({X('explicit', j)}=1,{P['g0']}+({P['gtx']}-{P['g0']})*MIN({X('year', j)}-{y0},FadeTo-{y0})/(FadeTo-{y0}),"
                      f"{P['glast']}-({X('year', j)}-ExplicitEnd)*({P['glast']}-{P['gt']})/FadeYears)"),
                "rev_fy": f"=IF({X('k', j)}=1,RevFY_Last*(1+{X('g', j)}),{W('rev_fy', j)}*(1+{X('g', j)}))",
                "ebit": (f"={X('rev', j)}*({P['margin']}+MarginConvAmt*MIN(({X('year', j)}-YEAR(CfStart))/(ExplicitEnd-YEAR(CfStart)),1))"
                         if c.d.get("v2") else f"={X('rev', j)}*{P['margin']}"),
                "dna": f"=IF({X('explicit', j)}=1,{X('rev', j)}*DnaRatio,0)",
                "capex": f"=IF({X('explicit', j)}=1,{X('rev', j)}*CapexRatio,0)",
                "nwc": (f"=IF({X('explicit', j)}=1,{X('rev_fy', j)}*DSO/DaysYr+{X('rev_fy', j)}*COGSR*DIO/DaysYr"
                        f"-{X('rev_fy', j)}*COGSR*DPO/DaysYr,{W('nwc', j)})"),
            })
        for k, lab, unit, kind in rows:
            s.fx(R[k], j, f[k], kind)
    return R


def forecast(c: Ctx):
    d, s = c.d, c.sheet("Forecast")
    n = n_periods(d)
    s.widths({0: 36, 1: 9, 2: 13, **{C_FIRST + j: 12 for j in range(n)}})
    s.text(0, 0, "Forecast — " + ("모회사 사업 예측" if d["type"] == "scenario_capex" else "연결 예측(기계적 경로)") + " (선택한 시나리오, 백만원)", "title")
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
        P = {"rev26": "Rev26_Sel", "gvec": "GVec_Sel", "glast": "GLast_Sel", "margin": "Margin_Sel", "gt": "GEff",
             "opflag": "OpFlag_Sel", "op26": "Op26_Sel"}

    # ---- timeline
    s.text(r, 0, "예측 (기초 열 = 2026-06-30 재무상태표)", "subtitle")
    s.text(r, C_OPEN, "기초", "header")
    s.ws.freeze_panes(r + 1, 3)
    R = forecast_rows(c, s, r + 1, P, main=True)
    for j in range(C_FIRST, C_FIRST + n):
        s.fx(r, j, f'=IF({a1(R["k"], j)}=1,"2H"&RIGHT({a1(R["year"], j)},2),""&{a1(R["year"], j)})', "gen")
    c.layout["fc_rows"] = R
    c.layout["n"] = n
    lp = (d.get("v2") or {}).get("start") == "ltm"
    if lp:                                 # P7-B3b loss path: cumulative explicit FCF vs cash-like (funding check)
        rc = max(R.values()) + 1
        s.text(rc, 0, "누적 FCF(명시 기간, 적자 경로 자금 점검)")
        s.text(rc, 1, "백만원", "note")
        for j in range(C_FIRST, C_FIRST + n):
            prev = f"N({a1(rc, j - 1)})" if j > C_FIRST else "0"
            s.fx(rc, j, f'=IF({a1(R["explicit"], j)}=1,{prev}+{a1(R["fcff"], j)},"")', "mn")
        _vlist(s, rc + 1, "누적 FCF 최저(0 이하)", f"=MIN(0,MIN({a1(rc, C_FIRST)}:{a1(rc, C_FIRST + n - 1)}))", "mn", "백만원",
               "FundTrough", "Checks: −최저 > 현금성이면 WARN(추가 자금 필요)")
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
    rows = [(lab_h, hist_cagr, "PlanHistCAGR"),
            ("예측 FY2026 매출 성장률(직전 회계연도 대비)", f"=Forecast!{a1(F['rev_fy'], C_FIRST)}/{rev_last}-1", "PlanG26"),
            ("예측 매출 CAGR(FY2026 → 명시 마지막 연도)",
             f"=(INDEX({fr('rev_fy')},MATCH(ExplicitEnd,{fr('year')},0))/Forecast!{a1(F['rev_fy'], C_FIRST)})^(1/(ExplicitEnd-YEAR(CfStart)))-1", "PlanFcCAGR"),
            ("  차이(예측 CAGR − 과거 CAGR)", "=PlanFcCAGR-PlanHistCAGR", "PlanGapCAGR"),
            (lab_m, hist_m, "PlanHistMargin"), ("예측 정상 영업이익률", "=Margin_Sel", "PlanMargin"),
            ("  차이(예측 − 과거)", "=PlanMargin-PlanHistMargin", "PlanGapMargin")]
    for i, (lab, f, nm) in enumerate(rows):
        _vlist(s, r + 1 + i, lab, f, "pct", "%", nm)
    c.range_name("PlanCheck", "Forecast", a1(r + 1, 0), a1(r + len(rows), 2))
    _plan_reference(c, s, r, fr)


ACC_KO = {"revenue": "매출", "operating_income": "영업이익"}


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
    s.fx(t + 1, c0 + 4, f"=(INDEX({fr('rev_fy')},MATCH(YEAR(CfStart)+{yrs}-1,{fr('year')},0))/{first})^(1/({yrs}-1))-1", "pct1",
         name="PlanFcCAGR5")
    s.text(t + 2, c0, "해당 구간(1~4)")
    s.fx(t + 2, c0 + 4, f"=IF(PlanFcCAGR5>={lo(3)},4,IF(PlanFcCAGR5>={lo(2)},3,IF(PlanFcCAGR5>={lo(1)},2,1)))", "int", name="PlanBand")
    s.fx(t + 2, c0 + 5, f'=IF(OR(PlanFcCAGR5<{lo(0)},PlanFcCAGR5>{a1(q3, c0 + 2, True)}),"표본 범위 밖(참고만)","표본 범위 안")', "gen",
         name="PlanBandRange")
    s.text(t + 3, c0, "그 구간 매출 달성률 중앙값 1차 / 2차 / 3차")
    for j in range(3):
        col_rng = f"{a1(q0, c0 + 4 + 2 * j, True)}:{a1(q3, c0 + 4 + 2 * j, True)}"
        s.fx(t + 3, c0 + 4 + j, f"=INDEX({col_rng},PlanBand)", "pct1", name=f"PlanBandH{j + 1}")
    s.text(t + 4, c0, "표시만: 예측을 자동으로 깎거나 경고 판정하지 않는다. 비교 기준이 다름(스팩 합병 의견서 5년 추정 vs 이 모델)", "note")


def _geff(c: Ctx, s, r):
    _vlist(s, r, "영구·체감 구간 g(데이터 표 입력 칸이 비면 시나리오 값)", "=IF(ISNUMBER(GOvr),GOvr,GTerm_Sel)", "pct", "%", "GEff",
           "Scenarios 시트의 데이터 표가 GOvr 칸에 값을 넣어 계산한다")
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
    days = [("DSO", "매출채권 회전일수(매출 기준)", "receivables", "revenue"), ("DIO", "재고 회전일수(매출원가 기준)", "inventories", "cogs"),
            ("DPO", "매입채무 회전일수(매출원가 기준)", "trade_payables", "cogs"), ("DCL", "계약부채 일수(매출 기준)", "contract_liabilities", "revenue")]
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
    _vlist(s, r, "매출원가율(LTM = FY + 당기 1H − 전기 1H)", f"=({o('cogs', fy)}+{o('cogs', h1)}-{o('cogs', h0)})/({o('revenue', fy)}+{o('revenue', h1)}-{o('revenue', h0)})",
           "pct", "%", "COGSR")
    _vlist(s, r + 1, "순운전자본(기초, 2026-06-30)", f"={o('receivables', h1)}+{o('inventories', h1)}-{o('trade_payables', h1)}-{o('contract_liabilities', h1)}",
           "mn", "백만원", "NWC_Open", "매출채권 + 재고 − 매입채무 − 계약부채")
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
    items = [("HistMargin", "영업이익률", "=({op})/({rev})"), ("DnaRatio", "D&A ÷ 매출", '=IF(ISNUMBER({dna}),({dna})/({rev}),"n/a")'),
             ("CapexRatio", "CAPEX ÷ 매출(유형 + 무형)", "=({cx1}+{cx2})/({rev})"), ("COGSR", "매출원가율", "=({cogs})/({rev})"),
             ("DSO", "매출채권 회전일수(매출 기준)", '=IF(({rev})=0,"n/a",({rec})/({rev})*DaysYr)'),
             ("DIO", "재고 회전일수(매출원가 기준)", '=IF(({cogs})=0,"n/a",({inv})/({cogs})*DaysYr)'),
             ("DPO", "매입채무 회전일수(매출원가 기준)", '=IF(({cogs})=0,"n/a",({pay})/({cogs})*DaysYr)')]
    for nm, lab, tpl in items:
        s.text(r, 0, lab)
        for j, y in enumerate(av):
            k = f"FY{y}"
            s.fx(r, 2 + j, tpl.format(op=o("operating_income", k), rev=o("revenue", k), dna=o("dna", k), cx1=o("capex_ppe", k),
                                      cx2=o("capex_intangibles", k), cogs=o("cogs", k), rec=o("receivables", k),
                                      inv=o("inventories", k), pay=o("trade_payables", k)), "days" if nm in ("DSO", "DIO", "DPO") else "pct")
        rg = f"{a1(r, 2)}:{a1(r, 1 + len(av))}"
        avg = f"=IF(COUNT({rg})=0,0,AVERAGE({rg}))" if nm in ("DSO", "DIO", "DPO") else f"=AVERAGE({rg})"   # B3-F5
        s.fx(r, 2 + len(av), avg, "days" if nm in ("DSO", "DIO", "DPO") else "pct", name=nm)
        r += 1
    # historical ROIC (RONIC cap): NOPAT_y / opening invested capital (NWC + PPE + intangibles + ROU at FY y−1)
    s.text(r, 0, "기초 투하자본(전년 말)")
    for j, y in enumerate(av):
        k = f"FY{y - 1}"
        s.fx(r, 2 + j, f"={o('receivables', k)}+{o('inventories', k)}-{o('trade_payables', k)}+{o('ppe', k)}+{o('intangibles', k)}+{o('rou_assets', k)}", "mn")
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
    _vlist(s, r, f"매출 5년 CAGR(FY{y0} → FY{y1})", f"=({o('revenue', f'FY{y1}')}/{o('revenue', f'FY{y0}')})^(1/({y1}-{y0}))-1", "pct", "%", "CAGR")
    _vlist(s, r + 1, "순운전자본(기초, 2026-06-30)", f"={o('receivables', h1)}+{o('inventories', h1)}-{o('trade_payables', h1)}",
           "mn", "백만원", "NWC_Open", "매출채권 + 재고 − 매입채무")
    _vlist(s, r + 2, "2026 상반기 매출(연결)", f"={o('revenue', h1)}", "mn", "백만원", "H1Rev")
    _vlist(s, r + 3, "2026 상반기 영업이익(연결)", f"={o('operating_income', h1)}", "mn", "백만원", "H1Op")
    _vlist(s, r + 4, f"FY{L - 1} 매출(연결)", f"={o('revenue', fy)}", "mn", "백만원", "RevFY_Last")
    _vlist(s, r + 5, "LTM 세전이익(세후 Kd 한계세율 기준)", f"={o('pretax_income', fy)}+{o('pretax_income', h1)}-{o('pretax_income', h0)}",
           "mn", "백만원", "PretaxLTM")
    r += 7
    if d.get("v2"):                      # P7-B2b mechanical_v2 (auto drafts): config/p7b2b.yaml, company_dcf.v2_inputs
        s.text(r, 0, "기본 경로 v2 — 5년 이익률 중앙값, 피어 쪽 수렴, 성장률 혼합(사전 고정 91a84dd)", "subtitle")
        r += 1
        s.text(r, 0, "영업이익률 FY2021~2025(매출 > 0인 해)")
        for j, y in enumerate(range(2021, 2026)):
            k = f"FY{y}"
            f = (f'=IF({o("revenue", k)}>0,{o("operating_income", k)}/{o("revenue", k)},"n/a")'
                 if ("CFS", k, "revenue") in fs and ("CFS", k, "operating_income") in fs else '="n/a"')
            s.fx(r, 2 + j, f, "pct")
        mrow = f"{a1(r, 2)}:{a1(r, 6)}"
        ovr = d.get("overrides") or {}
        if ovr.get("normal_margin") is not None:   # P7-C1: confirmed normal margin (Inputs '사람 확정값')
            _vlist(s, r + 1, "출발 정상 이익률 = 사람 확정값(평가 세션)", "=M0Override", "pct", "%", "M0V2", "자동값은 Diagnostics I")
        elif d["v2"].get("start") == "ltm":     # P7-B3b loss path: start = LTM margin (config/p7b3b.yaml b_transition_dcf)
            ltm_m = (f"=({o('operating_income', fy)}+{o('operating_income', h1)}-{o('operating_income', h0)})"
                     f"/({o('revenue', fy)}+{o('revenue', h1)}-{o('revenue', h0)})")
            _vlist(s, r + 1, "출발 이익률(적자 경로) = LTM 영업이익률(FY + 당기 1H − 전기 1H)", ltm_m, "pct", "%", "M0V2",
                   "2032년에 피어 중앙값 도달(수렴 비율 1.0) — 위 5년 값은 참고")
        else:
            _vlist(s, r + 1, "출발 정상 이익률 v2 = 중앙값(3년 이상), 아니면 3년 평균", f"=IF(COUNT({mrow})>=3,MEDIAN({mrow}),HistMargin)", "pct", "%", "M0V2")
        _vlist(s, r + 2, "2032년까지 피어 쪽 이동 폭 = 수렴 비율 × (피어 중앙값 − 출발)", "=IF(ISNUMBER(PeerMarginV2),ConvShare*(PeerMarginV2-M0V2),0)",
               "pct", "%", "MarginConvAmt", "체감·영구 구간 = 출발 + 이동 폭")
        if ovr.get("g_start") is not None:         # P7-C1: confirmed start growth
            _vlist(s, r + 3, "출발 성장률 = 사람 확정값(평가 세션)", "=G0Override", "pct", "%", "G0Base")
        else:
            _vlist(s, r + 3, "출발 성장률 v2 = clip(가중 × CAGR + (1 − 가중) × 피어 성장률)",
                   "=MAX(ClipLo,MIN(ClipHi,IF(ISNUMBER(PeerGrowthV2),WOwn*CAGR+(1-WOwn)*PeerGrowthV2,CAGR)))", "pct", "%", "G0Base")
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
    der = {k: der0 + 1 + i for i, k in enumerate(["sub_2h", "sub26_rev", "sub26_op", "sub27_rev", "sub27_op",
                                                   "p26_rev", "p26_op", "p27_rev", "p27_op"])}
    for i, (pk, lab, kind) in enumerate(SCEN_PARAMS):
        rr = r + i
        prow[pk] = rr
        s.text(rr, 0, lab)
        for j, k in enumerate(keys):
            if j == bk_col:
                bc = a1(rr, 2 + base_j)
                f = {"rev_2026": f"={a1(der['p26_rev'], 2)}", "g_2027": f"={a1(der['p27_rev'], 2)}/{a1(der['p26_rev'], 2)}-1",
                     "margin": f"={a1(der['p27_op'], 2)}/{a1(der['p27_rev'], 2)}", "op_2026": f"={a1(der['p26_op'], 2)}"}.get(pk, f"={bc}")
                if pk == "op_flag":
                    s.const(rr, 2 + j, 1, "int")
                else:
                    s.fx(rr, 2 + j, f, kind)
            else:
                src = a1(st["rows"][pk], st["col0"] + j)
                s.fx(rr, 2 + j, f"=N(Inputs!{src})" if pk == "op_2026" else f"=Inputs!{src}", kind)
        sel = f"INDEX({a1(rr, 2)}:{a1(rr, 1 + len(keys))},ScenIdx)"
        if pk in ovr_rows:              # sensitivity data table: growth override
            sel = f"IF(ISNUMBER(GrowthOvr),GrowthOvr,{sel})"
        elif pk == "margin":            # sensitivity data table: margin override
            sel = f"IF(ISNUMBER(MarginOvr),MarginOvr,{sel})"
        s.fx(rr, sel_c, f"={sel}", kind)
    c.range_name("GVec_Sel", "Forecast", a1(prow["g_2027"], sel_c), a1(prow["g_2032"], sel_c))
    for pk, nm in (("rev_2026", "Rev26_Sel"), ("margin", "Margin_Sel"), ("g_terminal", "GTerm_Sel"), ("op_flag", "OpFlag_Sel"),
                   ("op_2026", "Op26_Sel")):
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
    fd = {"sub_2h": ("종속회사 2H26 매출", f"=({seg[('sub', 'revenue', 'FY2025')]}-{seg[('sub', 'revenue', '1H25')]})*(1+SubG)"),
          "sub26_rev": ("종속회사 2026 매출", f"={seg[('sub', 'revenue', '1H26')]}+{a1(der['sub_2h'], 2)}"),
          "sub26_op": ("종속회사 2026 영업이익", f"={seg[('sub', 'op', '1H26')]}+{a1(der['sub_2h'], 2)}*SubM"),
          "sub27_rev": ("종속회사 2027 매출", f"={a1(der['sub26_rev'], 2)}*(1+SubG)"),
          "sub27_op": ("종속회사 2027 영업이익", f"={a1(der['sub27_rev'], 2)}*SubM"),
          "p26_rev": ("모회사 2026 매출(파생)", f"=BK_rev_2026-{a1(der['sub26_rev'], 2)}"),
          "p26_op": ("모회사 2026 영업이익(파생)", f"=BK_op_2026-{a1(der['sub26_op'], 2)}"),
          "p27_rev": ("모회사 2027 매출(파생)", f"=BK_rev_2027-{a1(der['sub27_rev'], 2)}"),
          "p27_op": ("모회사 2027 영업이익(파생)", f"=BK_op_2027-{a1(der['sub27_op'], 2)}")}
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
    v2 = bool(d.get("v2"))               # P7-B2b: v2 base values (auto drafts)
    der = [("g0", "출발 성장률 = v2 출발 성장률 + 이동" if v2 else "출발 성장률 g_2026 = CAGR + 이동", "=G0Base+{gs}" if v2 else "=CAGR+{gs}", "G0_Sel"),
           ("margin", "출발 정상 영업이익률 = v2 중앙값 + 이동" if v2 else "정상 영업이익률 = 3년 평균 + 이동",
            "=M0V2+{ms}" if v2 else "=HistMargin+{ms}", "Margin_Sel"),
           ("glast", "명시 마지막 연도 성장률", "={g0}+(GTermCfg-{g0})*MIN(ExplicitEnd-YEAR(CfStart),FadeTo-YEAR(CfStart))/(FadeTo-YEAR(CfStart))", "GLast_Sel")]
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


def _row_range(sheet: str, row: int, n: int) -> str:
    return f"{sheet}!${col(C_FIRST)}${row + 1}:${col(C_FIRST + n - 1)}${row + 1}"


# ---------------------------------------------------------------- WACC

def wacc_sheet(c: Ctx):
    d, s = c.d, c.sheet("WACC")
    s.widths({0: 20, 1: 10, 2: 9, 3: 9, 4: 9, 5: 9, 6: 8, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 11, 13: 11, 14: 11})
    s.text(0, 0, "WACC — 피어 베타 → 할인율", "title")
    s.text(1, 0, "원 β → Blume(0.67 β + 0.33) → Hamada 언레버(회사별 기간평균 D/E, t 22%) → 포함 피어 중앙값. 회귀 결과는 한국거래소 통계정보 기반", "note")
    if d.get("public"):                    # P7-C1 public mode: beta aggregates (Inputs 표 B), no per-peer rows
        r = 4
        _vlist(s, r, "포함 피어 수", "=BetaPubN", "int", "곳")
        if d["engine"].get("beta_src") == "override":
            _vlist(s, r + 1, "βu = 사람 확정값(평가 세션)", "=BetaOverride", "beta", "", "BetaU", bold=True)
        else:
            _vlist(s, r + 1, "βu(공개 모드 집계 입력)", "=BetaPubU", "beta", "", "BetaU", bold=True)
        _vlist(s, r + 2, "R² 중앙값(포함 피어, 집계 입력)", "=BetaPubR2", "beta", "", "BetaR2Median")
    else:
        hdr = ["회사", "등급", "포함", "원 β", "표준오차", "R²", "관측 수", "기간평균 D/E", "Blume β", "βu (Blume)", "βu (원 β, 민감도)",
               "βu 포함분", "R² 포함분", "엔진 Blume", "엔진 βu"]
        for j, h in enumerate(hdr):
            s.text(3, j, h, "header" if j < 13 else "header")
        rows = c.layout["beta_rows"]
        r0 = 4
        for i, ir in enumerate(rows):
            r = r0 + i
            b = d["beta"][i]
            s.fx(r, 0, f"=Inputs!{a1(ir, 0)}", "gen")
            s.fx(r, 1, f"=Inputs!{a1(ir, 1)}", "gen")
            for j, cc in ((2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7)):
                s.fx(r, j, f"=Inputs!{a1(ir, cc)}", "int" if j in (2, 6) else ("ratio" if j == 7 else "beta"))
            s.fx(r, 8, f"=BlumeW*{a1(r, 3)}+BlumeC", "beta")
            s.fx(r, 9, f"={a1(r, 8)}/(1+(1-T_Hamada)*{a1(r, 7)})", "beta")
            s.fx(r, 10, f"={a1(r, 3)}/(1+(1-T_Hamada)*{a1(r, 7)})", "beta")
            s.fx(r, 11, f'=IF({a1(r, 2)}=1,{a1(r, 9)},"")', "beta")
            s.fx(r, 12, f'=IF({a1(r, 2)}=1,{a1(r, 5)},"")', "beta")
            s.eng(r, 13, b["blume_engine"], "beta")
            s.eng(r, 14, b["bu_engine"], "beta")
        r1 = r0 + len(rows) - 1
        s.engine_range(r0, 13, r1, 14)
        c.layout["wacc_beta_rows"] = (r0, r1)
        r = r1 + 2
        _vlist(s, r, "포함 피어 수", f"=COUNT({a1(r0, 11)}:{a1(r1, 11)})", "int", "곳")
        if d["engine"].get("beta_src") == "override":      # P7-C1: confirmed βu (Inputs '사람 확정값')
            _vlist(s, r + 1, "βu = 사람 확정값(평가 세션)", "=BetaOverride", "beta", "", "BetaU", bold=True)
        elif d["engine"].get("beta_src", "peer") == "peer":
            _vlist(s, r + 1, "βu 중앙값(기본)", f"=MEDIAN({a1(r0, 11)}:{a1(r1, 11)})", "beta", "", "BetaU", bold=True)
        else:                                  # P7-B5 beta fallback: no peer βu (Inputs BetaFallback)
            _vlist(s, r + 1, "βu(피어 βu 없음 → 대체값)", f"=IF(COUNT({a1(r0, 11)}:{a1(r1, 11)})=0,BetaFallback,MEDIAN({a1(r0, 11)}:{a1(r1, 11)}))",
                   "beta", "", "BetaU", bold=True)
        _vlist(s, r + 2, "R² 중앙값(포함 피어)", f"=MEDIAN({a1(r0, 12)}:{a1(r1, 12)})", "beta", "", "BetaR2Median")
    s.text(r + 3, 0, "베타 신뢰성 경고", "bold")
    s.fx(r + 3, 2, '=IF(BetaR2Median<BetaR2Warn,"경고: 회귀 베타 신뢰 낮음(R² 중앙값 "&TEXT(BetaR2Median,"0.00")&" < "&TEXT(BetaR2Warn,"0.00")&")","경고 없음")', "gen", name="BetaWarn")
    s.text(r + 3, 3, "표시만(경로 불변, common_rules)", "note")
    s.text(r + 1, 3, "엔진 βu 중앙값", "note")
    s.eng(r + 1, 4, d["engine"]["beta_u"], "beta")
    s.engine_range(r + 1, 4, r + 1, 4)
    c.layout["beta_u_engine"] = f"WACC!{a1(r + 1, 4, True)}"
    r += 5
    if d["de"]["rule"] == "points":           # own average D/E (company_dcf: mean of the balance-sheet-date points)
        s.text(r, 0, "목표 D/E = 자체 D/E 시점 평균 (Inputs 표 6)", "subtitle")
        for j, h in enumerate(["시점", "총차입금", "리스부채", "시가총액", "D/E"]):
            s.text(r + 1, j, h, "header")
        q0, q1 = c.layout["de_rows"]
        for i in range(q1 - q0 + 1):
            rr = r + 2 + i
            s.fx(rr, 0, f"=Inputs!{a1(q0 + i, 0)}", "gen")
            for j in (1, 2, 3):
                s.fx(rr, j, f"=Inputs!{a1(q0 + i, j)}", "mn")
            s.fx(rr, 4, f"=({a1(rr, 1)}+{a1(rr, 2)})/{a1(rr, 3)}", "ratio")
        re_ = r + 2 + q1 - q0
        if (d.get("overrides") or {}).get("de") is not None:     # P7-C1: confirmed D/E
            _vlist(s, re_ + 1, "목표 D/E = 사람 확정값(평가 세션, 위 평균은 자동값)", "=DeOverride", "ratio", "배", "DE_Target")
        else:
            _vlist(s, re_ + 1, "목표 D/E(평균)", f"=AVERAGE({a1(r + 2, 4)}:{a1(re_, 4)})", "ratio", "배", "DE_Target")
        r = re_ + 3
    s.text(r, 0, "할인율 (선택한 SRP)", "subtitle")
    r += 1
    rows_w = [("Rf(Inputs 'Rf 만기 선택', 데이터 표 입력 칸이 비면)", "=IF(ISNUMBER(RfOvr),RfOvr,IF(RfTenor=10,Rf_10Y,Rf_5Y))", "pct3", "", "Rf"), ("MRP(데이터 표 입력 칸이 비면 Inputs 값)", "=IF(ISNUMBER(MrpOvr),MrpOvr,MRP)", "pct", "", "MRP_Eff"),
              ("SRP(데이터 표 입력 칸이 비면 선택 값)", "=IF(ISNUMBER(SrpOvr),SrpOvr,SRP_Sel)", "pct", "", "SRP_Eff"),
              ("βu", "=BetaU", "beta", "", None), ("목표 D/E", "=DE_Target", "ratio", "배", None),
              ("βL = βu × (1 + (1 − t) × D/E)", "=BetaU*(1+(1-T_Hamada)*DE_Target)", "beta", "", "BetaL"),
              ("Ke = Rf + βL × MRP + SRP", "=Rf+BetaL*MRP_Eff+SRP_Eff", "pct3", "", "Ke")]
    for i, (lab, f, kind, unit, nm) in enumerate(rows_w):
        _vlist(s, r + i, lab, f, kind, unit, nm)
    r += len(rows_w)
    R, n = c.layout["fc_rows"], c.layout["n"]
    ebit_rng, year_rng = _row_range("Forecast", R["ebit"], n), _row_range("Forecast", R["year"], n)
    if d["kd_tax_base"] == "ltm_pretax":
        _vlist(s, r, "한계세율 기준: 연결 LTM 세전이익", "=PretaxLTM", "mn", "백만원", "EbitEnd", "company_dcf.discount_rate")
    else:
        _vlist(s, r, "한계세율 기준: 명시 마지막 연도 EBIT", f"=INDEX({ebit_rng},MATCH(ExplicitEnd,{year_rng},0))", "mn", "백만원", "EbitEnd",
               "rf_dcf2.value")
    _vlist(s, r + 1, "한계세율(세후 Kd)", '=INDEX(TaxRate,COUNTIF(TaxTo,"<"&EbitEnd)+1)', "pct1", "%", "T_Kd")
    implied = d.get("kd_method") == "implied"           # P7-B draft: no rating found -> interest ÷ average debt (Inputs 표 5)
    _vlist(s, r + 2, "이자비용 ÷ 평균 차입금(Inputs 표 5)" if implied else "실제 가중 약정이자율(Inputs 표 5)",
           "=IF(SUM(BorrowAmt)>0,SUMPRODUCT(BorrowRate,BorrowAmt)/SUM(BorrowAmt),0)", "pct3", "%",
           "Kd_Actual", "등급 미확인 → 규칙 Kd(하한 Rf 전)로 쓴다" if implied else "등급 A+~BBB+일 때만 규칙에 쓰인다")
    if implied:
        s.fx(r + 2, 4, '="사용(등급 미확인 → 이자비용 ÷ 평균 차입금)"', "gen", name="KdActualUse")
    else:
        s.fx(r + 2, 4, '=IF(OR(RatingIdx=0,RatingIdx<=MATCH("AA-",RatingScale,0),RatingIdx>MATCH("BBB+",RatingScale,0)),'
                       '"미사용(규칙상: "&IF(RatingIdx=0,"무등급 → BBB- 3년","등급 구간 밖")&")","사용")', "gen", name="KdActualUse")
    _vlist(s, r + 3, "등급 순번(빈칸 = 무등급 0)", '=IF(Rating="",0,MATCH(Rating,RatingScale,0))', "int", "", "RatingIdx")
    _vlist(s, r + 4, "규칙 Kd(하한 전)", "=N(Kd_Actual)" if implied else
           ('=IF(RatingIdx=0,Kd_BBB,IF(RatingIdx<=MATCH("AA-",RatingScale,0),Kd_AA,'
            'IF(RatingIdx<=MATCH("BBB+",RatingScale,0),MAX(N(Kd_Actual),Kd_AA),Kd_BBB)))'), "pct3", "%")
    if (d.get("overrides") or {}).get("kd") is not None:          # P7-C1: confirmed Kd (no Rf floor)
        _vlist(s, r + 5, "세전 Kd = 사람 확정값(평가 세션)", "=KdOverride", "pct3", "%", "Kd_Pre")
    else:
        _vlist(s, r + 5, "세전 Kd = max(규칙 Kd, Rf)", f"=MAX({a1(r + 4, 2)},Rf)", "pct3", "%", "Kd_Pre")
    _vlist(s, r + 6, "세후 Kd", "=Kd_Pre*(1-T_Kd)", "pct3", "%", "Kd_AT")
    s.fx(r + 6, 4, '=IF(DE_Target=0,"미사용(D/E 0 → WACC에 Kd 반영 안 됨)","사용(D/V "&TEXT(DE_Target/(1+DE_Target),"0.0%")&")")', "gen", name="KdUse")
    _vlist(s, r + 7, "D/V = D/E ÷ (1 + D/E)", "=DE_Target/(1+DE_Target)", "pct", "%", "WD")
    _vlist(s, r + 8, "WACC(계산) = E/V × Ke + D/V × Kd × (1 − t)", "=(1-WD)*Ke+WD*Kd_AT", "pct3", "%", "WaccCalc")
    _vlist(s, r + 9, "WACC(모델 사용, 데이터 표 입력 칸이 비면 계산값)", "=IF(ISNUMBER(WaccOvr),WaccOvr,WaccCalc)", "pct3", "%", "WACC",
           "Scenarios 시트 WACC × g 데이터 표가 WaccOvr 칸에 값을 넣어 계산", bold=True)
    s.text(r + 10, 0, "Kd 규칙(공통 규칙, 위 순서): 무등급 → BBB- 3년 / AA- 이상 → AA- 3년 / A+~BBB+ → max(실제 가중, AA- 3년) / BBB 이하 → BBB- 3년, 하한 Rf", "note")
    r += 12
    s.text(r, 0, "SRP 열별 WACC(같은 βu·D/E)", "subtitle")
    for i in range(len(d["rates"]["srp_list"])):
        _vlist(s, r + 1 + i, f"SRP 열 {i + 1}", f"=(1-WD)*(Rf+BetaL*MRP+SRP_{i + 1})+WD*Kd_AT", "pct3", "%")


# ---------------------------------------------------------------- DCF

DCF_ROWS = [("label", "기간", "", "gen"), ("year", "연도", "", "year"), ("f", "기간 비율", "", "ratio"), ("end", "종료일", "", "date"),
            ("fcff", "FCFF", "백만원", "mn"), ("t_end", "기간 말까지 연수(할인 기준일부터)", "년", "ratio"),
            ("t", "할인 연수(mid-year면 기간 중앙)", "년", "ratio"), ("df", "할인계수 (1 + WACC)^−t", "", "ratio"),
            ("pv", "현재가치(6/30)", "백만원", "mn")]


def dcf_sheet(c: Ctx):
    d, s = c.d, c.sheet("DCF")
    n = c.layout["n"]
    F = c.layout["fc_rows"]
    s.widths({0: 42, 1: 9, 2: 14, 3: 40, **{C_FIRST + j: 12 for j in range(1, n)}})
    s.ws.set_column(C_FIRST, C_FIRST, 14)
    s.text(0, 0, "DCF — 할인·영구가치·EV (선택한 시나리오·SRP)", "title")
    s.text(1, 0, "할인 기준일 6/30(재무상태표) → mid-year 할인 → EV를 평가기준일 9/30로 이월. 순현금은 6/30 장부(이월 안 함)", "note")
    top = 3
    R = {k: top + i for i, (k, *_r) in enumerate(DCF_ROWS)}
    for k, lab, unit, kind in DCF_ROWS:
        s.text(R[k], 0, lab)
        if unit:
            s.text(R[k], 1, unit, "note")
    lab_row = F["k"] - 1
    for j in range(C_FIRST, C_FIRST + n):
        X = lambda k: a1(R[k], j)  # noqa: E731
        s.fx(R["label"], j, f"=Forecast!{a1(lab_row, j)}", "gen")
        s.fx(R["year"], j, f"=Forecast!{a1(F['year'], j)}", "year")
        s.fx(R["f"], j, f"=Forecast!{a1(F['f'], j)}", "ratio")
        s.fx(R["end"], j, f"=Forecast!{a1(F['end'], j)}", "date")
        s.fx(R["fcff"], j, f"=Forecast!{a1(F['fcff'], j)}", "mn")
        s.fx(R["t_end"], j, f"=({X('end')}-DiscDate)/DaysYr", "ratio")
        s.fx(R["t"], j, f"={X('t_end')}-IF(MidYear=1,{X('f')}/2,0)", "ratio")
        s.fx(R["df"], j, f"=(1+WACC)^(-{X('t')})", "ratio")
        s.fx(R["pv"], j, f"={X('fcff')}*{X('df')}", "mn")
    c.layout["dcf_rows"] = R
    last = C_FIRST + n - 1
    fr = lambda k: _row_range("Forecast", F[k], n)  # noqa: E731
    r = R["pv"] + 2
    s.text(r, 0, "RONIC — 2027~명시 마지막 연도 증분 ROIC (P3-B2 규칙, P3-C3 출발점)", "subtitle")
    r += 1
    end_idx = f"MATCH(ExplicitEnd,{fr('year')},0)"
    items = [
        ("e26", "FY2026 EBIT(정상 = FY2026 매출 × 정상 이익률)", f"=Forecast!{a1(F['rev_fy'], C_FIRST)}*Margin_Sel", "mn", None, ""),
        ("n26n", "  NOPAT FY2026 (normal 규칙)", None, "mn", None, ""),
        ("fy26", "FY2026 EBIT(혼합 = 1H 실적 + 2H 정상)", f"=Forecast!{a1(F['fy_ebit'], C_FIRST)}", "mn", None, ""),
        ("n26m", "  NOPAT FY2026 (mixed 규칙)", None, "mn", None, ""),
        ("n26", "출발 NOPAT(선택 규칙)", None, "mn", None, "Inputs의 RONIC 출발점 규칙"),
        ("e32", "명시 마지막 연도 EBIT", f"=INDEX({fr('ebit')},{end_idx})", "mn", None, ""),
        ("n32", "  NOPAT", None, "mn", None, ""),
        ("reinv", "누적 재투자 Σ(CAPEX − D&A + ΔNWC), 2027~명시 끝", f"=SUMPRODUCT(({fr('k')}>1)*{fr('explicit')}*({fr('capex')}-{fr('dna')}+{fr('dnwc')}))", "mn", None, ""),
        ("rcalc", "증분 ROIC(계산값)", None, "pct", None, ""),
        ("ronic", "RONIC(적용)", None, "pct", "RONIC", "계산값 ≤ 0 또는 ≤ g면 WACC로 대체" if d["type"] == "scenario_capex"
         else "재투자 ≤ 0이면 WACC, 그 밖은 [WACC, 과거 3년 ROIC]로 자름(사전 고정)"),
        ("flag", "대체 여부", None, "gen", None, ""),
    ]
    V = {k: r + i for i, (k, *_x) in enumerate(items)}
    A = lambda k: a1(V[k], 2)  # noqa: E731
    fm = {"n26n": f"={A('e26')}-{tax_of(A('e26'))}", "n26m": f"={A('fy26')}-{tax_of(A('fy26'))}",
          "n26": f'=IF(RonicStart="normal",{A("n26n")},{A("n26m")})', "n32": f"={A('e32')}-{tax_of(A('e32'))}",
          "rcalc": f"=IF({A('reinv')}>0,({A('n32')}-{A('n26')})/{A('reinv')},0)",
          "ronic": ronic_formula(d, A("reinv"), A("rcalc"), "WACC", "GEff"),
          "flag": ronic_flag(d, A("reinv"), A("rcalc"), "WACC", "GEff")}
    for k, lab, f, kind, nm, note in items:
        _vlist(s, V[k], lab, f or fm[k], kind, "백만원" if kind == "mn" else "", nm, note, bold=(k == "ronic"))
    r = V["flag"] + 2
    s.text(r, 0, "영구가치 (가치동인: FCF = NOPAT × (1 − g ÷ RONIC))", "subtitle")
    r += 1
    lastc = col(last)
    items2 = [
        ("revN", "마지막 체감 연도 매출", f"=Forecast!${lastc}${F['rev'] + 1}", "mn", None, ""),
        ("ebitN", "마지막 체감 연도 EBIT", f"=Forecast!${lastc}${F['ebit'] + 1}", "mn", None, ""),
        ("revX", "다음 해 매출 = 매출 × (1 + g)", None, "mn", None, ""),
        ("ebitX", "다음 해 EBIT", None, "mn", None, ""),
        ("nopX", "다음 해 NOPAT", None, "mn", None, ""),
        ("fcfX", "다음 해 FCF = NOPAT × (1 − g ÷ RONIC)", None, "mn", None, ""),
        ("tv", "영구가치 TV(Gordon, mid-year면 × (1+WACC)^0.5)", None, "mn", "TV_Gordon", ""),
        ("tN", "마지막 기간 말까지 연수", f"={a1(R['t_end'], last)}", "ratio", None, ""),
        ("pvtv", "영구가치 현재가치", None, "mn", None, ""),
        ("pvsum", "명시·체감 FCFF 현재가치 합", f"=SUM({a1(R['pv'], C_FIRST)}:{a1(R['pv'], last)})", "mn", None, ""),
        ("ev630", "EV(할인 기준일 6/30)", None, "mn", "EV_630", ""),
        ("days", "이월 일수(평가기준일 − 할인 기준일)", "=ValDate-DiscDate", "int", None, ""),
        ("ev930", "EV(평가기준일, × (1+WACC)^(일수 ÷ 365))", None, "mn", "EV_930", ""),
        ("tvshare", "영구가치 비중(PV TV ÷ EV)", None, "pct1", "TVShare", ""),
        ("dnaE", "명시 마지막 연도 D&A", f"=INDEX({fr('dna')},{end_idx})", "mn", None, ""),
        ("revE", "명시 마지막 연도 매출", f"=INDEX({fr('rev')},{end_idx})", "mn", None, ""),
        ("dnaN", "마지막 연도 D&A(명시 끝 D&A × 매출비)" if d["type"] == "scenario_capex" else "마지막 연도 D&A(매출 × D&A/매출)",
         None, "mn", None, ""),
        ("ebitdaN", "마지막 연도 EBITDA", None, "mn", None, ""),
        ("impl", "Gordon 함의 EV/EBITDA(TV ÷ EBITDA)", None, "x", "ImpliedMultiple", ""),
        ("exitm", "Exit 배수(EV/EBITDA)", "=PeerEvEbitdaMed" if d["type"] == "mechanical" else "=ExitMult", "x",
         "ExitMult" if d["type"] == "mechanical" else None,
         "피어 EV/EBITDA 중앙값(병행 표시용, 엔진은 Exit 미계산 ⚠️)" if d["type"] == "mechanical" else "Inputs 6절"),
        ("tvx", "Exit 영구가치(배수 × EBITDA)", None, "mn", None, "시장 배수 → mid-year 조정 없음"),
        ("pvx", "Exit 영구가치 현재가치", None, "mn", None, ""),
        ("evx630", "EV(Exit, 6/30)", None, "mn", None, ""),
        ("evx930", "EV(Exit, 평가기준일)", None, "mn", "EVExit_930", ""),
        ("tvsx", "영구가치 비중(Exit)", None, "pct1", "TVShare_Exit", ""),
        ("gimp", "Exit 함의 영구성장률", None, "pct", "ImpliedG_Exit", ""),
    ]
    V2 = {k: r + i for i, (k, *_x) in enumerate(items2)}
    B = lambda k: a1(V2[k], 2)  # noqa: E731
    mid = "IF(MidYear=1,(1+WACC)^0.5,1)"
    fm2 = {"revX": f"={B('revN')}*(1+GEff)", "ebitX": f"={B('revX')}*(Margin_Sel+MarginConvAmt)" if d.get("v2") else f"={B('revX')}*Margin_Sel",
           "nopX": f"={B('ebitX')}-{tax_of(B('ebitX'))}",
           "fcfX": f"={B('nopX')}*(1-GEff/RONIC)", "tv": f"={B('fcfX')}/(WACC-GEff)*{mid}",
           "pvtv": f"={B('tv')}*(1+WACC)^(-{B('tN')})", "ev630": f"={B('pvsum')}+{B('pvtv')}",
           "ev930": f"={B('ev630')}*(1+WACC)^({B('days')}/DaysYr)", "tvshare": f"={B('pvtv')}/{B('ev630')}",
           "dnaN": f"={B('dnaE')}*{B('revN')}/{B('revE')}" if d["type"] == "scenario_capex" else f"={B('revN')}*DnaRatio",
           "ebitdaN": f"={B('ebitN')}+{B('dnaN')}",
           "impl": f'=IF({B("ebitdaN")}>0,{B("tv")}/{B("ebitdaN")},"N/M")', "tvx": f"={B('exitm')}*{B('ebitdaN')}",
           "pvx": f"={B('tvx')}*(1+WACC)^(-{B('tN')})", "evx630": f"={B('pvsum')}+{B('pvx')}",
           "evx930": f"={B('evx630')}*(1+WACC)^({B('days')}/DaysYr)", "tvsx": f"={B('pvx')}/{B('evx630')}",
           "gimp": f"=({B('tvx')}/{mid}*WACC-{B('fcfX')}/(1+GEff))/({B('tvx')}/{mid}+{B('fcfX')}/(1+GEff))"}
    for k, lab, f, kind, nm, note in items2:
        _vlist(s, V2[k], lab, f or fm2[k], kind, "백만원" if kind == "mn" else "", nm, note, bold=k in ("ev930", "tv"))
    c.layout["dcf_vals"] = {**V, **V2}
    r = max(V2.values()) + 2
    s.text(r, 0, "영구가치 교차 확인 (Gordon vs Exit, 같은 명시·체감 현금흐름)", "subtitle")
    for j, h in enumerate(["방식", "", "주당(원)", "EV/EBITDA(배)", "영구성장률", "영구가치 비중"]):
        s.text(r + 1, j, h, "header")
    rows_x = [("Gordon(가치동인)", "=PerShare", "=ImpliedMultiple", "=GEff", "=TVShare"),
              ("Exit(배수)", "=PerShareExit", "=ExitMult", "=ImpliedG_Exit", "=TVShare_Exit")]
    for i, (lab, *fs_) in enumerate(rows_x):
        s.text(r + 2 + i, 0, lab)
        for j, (f, kind) in enumerate(zip(fs_, ("won", "x", "pct", "pct1"))):
            s.fx(r + 2 + i, 2 + j, f, kind)
    s.text(r + 4, 0, "Gordon 행의 배수 = 함의 배수, Exit 행의 g = 함의 영구성장률. 차이는 사실로만 표시", "note")
    c.range_name("TVCross", "DCF", a1(r + 2, 0), a1(r + 3, 5))


# ---------------------------------------------------------------- Bridge

def bridge_sotp(c: Ctx):
    d, s = c.d, c.sheet("Bridge")
    fs, L = c.layout["fs_refs"], d["meta"]["ltm_year"]
    h1 = f"H1{L}"
    o = lambda a: fs[("OFS", h1, a)]  # noqa: E731
    k = lambda a: fs[("CFS", h1, a)]  # noqa: E731
    seg = c.layout["seg_refs"]
    sub = d["market"]["sub_name"]
    n = c.layout["n"]
    s.widths({0: 46, 1: 9, 2: 15, 3: 50, **{C_FIRST + j: 12 for j in range(1, 8)}})
    s.ws.set_column(C_FIRST, C_FIRST, 15)
    s.text(0, 0, "Bridge — EV → 주식가치 → 주당 (SOTP)", "title")
    s.text(1, 0, "SOTP = 모회사 사업 EV(DCF) + 상장 종속회사 지분 × 시가총액 + 모회사 순현금(리스부채 포함 차입금 차감) + 비영업자산 − 본사 공통비", "note")
    r = 3
    rows = [
        ("ev", "모회사 사업 EV(평가기준일)", "=EV_930", "mn", None, "DCF 시트"),
        ("stake_v", f"{sub} 지분가치 = 지분율 × 시가총액", "=Stake*SubMC", "mn", "StakeValue", "기준일 시가총액(한국거래소 통계정보)"),
        ("cash", "모회사 현금및현금성자산", f"={o('cash')}", "mn", None, "2026-06-30 별도(정부보조금 차감 순액)"),
        ("stf", "모회사 단기금융자산", f"={o('short_term_fin')}", "mn", None, "CP·전단채·금융채·MMF형 → 현금성"),
        ("debt_api", "모회사 차입금(API 표준 계정)", f"={o('total_debt')}", "mn", None, ""),
        ("debt_fix", "모회사 장기차입금 보정", "=LTB_Override", "mn", None, "API 계정 오표기(Inputs 5)"),
        ("debt", "모회사 총차입금", None, "mn", None, ""),
        ("lease", "모회사 리스부채(IFRS 16)", f"={o('lease_liabilities')}", "mn", None, "WACC D/E와 일관되게 차입금 취급"),
        ("netcash", "모회사 순현금 = 현금 + 단기금융 − 차입금 − 리스", None, "mn", "ParentNetCash", ""),
        ("nonop", "모회사 비영업자산(장기금융자산)", f"={o('long_term_fin')}", "mn", "ParentNonOp", "상각후원가·FVPL·FVOCI 장부 = 공정가치"),
        ("hq", "본사 미배분 공통비 PV(차감)", "=-HQ_PV", "mn", None, ""),
        ("equity", "주식가치(SOTP)", None, "mn", "Equity", ""),
        ("adj", "  EV 밖 항목 합계(시나리오·SRP와 무관)", None, "mn", "BridgeAdj", "Scen_Calc가 같은 값을 쓴다"),
        ("eqadd", "  지분 방식 배수(PER·PBR)에 더할 항목 = 종속회사 지분 시가", "=StakeValue", "mn", "EqAddOn", "p3c1.sotp_from_multiple"),
        ("shares", "유통주식수 = (보통주 + 우선주) − 자기주식", "=(CommonIssued-CommonTreasury)+(PrefIssued-PrefTreasury)", "int", "Shares", ""),
        ("ps", "주당 가치(원, Gordon)", None, "won", "PerShare", "가정 하의 추정 내재가치(예시)"),
        ("vs", "기준일 종가 대비", "=PerShare/Close-1", "pct1", None, ""),
        ("eqx", "주식가치(Exit 영구가치)", None, "mn", None, ""),
        ("psx", "주당 가치(원, Exit)", None, "won", "PerShareExit", ""),
        ("inv", "참고: 종속기업투자(별도 장부) — 더하지 않음", "=InvSubsBook", "mn", None, "지분은 시가로 한 번만 센다"),
        ("nav", "참고: 순자산가치(연결 지배주주지분 장부, 주당 원)", f"={fs[('CFS', h1, 'equity_parent')]}*MnToWon/Shares", "won", "NavPerShare",
         "자산가치 접근(재평가 없음, 장부 그대로) — 03 문서 3-2"),
    ]
    V = {kk: r + i for i, (kk, *_x) in enumerate(rows)}
    A = lambda kk: a1(V[kk], 2)  # noqa: E731
    fm = {"debt": f"={A('debt_api')}+{A('debt_fix')}", "netcash": f"={A('cash')}+{A('stf')}-{A('debt')}-{A('lease')}",
          "equity": f"={A('ev')}+{A('stake_v')}+{A('netcash')}+{A('nonop')}+{A('hq')}",
          "adj": f"={A('equity')}-{A('ev')}", "ps": f"={A('equity')}*MnToWon/Shares",
          "eqx": "=EVExit_930+BridgeAdj", "psx": f"={A('eqx')}*MnToWon/Shares"}
    for kk, lab, f, kind, nm, note in rows:
        _vlist(s, V[kk], lab, f or fm[kk], kind, "원" if kind == "won" else ("주" if kind == "int" else ("백만원" if kind == "mn" else "")),
               nm, note, bold=kk in ("equity", "ps"))
    c.layout["bridge_vals"] = V
    r = V["inv"] + 2

    # ---- structure decision (src/valuation/structure.decide)
    s.text(r, 0, "구조 판단 규칙 (config/valuation_rules.yaml structure)", "subtitle")
    r += 1
    ltm = lambda ent, it: f"{seg[(ent, it, 'FY2025')]}+{seg[(ent, it, '1H26')]}-{seg[(ent, it, '1H25')]}"  # noqa: E731
    rows2 = [
        ("nci_mv", "비지배지분 시가 = (1 − 지분율) × 시가총액", "=(1-Stake)*SubMC", "mn"),
        ("nci_sh", "비지배지분 시가 ÷ 대상 시가총액", None, "pct1"),
        ("pm", "모회사 LTM 영업이익률(부문)", f"=({ltm('parent', 'op')})/({ltm('parent', 'revenue')})", "pct1"),
        ("sm", f"{sub} LTM 영업이익률(부문)", f"=({ltm('sub', 'op')})/({ltm('sub', 'revenue')})", "pct1"),
        ("pg", "모회사 1H 매출 성장률", f"={seg[('parent', 'revenue', '1H26')]}/{seg[('parent', 'revenue', '1H25')]}-1", "pct1"),
        ("sg", f"{sub} 1H 매출 성장률", f"={seg[('sub', 'revenue', '1H26')]}/{seg[('sub', 'revenue', '1H25')]}-1", "pct1"),
        ("mgap", "부문 이익률 차이", None, "pct1"),
        ("ggap", "부문 성장률 차이", None, "pct1"),
        ("dec", "규칙 판정", None, "gen"),
    ]
    V2 = {kk: r + i for i, (kk, *_x) in enumerate(rows2)}
    B = lambda kk: a1(V2[kk], 2)  # noqa: E731
    fm2 = {"nci_sh": f"={B('nci_mv')}/TargetMC", "mgap": f"=ABS({B('pm')}-{B('sm')})", "ggap": f"=ABS({B('pg')}-{B('sg')})",
           "dec": (f'=IF(OR({B("nci_sh")}>=NciShareMin,AND(ListedSub=1,OR({B("mgap")}>=MarginGapMin,{B("ggap")}>=GrowthGapMin))),'
                   f'"sotp","consolidated")')}
    for kk, lab, f, kind in rows2:
        _vlist(s, V2[kk], lab, f or fm2[kk], kind, "백만원" if kind == "mn" else "", "StructureRule" if kk == "dec" else None,
               bold=kk == "dec")
    s.text(V2["dec"], 3, "비지배 ≥ 10% 또는 (상장 종속회사 + 이익률 차이 ≥ 5%p 또는 성장률 차이 ≥ 10%p) → SOTP", "note")
    r = V2["dec"] + 2

    # ---- consolidated cross-check: parent DCF + subsidiary simple DCF − consolidated net debt + non-op − NCI market
    s.text(r, 0, f"교차 확인 — 연결 DCF − 비지배 시가 ({sub} 단순 DCF, 같은 WACC)", "subtitle")
    r += 1
    F, D = c.layout["fc_rows"], c.layout["dcf_rows"]
    ne = 1 + (d["dcf"]["explicit_end"] - int(d["meta"]["cf_start"][:4]))      # explicit periods (2H26..2032)
    sub_rows = [("label", "기간", "gen"), ("k", "기간 순번", "int"), ("year", "연도", "year"), ("f", "기간 비율", "ratio"),
                ("rev_fy", "회계연도 매출", "mn"), ("rev", "기간 매출", "mn"), ("ebit", "영업이익", "mn"), ("fy_ebit", "회계연도 영업이익", "mn"),
                ("dna", "D&A = 매출 × LTM 감가상각비율", "mn"), ("capex", "CAPEX = D&A × 배수", "mn"),
                ("dnwc", "ΔNWC", "mn"), ("tax_rate", "실효세율", "pct"), ("tax", "법인세", "mn"), ("fcff", "FCFF", "mn"),
                ("t", "할인 연수", "ratio"), ("df", "할인계수", "ratio"), ("pv", "현재가치", "mn")]
    S = {kk: r + i for i, (kk, *_x) in enumerate(sub_rows)}
    for kk, lab, kind in sub_rows:
        s.text(S[kk], 0, lab)
    scal = S["pv"] + 2
    sv = {"rev2h": scal, "da": scal + 1, "nwc0": scal + 2}
    _vlist(s, sv["rev2h"], f"{sub} 2H26 매출 = (FY2025 − 1H25) × (1 + g)",
           f"=({seg[('sub', 'revenue', 'FY2025')]}-{seg[('sub', 'revenue', '1H25')]})*(1+SubG)", "mn", "백만원")
    _vlist(s, sv["da"], "LTM 감가상각비 ÷ LTM 매출(부문)", f"=({ltm('sub', 'depreciation')})/({ltm('sub', 'revenue')})", "pct")
    _vlist(s, sv["nwc0"], f"{sub} 순운전자본(연결 − 모회사, 6/30)",
           f"=({k('receivables')}+{k('inventories')}-{k('trade_payables')}-{k('contract_liabilities')})-NWC_Open", "mn", "백만원")
    Z = lambda kk: a1(sv[kk], 2)  # noqa: E731
    for i in range(ne):
        j = C_FIRST + i
        X = lambda kk: a1(S[kk], j)  # noqa: E731
        Wp = lambda kk: a1(S[kk], j - 1)  # noqa: E731
        fmap = {"label": f"=Forecast!{a1(F['k'] - 1, j)}", "k": f"=Forecast!{a1(F['k'], j)}", "year": f"=Forecast!{a1(F['year'], j)}",
                "f": f"=Forecast!{a1(F['f'], j)}",
                "rev_fy": f"=IF({X('k')}=1,{seg[('sub', 'revenue', '1H26')]}+{Z('rev2h')},{Wp('rev_fy')}*(1+SubG))",
                "rev": f"=IF({X('k')}=1,{Z('rev2h')},{X('rev_fy')})", "ebit": f"={X('rev')}*SubM",
                "fy_ebit": f"=IF({X('k')}=1,{seg[('sub', 'op', '1H26')]}+{X('ebit')},{X('ebit')})",
                "dna": f"={X('rev')}*{Z('da')}", "capex": f"={X('dna')}*SubCapexDna",
                "dnwc": f"=IF({X('k')}=1,{Z('nwc0')}*SubG*SubHalf,{Z('nwc0')}*(1+SubG)^({X('year')}-YEAR(CfStart))*SubG)",
                "tax_rate": f"={eff_of(X('fy_ebit'))}", "tax": f"=MAX({X('ebit')},0)*{X('tax_rate')}",
                "fcff": f"={X('ebit')}-{X('tax')}+{X('dna')}-{X('capex')}-{X('dnwc')}",
                "t": f"=DCF!{a1(D['t'], j)}", "df": f"=(1+WACC)^(-{X('t')})", "pv": f"={X('fcff')}*{X('df')}"}
        for kk, lab, kind in sub_rows:
            s.fx(S[kk], j, fmap[kk], kind)
    le = C_FIRST + ne - 1
    r = sv["nwc0"] + 1
    mid = "IF(MidYear=1,(1+WACC)^0.5,1)"
    rows3 = [
        ("fcfn", "정규화 FCF(마지막 연도 FCFF ÷ 기간 비율)", f"={a1(S['fcff'], le)}/{a1(S['f'], le)}", "mn"),
        ("tv", "영구가치(Gordon)", None, "mn"), ("pvtv", "영구가치 현재가치", None, "mn"),
        ("ev630", f"{sub} EV(6/30)", None, "mn"), ("ev930", f"{sub} EV(평가기준일)", None, "mn"),
        ("cnd", "연결 순차입금(6/30) = 차입금 + 리스 − 현금 − 단기금융",
         f"={k('total_debt')}+{k('lease_liabilities')}-{k('cash')}-{k('short_term_fin')}", "mn"),
        ("cltf", "연결 비영업자산(장기금융자산)", f"={k('long_term_fin')}", "mn"),
        ("ncimv", "비지배지분 시가", f"=(1-Stake)*SubMC", "mn"),
        ("ceq", "연결 주식가치 = (모회사 EV + 종속 EV) − 순차입금 + 비영업 − 비지배 시가", None, "mn"),
        ("cps", "연결 교차 확인 주당(원)", None, "won"), ("diff", "SOTP − 연결(주당, 원)", None, "won"),
        ("subnc", f"{sub} 순현금(연결 − 모회사)", f"=({k('cash')}+{k('short_term_fin')}-{k('total_debt')}-{k('lease_liabilities')})-ParentNetCash", "mn"),
        ("subno", f"{sub} 비영업(연결 − 모회사)", f"={k('long_term_fin')}-ParentNonOp", "mn"),
        ("subint", f"{sub} 내재 주식가치(EV + 순현금 + 비영업)", None, "mn"),
        ("gap", "  시가총액 − 내재가치(100%, 차이의 주원인)", None, "mn"),
        ("bookps", "참고: 비지배 장부가 차감 시 주당(원)", None, "won"),
    ]
    V3 = {kk: r + i for i, (kk, *_x) in enumerate(rows3)}
    C3 = lambda kk: a1(V3[kk], 2)  # noqa: E731
    fm3 = {"tv": f"={C3('fcfn')}*(1+SubGT)/(WACC-SubGT)*{mid}",
           "pvtv": f"={C3('tv')}*(1+WACC)^(-DCF!{a1(D['t_end'], le)})",
           "ev630": f"=SUM({a1(S['pv'], C_FIRST)}:{a1(S['pv'], le)})+{C3('pvtv')}",
           "ev930": f"={C3('ev630')}*(1+WACC)^((ValDate-DiscDate)/DaysYr)",
           "ceq": f"=EV_930+{C3('ev930')}-{C3('cnd')}+{C3('cltf')}-{C3('ncimv')}",
           "cps": f"={C3('ceq')}*MnToWon/Shares", "diff": f"=PerShare-{C3('cps')}",
           "subint": f"={C3('ev930')}+{C3('subnc')}+{C3('subno')}", "gap": f"=SubMC-{C3('subint')}",
           "bookps": f"=(EV_930+{C3('ev930')}-{C3('cnd')}+{C3('cltf')}-{k('nci')})*MnToWon/Shares"}
    for kk, lab, f, kind in rows3:
        _vlist(s, V3[kk], lab, f or fm3[kk], kind, "원" if kind == "won" else "백만원", "CrossPerShare" if kk == "cps" else None,
               bold=kk == "cps")
    c.layout["cross_vals"] = V3


def bridge(c: Ctx):
    if c.d["meta"]["structure"] == "sotp":
        bridge_sotp(c)
    else:
        bridge_cons(c)


def _market_equity(c: Ctx) -> str:
    """Market value of all shares (structure test): common at the close + listed preferred at their close + unlisted
    preferred at the common close (company_dcf.load_company)."""
    # prices are 원 per share -> divide by MnToWon to get 백만원 (P4-X: the value was in 원 with a 백만원 label)
    if c.d["shares"]["listed_pref"]:
        return ("=(Close*(CommonIssued-CommonTreasury)+SUMPRODUCT(PrefClose,PrefListed)"
                "+Close*MAX(PrefIssued-PrefTreasury-SUM(PrefListed),0))/MnToWon")
    return "=Close*(CommonIssued-CommonTreasury+PrefIssued-PrefTreasury)/MnToWon"


def bridge_cons(c: Ctx):
    """Consolidated: equity = EV − (debt + lease − cash-like) + non-operating − NCI (company_dcf.bridge / dcf_value).
    The affiliate-loan toggle only changes the value when set to 0 (default 1 = engine)."""
    d, s = c.d, c.sheet("Bridge")
    fs, L = c.layout["fs_refs"], d["meta"]["ltm_year"]
    h1 = f"H1{L}"
    k = lambda a: fs[("CFS", h1, a)]  # noqa: E731
    s.widths({0: 50, 1: 9, 2: 15, 3: 56})
    s.text(0, 0, "Bridge — EV → 주식가치 → 주당 (연결 DCF − 비지배지분)", "title")
    s.text(1, 0, "주식가치 = EV − 순차입금(차입금 + 리스부채 − 현금성) + 비영업자산 − 비지배지분(장부). 현금성·비영업은 FS_Hist 줄 분류(peer_p3 규칙)", "note")
    r = 3
    aff = bool(d.get("affiliate"))
    rows = [
        ("ev", "EV(평가기준일)", "=EV_930", "mn", None, "DCF 시트"),
        ("debt", "총차입금(차입금·사채)", f"={k('total_debt')}", "mn", None, f"{d['meta']['bs_date']} 연결"),
        ("lease", "리스부채(IFRS 16)", f"={k('lease_liabilities')}", "mn", None, "WACC D/E와 같은 정의"),
        ("cash", "현금성(유동 금융자산 줄 합계)" + (" − 사람 확정 영업용 현금" if (d.get("overrides") or {}).get("cash_adjust_mn") is not None else ""),
         '=SUMIFS(BsAmt,BsClass,"cash_like")' + ("-CashAdjust" if (d.get("overrides") or {}).get("cash_adjust_mn") is not None else ""),
         "mn", None, "FS_Hist 분류 cash_like"),
        ("netdebt", "순차입금 = 차입금 + 리스 − 현금성", None, "mn", "NetDebt", ""),
        ("nonop", "비영업자산(비유동 금융자산·관계기업 줄 합계)" + (" + SOTP 종속회사 가치" if d.get("sotp") else ""),
         ('=SUMIFS(BsAmt,BsClass,"non_operating")+SotpRemainder+SotpListed*(1-SubDiscount)+SotpUnlisted' if d.get("sotp")
          else '=SUMIFS(BsAmt,BsClass,"non_operating")'), "mn", None,
         "FS_Hist 분류 non_operating" + (" + 아래 SOTP 행(종속 줄은 빼고 바꿔 넣음)" if d.get("sotp") else "")),
        ("other_fin", "  참고: '기타금융자산' 줄 합계(유동 + 비유동)", '=SUMPRODUCT(ISNUMBER(SEARCH("기타금융자산",BsName))*BsAmt)', "mn", None,
         "현금성·비영업 안에 포함된 금액"),
    ]
    if d.get("sotp"):                    # P7-B3 general SOTP: parent (separate) + subsidiaries, no double count
        rows += [("sot_lines", "  SOTP: 별도 재무상태표 '종속' 투자 줄(비영업에서 제외)", '=SUMIFS(BsAmt,BsClass,"sub_inv")', "mn", "SotpSubLines",
                  "FS_Hist 분류 sub_inv"),
                 ("sot_book", "  SOTP: 그중 연결 범위 피투자회사 장부가(출자현황)", "=SUM(SubBook)", "mn", "SotpBook", "Inputs 표 10"),
                 ("sot_rem", "  SOTP: 합친 줄의 관계기업 몫 = max(줄 − 장부, 0)", None, "mn", "SotpRemainder", "장부가 유지"),
                 ("sot_listed", "  SOTP: 상장 종속회사 지분 시가 = 보유 주식수 × 종가", "=SUMPRODUCT(SubShares,SubClose,SubListedDirect)/MnToWon", "mn",
                  "SotpListed", "직접 보유분만, 한국거래소 통계정보 종가"),
                 ("sot_disc", "  SOTP: 상장 지분 할인율", "=SubDiscount", "pct", None, "기본 0%, 민감도 30%·50%"),
                 ("sot_unl", "  SOTP: 비상장 종속회사 장부가", "=SUMPRODUCT(SubBook,SubUnlisted)", "mn", "SotpUnlisted", "Inputs 표 10")]
    if aff:
        rows += [("aff", "  그중 계열사 대여금 등(특수관계자 자금거래 표)", "=SUM(AffLoanItems)", "mn", "AffLoanTotal", "Inputs 표 9"),
                 ("aff_adj", "계열사 대여금 조정 = −(1 − 포함 토글) × 대여금", "=-(1-AffLoanIncl)*AffLoanTotal", "mn", None,
                  "토글 1(기본) = 0 → 엔진과 같음")]
    rows += [
        (("nci", "비지배지분 = 사람 확정값(평가 세션)", "=NciOverride", "mn", None, "Inputs '사람 확정값'")
         if (d.get("overrides") or {}).get("nci_mn") is not None else
         ("nci", "비지배지분(장부)", f"={k('nci')}", "mn", None, "상장 종속회사 없음 → 장부")),
        ("equity", "주식가치", None, "mn", "Equity", ""),
        ("adj", "  EV 밖 항목 합계(시나리오·SRP와 무관)", None, "mn", "BridgeAdj", "Scen_Calc·Peers가 같은 값을 쓴다"),
        ("eqadd", "  지분법 방식 배수(PER·PBR)에 더할 항목", "=0", "mn", "EqAddOn", "연결 구조: 없음"),
        ("shares", "유통주식수 = (보통주 + 우선주) − 자기주식", "=(CommonIssued-CommonTreasury)+(PrefIssued-PrefTreasury)", "int", "Shares",
         "우선주를 보통주와 같은 청구권으로 본다(⚠️)"),
        ("ps", "주당 가치(원, Gordon)", None, "won", "PerShare", "가정 하의 추정 내재가치(예시)"),
        ("vs", "기준일 종가(보통주) 대비", "=PerShare/Close-1", "pct1", None, "가정 차이 표시(판단 아님)"),
        ("eqx", "주식가치(Exit 영구가치)", "=EVExit_930+BridgeAdj", "mn", None, ""),
        ("psx", "주당 가치(원, Exit)", None, "won", "PerShareExit", ""),
    ]
    if aff:
        rows += [("aff_ps", "참고: 계열사 대여금 제외 시 주당 영향(원)", "=-AffLoanTotal*MnToWon/Shares", "won", "AffLoanImpact",
                  "토글과 무관하게 표시")]
    rows += [("nav", "참고: 순자산가치(지배주주지분 장부, 없으면 자본총계 − 비지배, 주당 원)",
              f"=IF({k('equity_parent')}<>0,{k('equity_parent')},{k('total_equity')}-{k('nci')})*MnToWon/Shares", "won", "NavPerShare",
              "자산가치 접근(재평가 없음, 장부 그대로) — 03 문서 3-2")]
    V = {kk: r + i for i, (kk, *_x) in enumerate(rows)}
    A = lambda kk: a1(V[kk], 2)  # noqa: E731
    fm = {"netdebt": f"={A('debt')}+{A('lease')}-{A('cash')}",
          **({"sot_rem": f"=MAX({A('sot_lines')}-{A('sot_book')},0)"} if d.get("sotp") else {}),
          "equity": f"={A('ev')}-{A('netdebt')}+{A('nonop')}-{A('nci')}" + (f"+{A('aff_adj')}" if aff else ""),
          "adj": f"={A('equity')}-{A('ev')}", "ps": f"={A('equity')}*MnToWon/Shares", "psx": f"={A('eqx')}*MnToWon/Shares"}
    for kk, lab, f, kind, nm, note in rows:
        _vlist(s, V[kk], lab, f or fm[kk], kind, "원" if kind == "won" else ("주" if kind == "int" else ("백만원" if kind == "mn" else "")),
               nm, note, bold=kk in ("equity", "ps"))
    c.layout["bridge_vals"] = V
    r = max(V.values()) + 2
    s.text(r, 0, "구조 판단 규칙 (config/valuation_rules.yaml structure)", "subtitle")
    r += 1
    rows2 = [("meq", "시장 주식가치(보통주 + 우선주)", _market_equity(c), "mn"),
             ("nci_v", "비지배지분(상장 종속회사면 시가, 아니면 장부)", f"=IF(ListedSub=1,(1-Stake)*SubMC,{A('nci')})", "mn"),
             ("nci_sh", "비지배지분 ÷ 시장 주식가치", None, "pct1"),
             ("mgap", "부문 이익률 차이", "=SegMarginGap", "pct1"), ("ggap", "부문 성장률 차이", "=SegGrowthGap", "pct1"),
             ("dec", "규칙 판정", None, "gen")]
    V2 = {kk: r + i for i, (kk, *_x) in enumerate(rows2)}
    B = lambda kk: a1(V2[kk], 2)  # noqa: E731
    fm2 = {"nci_sh": f"={B('nci_v')}/{B('meq')}",
           "dec": (f'=IF(OR({B("nci_sh")}>=NciShareMin,AND(ListedSub=1,OR({B("mgap")}>=MarginGapMin,{B("ggap")}>=GrowthGapMin))),'
                   f'"sotp","consolidated")')}
    for kk, lab, f, kind in rows2:
        _vlist(s, V2[kk], lab, f or fm2[kk], kind, "백만원" if kind == "mn" else "", "StructureRule" if kk == "dec" else
               ("MarketEquity" if kk == "meq" else None), bold=kk == "dec")
    s.text(V2["dec"], 3, "비지배 ≥ 10% 또는 (상장 종속회사 + 이익률 차이 ≥ 5%p 또는 성장률 차이 ≥ 10%p) → SOTP", "note")


# ---------------------------------------------------------------- Scen_Calc

def scen_calc(c: Ctx):
    """One block per scenario: the Forecast rows with that scenario's parameters, then per SRP column: WACC, RONIC,
    FCFF (fade reinvestment uses that RONIC), PV, value-driver TV, EV, equity (EV + the same SOTP items) and per share."""
    d, s = c.d, c.sheet("Scen_Calc")
    n = c.layout["n"]
    s.widths({0: 40, 1: 9, 2: 13, **{C_FIRST + j: 12 for j in range(n)}})
    s.text(0, 0, "Scen_Calc — 시나리오 4 × SRP 3 (Forecast·DCF와 같은 수식, 시나리오 고정)", "title")
    s.text(1, 0, "Scenarios 시트 표의 계산. 할인 연수는 DCF 시트와 같은 행을 쓴다. 주식가치 = EV + Bridge의 EV 밖 항목", "note")
    keys, labels = d["excel"]["scenarios"], d["excel"]["scenario_labels"]
    prow, pcol = c.layout["param_rows"], c.layout["param_cols"]
    D = c.layout["dcf_rows"]
    srps = d["rates"]["srp_list"]
    last = C_FIRST + n - 1
    r = 3
    out = {}
    for k in keys:
        pc = col(pcol[k])
        s.text(r, 0, f"시나리오: {labels[k]}", "subtitle")
        pref = lambda pk: f"Forecast!${pc}${prow[pk] + 1}"  # noqa: E731
        if d["type"] == "mechanical":
            P = {"g0": pref("g0"), "gtx": "GTermCfg", "glast": pref("glast"), "margin": pref("margin"), "gt": "GTermCfg"}
        else:
            gvec = f"Forecast!${pc}${prow['g_2027'] + 1}:${pc}${prow['g_2032'] + 1}"
            P = {"rev26": pref("rev_2026"), "gvec": gvec, "glast": f"INDEX({gvec},ExplicitEnd-YEAR(CfStart))",
                 "margin": pref("margin"), "gt": pref("g_terminal"), "opflag": pref("op_flag"), "op26": pref("op_2026")}
        R = forecast_rows(c, s, r + 1, P, main=False)
        rr = R["fcff_pre"] + 2
        rng = lambda key: f"${col(C_FIRST)}${R[key] + 1}:${col(last)}${R[key] + 1}"  # noqa: E731
        end_idx = f"MATCH(ExplicitEnd,{rng('year')},0)"
        mend = f"({P['margin']}+MarginConvAmt)" if d.get("v2") else P["margin"]     # P7-B2b v2: terminal margin = path end
        sc = [("e26", "FY2026 EBIT(정상)", f"={a1(R['rev_fy'], C_FIRST)}*{P['margin']}", "mn"),
              ("fy26", "FY2026 EBIT(혼합)", f"={a1(R['fy_ebit'], C_FIRST)}", "mn"),
              ("n26", "출발 NOPAT(선택 규칙)", None, "mn"),
              ("e32", "명시 마지막 연도 EBIT", f"=INDEX({rng('ebit')},{end_idx})", "mn"),
              ("n32", "  NOPAT", None, "mn"),
              ("reinv", "누적 재투자", f"=SUMPRODUCT(({rng('k')}>1)*{rng('explicit')}*({rng('capex')}-{rng('dna')}+{rng('dnwc')}))", "mn"),
              ("rcalc", "증분 ROIC(계산값)", None, "pct"),
              ("tkd", "한계세율(세후 Kd)", None, "pct1"),
              ("revN", "마지막 연도 매출", f"=${col(last)}${R['rev'] + 1}", "mn"),
              ("nopX", "다음 해 NOPAT", None, "mn")]
        V = {kk: rr + i for i, (kk, *_x) in enumerate(sc)}
        A = lambda kk: a1(V[kk], 2)  # noqa: E731
        fm = {"n26": f'=IF(RonicStart="normal",{A("e26")}-{tax_of(A("e26"))},{A("fy26")}-{tax_of(A("fy26"))})',
              "n32": f"={A('e32')}-{tax_of(A('e32'))}", "rcalc": f"=IF({A('reinv')}>0,({A('n32')}-{A('n26')})/{A('reinv')},0)",
              "tkd": "=T_Kd" if d["kd_tax_base"] == "ltm_pretax" else f'=INDEX(TaxRate,COUNTIF(TaxTo,"<"&{A("e32")})+1)',
              "nopX": f"=({A('revN')}*(1+{P['gt']})*{mend})-{tax_of('(' + A('revN') + '*(1+' + P['gt'] + ')*' + mend + ')')}"}
        for kk, lab, f, kind in sc:
            _vlist(s, V[kk], lab, f or fm[kk], kind, "백만원" if kind == "mn" else "")
        rr = V["nopX"] + 2
        for jj, sv in enumerate(srps):
            s.text(rr, 0, f"SRP 열 {jj + 1}", "bold")
            s.fx(rr, 2, f"=SRP_{jj + 1}", "pct")
            w = a1(rr + 1, 2)
            _vlist(s, rr + 1, "WACC", f"=(1-WD)*(Rf+BetaL*MRP+SRP_{jj + 1})+WD*Kd_Pre*(1-{A('tkd')})", "pct3")
            ron = a1(rr + 2, 2)
            _vlist(s, rr + 2, "RONIC(적용)", ronic_formula(d, A("reinv"), A("rcalc"), w, f"({P['gt']})"), "pct")
            s.text(rr + 3, 0, "FCFF")
            s.text(rr + 4, 0, "현재가치")
            for j in range(C_FIRST, last + 1):
                s.fx(rr + 3, j, f"={a1(R['fcff_pre'], j)}-IF({a1(R['explicit'], j)}=1,0,{a1(R['nopat'], j)}*{a1(R['g'], j)}/{ron})", "mn")
                s.fx(rr + 4, j, f"={a1(rr + 3, j)}*(1+{w})^(-DCF!{a1(D['t'], j)})", "mn")
            mid = f"IF(MidYear=1,(1+{w})^0.5,1)"
            v = rr + 5
            _vlist(s, v, "영구가치(가치동인)", f"={A('nopX')}*(1-{P['gt']}/{ron})/({w}-{P['gt']})*{mid}", "mn", "백만원")
            _vlist(s, v + 1, "영구가치 현재가치", f"={a1(v, 2)}*(1+{w})^(-DCF!{a1(D['t_end'], last)})", "mn", "백만원")
            _vlist(s, v + 2, "EV(6/30)", f"=SUM({a1(rr + 4, C_FIRST)}:{a1(rr + 4, last)})+{a1(v + 1, 2)}", "mn", "백만원")
            _vlist(s, v + 3, "EV(평가기준일)", f"={a1(v + 2, 2)}*(1+{w})^((ValDate-DiscDate)/DaysYr)", "mn", "백만원")
            _vlist(s, v + 4, "주식가치 = EV + EV 밖 항목(Bridge)", f"={a1(v + 3, 2)}+BridgeAdj", "mn", "백만원")
            _vlist(s, v + 5, "주당 가치(원)", f"={a1(v + 4, 2)}*MnToWon/Shares", "won", "원", bold=True)
            _vlist(s, v + 6, "영구가치 비중", f"={a1(v + 1, 2)}/{a1(v + 2, 2)}", "pct1")
            out[(k, jj)] = {"ps": f"Scen_Calc!{a1(v + 5, 2, True)}", "wacc": f"Scen_Calc!{a1(rr + 1, 2, True)}",
                            "ronic": f"Scen_Calc!{a1(rr + 2, 2, True)}", "tv": f"Scen_Calc!{a1(v + 6, 2, True)}",
                            "ev": f"Scen_Calc!{a1(v + 3, 2, True)}"}
            rr = v + 8
        r = rr + 1
    c.layout["scen_cells"] = out
