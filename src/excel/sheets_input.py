"""Cover, Guide, Inputs and FS_Hist sheets (the only sheets with typed numbers, all in the input style).

Inputs: one row per scalar input (label | value | unit | source | as-of | status | basis), then tables (tax brackets,
rating scale, scenarios, growth CAPEX, peer betas, peer multiples). Key inputs get defined names (Rf, MRP, SRP_Sel ...).
FS_Hist: the historical statement lines the engine uses (separate = OFS for the parent, CFS 2026-06-30 for the
consolidated cross-check) and the segment note, each column with its DART receipt number.
"""

from __future__ import annotations

from datetime import date

from src.excel.context import Ctx
from src.excel.writer import a1
from src.workbench import pubcut

STATUS_NOTE = "상태: ✅ 1차 출처·독립 확인 / 🔸 단일 출처·직접 계산 / ⚠️ 미확인·프로젝트 가정"
KRX = "한국거래소 통계정보"
SCEN_PARAMS = [
    ("rev_2026", "FY2026 매출", "mn"),
    ("g_2027", "2027 성장률", "pct"),
    ("g_2028", "2028 성장률", "pct"),
    ("g_2029", "2029 성장률", "pct"),
    ("g_2030", "2030 성장률", "pct"),
    ("g_2031", "2031 성장률", "pct"),
    ("g_2032", "2032 성장률", "pct"),
    ("margin", "정상 영업이익률", "pct"),
    ("g_terminal", "영구성장률 g", "pct"),
    ("op_flag", "FY2026 영업이익 지정(1=예)", "int"),
    ("op_2026", "FY2026 영업이익(지정 시)", "mn"),
]


def _d(s: str) -> date:
    return date.fromisoformat(s)


class Rows:
    """Running row writer for the Inputs sheet."""

    def __init__(self, c: Ctx, sheet: str, start: int):
        self.c, self.s, self.r = c, c.sheet(sheet), start

    def sec(self, title: str):
        self.r += 1
        self.s.text(self.r, 0, title, "subtitle")
        self.r += 1

    def item(self, key, label, value, kind="gen", unit="", src="", asof="", status="🔸", basis="", name=None, krx=None):
        s, r = self.s, self.r
        s.text(r, 0, label)
        ref = s.inp(r, 1, value, kind, name=name, krx=krx)
        for j, t in enumerate((unit, src, asof, status, basis), start=2):
            if t:
                s.text(r, j, str(t), "wrap" if j in (3, 6) else "label")
        self.c.R[key] = name or ref
        self.r += 1
        return ref


def cover_target(m: dict) -> str:
    """Cover '평가대상': name (market code, corp code). Market = config target.market (P7-D2 D-F6; was a fixed 'KOSDAQ')."""
    return f"{m['name']} ({m.get('market') or '시장 미확인'} {m['stock_code']}, 법인 {m['corp_code']})"


def beta_title(m: dict) -> str:
    """Table B title with the regression index of the config (P7-D2 D-F6; was a fixed 'KOSDAQ 지수')."""
    ix = m.get("beta_index")
    return f"표 B. 피어 베타 회귀 결과 (주간 2년, {f'{ix} 지수' if ix else '지수 미확인'}, 한국거래소 통계정보 기반 계산값 · 시계열 없음)"


def cover(c: Ctx):
    d, s = c.d, c.sheet("Cover")
    m = d["meta"]
    s.widths({0: 3, 1: 28, 2: 70})
    s.text(1, 1, f"{m['name']} ({m['stock_code']}) 주식가치 산정 모델 (자동 생성 초안)", "title")
    s.text(
        2,
        1,
        "자동 생성 초안. 기계적 가치산정 결과이며 전문가 판단을 거친 가치평가(평가보고서)가 아님. 투자 권유 아님",
        "bold",
        font_color="#C00000",
    )
    if d.get("example_label"):  # P7-D public mode with the screen's round example prices
        s.text(3, 1, d["example_label"], "bold", font_color="#C00000")
    rows = [
        ("평가대상", cover_target(m)),
        ("평가기준일", m["as_of"]),
        ("재무 기준일", f"{m['bs_date']} (반기보고서)"),
        ("기준가치", "주당 내재가치 추정(가치산정, 가정 하의 예시). '공정가치'(K-IFRS 1113·자본시장법 공정가액)가 아님"),
        ("평가 전제", (d.get("engagement") or {}).get("premise", "계속기업")),
        ("목적", (d.get("engagement") or {}).get("excel_purpose", "방법론 예시·교육(실제 거래·공시용 아님)")),
        *([("평가자", d["engagement"]["evaluator"])] if (d.get("engagement") or {}).get("evaluator") else []),
        (
            "평가 구조",
            "SOTP: 모회사 DCF + 상장 종속회사 지분 시가 + 모회사 순현금·비영업 (교차 확인: 연결 DCF − 비지배 시가)"
            if m["structure"] == "sotp"
            else "연결 DCF − 비지배지분",
        ),
        ("단위", "백만원(주당 값은 원). 비율은 %"),
        (
            "출처 표시",
            "재무: DART 접수번호 / 금리: ECOS 817Y002 / 시세·시가총액·VWAP·베타: 한국거래소 통계정보(기준일 단일 값·집계만)",
        ),
        ("생성", f"src/excel/build.py ← {d['cfg_label']} (P4, 엔진 형태 {d['type']}). 결과 확인: Checks 시트의 master check"),
    ]
    for i, (k, v) in enumerate(rows):
        s.text(4 + i, 1, k, "bold")
        s.text(4 + i, 2, v, "wrap")
    s.text(16, 1, "현재 선택", "bold")
    s.fx(
        16, 2, '="시나리오: "&ScenSel&" / SRP: "&TEXT(SRP_Sel,"0.0%")&" / 주당 가치(Gordon): "&TEXT(PerShare,"#,##0")&"원"', "gen"
    )
    s.text(17, 1, "master check", "bold")
    s.fx(17, 2, "=MasterCheck", "gen", bold=True)
    s.text(19, 1, "사람이 작성할 칸", "bold")
    for i, t in enumerate(["평가방법 선택 근거", "주요 가정의 합리성", "평가상 한계", "검토자·검토일"]):
        s.text(20 + i, 1, t)
        s.ws.write_blank(20 + i, 2, None, c.book.fmt("input", "gen"))
        c.book.reg.inputs.append(("Cover", a1(20 + i, 2)))


def guide(c: Ctx):
    s = c.sheet("Guide")
    s.widths({0: 3, 1: 16, 2: 95})
    s.text(1, 1, "모델 안내", "title")
    rows = [
        ("시트 지도", ""),
        ("Inputs", "모든 입력값(파란 글씨·노란 바탕). 출처·기준일·상태(✅/🔸/⚠️) 열. 시나리오·SRP·RONIC 규칙 선택 칸이 맨 위"),
        ("FS_Hist", "엔진이 쓴 과거 재무(모회사 별도, 연결 2026-06-30)와 부문 주석, 열마다 DART 접수번호"),
        (
            "Forecast",
            "선택한 시나리오의 2H26~2040 예측: 매출·EBIT·D&A·CAPEX·ΔNWC·누진 세금·NOPAT·FCFF. 2032까지 명시, 2033~2040 체감",
        ),
        ("WACC", "피어 베타(원 β → Blume → Hamada 언레버 → 중앙값) → 리레버 → Ke, Kd 규칙(등급·Rf 하한), WACC, R² 경고"),
        ("DCF", "할인계수(mid-year, 6/30 할인 → 9/30 이월), RONIC, 가치동인 영구가치, EV, 영구가치 비중, 함의 배수, Exit 병행"),
        (
            "Bridge",
            "SOTP(모회사 EV + 종속회사 지분 시가 + 순현금·비영업) → 주당 가치. 구조 판단, 연결 교차 확인"
            if c.d["meta"]["structure"] == "sotp"
            else "연결 EV − 순차입금(리스 포함) + 비영업 − 비지배 → 주당 가치. 계열사 대여금 표시·토글, 구조 판단",
        ),
        ("Peers", "피어 배수 4종(LTM), N/M 처리, 사분위(QUARTILE.INC) → 주당 가치"),
        ("Premium", "시총 백분위와 D6 적용 규칙(method·이유) → 20일 VWAP × (1+프리미엄) 블록 1주당 범위, 상증법 할증 비교"),
        (
            "Scenarios",
            f"시나리오 {len(c.d['excel']['scenarios'])} × SRP 3 표(살아 있는 수식, Scen_Calc), 데이터 표 2개(WACC×g, 성장×이익률, 엑셀 What-If), 역DCF(엔진 값)",
        ),
        ("Scen_Calc", "Scenarios 표를 계산하는 시나리오별 블록(Forecast와 같은 수식, 시나리오 고정)"),
        ("Football", "방법별 주당 범위 그림(수식 셀 참조) + 기준일 종가 선"),
        ("Convergence", "수렴 시험(사전 고정 기준): 엔진 기록 판정(C2 1차, C3)과 살아 있는 모델 재계산"),
        ("Checks", "항목별 check와 master check(전부 OK면 OK). INFO는 엔진 대조(입력을 바꾸면 달라지는 것이 정상)"),
        ("", ""),
        (
            "색 규칙",
            "파란 글씨·노란 바탕 = 입력 / 검정 = 같은 시트 수식 / 초록 = 다른 시트 참조 / 회색 기울임 = 엔진 값(수식 아님)",
        ),
        ("단위", "금액 백만원, 주당 값 원, 비율 %. 열 머리·행 이름에 단위 표시"),
        (
            "시나리오 선택",
            "Inputs의 '시나리오 선택' 칸에서 "
            + "/".join(c.d["excel"]["scenario_labels"][k] for k in c.d["excel"]["scenarios"])
            + " 중 고른다(목록). Forecast·DCF·Bridge가 바뀐다",
        ),
        ("SRP 선택", "Inputs의 'SRP 선택' 칸에서 0%/1%/2% 중 고른다. 표 전체(3 × 3)는 Scenarios 시트에 항상 같이 나온다"),
        (
            "check 읽는 법",
            "Checks 시트: OK = 통과, ERR = 모델 오류(master check가 ERR), WARN = 주의(표본 수 등), INFO = 엔진 값과의 대조",
        ),
        ("생성 시 고정", "기간 열 수(명시 끝 연도·체감 연수)는 생성 시 고정. 바꾸려면 config를 고치고 다시 생성(Checks에 표시)"),
        (
            "데이터 표",
            "WACC×g, 성장×이익률은 엑셀 데이터 표({=TABLE()})다. 입력 칸(WaccOvr 등)은 Scenarios 시트에 있고 비워 둔다. 계산 옵션이 '데이터 표 제외 자동'이면 F9. 역DCF는 엔진 값",
        ),
        (
            "KRX 자료",
            "종가·시가총액·20일 VWAP·베타 회귀 결과·시총 백분위는 기준일 단일 값·집계값만 넣었다(시세 시계열 없음). 출처 한국거래소 통계정보",
        ),
        (
            "Rf 만기 선택(P6-A)",
            "Inputs의 'Rf 만기 선택' 칸: 5 = 국고채 5년(기본, 사전 고정 결과) / 10 = 국고채 10년. 10이면 모델 전체(Ke·Kd 하한)가 10년 값으로 바뀌고 "
            "Checks의 'Rf 10년' 대조가 Scenarios G-2(엔진)와 비교한다. 기본 결과를 바꾸지 않고 보려면 Scenarios G-1 데이터 표",
        ),
        (
            "P5-B 참고값(P6-A)",
            "Forecast 사업계획 검증 옆 달성률 표, Inputs SRP 옆 한공회 인용 표는 스팩 합병 외부평가 의견서 집계(회색, 표시만). 자동 감액·경고 판정 없음",
        ),
    ]
    for i, (k, v) in enumerate(rows):
        s.text(3 + i, 1, k, "bold")
        s.text(3 + i, 2, v, "wrap")


