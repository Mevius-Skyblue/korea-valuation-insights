"""Calculation sheets for the scenario_capex engine: Forecast, WACC, DCF, Bridge, Scen_Calc.

Every row has one formula across its period columns (FAST rule); the opening column (기초, 2026-06-30) holds links or
structural zeros so the first period needs no special formula. Formulas mirror src/valuation/rf_dcf.parent_case,
rf_dcf2.value (three stages, value drivers, RONIC rule), dcf.fcff_rows / run_dcf (mid-year, partial first period,
roll-forward), wacc.wacc and sotp.sotp_equity - see the comments next to each block.
"""

from __future__ import annotations

from src.excel.context import Ctx
from src.excel.sheets_forecast import forecast_rows
from src.excel.sheets_layout import C_FIRST, _row_range, _vlist, eff_of, ronic_flag, ronic_formula, tax_of
from src.excel.writer import a1, col

# ---------------------------------------------------------------- Forecast


# ---------------------------------------------------------------- WACC


def nm_unless_number(formula: str, dep: str) -> str:
    """P7-X2a public mode: '=expr' -> '=IF(ISNUMBER(dep),expr,"N/M")' (a hidden aggregate is a text)."""
    return f'=IF(ISNUMBER({dep}),{formula[1:]},"N/M")'


