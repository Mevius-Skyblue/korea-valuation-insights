"""Shared pieces of the calculation sheets (split out of sheets_calc.py in P7-C4): the Forecast sheet's row layout and the
formula snippets that more than one sheet writes (tax, effective tax, RONIC rule, number of periods, a labelled value row).
"""

from __future__ import annotations

from src.excel.writer import col

C_OPEN, C_FIRST = 2, 3  # opening column C, first period column D


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
        return (
            f'=IF({reinv}<=0,"재투자 ≤ 0 → WACC",IF({rc}<{w},"계산값 < WACC → 하한",'
            f'IF({rc}>RonicCap,"계산값 > 상한(과거 ROIC)","계산값 사용")))'
        )
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


FC_ROWS = [  # key, label, unit, kind
    ("k", "기간 순번", "", "int"),
    ("year", "연도", "", "year"),
    ("stage", "구간", "", "gen"),
    ("start", "시작일", "", "date"),
    ("end", "종료일", "", "date"),
    ("f", "기간 비율(일수 ÷ 365)", "", "ratio"),
    ("explicit", "명시 구간(1/0)", "", "int"),
    ("g", "매출 성장률", "%", "pct"),
    ("rev_fy", "회계연도 매출", "백만원", "mn"),
    ("rev", "기간 매출", "백만원", "mn"),
    ("ebit", "영업이익(EBIT)", "백만원", "mn"),
    ("fy_ebit", "회계연도 영업이익(과세표준)", "백만원", "mn"),
    ("maint", "유지 CAPEX", "백만원", "mn"),
    ("cum_maint", "기초 누적 유지 CAPEX", "백만원", "mn"),
    ("dep_m", "유지 CAPEX 상각", "백만원", "mn"),
    ("dep_b", "신규 공장 상각", "백만원", "mn"),
    ("dep_old", "기존 자산 D&A(FY2025 수준)", "백만원", "mn"),
    ("dna", "D&A 합계", "백만원", "mn"),
    ("gcapex", "성장 CAPEX(시설자금)", "백만원", "mn"),
    ("capex", "CAPEX 합계", "백만원", "mn"),
    ("nwc", "순운전자본(기말)", "백만원", "mn"),
    ("dnwc", "ΔNWC(증가 = 유출)", "백만원", "mn"),
    ("tax_rate", "실효세율(누진, 회계연도 과세표준)", "%", "pct"),
    ("tax", "법인세", "백만원", "mn"),
    ("nopat", "NOPAT", "백만원", "mn"),
]


FC_ROWS_MECH = [r for r in FC_ROWS if r[0] not in ("maint", "cum_maint", "dep_m", "dep_b", "dep_old", "gcapex")]


FC_ROWS_MECH = [
    (k, "D&A = 매출 × 과거 3년 D&A/매출", u, kd)
    if k == "dna"
    else (k, "CAPEX = 매출 × 과거 3년 CAPEX/매출", u, kd)
    if k == "capex"
    else (k, lab, u, kd)
    for k, lab, u, kd in FC_ROWS_MECH
]


FC_TAIL_MAIN = [
    ("reinv_rate", "체감 구간 재투자율 g ÷ RONIC", "%", "pct"),
    ("reinv", "체감 구간 재투자", "백만원", "mn"),
    ("fcff", "FCFF", "백만원", "mn"),
    ("ebitda", "EBITDA", "백만원", "mn"),
]


FC_TAIL_SCEN = [("fcff_pre", "FCFF(체감 재투자 전)", "백만원", "mn")]


ACC_KO = {"revenue": "매출", "operating_income": "영업이익"}


def _row_range(sheet: str, row: int, n: int) -> str:
    return f"{sheet}!${col(C_FIRST)}${row + 1}:${col(C_FIRST + n - 1)}${row + 1}"