def inputs(c: Ctx):
    d, s = c.d, c.sheet("Inputs")
    cap = d["type"] == "scenario_capex"
    s.widths({0: 36, 1: 15, 2: 13, 3: 48, 4: 11, 5: 6, 6: 56, 7: 13, 8: 13, 9: 13, 10: 13, 11: 13, 12: 13, 13: 13, 14: 30})
    s.ws.freeze_panes(4, 1)
    s.text(0, 0, "Inputs — 입력값 (파란 글씨·노란 바탕 칸만 바꾼다)", "title")
    s.text(1, 0, "단위: 백만원(주당 값은 원). 출처 열: DART 접수번호·ECOS 코드·config 경로. " + STATUS_NOTE, "note")
    for j, h in enumerate(["항목", "값", "단위", "출처", "기준일", "상태", "근거·비고"]):
        s.text(3, j, h, "header")
    m, rt, mk = d["meta"], d["rates"], d["market"]
    asof = m["as_of"]
    cfgp = d["cfg_label"]
    w = Rows(c, "Inputs", 3)
    labels = d["excel"]["scenario_labels"]

    w.sec("1. 선택 (모델 실행)")
    w.item(
        "scen_sel",
        "시나리오 선택",
        labels[d["excel"]["default_scenario"]],
        "gen",
        "",
        f"{cfgp} excel.default_scenario",
        "",
        "🔸",
        "목록: "
        + "/".join(labels[k] for k in d["excel"]["scenarios"])
        + (". 증권사는 참고 열(대표 시나리오 아님)" if cap else ""),
        name="ScenSel",
    )
    scen_row = w.r - 1
    w.item(
        "srp_sel",
        "SRP 선택(규모위험프리미엄)",
        d["excel"]["default_srp"],
        "pct",
        "%",
        "config/valuation_rf.yaml decisions.srp_columns (D4)",
        "",
        "⚠️",
        "목록: SRP 열 세 값. 한공회 구간 표 미확보 → 세 열 병기",
        name="SRP_Sel",
    )
    srp_row = w.r - 1
    w.item(
        "rf_tenor",
        "Rf 만기 선택(5 = 국고채 5년, 10 = 국고채 10년)",
        rt["rf_tenor"],
        "int",
        "년",
        "config/valuation_rf.yaml risk_free.tenor",
        "",
        "🔸",
        "기본 5년(P3 공통 장부, 사전 고정 결과 그대로). 10년 = 선택: " + rt["rf_tenor_basis"],
        name="RfTenor",
    )
    tenor_row = w.r - 1
    w.item(
        "ronic_start",
        "RONIC 출발점 규칙",
        d["excel"]["ronic_start"],
        "gen",
        "",
        "config/valuation_rules.yaml common_rules.ronic",
        "",
        "🔸",
        "normal = P3-C3 공통 규칙(FY2026 매출 × 정상 이익률) / mixed = P3-B2·C2 방식(1H 실적 + 2H 정상)",
        name="RonicStart",
    )
    ronic_row = w.r - 1
    aff_row = None
    if d.get("affiliate"):
        af = d["affiliate"]
        w.item(
            "aff_incl",
            "계열사 대여금을 비영업·현금성에 포함(1) / 제외(0)",
            af["default_include"],
            "int",
            "",
            f"{cfgp} excel.affiliate_loans",
            "",
            af["status"],
            "기본 1 = 엔진과 같음(이름 기반 분류 규칙 그대로). 0이면 표 9의 합계를 뺀다",
            name="AffLoanIncl",
        )
        aff_row = w.r - 1

    w.sec("2. 기준일·기간 구조")
    w.item(
        "val_date",
        "평가기준일",
        _d(asof),
        "date",
        "날짜",
        f"{cfgp} meta.as_of",
        asof,
        "🔸",
        "KRX 시세 마지막 적재 거래일",
        name="ValDate",
    )
    w.item(
        "disc_date",
        "할인 기준일(재무상태표일)",
        _d(m["discount_date"]),
        "date",
        "날짜",
        f"{cfgp} {'dcf.discount_date' if cap else 'meta.bs_date'}",
        "",
        "🔸",
        "순현금(6/30 재무상태표)과 시작점을 맞춘다. EV는 평가기준일로 이월",
        name="DiscDate",
    )
    w.item(
        "cf_start",
        "현금흐름 시작일",
        _d(m["cf_start"]),
        "date",
        "날짜",
        f"{cfgp} {'dcf.cash_flow_start' if cap else 'meta.bs_date + 1일'}",
        "",
        "🔸",
        "",
        name="CfStart",
    )
    w.item(
        "days",
        "연 일수",
        d["dcf"]["days"],
        "int",
        "일",
        "src/valuation/dcf.py DAYS",
        "",
        "🔸",
        "할인 기간·회전일수 계산(윤일 포함 실제 일수 ÷ 365)",
        name="DaysYr",
    )
    w.item(
        "mn_to_won",
        "단위 환산",
        1_000_000,
        "int",
        "원/백만원",
        "단위",
        "",
        "🔸",
        "주당 가치 = 주식가치(백만원) × 1,000,000 ÷ 주식수",
        name="MnToWon",
    )
    w.item(
        "mid_year",
        "mid-year 할인(1=예, 0=기말)",
        d["dcf"]["mid_year"],
        "int",
        "",
        f"{cfgp} {'dcf.mid_year' if cap else 'forecast.mid_year'}",
        "",
        "🔸",
        "",
        name="MidYear",
    )
    w.item(
        "explicit_end",
        "명시 기간 마지막 연도(생성 시 고정)",
        d["dcf"]["explicit_end"],
        "year",
        "연도",
        f"{cfgp} dcf.explicit_end" if cap else "company_dcf.EXPLICIT_END (P3-B2 구조)",
        "",
        "🔸",
        "열 수가 생성 시 정해진다. 바꾸려면 config 수정 후 재생성(Checks에서 확인)",
        name="ExplicitEnd",
    )
    w.item(
        "fade_years",
        "체감 구간 연수(생성 시 고정)",
        d["dcf"]["fade_years"],
        "int",
        "년",
        "p3b2.stages.fade_years",
        "",
        "⚠️",
        "g_t = g_2032 − k × (g_2032 − g) / 8",
        name="FadeYears",
    )
    w.item(
        "structure",
        "평가 구조(사용자 결정·규칙 판정)",
        m["structure"],
        "gen",
        "",
        f"{cfgp} {'decisions.structure (D2)' if cap else 'structure (규칙 판정)'}",
        "",
        "🔸",
        "Bridge 시트의 구조 판단 규칙(valuation_rules.yaml) 결과와 같아야 한다",
        name="StructureChoice",
    )

    w.sec("3. 할인율 (공통 장부)")
    w.item(
        "rf",
        "무위험이자율 국고채 5년(기본)",
        rt["rf"],
        "pct3",
        "%",
        rt["rf_series"],
        asof,
        rt["rf_status"],
        "평가 표본 5년 48%·10년 39%(P3) → 5년 기본. 모델이 쓰는 Rf = WACC 시트 'Rf'(Rf 만기 선택)",
        name="Rf_5Y",
    )
    w.item(
        "rf10",
        "무위험이자율 국고채 10년(선택)",
        rt["rf10"],
        "pct3",
        "%",
        rt["rf10_series"],
        asof,
        "✅",
        "P5-B 외부평가 의견서 Rf 만기 표시 57건 중 10년 56건(reports/p5b_final.md 7절)",
        name="Rf_10Y",
    )
    w.item(
        "mrp",
        "시장위험프리미엄 MRP",
        rt["mrp"],
        "pct",
        "%",
        rt["mrp_src"],
        rt["mrp_asof"],
        rt["mrp_status"],
        "가이던스 7~9% 중앙값",
        name="MRP",
    )
    srp0 = w.r
    for i, v in enumerate(rt["srp_list"]):
        w.item(
            f"srp_{i}",
            f"SRP 열 {i + 1}",
            v,
            "pct",
            "%",
            "config/valuation_rf.yaml decisions.srp_columns",
            "",
            "⚠️",
            rt["srp_src"] if i == 0 else "",
            name=f"SRP_{i + 1}",
        )
    c.range_name("SRP_List", "Inputs", a1(srp0, 1), a1(w.r - 1, 1))
    pk = d["p5b_ref"]["srp_pick"]
    w.item(
        "srp_cite",
        f"SRP 인용 참고값(한공회 {pk['band']}, 민감도 전용)",
        pk["value"],
        "pct",
        "%",
        "DB p5b_srp_cites: 가장 최근 신고서의 같은 구간 인용값(reports/p5b_final.md 8절)",
        pk["latest_filed"],
        "🔸",
        f"의견서 2차 인용 {pk['n']}건({pk['filed']} 신고서). SRP 기본 열(결정 D4)은 그대로. Scenarios G 표에서만 쓴다",
        name="SRP_Cite",
    )
    _srp_cite_table(c, s, srp0 - 2)
    w.item(
        "t_hamada",
        "Hamada 세율(언레버·리레버)",
        rt["t_hamada"],
        "pct",
        "%",
        f"{cfgp} beta.{'tax_for_hamada' if cap else 'tax'}",
        "",
        "🔸",
        "피어 대부분의 과세표준 구간 한계세율",
        name="T_Hamada",
    )
    w.item(
        "blume_w",
        "Blume 가중치(원 β)",
        rt["blume_w"],
        "ratio",
        "",
        "config/valuation_rules.yaml common_rules.beta.blume",
        "",
        "🔸",
        "Blume = 0.67 × 원 β + 0.33",
        name="BlumeW",
    )
    w.item(
        "blume_c",
        "Blume 상수",
        rt["blume_c"],
        "ratio",
        "",
        "config/valuation_rules.yaml common_rules.beta.blume",
        "",
        "🔸",
        "",
        name="BlumeC",
    )
    if d["de"]["rule"] == "fixed":
        w.item(
            "de_target",
            "목표 D/E (WACC)",
            d["de"]["value"],
            "ratio",
            "배",
            f"{cfgp} {d['de']['src']}",
            "",
            "🔸",
            d["de"]["basis"],
            name="DE_Target",
        )
    w.item(
        "rating",
        "신용등급(빈칸 = 무등급)",
        rt["rating"] or None,
        "gen",
        "",
        d.get("rating_src") or "common_rules.kd",
        "",
        "✅" if rt["rating"] else "🔸",
        "Kd 규칙: 무등급·BBB 이하 → BBB- 3년, AA- 이상 → AA-, A+~BBB+ → max(실제 가중, AA-), 하한 Rf",
        name="Rating",
    )
    w.item(
        "kd_bbb",
        "회사채 3년 BBB-",
        rt["kd_bbb"],
        "pct3",
        "%",
        "ECOS 817Y002 010320000 (CB3Y_BBBm)",
        asof,
        "✅",
        "",
        name="Kd_BBB",
    )
    w.item("kd_aa", "회사채 3년 AA-", rt["kd_aa"], "pct3", "%", "ECOS 817Y002 010300000 (CB3Y_AAm)", asof, "✅", "", name="Kd_AA")
    w.item(
        "r2_warn",
        "베타 신뢰성 경고 기준(피어 R² 중앙값 미만)",
        d["common"]["r2_warn"],
        "ratio",
        "",
        "common_rules.beta.warn_r2_median_below",
        "",
        "🔸",
        "표시만(경로 불변)",
        name="BetaR2Warn",
    )

    w.sec("4. 주식·시장 (기준일 단일 값)")
    sh = d["shares"]
    w.item(
        "common_issued",
        "보통주 발행주식수(기준일)",
        sh["common_issued"],
        "int",
        "주",
        sh["src"],
        asof,
        sh["status"],
        sh["basis"],
        name="CommonIssued",
    )
    w.item(
        "common_treasury",
        "보통주 자기주식수(기준일)",
        sh["common_treasury"],
        "int",
        "주",
        sh["src"],
        asof,
        sh["status"],
        "",
        name="CommonTreasury",
    )
    w.item(
        "pref_issued",
        "우선주 발행주식수(기준일)",
        sh["pref_issued"],
        "int",
        "주",
        sh["src"],
        asof,
        sh["status"],
        "주당가치 분모 = 보통주 + 우선주 유통주식수(같은 청구권 가정 ⚠️)" if sh["pref_issued"] else "우선주 없음",
        name="PrefIssued",
    )
    w.item(
        "pref_treasury",
        "우선주 자기주식수(기준일)",
        sh["pref_treasury"],
        "int",
        "주",
        sh["src"],
        asof,
        sh["status"],
        "",
        name="PrefTreasury",
    )
    w.item("close", "기준일 종가(보통주)", mk["close"], "won", "원", KRX, asof, "✅", "", name="Close", krx="close")
    w.item(
        "rf_mc",
        "기준일 시가총액(대상 보통주)",
        mk["rf_mc"],
        "mn",
        "백만원",
        KRX + " (mktcap_fix 보정 적용)",
        asof,
        "✅",
        "시총 백분위에 사용",
        name="TargetMC",
        krx="target market cap",
    )
    if cap or mk.get("sub_mc"):
        w.item(
            "sub_mc",
            f"기준일 시가총액({mk['sub_name']} {mk['sub_code']})",
            mk["sub_mc"],
            "mn",
            "백만원",
            KRX,
            asof,
            "✅",
            "상장 종속회사 지분 시가",
            name="SubMC",
            krx="subsidiary market cap",
        )
        w.item(
            "stake",
            f"{mk['sub_name']} 지분율(모회사)",
            mk["stake"],
            "pct",
            "%",
            "반기보고서 주석 1·31 (20260814001631)" if cap else f"{cfgp} (상장 종속회사)",
            m["bs_date"],
            "✅",
            "RFHIC 위임 포함 의결권 44.09% → 사실상 지배" if cap else "",
            name="Stake",
        )
    else:
        w.item(
            "sub_mc",
            "상장 종속회사 시가총액(없음)",
            0,
            "mn",
            "백만원",
            "상장 종속회사 없음",
            asof,
            "✅",
            "구조 판단 수식용 0",
            name="SubMC",
        )
        w.item("stake", "상장 종속회사 지분율(없음)", 0, "pct", "%", "상장 종속회사 없음", "", "✅", "", name="Stake")
    w.item(
        "listed_sub",
        "중요 종속회사 상장 여부(1=예)",
        int(mk.get("listed_sub", 1 if cap else 0)),
        "int",
        "",
        "corp_master (KOSDAQ 474610)" if cap else f"{cfgp} structure.listed_subsidiary (otrCprInvstmntSttus)",
        "",
        "✅",
        "",
        name="ListedSub",
    )

    if cap:
        w.sec("5. 재무상태표 보정·SOTP 항목")
        w.item(
            "ltb_override",
            "모회사 장기차입금 보정(API 계정 오표기)",
            d["lt_borrowings_override"],
            "mn",
            "백만원",
            "반기보고서 20260814001631 별도 재무상태표 '장기차입금'",
            m["bs_date"],
            "✅",
            "API가 '장기매입채무 및 기타비유동채무'로 표기 → 총차입금에 더함",
            name="LTB_Override",
        )
        w.item(
            "inv_subs",
            "종속기업투자(별도 장부, 더하지 않음)",
            d["inv_subs_book"],
            "mn",
            "백만원",
            "fs_raw 별도 BS '종속기업투자' (20260814001631)",
            m["bs_date"],
            "✅",
            "종속회사는 시가로 한 번만 센다(이중 계상 방지). PBR 분모에서 뺀다",
            name="InvSubsBook",
        )
        w.item(
            "hq_pv",
            "본사 미배분 공통비 PV(차감)",
            d["dcf"]["unallocated_hq_pv"],
            "mn",
            "백만원",
            "부문 주석 영업이익 = 별도 영업이익",
            "",
            "🔸",
            "미배분 공통비 없음 → 0",
            name="HQ_PV",
        )

        w.sec("6. DCF 가정 (모회사 시나리오)")
        lv = d["lives"]
        w.item(
            "life_m",
            "유지 CAPEX 상각 연수",
            lv["maint"],
            "int",
            "년",
            f"{cfgp} parent_scenarios.maintenance_capex_life_years",
            "",
            "⚠️",
            "정액, 지출 연도는 절반",
            name="LifeM",
        )
        w.item(
            "life_b",
            "신규 공장 상각 연수",
            lv["growth"],
            "int",
            "년",
            f"{cfgp} parent_scenarios.growth_capex_life_years",
            "",
            "⚠️",
            "",
            name="LifeB",
        )
        w.item(
            "bldg_start",
            "신규 공장 상각 시작 연도",
            lv["bldg_start"],
            "year",
            "연도",
            f"{cfgp} excel.growth_capex_dep_start",
            "",
            "⚠️",
            "2027년 말 준공 가정",
            name="BldgStart",
        )
        w.item(
            "exit_mult",
            "Exit 배수(EV/EBITDA, 병행 표시)",
            d["dcf"]["exit_multiple"],
            "x",
            "배",
            f"{cfgp} dcf.exit_multiple",
            "",
            "⚠️",
            d["dcf"]["exit_src"],
            name="ExitMult",
        )

        w.sec(f"7. {mk['sub_name']} 단순 가정 (연결 교차 확인 전용)")
        ss = d["sub_simple"]
        w.item(
            "sub_g", "매출 성장률", ss["growth"], "pct", "%", f"{cfgp} subsidiary_simple", "", "⚠️", "연 3~5%의 중간", name="SubG"
        )
        w.item(
            "sub_m", "영업이익률", ss["margin"], "pct", "%", f"{cfgp} subsidiary_simple", "", "⚠️", "과거 평균 11~12%", name="SubM"
        )
        w.item("sub_gt", "영구성장률", ss["g_terminal"], "pct", "%", f"{cfgp} subsidiary_simple", "", "⚠️", "", name="SubGT")
        w.item(
            "sub_capex",
            "CAPEX ÷ D&A",
            ss["capex_to_dna"],
            "ratio",
            "배",
            f"{cfgp} subsidiary_simple",
            "",
            "⚠️",
            "",
            name="SubCapexDna",
        )
        w.item(
            "sub_half",
            "2H26 ΔNWC 반기 비율",
            0.5,
            "ratio",
            "",
            "src/valuation/rf_dcf.py sub_value",
            "",
            "🔸",
            "2H26 ΔNWC = 기초 NWC × g × 0.5",
            name="SubHalf",
        )
    else:
        w.sec(f"5. 기계적 예측 규칙 ({d['labels']['rule_tag']})")
        mc = d["mech"]
        w.item(
            "g_terminal",
            "영구성장률 g(사람 값)",
            mc["g_terminal"],
            "pct",
            "%",
            f"{cfgp} forecast.human.g_terminal",
            "",
            "⚠️",
            "세 시나리오 같음. 2030년까지 출발 성장률에서 같은 폭으로 체감",
            name="GTermCfg",
        )
        w.item(
            "fade_to",
            "출발 성장률 → g 도달 연도",
            mc["fade_to"],
            "year",
            "연도",
            f"{cfgp} params.fade_to_terminal_by",
            "",
            "🔸",
            "2031~2032 = g",
            name="FadeTo",
        )
        er = mc["ebitda_rule"]
        for k, lab, nm in (
            ("h1_lo", "D&A 반기 ÷ 연간 하한", "DnaH1Lo"),
            ("h1_hi", "D&A 반기 ÷ 연간 상한", "DnaH1Hi"),
            ("ratio_lo", "D&A ÷ 매출 하한(N/M)", "DnaRatioLo"),
            ("ratio_hi", "D&A ÷ 매출 상한(N/M)", "DnaRatioHi"),
        ):
            w.item(
                f"er_{k}",
                lab,
                er[k],
                "pct",
                "",
                f"{cfgp} params.ebitda_rule",
                "",
                "🔸",
                "반기 D&A가 3개월 값으로 보이면 LTM = FY D&A" if k == "h1_lo" else "",
                name=nm,
            )
        w.item(
            "seg_mgap",
            "부문 이익률 차이(단일 보고부문)",
            0.0,
            "pct",
            "%p",
            f"{cfgp} structure.segments",
            "",
            "✅",
            d["labels"]["seg_note"],
            name="SegMarginGap",
        )
        w.item(
            "seg_ggap",
            "부문 성장률 차이(단일 보고부문)",
            0.0,
            "pct",
            "%p",
            f"{cfgp} structure.segments",
            "",
            "✅",
            "",
            name="SegGrowthGap",
        )
        ovr = d.get("overrides") or {}  # P7-C1 workbench: confirmed values the calculation sheets read
        src_wb = f"평가 세션 {(d.get('workbench') or {}).get('session_id', '')} v{(d.get('workbench') or {}).get('version', '')}"
        for key, lab, kind, unit, nm in (
            ("normal_margin", "사람 확정값: 출발 정상 영업이익률", "pct", "%", "M0Override"),
            ("g_start", "사람 확정값: 출발 성장률", "pct", "%", "G0Override"),
            ("beta_u", "사람 확정값: βu", "beta", "", "BetaOverride"),
            ("de", "사람 확정값: 목표 D/E", "ratio", "배", "DeOverride"),
            ("kd", "사람 확정값: 세전 Kd", "pct3", "%", "KdOverride"),
            ("cash_adjust_mn", "사람 확정값: 현금성에서 뺄 영업용 현금", "mn", "백만원", "CashAdjust"),
            ("nci_mn", "사람 확정값: 비지배지분", "mn", "백만원", "NciOverride"),
            # P7-X2b (config/p7x2b.yaml judgements): the large assumptions a person may confirm
            ("dna_ratio", "사람 확정값: D&A ÷ 매출", "pct", "%", "DnaRatioOverride"),
            ("capex_ratio", "사람 확정값: CAPEX ÷ 매출", "pct", "%", "CapexRatioOverride"),
            ("conv_share", "사람 확정값: 피어 쪽 이익률 수렴 비율", "pct", "", "ConvShareOverride"),
            ("conv_end", "사람 확정값: 이익률 수렴 도달 연도", "year", "연도", "ConvEndOverride"),
            ("ronic", "사람 확정값: 영구 구간 RONIC", "pct", "%", "RonicOverride"),
        ):
            if ovr.get(key) is not None:
                w.item(
                    f"ovr_{key}",
                    lab,
                    float(ovr[key]),
                    kind,
                    unit,
                    src_wb,
                    "",
                    "⚠️",
                    "사람 판단 반영 내역(Judgements 시트)",
                    name=nm,
                )
        if ovr.get("fade_reinvest") == "linear":  # P7-U1F D-2 (C): the fade reinvestment rule a person chose
            w.item(
                "ovr_fade_reinvest",
                "사람 확정값: 수렴 구간 재투자율 선형 수렴(1 = 켬)",
                1,
                "int",
                "",
                src_wb,
                "",
                "⚠️",
                "마지막 명시 연도 재투자율 → g ÷ RONIC(Judgements 시트)",
                name="FadeReinvLinear",
            )
        if ovr.get("nwc_days") is not None:  # P7-X2b: the three turnover days together
            for k, lab, nm in (("dso", "DSO", "DsoOverride"), ("dio", "DIO", "DioOverride"), ("dpo", "DPO", "DpoOverride")):
                w.item(
                    f"ovr_{k}",
                    f"사람 확정값: {lab}(회전일수)",
                    float(ovr["nwc_days"][k]),
                    "days",
                    "일",
                    src_wb,
                    "",
                    "⚠️",
                    "사람 판단 반영 내역(Judgements 시트)",
                    name=nm,
                )
        bs = d["engine"].get("beta_src", "peer")
        if bs not in ("peer", "override"):  # P7-B5 beta fallback (config/p7b5.yaml peer_relax.beta_fallback)
            w.item(
                "beta_fb",
                "βu 대체값(피어 βu 없음)",
                d["engine"]["beta_u"],
                "beta",
                "",
                "대상 자기 회귀 βu(Blume·Hamada)" if bs == "target_own" else "시장 평균 1.0",
                "",
                "⚠️",
                "피어 직접 지정 필요 — 판단 1순위",
                name="BetaFallback",
            )
        if d.get("v2"):  # P7-B2b mechanical_v2 inputs (config/p7b2b.yaml; peer values from the peer statements)
            v = d["v2"]
            src2 = "config/p7b2b.yaml mechanical_v2"
            w.item(
                "v2_pm",
                f"v2 피어 LTM 영업이익률 중앙값(n={v['peer_margin_n']})",
                v["peer_margin"],
                "pct",
                "%",
                "피어 fs_std LTM(company_dcf.peer_metrics)",
                "",
                "🔸",
                "피어 3곳 미만이면 빈칸(수렴 없음)",
                name="PeerMarginV2",
            )
            w.item(
                "v2_pg",
                f"v2 피어 매출 성장률 중앙값(n={v['peer_growth_n']})",
                v["peer_growth"],
                "pct",
                "%",
                "피어 fs_std FY2023→2025 CAGR",
                "",
                "🔸",
                "피어 3곳 미만이면 빈칸(대상 CAGR만)",
                name="PeerGrowthV2",
            )
            w.item(
                "v2_cs",
                "v2 수렴 비율(2032년까지 피어 쪽으로 좁히는 몫)",
                v["conv_share"],
                "pct",
                "",
                src2,
                "",
                "⚠️",
                "사이클 평균 + 경쟁에 따른 평균 회귀(근거 reports/p7b2b_default.md)",
                name="ConvShare",
            )
            w.item(
                "v2_w",
                "v2 대상 CAGR 가중치(나머지 = 피어 성장률)",
                v["weight_own"],
                "pct",
                "",
                src2,
                "",
                "⚠️",
                "기저율 혼합",
                name="WOwn",
            )
            w.item("v2_lo", "v2 출발 성장률 하한", v["clip"][0], "pct", "", src2, "", "⚠️", "", name="ClipLo")
            w.item("v2_hi", "v2 출발 성장률 상한", v["clip"][1], "pct", "", src2, "", "⚠️", "", name="ClipHi")

    w.sec("8. 구조 판단 규칙 (config/valuation_rules.yaml structure)")
    sr = d["structure_rules"]
    w.item(
        "nci_min",
        "비지배지분 ÷ 주식가치 ≥ (SOTP)",
        sr["nci_share_min"],
        "pct",
        "%",
        "valuation_rules.yaml structure.nci_share_min",
        "",
        sr["status"],
        sr["nci_share_basis"],
        name="NciShareMin",
    )
    w.item(
        "mgap",
        "상장 종속회사 + 부문 이익률 차이 ≥",
        sr["listed_sub_margin_gap_pp"] / 100,
        "pct",
        "%p",
        "valuation_rules.yaml listed_sub_margin_gap_pp",
        "",
        sr["status"],
        "",
        name="MarginGapMin",
    )
    w.item(
        "ggap",
        "상장 종속회사 + 부문 성장률 차이 ≥",
        sr["listed_sub_growth_gap_pp"] / 100,
        "pct",
        "%p",
        "valuation_rules.yaml listed_sub_growth_gap_pp",
        "",
        sr["status"],
        "",
        name="GrowthGapMin",
    )

    pr = d["premium"]
    if pr.get("withheld"):  # P7-C3 public deployment: premium aggregates not published
        w.sec("9. 블록 프리미엄 — 공개 배포에서는 비공개")
        w.s.text(w.r, 0, pr["note"] + ". 블록 1주당 가격은 계산하지 않는다(PC 모드에서 계산)", "note")
        w.r += 1
        w.item(
            "vwap",
            "20거래일 VWAP(사용자 입력)",
            pr["vwap"],
            "won",
            "원",
            "사용자 입력 시세",
            asof,
            "🔸",
            "공개 모드: 사용자가 넣은 값",
            name="VWAP20",
            krx="20-day VWAP (user input)",
        )
        w.item(
            "tax_prem",
            "상증법 최대주주 할증률(비교용)",
            pr["tax_premium"],
            "pct",
            "%",
            "상증법 제63조 제3항(원문 미확인)",
            "",
            "⚠️",
            "중소기업·일정 중견기업은 제외 → 해당 여부 미확인",
            name="TaxPrem",
        )
        w.item(
            "peer_nwarn",
            "피어 배수 표본 수 경고 기준(미만)",
            d["relative"]["n_warn"],
            "int",
            "곳",
            f"{cfgp} relative.n_warn",
            "",
            "🔸",
            "N/M(분모 ≤ 0) 제외 후 표본 수",
            name="PeerNWarn",
        )
    else:
        w.sec("9. 블록 프리미엄 (프리미엄 DB 집계값만, 거래 목록 없음)")
        src_db = "predict.premium_range (주 표본 n=510, bu20_doc), 결정 D1·D6"
        if pr.get("pct_fixed"):  # P7-C3b public mode: the as-of percentile, fixed (config/p7c3b.yaml percentile)
            w.item(
                "prem_pct",
                f"기준일 시총 백분위(고정, {pr['market']} 보통주 {pr['n_universe']:,}종목 중)",
                pr["pct"],
                "days",
                "백분위",
                KRX + " → predict.mktcap_percentile, 기준일 값 고정(공개 모드: 입력한 주가로 바뀌지 않음)",
                asof,
                "🔸",
                "중간 순위 백분위(0~100). 공개 배포 스냅샷은 소수 첫째 자리",
                name="Prem_Pct",
                krx="market-cap percentile (derived)",
            )
            w.item(
                "prem_pct_fixed",
                "시총 백분위 고정 여부(공개 모드)",
                1,
                "int",
                "",
                "config/p7c3b.yaml percentile",
                "",
                "🔸",
                "1 = 기준일 값 고정",
                name="PremPctFixed",
            )
        else:
            w.item(
                "prem_pct",
                f"시총 백분위({pr['market']} 보통주 {pr['n_universe']:,}종목 중)",
                pr["pct"],
                "days",
                "백분위",
                KRX + " → predict.mktcap_percentile",
                asof,
                "🔸",
                "중간 순위 백분위(0~100)",
                name="Prem_Pct",
                krx="market-cap percentile (derived)",
            )
        w.item("prem_market", "시장", pr["market"], "gen", "", f"{cfgp} meta.target.market", "", "✅", "", name="Prem_Market")
        w.item(
            "prem_cv",
            "C3 판정: CV q50 손실 개선",
            pr["cv_improvement"],
            "pct",
            "%",
            "predict.adoption (사전 등록 5-fold CV)",
            "",
            "🔸",
            "5.15% ≥ 5% → 회귀 채택(D1, 판정 불안정 공개)",
            name="Prem_CV",
        )
        w.item(
            "prem_thr",
            "회귀 채택 기준",
            pr["adopt_threshold"],
            "pct",
            "%",
            "config/premium_p2c3.yaml",
            "",
            "🔸",
            "",
            name="Prem_Thr",
        )
        w.item(
            "prem_top",
            "D6: KOSDAQ 상위 구간 기준(백분위 이상)",
            pr["top_band_pct"],
            "int",
            "백분위",
            "config/premium_p2c3.yaml application_rule",
            "",
            "🔸",
            "D6(사용자 2026-10-03)",
            name="Prem_TopBand",
        )
        w.item(
            "prem_gap",
            "경고: 회귀 vs 이웃 중앙값 차이 >",
            pr["gap_warn"],
            "pct",
            "%p",
            "predict.GAP_WARN (사전 등록)",
            "",
            "🔸",
            "",
            name="Prem_GapWarn",
        )
        for nm, lab in (("neighbour", "이웃 50건"), ("regression", "분위 회귀(참고)")):
            for q in ("q25", "q50", "q75"):
                w.item(
                    f"prem_{nm}_{q}",
                    f"{lab} {q}",
                    pr[nm][q],
                    "pct1",
                    "%",
                    src_db,
                    "",
                    "🔸",
                    "",
                    name=f"Prem_{nm[:3].upper()}_{q}",
                )
        w.item(
            "prem_nb_n", "이웃 표본 수", pr["neighbour"]["n"], "int", "건", src_db, "", "🔸", "같은 시장 우선", name="Prem_NB_n"
        )
        b = pr["band"]
        for q in ("q25", "q50", "q75"):
            v = b[q]
            if d.get("public") and (v is None or v != v):  # P7-X2a: a band cell of fewer than 10 deals has no quantile
                v = pubcut.FEW_DEALS
            w.item(f"prem_band_{q}", f"구간 표 {b['band']} {q}", v, "pct1", "%", src_db, "", "🔸", "", name=f"Prem_BAN_{q}")
        w.item("prem_band_n", f"구간 표 {b['band']} 표본 수", b["n"], "int", "건", src_db, "", "🔸", "", name="Prem_BAN_n")
        if pr.get("vwap_user"):  # public mode: the user's typed VWAP
            w.item(
                "vwap",
                "20거래일 VWAP(사용자 입력)",
                pr["vwap"],
                "won",
                "원",
                "사용자 입력 시세",
                asof,
                "🔸",
                "공개 모드: 사용자가 넣은 값",
                name="VWAP20",
                krx="20-day VWAP (user input)",
            )
        else:
            w.item(
                "vwap",
                f"20거래일 VWAP({pr['vwap_start']}~{pr['vwap_end']}, n={pr['vwap_n']})",
                pr["vwap"],
                "won",
                "원",
                KRX + " (거래대금 합 ÷ 거래량 합, 수정 계수)",
                asof,
                "🔸",
                "파생 단일 값",
                name="VWAP20",
                krx="20-day VWAP (derived)",
            )
        w.item(
            "tax_prem",
            "상증법 최대주주 할증률(비교용)",
            pr["tax_premium"],
            "pct",
            "%",
            "상증법 제63조 제3항(원문 미확인)",
            "",
            "⚠️",
            "중소기업·일정 중견기업은 제외 → 해당 여부 미확인",
            name="TaxPrem",
        )
        w.item(
            "peer_nwarn",
            "피어 배수 표본 수 경고 기준(미만)",
            d["relative"]["n_warn"],
            "int",
            "곳",
            f"{cfgp} relative.n_warn",
            "",
            "🔸",
            "N/M(분모 ≤ 0) 제외 후 표본 수",
            name="PeerNWarn",
        )
        w.item(
            "block_nwarn",
            "프리미엄 표본 수 경고 기준(미만)",
            10,
            "int",
            "건",
            "CLAUDE.md 통계 원칙(n<10 경고)",
            "",
            "🔸",
            "",
            name="PremNWarn",
        )

    if cap:
        w.sec("10. 참고 범위·증권사 추정 (참고 시나리오 파생 입력)")
        tp = d["broker_targets"]
        for k, lab in (
            ("low", "증권사 목표주가 하단"),
            ("high", "증권사 목표주가 상단"),
            ("consensus", "증권사 목표주가 컨센서스"),
        ):
            w.item(
                f"tp_{k}", lab, tp[k], "won", "원", tp["source"], "2026-08~09", "🔸", "투자의견과 무관하게 범위만", name=f"TP_{k}"
            )
        bk = d["broker"]
        for k, lab in (
            ("rev_2026", "연결 2026 매출(증권사)"),
            ("rev_2027", "연결 2027 매출(증권사)"),
            ("op_2026", "연결 2026 영업이익(증권사)"),
            ("op_2027", "연결 2027 영업이익(증권사)"),
        ):
            w.item(
                f"bk_{k}",
                lab,
                bk["cons"][k],
                "mn",
                "백만원",
                bk["src"][k],
                "",
                "🔸",
                "매출 2026-03·영업이익 2026-07 보고서 혼합(파생값)",
                name=f"BK_{k}",
            )

    # ---------------- tables
    r = w.r + 2
    r = _tax_table(c, s, r)
    r = _rating_table(c, s, r)
    r = _scenario_table(c, s, r) if cap else _shift_table(c, s, r)
    if cap:
        r = _growth_capex_table(c, s, r)
    r = _borrowings_table(c, s, r)
    if d["de"]["rule"] == "points":
        r = _de_table(c, s, r)
    if sh["listed_pref"]:
        r = _pref_table(c, s, r)
    r = _beta_table(c, s, r)
    r = _peer_table(c, s, r)
    if d.get("affiliate"):
        r = _affiliate_table(c, s, r)
    if d.get("sotp"):
        r = _sotp_table(c, s, r)
    if d.get("associates"):
        r = _assoc_table(c, s, r)
    s.ws.data_validation(scen_row, 1, scen_row, 1, {"validate": "list", "source": "=ScenNames"})
    s.ws.data_validation(srp_row, 1, srp_row, 1, {"validate": "list", "source": "=SRP_List"})
    s.ws.data_validation(ronic_row, 1, ronic_row, 1, {"validate": "list", "source": ["normal", "mixed"]})
    s.ws.data_validation(tenor_row, 1, tenor_row, 1, {"validate": "list", "source": ["5", "10"]})
    if aff_row is not None:
        s.ws.data_validation(aff_row, 1, aff_row, 1, {"validate": "list", "source": ["1", "0"]})
    c.layout["inputs_rows"] = {
        "scen_sel": scen_row,
        "srp_sel": srp_row,
        "ronic": ronic_row,
        "aff": aff_row,
        "rf_tenor": tenor_row,
    }