def wacc_sheet(c: Ctx):
    d, s = c.d, c.sheet("WACC")
    s.widths({0: 20, 1: 10, 2: 9, 3: 9, 4: 9, 5: 9, 6: 8, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 11, 13: 11, 14: 11})
    s.text(0, 0, "WACC — 피어 베타 → 할인율", "title")
    s.text(
        1,
        0,
        "원 β → Blume(0.67 β + 0.33) → Hamada 언레버(회사별 기간평균 D/E, t 22%) → 포함 피어 중앙값. 회귀 결과는 한국거래소 통계정보 기반",
        "note",
    )
    if d.get("public"):  # P7-C1 public mode: beta aggregates (Inputs 표 B), no per-peer rows
        r = 4
        _vlist(s, r, "포함 피어 수", "=BetaPubN", "int", "곳")
        if d["engine"].get("beta_src") == "override":
            _vlist(s, r + 1, "βu = 사람 확정값(평가 세션)", "=BetaOverride", "beta", "", "BetaU", bold=True)
        else:
            _vlist(s, r + 1, "βu(공개 모드 집계 입력)", "=BetaPubU", "beta", "", "BetaU", bold=True)
        _vlist(s, r + 2, "R² 중앙값(포함 피어, 집계 입력)", "=BetaPubR2", "beta", "", "BetaR2Median")
    else:
        hdr = [
            "회사",
            "등급",
            "포함",
            "원 β",
            "표준오차",
            "R²",
            "관측 수",
            "기간평균 D/E",
            "Blume β",
            "βu (Blume)",
            "βu (원 β, 민감도)",
            "βu 포함분",
            "R² 포함분",
            "엔진 Blume",
            "엔진 βu",
        ]
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
        if d["engine"].get("beta_src") == "override":  # P7-C1: confirmed βu (Inputs '사람 확정값')
            _vlist(s, r + 1, "βu = 사람 확정값(평가 세션)", "=BetaOverride", "beta", "", "BetaU", bold=True)
        elif d["engine"].get("beta_src", "peer") == "peer":
            _vlist(s, r + 1, "βu 중앙값(기본)", f"=MEDIAN({a1(r0, 11)}:{a1(r1, 11)})", "beta", "", "BetaU", bold=True)
        else:  # P7-B5 beta fallback: no peer βu (Inputs BetaFallback)
            _vlist(
                s,
                r + 1,
                "βu(피어 βu 없음 → 대체값)",
                f"=IF(COUNT({a1(r0, 11)}:{a1(r1, 11)})=0,BetaFallback,MEDIAN({a1(r0, 11)}:{a1(r1, 11)}))",
                "beta",
                "",
                "BetaU",
                bold=True,
            )
        _vlist(s, r + 2, "R² 중앙값(포함 피어)", f"=MEDIAN({a1(r0, 12)}:{a1(r1, 12)})", "beta", "", "BetaR2Median")
    s.text(r + 3, 0, "베타 신뢰성 경고", "bold")
    warn = '=IF(BetaR2Median<BetaR2Warn,"경고: 회귀 베타 신뢰 낮음(R² 중앙값 "&TEXT(BetaR2Median,"0.00")&" < "&TEXT(BetaR2Warn,"0.00")&")","경고 없음")'
    if d.get("public"):  # P7-X2a: the R² median of fewer than 5 peers is a text in the public mode
        warn = f'=IF(ISNUMBER(BetaR2Median),{warn[1:]},"공개 모드: 피어 부족 — R² 중앙값 표시 안 함")'
    s.fx(r + 3, 2, warn, "gen", name="BetaWarn")
    s.text(r + 3, 3, "표시만(경로 불변, common_rules)", "note")
    s.text(r + 1, 3, "엔진 βu 중앙값", "note")
    s.eng(r + 1, 4, d["engine"]["beta_u"], "beta")
    s.engine_range(r + 1, 4, r + 1, 4)
    c.layout["beta_u_engine"] = f"WACC!{a1(r + 1, 4, True)}"
    r += 5
    if d["de"]["rule"] == "points":  # own average D/E (company_dcf: mean of the balance-sheet-date points)
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
        if (d.get("overrides") or {}).get("de") is not None:  # P7-C1: confirmed D/E
            _vlist(s, re_ + 1, "목표 D/E = 사람 확정값(평가 세션, 위 평균은 자동값)", "=DeOverride", "ratio", "배", "DE_Target")
        else:
            _vlist(s, re_ + 1, "목표 D/E(평균)", f"=AVERAGE({a1(r + 2, 4)}:{a1(re_, 4)})", "ratio", "배", "DE_Target")
        r = re_ + 3
    s.text(r, 0, "할인율 (선택한 SRP)", "subtitle")
    r += 1
    rows_w = [
        (
            "Rf(Inputs 'Rf 만기 선택', 데이터 표 입력 칸이 비면)",
            "=IF(ISNUMBER(RfOvr),RfOvr,IF(RfTenor=10,Rf_10Y,Rf_5Y))",
            "pct3",
            "",
            "Rf",
        ),
        ("MRP(데이터 표 입력 칸이 비면 Inputs 값)", "=IF(ISNUMBER(MrpOvr),MrpOvr,MRP)", "pct", "", "MRP_Eff"),
        ("SRP(데이터 표 입력 칸이 비면 선택 값)", "=IF(ISNUMBER(SrpOvr),SrpOvr,SRP_Sel)", "pct", "", "SRP_Eff"),
        ("βu", "=BetaU", "beta", "", None),
        ("목표 D/E", "=DE_Target", "ratio", "배", None),
        ("βL = βu × (1 + (1 − t) × D/E)", "=BetaU*(1+(1-T_Hamada)*DE_Target)", "beta", "", "BetaL"),
        ("Ke = Rf + βL × MRP + SRP", "=Rf+BetaL*MRP_Eff+SRP_Eff", "pct3", "", "Ke"),
    ]
    for i, (lab, f, kind, unit, nm) in enumerate(rows_w):
        _vlist(s, r + i, lab, f, kind, unit, nm)
    r += len(rows_w)
    R, n = c.layout["fc_rows"], c.layout["n"]
    ebit_rng, year_rng = _row_range("Forecast", R["ebit"], n), _row_range("Forecast", R["year"], n)
    if d["kd_tax_base"] == "ltm_pretax":
        _vlist(s, r, "한계세율 기준: 연결 LTM 세전이익", "=PretaxLTM", "mn", "백만원", "EbitEnd", "company_dcf.discount_rate")
    else:
        _vlist(
            s,
            r,
            "한계세율 기준: 명시 마지막 연도 EBIT",
            f"=INDEX({ebit_rng},MATCH(ExplicitEnd,{year_rng},0))",
            "mn",
            "백만원",
            "EbitEnd",
            "rf_dcf2.value",
        )
    _vlist(s, r + 1, "한계세율(세후 Kd)", '=INDEX(TaxRate,COUNTIF(TaxTo,"<"&EbitEnd)+1)', "pct1", "%", "T_Kd")
    implied = d.get("kd_method") == "implied"  # P7-B draft: no rating found -> interest ÷ average debt (Inputs 표 5)
    _vlist(
        s,
        r + 2,
        "이자비용 ÷ 평균 차입금(Inputs 표 5)" if implied else "실제 가중 약정이자율(Inputs 표 5)",
        "=IF(SUM(BorrowAmt)>0,SUMPRODUCT(BorrowRate,BorrowAmt)/SUM(BorrowAmt),0)",
        "pct3",
        "%",
        "Kd_Actual",
        "등급 미확인 → 규칙 Kd(하한 Rf 전)로 쓴다" if implied else "등급 A+~BBB+일 때만 규칙에 쓰인다",
    )
    if implied:
        s.fx(r + 2, 4, '="사용(등급 미확인 → 이자비용 ÷ 평균 차입금)"', "gen", name="KdActualUse")
    else:
        s.fx(
            r + 2,
            4,
            '=IF(OR(RatingIdx=0,RatingIdx<=MATCH("AA-",RatingScale,0),RatingIdx>MATCH("BBB+",RatingScale,0)),'
            '"미사용(규칙상: "&IF(RatingIdx=0,"무등급 → BBB- 3년","등급 구간 밖")&")","사용")',
            "gen",
            name="KdActualUse",
        )
    _vlist(s, r + 3, "등급 순번(빈칸 = 무등급 0)", '=IF(Rating="",0,MATCH(Rating,RatingScale,0))', "int", "", "RatingIdx")
    _vlist(
        s,
        r + 4,
        "규칙 Kd(하한 전)",
        "=N(Kd_Actual)"
        if implied
        else (
            '=IF(RatingIdx=0,Kd_BBB,IF(RatingIdx<=MATCH("AA-",RatingScale,0),Kd_AA,'
            'IF(RatingIdx<=MATCH("BBB+",RatingScale,0),MAX(N(Kd_Actual),Kd_AA),Kd_BBB)))'
        ),
        "pct3",
        "%",
    )
    if (d.get("overrides") or {}).get("kd") is not None:  # P7-C1: confirmed Kd (no Rf floor)
        _vlist(s, r + 5, "세전 Kd = 사람 확정값(평가 세션)", "=KdOverride", "pct3", "%", "Kd_Pre")
    else:
        _vlist(s, r + 5, "세전 Kd = max(규칙 Kd, Rf)", f"=MAX({a1(r + 4, 2)},Rf)", "pct3", "%", "Kd_Pre")
    _vlist(s, r + 6, "세후 Kd", "=Kd_Pre*(1-T_Kd)", "pct3", "%", "Kd_AT")
    s.fx(
        r + 6,
        4,
        '=IF(DE_Target=0,"미사용(D/E 0 → WACC에 Kd 반영 안 됨)","사용(D/V "&TEXT(DE_Target/(1+DE_Target),"0.0%")&")")',
        "gen",
        name="KdUse",
    )
    _vlist(s, r + 7, "D/V = D/E ÷ (1 + D/E)", "=DE_Target/(1+DE_Target)", "pct", "%", "WD")
    _vlist(s, r + 8, "WACC(계산) = E/V × Ke + D/V × Kd × (1 − t)", "=(1-WD)*Ke+WD*Kd_AT", "pct3", "%", "WaccCalc")
    _vlist(
        s,
        r + 9,
        "WACC(모델 사용, 데이터 표 입력 칸이 비면 계산값)",
        "=IF(ISNUMBER(WaccOvr),WaccOvr,WaccCalc)",
        "pct3",
        "%",
        "WACC",
        "Scenarios 시트 WACC × g 데이터 표가 WaccOvr 칸에 값을 넣어 계산",
        bold=True,
    )
    s.text(
        r + 10,
        0,
        # P7-X2b X8: an auto draft without a rating uses the implied rate (config/p7b.yaml draft.kd), not the rating bands
        "Kd 규칙(자동 초안, 등급 미확인): 이자비용(없으면 이자의 지급) ÷ 평균(차입금 + 리스부채, 전기말·당기말), 하한 Rf / "
        "계산 불가(이자 없음·평균 차입 ≤ 0)면 무등급 → BBB- 3년"
        if d["meta"].get("draft") and d.get("kd_method") == "implied"
        else "Kd 규칙(공통 규칙, 위 순서): 무등급 → BBB- 3년 / AA- 이상 → AA- 3년 / A+~BBB+ → max(실제 가중, AA- 3년) / BBB 이하 → BBB- 3년, 하한 Rf",
        "note",
    )
    r += 12
    s.text(r, 0, "SRP 열별 WACC(같은 βu·D/E)", "subtitle")
    for i in range(len(d["rates"]["srp_list"])):
        _vlist(s, r + 1 + i, f"SRP 열 {i + 1}", f"=(1-WD)*(Rf+BetaL*MRP+SRP_{i + 1})+WD*Kd_AT", "pct3", "%")


# ---------------------------------------------------------------- DCF