def _srp_cite_table(c: Ctx, s, r):
    """P6-A: 한공회 size-premium values quoted in merger opinions (P5-B, 2nd-hand 🔸), next to the SRP rows (columns I~M).
    Aggregates only (cited year x band x value: count, filing years). Grey = reference values, not model inputs."""
    ref = c.d["p5b_ref"]
    rows = ref["srp_cites"]
    c0 = 8
    s.text(r, c0, "참고: 한공회 규모위험 프리미엄 인용값(P5-B 외부평가 의견서 재인용 🔸, 집계)", "subtitle")
    for j, h in enumerate(["인용 기준 연도", "구간 이름", "값", "건수", "신고서 연도"]):
        s.text(r + 1, c0 + j, h, "header")
    for i, x in enumerate(rows):
        rr = r + 2 + i
        s.eng(rr, c0, x["cited"])
        s.eng(rr, c0 + 1, x["band"])
        s.eng(rr, c0 + 2, round(x["srp"], 6), "pct")
        s.eng(rr, c0 + 3, x["n"], "int")
        s.eng(rr, c0 + 4, x["filed"])
    s.engine_range(r + 2, c0, r + 1 + len(rows), c0 + 4)
    c.range_name("SrpCiteTable", "Inputs", a1(r + 2, c0), a1(r + 1 + len(rows), c0 + 4))
    s.text(
        r + 2 + len(rows),
        c0,
        "구간 경계(시가총액)와 대상 회사가 속한 구간은 미확인. 같은 이름도 연구 기준 연도마다 값이 다름. 출처: " + ref["source"],
        "note",
    )


def _shift_table(c: Ctx, s, r):
    d = c.d
    keys, labels = d["excel"]["scenarios"], d["excel"]["scenario_labels"]
    tag = c.d["labels"]["rule_tag"].split(" · ")[0] if c.d.get("labels") else "사전 고정 370efdb"
    s.text(r, 0, f"표 3. 시나리오 (출발 성장률·정상 이익률 이동, {tag})", "subtitle")
    _hdr(s, r + 1, ["항목"] + [labels[k] for k in keys] + ["", "출처·근거"])
    c.range_name("ScenNames", "Inputs", a1(r + 1, 1), a1(r + 1, len(keys)))
    rows = {}
    for i, (pk, lab) in enumerate(
        (("growth_shift", "출발 성장률 이동(g_2026 = 5년 CAGR + 이동)"), ("margin_shift", "정상 이익률 이동"))
    ):
        rr = r + 2 + i
        s.text(rr, 0, lab)
        for j, k in enumerate(keys):
            s.inp(rr, 1 + j, d["scenarios"][k][pk], "pct")
        rows[pk] = rr
    s.text(r + 2, len(keys) + 2, f"{d['cfg_label']} scenarios.human · 상태 ⚠️(±2%p 사용자 지시)", "wrap")
    c.layout["scen_table"] = {"rows": rows, "keys": keys, "col0": 1}
    return r + 5