DCF_ROWS = [
    ("label", "기간", "", "gen"),
    ("year", "연도", "", "year"),
    ("f", "기간 비율", "", "ratio"),
    ("end", "종료일", "", "date"),
    ("fcff", "FCFF", "백만원", "mn"),
    ("t_end", "기간 말까지 연수(할인 기준일부터)", "년", "ratio"),
    ("t", "할인 연수(mid-year면 기간 중앙)", "년", "ratio"),
    ("df", "할인계수 (1 + WACC)^−t", "", "ratio"),
    ("pv", "현재가치(6/30)", "백만원", "mn"),
]


def dcf_sheet(c: Ctx):
    d, s = c.d, c.sheet("DCF")
    n = c.layout["n"]
    F = c.layout["fc_rows"]
    s.widths({0: 42, 1: 9, 2: 14, 3: 40, **{C_FIRST + j: 12 for j in range(1, n)}})
    s.ws.set_column(C_FIRST, C_FIRST, 14)
    s.text(0, 0, "DCF — 할인·영구가치·EV (선택한 시나리오·SRP)", "title")
    bs_, ao_ = d["meta"]["bs_date"][5:].replace("-", "/").lstrip("0"), d["meta"]["as_of"][5:].replace("-", "/").lstrip("0")
    s.text(
        1,
        0,
        f"할인 기준일 {bs_}(재무상태표) → mid-year 할인 → EV를 평가기준일 {ao_}로 이월. 순현금은 {bs_} 장부(이월 안 함)",
        "note",
    )
    top = 3
    R = {k: top + i for i, (k, *_r) in enumerate(DCF_ROWS)}
    for k, lab, unit, _kind in DCF_ROWS:
        s.text(R[k], 0, lab)
        if unit:
            s.text(R[k], 1, unit, "note")
    lab_row = F["k"] - 1
    for j in range(C_FIRST, C_FIRST + n):
        X = lambda k: a1(R[k], j)  # noqa: E731, B023
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
        (
            "e26",
            f"FY{d['meta']['ltm_year']} EBIT(정상 = FY{d['meta']['ltm_year']} 매출 × 정상 이익률)",
            f"=Forecast!{a1(F['rev_fy'], C_FIRST)}*Margin_Sel",
            "mn",
            None,
            "",
        ),
        ("n26n", f"  NOPAT FY{d['meta']['ltm_year']} (normal 규칙)", None, "mn", None, ""),
        (
            "fy26",
            f"FY{d['meta']['ltm_year']} EBIT(혼합 = 1H 실적 + 2H 정상)",
            f"=Forecast!{a1(F['fy_ebit'], C_FIRST)}",
            "mn",
            None,
            "",
        ),
        ("n26m", f"  NOPAT FY{d['meta']['ltm_year']} (mixed 규칙)", None, "mn", None, ""),
        ("n26", "출발 NOPAT(선택 규칙)", None, "mn", None, "Inputs의 RONIC 출발점 규칙"),
        ("e32", "명시 마지막 연도 EBIT", f"=INDEX({fr('ebit')},{end_idx})", "mn", None, ""),
        ("n32", "  NOPAT", None, "mn", None, ""),
        (
            "reinv",
            "누적 재투자 Σ(CAPEX − D&A + ΔNWC), 2027~명시 끝",
            f"=SUMPRODUCT(({fr('k')}>1)*{fr('explicit')}*({fr('capex')}-{fr('dna')}+{fr('dnwc')}))",
            "mn",
            None,
            "",
        ),
        ("rcalc", "증분 ROIC(계산값)", None, "pct", None, ""),
        (
            "ronic",
            "RONIC(적용)",
            None,
            "pct",
            "RONIC",
            "계산값 ≤ 0 또는 ≤ g면 WACC로 대체"
            if d["type"] == "scenario_capex"
            else "재투자 ≤ 0이면 WACC, 그 밖은 [WACC, 과거 3년 ROIC]로 자름(사전 고정)"
            + ("; 과거 ROIC < WACC면 WACC(하한 우선, P7-X2b)" if d["meta"].get("draft") else ""),
        ),
        ("flag", "대체 여부", None, "gen", None, ""),
    ]
    V = {k: r + i for i, (k, *_x) in enumerate(items)}
    A = lambda k: a1(V[k], 2)  # noqa: E731
    fm = {
        "n26n": f"={A('e26')}-{tax_of(A('e26'))}",
        "n26m": f"={A('fy26')}-{tax_of(A('fy26'))}",
        "n26": f'=IF(RonicStart="normal",{A("n26n")},{A("n26m")})',
        "n32": f"={A('e32')}-{tax_of(A('e32'))}",
        "rcalc": f"=IF({A('reinv')}>0,({A('n32')}-{A('n26')})/{A('reinv')},0)",
        "ronic": ronic_formula(d, A("reinv"), A("rcalc"), "WACC", "GEff"),
        "flag": ronic_flag(d, A("reinv"), A("rcalc"), "WACC", "GEff"),
    }
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
        (
            "dnaN",
            "마지막 연도 D&A(명시 끝 D&A × 매출비)" if d["type"] == "scenario_capex" else "마지막 연도 D&A(매출 × D&A/매출)",
            None,
            "mn",
            None,
            "",
        ),
        ("ebitdaN", "마지막 연도 EBITDA", None, "mn", None, ""),
        ("impl", "Gordon 함의 EV/EBITDA(TV ÷ EBITDA)", None, "x", "ImpliedMultiple", ""),
        (
            "exitm",
            "Exit 배수(EV/EBITDA)",
            "=PeerEvEbitdaMed" if d["type"] == "mechanical" else "=ExitMult",
            "x",
            "ExitMult" if d["type"] == "mechanical" else None,
            "피어 EV/EBITDA 중앙값(병행 표시용, 엔진은 Exit 미계산 ⚠️)" if d["type"] == "mechanical" else "Inputs 6절",
        ),
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
    fm2 = {
        "revX": f"={B('revN')}*(1+GEff)",
        "ebitX": f"={B('revX')}*(Margin_Sel+MarginConvAmt)" if d.get("v2") else f"={B('revX')}*Margin_Sel",
        "nopX": f"={B('ebitX')}-{tax_of(B('ebitX'))}",
        "fcfX": f"={B('nopX')}*(1-GEff/RONIC)",
        "tv": f"={B('fcfX')}/(WACC-GEff)*{mid}",
        "pvtv": f"={B('tv')}*(1+WACC)^(-{B('tN')})",
        "ev630": f"={B('pvsum')}+{B('pvtv')}",
        "ev930": f"={B('ev630')}*(1+WACC)^({B('days')}/DaysYr)",
        "tvshare": f"={B('pvtv')}/{B('ev630')}",
        "dnaN": f"={B('dnaE')}*{B('revN')}/{B('revE')}" if d["type"] == "scenario_capex" else f"={B('revN')}*DnaRatio",
        "ebitdaN": f"={B('ebitN')}+{B('dnaN')}",
        "impl": f'=IF({B("ebitdaN")}>0,{B("tv")}/{B("ebitdaN")},"N/M")',
        "tvx": f"={B('exitm')}*{B('ebitdaN')}",
        "pvx": f"={B('tvx')}*(1+WACC)^(-{B('tN')})",
        "evx630": f"={B('pvsum')}+{B('pvx')}",
        "evx930": f"={B('evx630')}*(1+WACC)^({B('days')}/DaysYr)",
        "tvsx": f"={B('pvx')}/{B('evx630')}",
        "gimp": f"=({B('tvx')}/{mid}*WACC-{B('fcfX')}/(1+GEff))/({B('tvx')}/{mid}+{B('fcfX')}/(1+GEff))",
    }
    if d.get("public"):  # P7-X2a: the peer EV/EBITDA median may be hidden (few peers) -> the Exit rows are N/M
        for k in ("tvx", "pvx", "evx630", "evx930", "tvsx", "gimp"):
            fm2[k] = nm_unless_number(fm2[k], B("exitm"))
    for k, lab, f, kind, nm, note in items2:
        _vlist(s, V2[k], lab, f or fm2[k], kind, "백만원" if kind == "mn" else "", nm, note, bold=k in ("ev930", "tv"))
    c.layout["dcf_vals"] = {**V, **V2}
    r = max(V2.values()) + 2
    s.text(r, 0, "영구가치 교차 확인 (Gordon vs Exit, 같은 명시·체감 현금흐름)", "subtitle")
    for j, h in enumerate(["방식", "", "주당(원)", "EV/EBITDA(배)", "영구성장률", "영구가치 비중"]):
        s.text(r + 1, j, h, "header")
    rows_x = [
        ("Gordon(가치동인)", "=PerShare", "=ImpliedMultiple", "=GEff", "=TVShare"),
        ("Exit(배수)", "=PerShareExit", "=ExitMult", "=ImpliedG_Exit", "=TVShare_Exit"),
    ]
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
    s.widths({0: 46, 1: 9, 2: 15, 3: 50, **{C_FIRST + j: 12 for j in range(1, 8)}})
    s.ws.set_column(C_FIRST, C_FIRST, 15)
    s.text(0, 0, "Bridge — EV → 주식가치 → 주당 (SOTP)", "title")
    s.text(
        1,
        0,
        "SOTP = 모회사 사업 EV(DCF) + 상장 종속회사 지분 × 시가총액 + 모회사 순현금(리스부채 포함 차입금 차감) + 비영업자산 − 본사 공통비",
        "note",
    )
    r = 3
    rows = [
        ("ev", "모회사 사업 EV(평가기준일)", "=EV_930", "mn", None, "DCF 시트"),
        (
            "stake_v",
            f"{sub} 지분가치 = 지분율 × 시가총액",
            "=Stake*SubMC",
            "mn",
            "StakeValue",
            "기준일 시가총액(한국거래소 통계정보)",
        ),
        ("cash", "모회사 현금및현금성자산", f"={o('cash')}", "mn", None, "2026-06-30 별도(정부보조금 차감 순액)"),
        ("stf", "모회사 단기금융자산", f"={o('short_term_fin')}", "mn", None, "CP·전단채·금융채·MMF형 → 현금성"),
        ("debt_api", "모회사 차입금(API 표준 계정)", f"={o('total_debt')}", "mn", None, ""),
        ("debt_fix", "모회사 장기차입금 보정", "=LTB_Override", "mn", None, "API 계정 오표기(Inputs 5)"),
        ("debt", "모회사 총차입금", None, "mn", None, ""),
        ("lease", "모회사 리스부채(IFRS 16)", f"={o('lease_liabilities')}", "mn", None, "WACC D/E와 일관되게 차입금 취급"),
        ("netcash", "모회사 순현금 = 현금 + 단기금융 − 차입금 − 리스", None, "mn", "ParentNetCash", ""),
        (
            "nonop",
            "모회사 비영업자산(장기금융자산)",
            f"={o('long_term_fin')}",
            "mn",
            "ParentNonOp",
            "상각후원가·FVPL·FVOCI 장부 = 공정가치",
        ),
        ("hq", "본사 미배분 공통비 PV(차감)", "=-HQ_PV", "mn", None, ""),
        ("equity", "주식가치(SOTP)", None, "mn", "Equity", ""),
        ("adj", "  EV 밖 항목 합계(시나리오·SRP와 무관)", None, "mn", "BridgeAdj", "Scen_Calc가 같은 값을 쓴다"),
        (
            "eqadd",
            "  지분 방식 배수(PER·PBR)에 더할 항목 = 종속회사 지분 시가",
            "=StakeValue",
            "mn",
            "EqAddOn",
            "p3c1.sotp_from_multiple",
        ),
        (
            "shares",
            "유통주식수 = (보통주 + 우선주) − 자기주식",
            "=(CommonIssued-CommonTreasury)+(PrefIssued-PrefTreasury)",
            "int",
            "Shares",
            "",
        ),
        ("ps", "주당 가치(원, Gordon)", None, "won", "PerShare", "가정 하의 추정 내재가치(예시)"),
        ("vs", "기준일 종가 대비", "=PerShare/Close-1", "pct1", None, ""),
        ("eqx", "주식가치(Exit 영구가치)", None, "mn", None, ""),
        ("psx", "주당 가치(원, Exit)", None, "won", "PerShareExit", ""),
        ("inv", "참고: 종속기업투자(별도 장부) — 더하지 않음", "=InvSubsBook", "mn", None, "지분은 시가로 한 번만 센다"),
        (
            "nav",
            "참고: 순자산가치(연결 지배주주지분 장부, 주당 원)",
            f"={fs[('CFS', h1, 'equity_parent')]}*MnToWon/Shares",
            "won",
            "NavPerShare",
            "자산가치 접근(재평가 없음, 장부 그대로) — 03 문서 3-2",
        ),
    ]
    V = {kk: r + i for i, (kk, *_x) in enumerate(rows)}
    A = lambda kk: a1(V[kk], 2)  # noqa: E731
    fm = {
        "debt": f"={A('debt_api')}+{A('debt_fix')}",
        "netcash": f"={A('cash')}+{A('stf')}-{A('debt')}-{A('lease')}",
        "equity": f"={A('ev')}+{A('stake_v')}+{A('netcash')}+{A('nonop')}+{A('hq')}",
        "adj": f"={A('equity')}-{A('ev')}",
        "ps": f"={A('equity')}*MnToWon/Shares",
        "eqx": "=EVExit_930+BridgeAdj",
        "psx": f"={A('eqx')}*MnToWon/Shares",
    }
    if d.get("public"):  # P7-X2a: Exit value N/M when the peer EV/EBITDA median is hidden
        fm["eqx"] = nm_unless_number(fm["eqx"], "EVExit_930")
        fm["psx"] = nm_unless_number(fm["psx"], A("eqx"))
    for kk, lab, f, kind, nm, note in rows:
        _vlist(
            s,
            V[kk],
            lab,
            f or fm[kk],
            kind,
            "원" if kind == "won" else ("주" if kind == "int" else ("백만원" if kind == "mn" else "")),
            nm,
            note,
            bold=kk in ("equity", "ps"),
        )
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
    fm2 = {
        "nci_sh": f"={B('nci_mv')}/TargetMC",
        "mgap": f"=ABS({B('pm')}-{B('sm')})",
        "ggap": f"=ABS({B('pg')}-{B('sg')})",
        "dec": (
            f"=IF(OR({B('nci_sh')}>=NciShareMin,AND(ListedSub=1,OR({B('mgap')}>=MarginGapMin,{B('ggap')}>=GrowthGapMin))),"
            f'"sotp","consolidated")'
        ),
    }
    for kk, lab, f, kind in rows2:
        _vlist(
            s,
            V2[kk],
            lab,
            f or fm2[kk],
            kind,
            "백만원" if kind == "mn" else "",
            "StructureRule" if kk == "dec" else None,
            bold=kk == "dec",
        )
    s.text(V2["dec"], 3, "비지배 ≥ 10% 또는 (상장 종속회사 + 이익률 차이 ≥ 5%p 또는 성장률 차이 ≥ 10%p) → SOTP", "note")
    r = V2["dec"] + 2

    # ---- consolidated cross-check: parent DCF + subsidiary simple DCF − consolidated net debt + non-op − NCI market
    s.text(r, 0, f"교차 확인 — 연결 DCF − 비지배 시가 ({sub} 단순 DCF, 같은 WACC)", "subtitle")
    r += 1
    F, D = c.layout["fc_rows"], c.layout["dcf_rows"]
    ne = 1 + (d["dcf"]["explicit_end"] - int(d["meta"]["cf_start"][:4]))  # explicit periods (2H26..2032)
    sub_rows = [
        ("label", "기간", "gen"),
        ("k", "기간 순번", "int"),
        ("year", "연도", "year"),
        ("f", "기간 비율", "ratio"),
        ("rev_fy", "회계연도 매출", "mn"),
        ("rev", "기간 매출", "mn"),
        ("ebit", "영업이익", "mn"),
        ("fy_ebit", "회계연도 영업이익", "mn"),
        ("dna", "D&A = 매출 × LTM 감가상각비율", "mn"),
        ("capex", "CAPEX = D&A × 배수", "mn"),
        ("dnwc", "ΔNWC", "mn"),
        ("tax_rate", "실효세율", "pct"),
        ("tax", "법인세", "mn"),
        ("fcff", "FCFF", "mn"),
        ("t", "할인 연수", "ratio"),
        ("df", "할인계수", "ratio"),
        ("pv", "현재가치", "mn"),
    ]
    S = {kk: r + i for i, (kk, *_x) in enumerate(sub_rows)}
    for kk, lab, _kind in sub_rows:
        s.text(S[kk], 0, lab)
    scal = S["pv"] + 2
    sv = {"rev2h": scal, "da": scal + 1, "nwc0": scal + 2}
    _vlist(
        s,
        sv["rev2h"],
        f"{sub} 2H26 매출 = (FY2025 − 1H25) × (1 + g)",
        f"=({seg[('sub', 'revenue', 'FY2025')]}-{seg[('sub', 'revenue', '1H25')]})*(1+SubG)",
        "mn",
        "백만원",
    )
    _vlist(s, sv["da"], "LTM 감가상각비 ÷ LTM 매출(부문)", f"=({ltm('sub', 'depreciation')})/({ltm('sub', 'revenue')})", "pct")
    _vlist(
        s,
        sv["nwc0"],
        f"{sub} 순운전자본(연결 − 모회사, 6/30)",
        f"=({k('receivables')}+{k('inventories')}-{k('trade_payables')}-{k('contract_liabilities')})-NWC_Open",
        "mn",
        "백만원",
    )
    Z = lambda kk: a1(sv[kk], 2)  # noqa: E731
    for i in range(ne):
        j = C_FIRST + i
        X = lambda kk: a1(S[kk], j)  # noqa: E731, B023
        Wp = lambda kk: a1(S[kk], j - 1)  # noqa: E731, B023
        fmap = {
            "label": f"=Forecast!{a1(F['k'] - 1, j)}",
            "k": f"=Forecast!{a1(F['k'], j)}",
            "year": f"=Forecast!{a1(F['year'], j)}",
            "f": f"=Forecast!{a1(F['f'], j)}",
            "rev_fy": f"=IF({X('k')}=1,{seg[('sub', 'revenue', '1H26')]}+{Z('rev2h')},{Wp('rev_fy')}*(1+SubG))",
            "rev": f"=IF({X('k')}=1,{Z('rev2h')},{X('rev_fy')})",
            "ebit": f"={X('rev')}*SubM",
            "fy_ebit": f"=IF({X('k')}=1,{seg[('sub', 'op', '1H26')]}+{X('ebit')},{X('ebit')})",
            "dna": f"={X('rev')}*{Z('da')}",
            "capex": f"={X('dna')}*SubCapexDna",
            "dnwc": f"=IF({X('k')}=1,{Z('nwc0')}*SubG*SubHalf,{Z('nwc0')}*(1+SubG)^({X('year')}-YEAR(CfStart))*SubG)",
            "tax_rate": f"={eff_of(X('fy_ebit'))}",
            "tax": f"=MAX({X('ebit')},0)*{X('tax_rate')}",
            "fcff": f"={X('ebit')}-{X('tax')}+{X('dna')}-{X('capex')}-{X('dnwc')}",
            "t": f"=DCF!{a1(D['t'], j)}",
            "df": f"=(1+WACC)^(-{X('t')})",
            "pv": f"={X('fcff')}*{X('df')}",
        }
        for kk, _lab, kind in sub_rows:
            s.fx(S[kk], j, fmap[kk], kind)
    le = C_FIRST + ne - 1
    r = sv["nwc0"] + 1
    mid = "IF(MidYear=1,(1+WACC)^0.5,1)"
    rows3 = [
        ("fcfn", "정규화 FCF(마지막 연도 FCFF ÷ 기간 비율)", f"={a1(S['fcff'], le)}/{a1(S['f'], le)}", "mn"),
        ("tv", "영구가치(Gordon)", None, "mn"),
        ("pvtv", "영구가치 현재가치", None, "mn"),
        ("ev630", f"{sub} EV(6/30)", None, "mn"),
        ("ev930", f"{sub} EV(평가기준일)", None, "mn"),
        (
            "cnd",
            "연결 순차입금(6/30) = 차입금 + 리스 − 현금 − 단기금융",
            f"={k('total_debt')}+{k('lease_liabilities')}-{k('cash')}-{k('short_term_fin')}",
            "mn",
        ),
        ("cltf", "연결 비영업자산(장기금융자산)", f"={k('long_term_fin')}", "mn"),
        ("ncimv", "비지배지분 시가", "=(1-Stake)*SubMC", "mn"),
        ("ceq", "연결 주식가치 = (모회사 EV + 종속 EV) − 순차입금 + 비영업 − 비지배 시가", None, "mn"),
        ("cps", "연결 교차 확인 주당(원)", None, "won"),
        ("diff", "SOTP − 연결(주당, 원)", None, "won"),
        (
            "subnc",
            f"{sub} 순현금(연결 − 모회사)",
            f"=({k('cash')}+{k('short_term_fin')}-{k('total_debt')}-{k('lease_liabilities')})-ParentNetCash",
            "mn",
        ),
        ("subno", f"{sub} 비영업(연결 − 모회사)", f"={k('long_term_fin')}-ParentNonOp", "mn"),
        ("subint", f"{sub} 내재 주식가치(EV + 순현금 + 비영업)", None, "mn"),
        ("gap", "  시가총액 − 내재가치(100%, 차이의 주원인)", None, "mn"),
        ("bookps", "참고: 비지배 장부가 차감 시 주당(원)", None, "won"),
    ]
    V3 = {kk: r + i for i, (kk, *_x) in enumerate(rows3)}
    C3 = lambda kk: a1(V3[kk], 2)  # noqa: E731
    fm3 = {
        "tv": f"={C3('fcfn')}*(1+SubGT)/(WACC-SubGT)*{mid}",
        "pvtv": f"={C3('tv')}*(1+WACC)^(-DCF!{a1(D['t_end'], le)})",
        "ev630": f"=SUM({a1(S['pv'], C_FIRST)}:{a1(S['pv'], le)})+{C3('pvtv')}",
        "ev930": f"={C3('ev630')}*(1+WACC)^((ValDate-DiscDate)/DaysYr)",
        "ceq": f"=EV_930+{C3('ev930')}-{C3('cnd')}+{C3('cltf')}-{C3('ncimv')}",
        "cps": f"={C3('ceq')}*MnToWon/Shares",
        "diff": f"=PerShare-{C3('cps')}",
        "subint": f"={C3('ev930')}+{C3('subnc')}+{C3('subno')}",
        "gap": f"=SubMC-{C3('subint')}",
        "bookps": f"=(EV_930+{C3('ev930')}-{C3('cnd')}+{C3('cltf')}-{k('nci')})*MnToWon/Shares",
    }
    for kk, lab, f, kind in rows3:
        _vlist(
            s,
            V3[kk],
            lab,
            f or fm3[kk],
            kind,
            "원" if kind == "won" else "백만원",
            "CrossPerShare" if kk == "cps" else None,
            bold=kk == "cps",
        )
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
        return (
            "=(Close*(CommonIssued-CommonTreasury)+SUMPRODUCT(PrefClose,PrefListed)"
            "+Close*MAX(PrefIssued-PrefTreasury-SUM(PrefListed),0))/MnToWon"
        )
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
    s.text(
        1,
        0,
        "주식가치 = EV − 순차입금(차입금 + 리스부채 − 현금성) + 비영업자산 − 비지배지분(장부). 현금성·비영업은 FS_Hist 줄 분류(peer_p3 규칙)",
        "note",
    )
    r = 3
    aff = bool(d.get("affiliate"))
    rows = [
        ("ev", "EV(평가기준일)", "=EV_930", "mn", None, "DCF 시트"),
        ("debt", "총차입금(차입금·사채)", f"={k('total_debt')}", "mn", None, f"{d['meta']['bs_date']} 연결"),
        ("lease", "리스부채(IFRS 16)", f"={k('lease_liabilities')}", "mn", None, "WACC D/E와 같은 정의"),
        (
            "cash",
            "현금성(유동 금융자산 줄 합계)"
            + (" − 사람 확정 영업용 현금" if (d.get("overrides") or {}).get("cash_adjust_mn") is not None else ""),
            '=SUMIFS(BsAmt,BsClass,"cash_like")'
            + ("-CashAdjust" if (d.get("overrides") or {}).get("cash_adjust_mn") is not None else ""),
            "mn",
            None,
            "FS_Hist 분류 cash_like",
        ),
        ("netdebt", "순차입금 = 차입금 + 리스 − 현금성", None, "mn", "NetDebt", ""),
        (
            "nonop",
            "비영업자산(비유동 금융자산·관계기업 줄 합계)" + (" + SOTP 종속회사 가치" if d.get("sotp") else ""),
            (
                '=SUMIFS(BsAmt,BsClass,"non_operating")+SotpRemainder+SotpListed*(1-SubDiscount)+SotpUnlisted'
                if d.get("sotp")
                else '=SUMIFS(BsAmt,BsClass,"non_operating")'
            )
            + ("+AssocLines+AssocValue-AssocReplaced" if d.get("associates") else ""),  # P7-X2b listed associates
            "mn",
            None,
            "FS_Hist 분류 non_operating" + (" + 아래 SOTP 행(종속 줄은 빼고 바꿔 넣음)" if d.get("sotp") else ""),
        ),
        (
            "other_fin",
            "  참고: '기타금융자산' 줄 합계(유동 + 비유동)",
            '=SUMPRODUCT(ISNUMBER(SEARCH("기타금융자산",BsName))*BsAmt)',
            "mn",
            None,
            "현금성·비영업 안에 포함된 금액",
        ),
    ]
    if d.get("sotp"):  # P7-B3 general SOTP: parent (separate) + subsidiaries, no double count
        rows += [
            (
                "sot_lines",
                "  SOTP: 별도 재무상태표 '종속' 투자 줄(비영업에서 제외)",
                '=SUMIFS(BsAmt,BsClass,"sub_inv")',
                "mn",
                "SotpSubLines",
                "FS_Hist 분류 sub_inv",
            ),
            ("sot_book", "  SOTP: 그중 연결 범위 피투자회사 장부가(출자현황)", "=SUM(SubBook)", "mn", "SotpBook", "Inputs 표 10"),
            ("sot_rem", "  SOTP: 합친 줄의 관계기업 몫 = max(줄 − 장부, 0)", None, "mn", "SotpRemainder", "장부가 유지"),
            (
                "sot_listed",
                "  SOTP: 상장 종속회사 지분 시가 = 보유 주식수 × 종가",
                "=SUMPRODUCT(SubShares,SubClose,SubListedDirect)/MnToWon",
                "mn",
                "SotpListed",
                "직접 보유분만, 한국거래소 통계정보 종가",
            ),
            ("sot_disc", "  SOTP: 상장 지분 할인율", "=SubDiscount", "pct", None, "기본 0%, 민감도 30%·50%"),
            (
                "sot_unl",
                "  SOTP: 비상장 종속회사 장부가",
                "=SUMPRODUCT(SubBook,SubUnlisted)",
                "mn",
                "SotpUnlisted",
                "Inputs 표 10",
            ),
        ]
    if d.get("associates"):  # P7-X2b (config/p7x2b.yaml associates): listed associates at market value
        rows += [
            (
                "as_lines",
                "  상장 관계기업: 관계기업·공동기업·지분법 줄(비영업, 장부)",
                '=SUMIFS(BsAmt,BsClass,"nonop_assoc")',
                "mn",
                "AssocLines",
                "FS_Hist 분류 nonop_assoc",
            ),
            (
                "as_val",
                "  상장 관계기업 지분 시가 × (1 − 할인)",
                "=SUMPRODUCT(AssocShares,AssocClose)/MnToWon*(1-AssocDiscount)",
                "mn",
                "AssocValue",
                "Inputs 표 11, 한국거래소 통계정보 종가",
            ),
            (
                "as_rep",
                "  빼는 장부 = MIN(관계기업 줄, Σ 관계기업 장부)" + (" (줄이 없으면 SOTP 나머지에서)" if d.get("sotp") else ""),
                (
                    "=IF(AssocLines>0,MIN(AssocLines,SUM(AssocBook)),MIN(SotpRemainder,SUM(AssocBook)))"
                    if d.get("sotp")
                    else "=MIN(AssocLines,SUM(AssocBook))"
                ),
                "mn",
                "AssocReplaced",
                "이중 계산 방지(관계기업 장부를 시가로 바꿈)",
            ),
        ]
    if aff:
        rows += [
            ("aff", "  그중 계열사 대여금 등(특수관계자 자금거래 표)", "=SUM(AffLoanItems)", "mn", "AffLoanTotal", "Inputs 표 9"),
            (
                "aff_adj",
                "계열사 대여금 조정 = −(1 − 포함 토글) × 대여금",
                "=-(1-AffLoanIncl)*AffLoanTotal",
                "mn",
                None,
                "토글 1(기본) = 0 → 엔진과 같음",
            ),
        ]
    rows += [
        (
            ("nci", "비지배지분 = 사람 확정값(평가 세션)", "=NciOverride", "mn", None, "Inputs '사람 확정값'")
            if (d.get("overrides") or {}).get("nci_mn") is not None
            else ("nci", "비지배지분(장부)", f"={k('nci')}", "mn", None, "상장 종속회사 없음 → 장부")
        ),
        ("equity", "주식가치", None, "mn", "Equity", ""),
        ("adj", "  EV 밖 항목 합계(시나리오·SRP와 무관)", None, "mn", "BridgeAdj", "Scen_Calc·Peers가 같은 값을 쓴다"),
        ("eqadd", "  지분법 방식 배수(PER·PBR)에 더할 항목", "=0", "mn", "EqAddOn", "연결 구조: 없음"),
        (
            "shares",
            "유통주식수 = (보통주 + 우선주) − 자기주식",
            "=(CommonIssued-CommonTreasury)+(PrefIssued-PrefTreasury)",
            "int",
            "Shares",
            "우선주를 보통주와 같은 청구권으로 본다(⚠️)",
        ),
        ("ps", "주당 가치(원, Gordon)", None, "won", "PerShare", "가정 하의 추정 내재가치(예시)"),
        ("vs", "기준일 종가(보통주) 대비", "=PerShare/Close-1", "pct1", None, "가정 차이 표시(판단 아님)"),
        (
            "eqx",
            "주식가치(Exit 영구가치)",
            nm_unless_number("=EVExit_930+BridgeAdj", "EVExit_930") if d.get("public") else "=EVExit_930+BridgeAdj",
            "mn",
            None,
            "",
        ),
        ("psx", "주당 가치(원, Exit)", None, "won", "PerShareExit", ""),
    ]
    if aff:
        rows += [
            (
                "aff_ps",
                "참고: 계열사 대여금 제외 시 주당 영향(원)",
                "=-AffLoanTotal*MnToWon/Shares",
                "won",
                "AffLoanImpact",
                "토글과 무관하게 표시",
            )
        ]
    rows += [
        (
            "nav",
            "참고: 순자산가치(지배주주지분 장부, 없으면 자본총계 − 비지배, 주당 원)",
            f"=IF({k('equity_parent')}<>0,{k('equity_parent')},{k('total_equity')}-{k('nci')})*MnToWon/Shares",
            "won",
            "NavPerShare",
            "자산가치 접근(재평가 없음, 장부 그대로) — 03 문서 3-2",
        )
    ]
    V = {kk: r + i for i, (kk, *_x) in enumerate(rows)}
    A = lambda kk: a1(V[kk], 2)  # noqa: E731
    fm = {
        "netdebt": f"={A('debt')}+{A('lease')}-{A('cash')}",
        **({"sot_rem": f"=MAX({A('sot_lines')}-{A('sot_book')},0)"} if d.get("sotp") else {}),
        "equity": f"={A('ev')}-{A('netdebt')}+{A('nonop')}-{A('nci')}" + (f"+{A('aff_adj')}" if aff else ""),
        "adj": f"={A('equity')}-{A('ev')}",
        "ps": f"={A('equity')}*MnToWon/Shares",
        "psx": f"={A('eqx')}*MnToWon/Shares",
    }
    if d.get("public"):  # P7-X2a: Exit value N/M when the peer EV/EBITDA median is hidden
        fm["psx"] = nm_unless_number(fm["psx"], A("eqx"))
    for kk, lab, f, kind, nm, note in rows:
        _vlist(
            s,
            V[kk],
            lab,
            f or fm[kk],
            kind,
            "원" if kind == "won" else ("주" if kind == "int" else ("백만원" if kind == "mn" else "")),
            nm,
            note,
            bold=kk in ("equity", "ps"),
        )
    c.layout["bridge_vals"] = V
    r = max(V.values()) + 2
    s.text(r, 0, "구조 판단 규칙 (config/valuation_rules.yaml structure)", "subtitle")
    r += 1
    rows2 = [
        ("meq", "시장 주식가치(보통주 + 우선주)", _market_equity(c), "mn"),
        ("nci_v", "비지배지분(상장 종속회사면 시가, 아니면 장부)", f"=IF(ListedSub=1,(1-Stake)*SubMC,{A('nci')})", "mn"),
        ("nci_sh", "비지배지분 ÷ 시장 주식가치", None, "pct1"),
        ("mgap", "부문 이익률 차이", "=SegMarginGap", "pct1"),
        ("ggap", "부문 성장률 차이", "=SegGrowthGap", "pct1"),
        ("dec", "규칙 판정", None, "gen"),
    ]
    V2 = {kk: r + i for i, (kk, *_x) in enumerate(rows2)}
    B = lambda kk: a1(V2[kk], 2)  # noqa: E731
    fm2 = {
        "nci_sh": f"={B('nci_v')}/{B('meq')}",
        "dec": (
            f"=IF(OR({B('nci_sh')}>=NciShareMin,AND(ListedSub=1,OR({B('mgap')}>=MarginGapMin,{B('ggap')}>=GrowthGapMin))),"
            f'"sotp","consolidated")'
        ),
    }
    for kk, lab, f, kind in rows2:
        _vlist(
            s,
            V2[kk],
            lab,
            f or fm2[kk],
            kind,
            "백만원" if kind == "mn" else "",
            "StructureRule" if kk == "dec" else ("MarketEquity" if kk == "meq" else None),
            bold=kk == "dec",
        )
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
        pref = lambda pk: f"Forecast!${pc}${prow[pk] + 1}"  # noqa: E731, B023
        if d["type"] == "mechanical":
            P = {"g0": pref("g0"), "gtx": "GTermCfg", "glast": pref("glast"), "margin": pref("margin"), "gt": "GTermCfg"}
        else:
            gvec = f"Forecast!${pc}${prow['g_2027'] + 1}:${pc}${prow['g_2032'] + 1}"
            P = {
                "rev26": pref("rev_2026"),
                "gvec": gvec,
                "glast": f"INDEX({gvec},ExplicitEnd-YEAR(CfStart))",
                "margin": pref("margin"),
                "gt": pref("g_terminal"),
                "opflag": pref("op_flag"),
                "op26": pref("op_2026"),
            }
        R = forecast_rows(c, s, r + 1, P, main=False)
        rr = R["fcff_pre"] + 2
        rng = lambda key: f"${col(C_FIRST)}${R[key] + 1}:${col(last)}${R[key] + 1}"  # noqa: E731, B023
        end_idx = f"MATCH(ExplicitEnd,{rng('year')},0)"
        mend = f"({P['margin']}+MarginConvAmt)" if d.get("v2") else P["margin"]  # P7-B2b v2: terminal margin = path end
        sc = [
            ("e26", f"FY{d['meta']['ltm_year']} EBIT(정상)", f"={a1(R['rev_fy'], C_FIRST)}*{P['margin']}", "mn"),
            ("fy26", f"FY{d['meta']['ltm_year']} EBIT(혼합)", f"={a1(R['fy_ebit'], C_FIRST)}", "mn"),
            ("n26", "출발 NOPAT(선택 규칙)", None, "mn"),
            ("e32", "명시 마지막 연도 EBIT", f"=INDEX({rng('ebit')},{end_idx})", "mn"),
            ("n32", "  NOPAT", None, "mn"),
            (
                "reinv",
                "누적 재투자",
                f"=SUMPRODUCT(({rng('k')}>1)*{rng('explicit')}*({rng('capex')}-{rng('dna')}+{rng('dnwc')}))",
                "mn",
            ),
            ("rcalc", "증분 ROIC(계산값)", None, "pct"),
            ("tkd", "한계세율(세후 Kd)", None, "pct1"),
            ("revN", "마지막 연도 매출", f"=${col(last)}${R['rev'] + 1}", "mn"),
            ("nopX", "다음 해 NOPAT", None, "mn"),
        ]
        V = {kk: rr + i for i, (kk, *_x) in enumerate(sc)}
        A = lambda kk: a1(V[kk], 2)  # noqa: E731, B023
        fm = {
            "n26": f'=IF(RonicStart="normal",{A("e26")}-{tax_of(A("e26"))},{A("fy26")}-{tax_of(A("fy26"))})',
            "n32": f"={A('e32')}-{tax_of(A('e32'))}",
            "rcalc": f"=IF({A('reinv')}>0,({A('n32')}-{A('n26')})/{A('reinv')},0)",
            "tkd": "=T_Kd" if d["kd_tax_base"] == "ltm_pretax" else f'=INDEX(TaxRate,COUNTIF(TaxTo,"<"&{A("e32")})+1)',
            "nopX": f"=({A('revN')}*(1+{P['gt']})*{mend})-{tax_of('(' + A('revN') + '*(1+' + P['gt'] + ')*' + mend + ')')}",
        }
        for kk, lab, f, kind in sc:
            _vlist(s, V[kk], lab, f or fm[kk], kind, "백만원" if kind == "mn" else "")
        rr = V["nopX"] + 2
        for jj, _sv in enumerate(srps):
            s.text(rr, 0, f"SRP 열 {jj + 1}", "bold")
            s.fx(rr, 2, f"=SRP_{jj + 1}", "pct")
            w = a1(rr + 1, 2)
            _vlist(s, rr + 1, "WACC", f"=(1-WD)*(Rf+BetaL*MRP+SRP_{jj + 1})+WD*Kd_Pre*(1-{A('tkd')})", "pct3")
            ron = a1(rr + 2, 2)
            _vlist(s, rr + 2, "RONIC(적용)", ronic_formula(d, A("reinv"), A("rcalc"), w, f"({P['gt']})"), "pct")
            s.text(rr + 3, 0, "FCFF")
            s.text(rr + 4, 0, "현재가치")
            for j in range(C_FIRST, last + 1):
                s.fx(
                    rr + 3,
                    j,
                    f"={a1(R['fcff_pre'], j)}-IF({a1(R['explicit'], j)}=1,0,{a1(R['nopat'], j)}*{a1(R['g'], j)}/{ron})",
                    "mn",
                )
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
            out[(k, jj)] = {
                "ps": f"Scen_Calc!{a1(v + 5, 2, True)}",
                "wacc": f"Scen_Calc!{a1(rr + 1, 2, True)}",
                "ronic": f"Scen_Calc!{a1(rr + 2, 2, True)}",
                "tv": f"Scen_Calc!{a1(v + 6, 2, True)}",
                "ev": f"Scen_Calc!{a1(v + 3, 2, True)}",
            }
            rr = v + 8
        r = rr + 1
    c.layout["scen_cells"] = out