def _sotp_table(c: Ctx, s, r):
    """P7-B3 general SOTP inputs: consolidated subsidiaries held directly (타법인 출자현황 FY2025) and the listed ones held only
    indirectly (flag 0). Close = 한국거래소 통계정보 single as-of values (market provider)."""
    sp = c.d["sotp"]
    s.text(
        r, 0, "표 10. SOTP 종속회사 (config/p7b3.yaml sotp) — 상장·직접 보유 = 보유 주식수 × 종가, 비상장 = 장부가", "subtitle"
    )
    s.text(r, 6, "상장 지분 할인율", "bold")
    s.inp(r, 7, sp["discount"], "pct", name="SubDiscount")
    _hdr(
        s,
        r + 1,
        [
            "종속회사",
            "종목코드",
            "상장(1/0)",
            "직접 보유(1/0)",
            "보유 주식수",
            "종가(원)",
            "장부가(백만원)",
            "비상장(1/0)",
            "출처",
        ],
    )
    rows = sp["rows"]
    for i, x in enumerate(rows):
        rr = r + 2 + i
        s.text(rr, 0, x["name"])
        s.text(rr, 1, x.get("stock_code") or "-")
        s.inp(rr, 2, int(bool(x.get("listed"))), "int")
        s.inp(rr, 3, int(bool(x.get("listed") and x.get("direct"))), "int")
        s.inp(rr, 4, x.get("shares") or 0, "int")
        s.inp(rr, 5, x.get("close") or 0, "won", krx="subsidiary close" if x.get("close") else None)
        s.inp(rr, 6, (x.get("book") or 0) / 1e6, "mn")
        s.inp(rr, 7, int(not x.get("listed")), "int")
        s.text(
            rr,
            8,
            "타법인 출자현황 FY2025 · 사업보고서 연결 범위 표" + (" · 종가 한국거래소 통계정보" if x.get("close") else ""),
            "note",
        )
    r0, r1 = r + 2, r + 1 + max(len(rows), 1)
    for nm, j in (("SubShares", 4), ("SubClose", 5), ("SubBook", 6), ("SubListedDirect", 3), ("SubUnlisted", 7)):
        c.range_name(nm, "Inputs", a1(r0, j), a1(r1, j))
    return r1 + 3


def _assoc_table(c: Ctx, s, r):
    """P7-X2b listed associates (config/p7x2b.yaml associates): stake >= 20%, outside the consolidation scope, held directly.
    Value = shares x close x (1 − discount); the associates line of the balance sheet gives back min(line, Σ book) where book
    = estimated equity-method book (consolidated: stake x the associate's owners' equity) or the separate book."""
    a = c.d["associates"]
    s.text(
        r,
        0,
        "표 11. 상장 관계기업 (config/p7x2b.yaml associates) — 보유 주식수 × 종가 × (1 − 할인), 관계기업 줄 장부는 뺌",
        "subtitle",
    )
    s.text(r, 6, "관계기업 지분 할인율", "bold")
    s.inp(r, 7, a["discount"], "pct", name="AssocDiscount")
    _hdr(s, r + 1, ["관계기업", "종목코드", "지분율", "보유 주식수", "종가(원)", "빼는 장부(백만원)", "장부 근거", "출처"])
    rows = [x for x in a["rows"] if x.get("shares")]
    for i, x in enumerate(rows):
        rr = r + 2 + i
        cfs = a["basis"] == "CFS" and x.get("est_carrying") is not None
        s.text(rr, 0, x["name"])
        s.text(rr, 1, x.get("stock_code") or "-")
        s.inp(rr, 2, x.get("stake") or 0, "pct")
        s.inp(rr, 3, x.get("shares") or 0, "int")
        s.inp(rr, 4, x.get("close") or 0, "won", krx="associate close" if x.get("close") else None)
        s.inp(rr, 5, ((x["est_carrying"] if cfs else x.get("book")) or 0) / 1e6, "mn")
        s.text(
            rr,
            6,
            ("지분율 × 관계기업 지배주주지분 " + str(x.get("est_source", ""))) if cfs else "출자현황 장부가(별도 기준)",
            "note",
        )
        s.text(
            rr,
            7,
            "타법인 출자현황 · corp_master 이름 일치"
            + (" · " + x["shares_event_fixed"] if x.get("shares_event_fixed") else "")
            + (" · 종가 한국거래소 통계정보" if x.get("close") else ""),
            "note",
        )
    r0, r1 = r + 2, r + 1 + max(len(rows), 1)
    for nm, j in (("AssocShares", 3), ("AssocClose", 4), ("AssocBook", 5)):
        c.range_name(nm, "Inputs", a1(r0, j), a1(r1, j))
    ei = a.get("equity_income") or {}
    if ei:
        rr = r1 + 1
        s.text(
            rr,
            0,
            "영업이익 안 지분법 손익(이중 계산 방지로 매출·영업이익에서 뺌, FS_Hist 값은 뺀 뒤): "
            + "; ".join(
                f"{k.replace('|', ' ')} {v['amount'] / 1e6:,.0f}백만원{'(영업수익 안)' if v['in_revenue'] else ''}"
                for k, v in sorted(ei.items())
            ),
            "note",
        )
        r1 = rr
    return r1 + 3


def _borrowings_table(c: Ctx, s, r):
    s.text(r, 0, "표 5. 실제 차입(약정이자율·잔액, Kd 규칙의 '실제 가중' 계산용)", "subtitle")
    _hdr(s, r + 1, ["차입", "이자율", "잔액(백만원)", "출처"])
    bs = c.d["borrowings"]
    for i, b in enumerate(bs):
        rr = r + 2 + i
        s.text(rr, 0, b["label"])
        s.inp(rr, 1, b["rate"], "pct3")
        s.inp(rr, 2, b["amount"], "mn")
        s.text(rr, 3, c.d["borrowings_src"] if i == 0 else "", "wrap")
    r0, r1 = r + 2, r + 1 + len(bs)
    c.range_name("BorrowRate", "Inputs", a1(r0, 1), a1(r1, 1))
    c.range_name("BorrowAmt", "Inputs", a1(r0, 2), a1(r1, 2))
    return r1 + 3


def _de_table(c: Ctx, s, r):
    s.text(
        r, 0, "표 6. D/E 시점 (총차입금 + 리스부채 ÷ 그날 보통주 시가총액, 시가총액은 한국거래소 통계정보 단일 값)", "subtitle"
    )
    _hdr(s, r + 1, ["재무상태표일", "총차입금", "리스부채", "시가총액", "출처"])
    pts = c.d["de"]["points"]
    for i, p in enumerate(pts):
        rr = r + 2 + i
        s.text(rr, 0, p["date"])
        s.inp(rr, 1, p["debt"], "mn")
        s.inp(rr, 2, p["lease"], "mn")
        s.inp(rr, 3, p["mktcap"], "mn", krx="market cap at balance-sheet date (D/E)")
        s.text(rr, 4, c.d["de"]["src"] if i == 0 else "", "wrap")
    c.layout["de_rows"] = (r + 2, r + 1 + len(pts))
    return r + 3 + len(pts)


def _pref_table(c: Ctx, s, r):
    s.text(r, 0, "표 7. 상장 우선주 (시장 주식가치 계산용, 한국거래소 통계정보 기준일 값)", "subtitle")
    _hdr(s, r + 1, ["종목코드", "종가(원)", "상장주식수", "출처"])
    lp = c.d["shares"]["listed_pref"]
    for i, p in enumerate(lp):
        rr = r + 2 + i
        s.text(rr, 0, p["code"])
        s.inp(rr, 1, p["close"], "won", krx="preferred close")
        s.inp(rr, 2, p["listed"], "int")
        s.text(rr, 3, KRX if i == 0 else "")
    r0, r1 = r + 2, r + 1 + len(lp)
    c.range_name("PrefClose", "Inputs", a1(r0, 1), a1(r1, 1))
    c.range_name("PrefListed", "Inputs", a1(r0, 2), a1(r1, 2))
    return r1 + 3


def _affiliate_table(c: Ctx, s, r):
    af = c.d["affiliate"]
    s.text(r, 0, "표 9. '기타 금융자산' 중 계열사 대여금 등 (특수관계자 자금거래 표, 백만원)", "subtitle")
    _hdr(s, r + 1, ["항목", "잔액(백만원)", "출처"])
    for i, it in enumerate(af["items"]):
        rr = r + 2 + i
        s.text(rr, 0, it["label"])
        s.inp(rr, 1, it["amount"], "mn")
        s.text(rr, 2, af["source"] if i == 0 else "", "wrap")
    c.range_name("AffLoanItems", "Inputs", a1(r + 2, 1), a1(r + 1 + len(af["items"]), 1))
    return r + 3 + len(af["items"])


def _hdr(s, r, cols, c0=0):
    for j, h in enumerate(cols):
        s.text(r, c0 + j, h, "header")


def _tax_table(c: Ctx, s, r):
    s.text(r, 0, "표 1. 법인세 + 지방소득세 누진 구간 (2026~ 사업연도)", "subtitle")
    _hdr(s, r + 1, ["구간", "하한(백만원)", "상한(백만원)", "세율", "출처"])
    r0 = r + 2
    for i, b in enumerate(c.d["tax"]):
        s.text(r0 + i, 0, f"구간 {i + 1}")
        s.inp(r0 + i, 1, b["from"], "mn")
        s.inp(r0 + i, 2, b["to"], "mn")
        s.inp(r0 + i, 3, b["rate"], "pct1")
        s.text(r0 + i, 4, c.d["tax_src"] if i == 0 else "", "wrap")
    r1 = r0 + len(c.d["tax"]) - 1
    c.range_name("TaxFrom", "Inputs", a1(r0, 1), a1(r1, 1))
    c.range_name("TaxTo", "Inputs", a1(r0, 2), a1(r1, 2))
    c.range_name("TaxRate", "Inputs", a1(r0, 3), a1(r1, 3))
    c.layout["tax_rows"] = (r0, r1)
    s.text(r1 + 1, 0, "마지막 구간 상한은 빈칸(상한 없음). 상태 ✅(law.go.kr 개정이유·국회예산정책처)", "note")
    return r1 + 3


def _rating_table(c: Ctx, s, r):
    s.text(r, 0, "표 2. 신용등급 척도 (Kd 규칙)", "subtitle")
    sc = c.d["common"]["rating_scale"]
    _hdr(s, r + 1, ["순서", "등급"])
    for i, g in enumerate(sc):
        s.text(r + 2 + i, 0, str(i + 1))
        s.inp(r + 2 + i, 1, g, "gen")
    c.range_name("RatingScale", "Inputs", a1(r + 2, 1), a1(r + 1 + len(sc), 1))
    return r + 3 + len(sc)


def _scenario_table(c: Ctx, s, r):
    d = c.d
    keys = d["excel"]["scenarios"]
    labels = d["excel"]["scenario_labels"]
    s.text(r, 0, "표 3. 모회사 시나리오 (시나리오 v2, 사용자 확정 · 증권사 열은 Forecast 시트에서 파생)", "subtitle")
    _hdr(s, r + 1, ["항목"] + [labels[k] for k in keys] + ["", "출처·근거"])
    hr = r + 1
    c.range_name("ScenNames", "Inputs", a1(hr, 1), a1(hr, len(keys)))
    rows = {}
    for i, (pk, lab, kind) in enumerate(SCEN_PARAMS):
        rr = r + 2 + i
        s.text(rr, 0, lab)
        for j, k in enumerate(keys):
            if k == "broker":
                s.text(rr, 1 + j, "(파생)", "note")
                continue
            case = d["scenarios"][k]
            if pk.startswith("g_20") and pk not in ("g_2027",):
                v = case["g_2028_2032"][int(pk[2:]) - 2028]
            elif pk == "op_flag":
                v = 0
            elif pk == "op_2026":
                v = None
            else:
                v = case[pk]
            s.inp(rr, 1 + j, v, kind)
        rows[pk] = rr
    s.text(r + 2, 1 + len(keys) + 1, f"{d['cfg_label']} parent_scenarios.cases · 상태 ⚠️(프로젝트 가정)", "wrap")
    s.text(r + 3, 1 + len(keys) + 1, "2028~2032는 시작값에서 끝값으로 직선 체감", "note")
    c.layout["scen_table"] = {"rows": rows, "keys": keys, "col0": 1}
    return r + 3 + len(SCEN_PARAMS)


def _growth_capex_table(c: Ctx, s, r):
    s.text(r, 0, "표 4. 성장 CAPEX (유상증자 시설자금, 증권신고서 20260616000058)", "subtitle")
    _hdr(s, r + 1, ["구분", "회계연도", "금액(백만원)", "종류", "근거"])
    gc = c.d["growth_capex"]
    for i, g in enumerate(gc):
        rr = r + 2 + i
        s.text(rr, 0, g["period"])
        s.inp(rr, 1, g["year"], "year")
        s.inp(rr, 2, g["amount"], "mn")
        s.inp(rr, 3, g["kind"], "gen")
        s.text(rr, 4, g["basis"], "wrap")
    r0, r1 = r + 2, r + 1 + len(gc)
    c.range_name("GcYear", "Inputs", a1(r0, 1), a1(r1, 1))
    c.range_name("GcAmt", "Inputs", a1(r0, 2), a1(r1, 2))
    c.range_name("GcKind", "Inputs", a1(r0, 3), a1(r1, 3))
    s.text(r1 + 1, 0, "종류 building만 신규 공장 상각 대상(토지 land는 상각 없음). 상태 ⚠️", "note")
    return r1 + 3


def _beta_public(c: Ctx, s, r):
    """P7-C1 public mode: the beta aggregates as inputs (per-peer regression rows are not shown)."""
    b = c.d["public"]["beta"]
    s.text(r, 0, "표 B. 피어 베타 집계 (공개 모드: 피어별 회귀 결과는 표시하지 않음, PC에서 계산한 집계값)", "subtitle")
    _hdr(s, r + 1, ["항목", "값", "출처"])
    s.text(r + 2, 0, "포함 피어 수")
    s.inp(r + 2, 1, b["n"], "int", name="BetaPubN")
    s.text(r + 3, 0, "βu(Blume → Hamada 포함 피어 중앙값, 피어 없으면 대체값)")
    s.inp(r + 3, 1, b["bu"], "beta", name="BetaPubU")
    s.text(r + 4, 0, "R² 중앙값(포함 피어)")
    few = pubcut.few_peers(b["n"]) or b["n"] == 0  # P7-X2a: R² median of fewer than 5 peers not shown
    s.inp(r + 4, 1, pubcut.FEW_PEERS if few and b["r2_median"] is None else b["r2_median"], "beta", name="BetaPubR2")
    s.text(r + 2, 2, f"PC 엔진 집계(βu 출처 {b['src']}). 회귀는 한국거래소 통계정보 기반 계산값", "wrap")
    if b["src"] == pubcut.BETA_SRC:
        s.text(
            r + 3,
            2,
            f"공개 모드: 회귀가 있는 피어 {b['n']}곳 < {pubcut.params()['peer_min_n']}곳이라 중앙값을 표시하지 않고 βu 1.0(시장 평균, "
            "config/p7x2a.yaml public_scope) — 사람이 βu를 직접 입력할 수 있음",
            "wrap",
        )
    return r + 7


def _peer_public(c: Ctx, s, r):
    """P7-C1 public mode: peer names and inclusion, and the quartile multiples as inputs (no per-peer market cap / multiple)."""
    p = c.d["public"]
    s.text(r, 0, "표 P. 피어 목록과 배수 사분위 (공개 모드: 피어별 시가총액·배수는 표시하지 않음)", "subtitle")
    _hdr(s, r + 1, ["회사", "등급(tier)", "포함(1/0)", "재무 기준"])
    for i, x in enumerate(p["peers"]):
        rr = r + 2 + i
        s.text(rr, 0, x["name"])
        s.text(rr, 1, x["tier"])
        s.text(rr, 2, str(x["include"]))
        s.text(rr, 3, x["fs_div"])
    r = r + 3 + len(p["peers"])
    _hdr(s, r, ["배수", "n", "q25", "중앙값", "q75"])
    rows = {}
    for i, (nm, m) in enumerate(p["multiples"].items()):
        rr = r + 1 + i
        s.text(rr, 0, nm)
        s.inp(rr, 1, m["n"], "int")
        for j, q in enumerate(("q25", "med", "q75")):
            s.inp(rr, 2 + j, pubcut.FEW_PEERS if m.get("public_cut") else m[q], "x")  # P7-X2a: n < 5 -> text
        rows[nm] = rr
    s.text(
        r + 1 + len(rows),
        0,
        "PC에서 계산한 집계값(포함 피어의 양(+) 배수, QUARTILE.INC). 재무는 DART 정기보고서, 시가총액은 한국거래소 통계정보. "
        f"공개 모드는 포함 피어 {pubcut.params()['peer_min_n']}곳 미만인 배수의 사분위를 표시하지 않음(config/p7x2a.yaml public_scope)",
        "note",
    )
    c.layout["peer_pub_rows"] = rows
    return r + 3 + len(rows)


def _beta_table(c: Ctx, s, r):
    if c.d.get("public"):
        return _beta_public(c, s, r)
    s.text(r, 0, beta_title(c.d["meta"]), "subtitle")
    cols = ["회사", "등급(tier)", "포함(1/0)", "원 β", "표준오차", "R²", "관측 수", "기간평균 D/E"]
    _hdr(s, r + 1, cols + ["출처"])
    rows = []
    for i, b in enumerate(c.d["beta"]):
        rr = r + 2 + i
        s.text(rr, 0, b["name"])
        s.text(rr, 1, b["tier"])
        s.inp(rr, 2, b["include"], "int")
        s.inp(rr, 3, b["raw"], "beta", krx="beta regression result")
        s.inp(rr, 4, b["se"], "beta", krx="beta regression result")
        s.inp(rr, 5, b["r2"], "beta", krx="beta regression result")
        s.inp(rr, 6, b["n"], "int")
        s.inp(rr, 7, b["de_avg"], "ratio")
        if i == 0:
            s.text(
                rr,
                8,
                "DB beta_p3 (P3-A, src/valuation/beta_p3.py). 포함 = core+extended(config beta.peer_tiers), RFHIC는 참고",
                "wrap",
            )
        rows.append(rr)
    c.layout["beta_rows"] = rows
    return rows[-1] + 3


def _peer_table(c: Ctx, s, r):
    if c.d.get("public"):
        return _peer_public(c, s, r)
    s.text(r, 0, "표 P. 피어 배수 입력 (LTM 2026H1 흐름, 2026-06-30 재무상태표, 기준일 시가총액 · 백만원)", "subtitle")
    cols = [
        "회사",
        "등급(tier)",
        "포함(1/0)",
        "재무 기준",
        "시가총액",
        "총차입금(리스 포함)",
        "현금성",
        "비영업",
        "비지배지분",
        "매출 LTM",
        "EBITDA LTM",
        "지배순이익 LTM",
        "지배지분(자본)",
        "비고(N/M 사유 등)",
        "EBITDA LTM(D&A 보완 전)",
    ]
    _hdr(s, r + 1, cols)
    rows = []
    for i, p in enumerate(c.d["peers"]):
        rr = r + 2 + i
        s.text(rr, 0, p["name"])
        s.text(rr, 1, p["tier"])
        s.inp(rr, 2, p["include"], "int")
        s.text(rr, 3, p["fs_div"])
        s.inp(rr, 4, p["mktcap"], "mn", krx="peer market cap")
        for j, k in enumerate(("debt", "cash_like", "non_operating", "nci", "revenue", "ebitda", "ni", "equity"), start=5):
            s.inp(rr, j, p[k], "mn")
        s.text(rr, 13, p["note"] or "", "wrap")
        if "ebitda_pre" in p:
            s.inp(rr, 14, p["ebitda_pre"], "mn")
        rows.append(rr)
    s.text(
        rows[-1] + 1,
        0,
        "출처: DB peer_p3(P3-A 정의: EV = 시가총액 + 총차입금 − 현금성 − 비영업 + 비지배), 재무 DART 정기보고서(fs_std·fs_raw). "
        "포함 = core+extended(config p3c1.relative.tiers). 시가총액은 한국거래소 통계정보",
        "note",
    )
    c.layout["peer_rows"] = rows
    return rows[-1] + 3


# ---------------------------------------------------------------- FS_Hist

FS_LABELS = {
    "revenue": "매출액",
    "cogs": "매출원가",
    "operating_income": "영업이익",
    "net_income": "당기순이익",
    "capex_ppe": "유형자산 취득(CAPEX)",
    "capex_intangibles": "무형자산 취득",
    "dna": "감가상각비·무형자산상각비(주석)",
    "receivables": "매출채권",
    "inventories": "재고자산",
    "trade_payables": "매입채무",
    "contract_liabilities": "계약부채",
    "cash": "현금및현금성자산",
    "short_term_fin": "단기금융자산",
    "total_debt": "총차입금(API 표준 계정)",
    "lease_liabilities": "리스부채",
    "long_term_fin": "장기금융자산(비영업)",
    "total_equity": "자본총계",
    "ppe": "유형자산",
    "intangibles": "무형자산",
    "rou_assets": "사용권자산",
    "nci": "비지배지분",
    "equity_parent": "지배주주지분",
}


def fs_hist(c: Ctx):
    d, s = c.d, c.sheet("FS_Hist")
    s.text(0, 0, "FS_Hist — 엔진이 쓴 과거 재무 (백만원, DART 정기보고서 API·원문 주석)", "title")
    s.text(
        1,
        0,
        "열마다 주 접수번호(가장 많은 줄의 출처), 기타 접수번호는 비교 칸 출처. 값이 없는 줄은 0(엔진과 같음)"
        + (
            ", 재무 자료가 없는 기간은 빈칸(수식에서 0으로 계산)"
            if any(info.get("blank") for div in d["fs"] for info in d["fs"][div].values())
            else ""
        )
        + ". 입력 셀",
        "note",
    )
    cols = [("OFS", k) for k in d["fs"].get("OFS", {})] + [("CFS", k) for k in d["fs"].get("CFS", {})]
    s.widths({0: 34, 1: 20, **{2 + j: 14 for j in range(len(cols))}})
    s.ws.freeze_panes(7, 2)
    for i, h in enumerate(["재무제표", "기간", "주 접수번호", "기타 접수번호"]):
        s.text(3 + i, 0, h, "header")
        s.text(3 + i, 1, "", "header")
    for j, (div, k) in enumerate(cols):
        info = d["fs"][div][k]
        basis = div if "OFS" in d["fs"] else d["meta"].get("fs_div", div)  # mechanical: one column set on the config basis
        s.text(3, 2 + j, "별도(OFS)" if basis == "OFS" else "연결(CFS)", "header")
        s.text(4, 2 + j, f"{info['year']} {info['period']}", "header")
        s.text(5, 2 + j, info["rcept"], "header")
        s.text(6, 2 + j, ", ".join(info["rcept_other"]) or "-", "note")
    accts = list(dict.fromkeys([a for div, k in cols for a in d["fs"][div][k]["values"]]))
    refs = {}
    for i, a in enumerate(accts):
        rr = 7 + i
        s.text(rr, 0, FS_LABELS.get(a, a))
        s.text(rr, 1, a, "note")
        for j, (div, k) in enumerate(cols):
            v = d["fs"][div][k]["values"].get(a)
            if v is None and not (a == "dna" and a in d["fs"][div][k]["values"]) and not d["fs"][div][k].get("blank"):
                continue  # P7-X2b X7: a period without statements is a blank input cell (not skipped, not 0)
            refs[(div, k, a)] = s.inp(rr, 2 + j, v, "mn")  # P7-B2 B2-F5: a missing D&A period is a blank input cell
    c.layout["fs_refs"] = refs
    r = 7 + len(accts) + 2
    if d.get("bs_lines"):
        s.text(r, 0, f"연결 재무상태표 금융자산 줄 분류 ({d['meta']['bs_date']}, 백만원) — {d['bs_lines_src']}", "subtitle")
        for j, h in enumerate(["계정", "구간", "분류", "금액"]):
            s.text(r + 1, j, h, "header")
        for i, ln in enumerate(d["bs_lines"]):
            rr = r + 2 + i
            s.text(rr, 0, ln["name"])
            s.text(rr, 1, {"CA": "유동", "NCA": "비유동"}.get(ln["section"], ln["section"]))
            s.inp(rr, 2, ln["class"], "gen")
            s.inp(rr, 3, ln["amount"], "mn")
        r0, r1 = r + 2, r + 1 + len(d["bs_lines"])
        c.range_name("BsName", "FS_Hist", a1(r0, 0), a1(r1, 0))
        c.range_name("BsClass", "FS_Hist", a1(r0, 2), a1(r1, 2))
        c.range_name("BsAmt", "FS_Hist", a1(r0, 3), a1(r1, 3))
        s.text(
            r1 + 1,
            0,
            "분류 cash_like = 현금성(유동: 현금·단기금융·공정가치·기타 유동 금융자산), non_operating = 비영업(비유동: 공정가치·장기금융·기타 금융자산·관계기업·투자부동산). 대상과 피어에 같은 규칙(peer_p3.classify) ⚠️ '기타 금융자산'에는 대여금이 섞일 수 있음",
            "note",
        )
        r = r1 + 3
    if not d.get("segments"):
        c.layout["seg_refs"] = {}
        return
    s.text(r, 0, "부문 주석 (내부거래 제거 전, 백만원)", "subtitle")
    labs = ["FY2025", "1H25", "1H26"]
    s.text(r + 1, 0, "항목", "header")
    s.text(r + 1, 1, "", "header")
    for j, ln in enumerate(labs):
        s.text(r + 1, 2 + j, ln, "header")
    s.text(r + 1, 5, "출처", "header")
    seg = d["segments"]
    srefs = {}
    items = [
        ("sub", "revenue", f"{d['market']['sub_name']} 매출"),
        ("sub", "op", f"{d['market']['sub_name']} 영업이익"),
        ("sub", "depreciation", f"{d['market']['sub_name']} 감가상각비"),
        ("parent", "revenue", "모회사(패키지) 매출"),
        ("parent", "op", "모회사(패키지) 영업이익"),
    ]
    for i, (ent, it, lab) in enumerate(items):
        rr = r + 2 + i
        s.text(rr, 0, lab)
        s.text(rr, 1, f"{ent}.{it}", "note")
        for j, ln in enumerate(labs):
            srefs[(ent, it, ln)] = s.inp(rr, 2 + j, seg[ln][ent][it], "mn")
    s.text(r + 2, 5, "; ".join(f"{ln}: {seg[ln]['source']}" for ln in labs), "wrap")
    c.layout["seg_refs"] = srefs
