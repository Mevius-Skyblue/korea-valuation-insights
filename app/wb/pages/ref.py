"""Reference pages (A report style): practice discount rates, forecasts vs actuals, control premium, methodology.
Aggregates only (no deal, company or evaluator); n < 10 flagged. The same content in PC and public mode."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.wb import charts as ch
from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx

LAB = {"mrp": "MRP", "srp": "SRP", "wacc": "WACC", "g": "영구성장률", "tv_share": "영구가치 비중", "rf": "Rf"}


def _nav(c: nav.Ctx) -> None:
    st.markdown("<div class='wb-refnav'><b>KVI</b><span class='wb-kpi-note'>참고 자료</span></div>", unsafe_allow_html=True)
    cols = st.columns(len(nav.REFS) + 1)
    for i, (pid, label) in enumerate(nav.REFS):
        cols[i].button(label, key=f"ref_nav_{pid}", type="primary" if pid == c.page else "secondary", on_click=nav.go, args=(pid,),
                       width="stretch")
    cols[-1].button("워크벤치로 →", key="ref_back", on_click=nav.go, args=("result" if c.sid else "select",), width="stretch")


def render(c: nav.Ctx) -> None:
    _nav(c)
    {"ref_rates": _rates, "ref_accuracy": _accuracy, "ref_premium": _premium, "ref_method": _method, "ref_guide": _guide}[c.page](c)
    st.markdown(f"<div class='wb-foot'>투자 권유가 아닙니다. 공개 공시를 집계한 예시입니다. 개별 거래·회사·평가기관은 표시하지 않습니다. "
                f"n &lt; 10인 칸은 옅게 표시합니다(일반화 주의). 기준일 {M.AS_OF}.</div>", unsafe_allow_html=True)


def _rates(c: nav.Ctx) -> None:
    p = M.practice()
    full, late = p["full"], p["late"]
    y0, y1 = p["years"]
    st.markdown(f"<p class='wb-eyebrow'>합병 외부평가의견서 할인율 표 · DART · {y0}~{y1} · 기준일 {M.AS_OF}</p>"
                "<h1 class='wb-ref-title'>실무 할인율 관행</h1><p class='wb-ref-lead'>외부평가기관이 실제 합병 평가에 쓴 할인율 가정을 모았습니다. "
                "내가 잡은 가정이 실무와 비교해 어디쯤인지 확인하는 용도입니다. 표본은 스팩 합병 중심이라 상장 대형사와 비교할 때 주의합니다.</p>",
                unsafe_allow_html=True)
    with ui.card("rates_find", None, plain=True):
        st.markdown(f"<div class='wb-find'><div><b>{F.pct(late['mrp']['median'], 0)}</b><span>2023년부터 MRP는 한공회 가이던스 8%로 수렴. "
                    f"그 전에는 정보 단말 과거 평균형 9~11%</span></div><div><b>{p['rf10']} / {p['rf_marked']}</b><span>Rf 만기를 적은 의견서 중 국고채 "
                    f"10년을 쓴 건수</span></div><div><b>{F.pct(full['g']['median'])}</b><span>영구성장률 중앙값. 사분위도 {F.pct(full['g']['q1'])}~"
                    f"{F.pct(full['g']['q3'])}로 사실상 표준값</span></div></div>", unsafe_allow_html=True)
    st.markdown("<h2 class='wb-ref-h2'>전체 분포</h2>", unsafe_allow_html=True)
    with ui.card("rates_tab", None, plain=True):
        rows = [[LAB[m], int(full[m]["n"]), F.pct(full[m]["q1"]), F.pct(full[m]["median"]), F.pct(full[m]["q3"])]
                for m in ("mrp", "srp", "wacc", "g", "tv_share", "rf") if m in full]
        ui.table(["항목", "n", "하위 25%", "중앙값", "상위 25%"], rows, num_cols=(1, 2, 3, 4))
    st.markdown("<h2 class='wb-ref-h2'>연도별 MRP 중앙값</h2><p class='wb-kpi-note'>옅은 막대 = 표본 10건 미만(일반화 주의). 검정 막대부터 한공회 가이던스 시기. "
                "막대 높이는 0%부터.</p>", unsafe_allow_html=True)
    with ui.card("rates_year", None, plain=True):
        ar = pd.read_csv(M.APP_DATA / "assumptions_range.csv")
        yr = ar[(ar.year_from == ar.year_to) & (ar.group == "전체") & (ar.metric == "mrp") & (ar.n > 0)].copy()
        yr["연도"] = yr.year_from.astype(int).astype(str)
        st.altair_chart(ch.year_bars(yr, "연도", "median", "n", title="MRP 중앙값", hl_from=2023), width="stretch")
    st.markdown("<h2 class='wb-ref-h2'>MRP 출처 분류</h2>", unsafe_allow_html=True)
    with ui.card("rates_src", None, plain=True):
        so = pd.read_csv(M.APP_DATA / "sources.csv")
        so = so[(so.group == "전체") & (so.item == "MRP") & (so.source_class != "값 미확인")]
        t = so.groupby("source_class")["count"].sum().sort_values(ascending=False)
        ui.table(["출처 분류", "건수"], [[tx.mrp_source_label(k), int(v)] for k, v in t.items()], num_cols=(1,),
                 caption="값을 읽은 의견서만. 분류는 프로젝트 규칙(🔸)")
    st.markdown("<h2 class='wb-ref-h2'>한공회 규모위험 프리미엄 인용(의견서 2차 인용 🔸)</h2>", unsafe_allow_html=True)
    with ui.card("rates_srp", None, plain=True):
        sc = pd.read_csv(M.APP_DATA / "srp_cites.csv")
        ui.table(["인용 기준 연도", "구간(의견서 표기)", "값", "건수"], [[str(r.cited_year), r.band, F.pct(r.srp), int(r["count"])] for _, r in sc.iterrows()],
                 num_cols=(2, 3), caption="같은 구간 이름도 기준 연도마다 값이 다르다. 구간 경계(규모 기준)는 원문 미확인(⚠️)")


def _accuracy(c: nav.Ctx) -> None:
    st.markdown("<p class='wb-eyebrow'>합병 외부평가 추정 vs 합병 뒤 사업보고서 실적 · DART</p><h1 class='wb-ref-title'>추정 vs 실적</h1>"
                "<p class='wb-ref-lead'>외부평가의견서의 매출·영업이익 추정을 합병 뒤 실제 실적과 비교했습니다. 달성률 = 실적 ÷ 추정. "
                "높은 예측일수록 달성률이 낮게 나오는 기계적 성분이 있습니다.</p>", unsafe_allow_html=True)
    ac = pd.read_csv(M.APP_DATA / "achievement.csv")
    a = ac[(ac.period == "전체") & (ac.group == "스팩")]
    st.markdown("<h2 class='wb-ref-h2'>스팩 합병 달성률(중앙값)</h2>", unsafe_allow_html=True)
    with ui.card("acc_tab", None, plain=True):
        acct = {"revenue": "매출", "operating_income": "영업이익", "매출": "매출", "영업이익": "영업이익"}
        rows = [[acct.get(r.account, r.account), f"{int(r.h)}차연도", int(r.n), F.pct(r["median"], 1), F.pct(r.q1, 1), F.pct(r.q3, 1),
                 F.pct(r.shortfall_share, 1)] for _, r in a.iterrows()]
        ui.table(["계정", "연도", "n", "중앙값", "하위 25%", "상위 25%", "미달 비율"], rows, num_cols=(2, 3, 4, 5, 6))
    st.markdown("<h2 class='wb-ref-h2'>예측 매출 CAGR 구간별 매출 달성률</h2><p class='wb-kpi-note'>가정 화면의 '사업계획 점검'이 쓰는 표입니다.</p>",
                unsafe_allow_html=True)
    with ui.card("acc_band", None, plain=True):
        cb = pd.read_csv(M.APP_DATA / "cagr_bands.csv")
        ui.table(["구간", "CAGR 범위", "거래 수", "1차", "2차", "3차"],
                 [[r.label, f"{F.pct(r.cagr_lo, 1)}~{F.pct(r.cagr_hi, 1)}", int(r.n_deals), f"{F.pct(r.h1_median, 1)} (n={int(r.h1_n)})",
                   f"{F.pct(r.h2_median, 1)} (n={int(r.h2_n)})", f"{F.pct(r.h3_median, 1)} (n={int(r.h3_n)})"] for _, r in cb.iterrows()],
                 num_cols=(2,), min_width=560)
    st.markdown("<h2 class='wb-ref-h2'>보도 수치와 나란히</h2>", unsafe_allow_html=True)
    with ui.card("acc_fss", None, plain=True):
        fs = pd.read_csv(M.APP_DATA / "fss_compare.csv")
        ui.table(["출처", "범위", "미달 비율", "평균 미달률", "상태"], [[tx.plain_label(r.label), r.scope, F.pct(r.shortfall_share, 1), F.pct(r.mean_shortfall, 1), r.status]
                                                                for _, r in fs.iterrows()], num_cols=(2, 3))


def _premium(c: nav.Ctx) -> None:
    st.markdown("<p class='wb-eyebrow'>최대주주 변경을 수반하는 주식양수도 · 2010~2026 공시 · 주 표본</p><h1 class='wb-ref-title'>경영권 프리미엄</h1>"
                "<p class='wb-ref-lead'>최대주주 지분 거래 가격이 공시 전(문서 신호 직전 20거래일 VWAP) 시장가보다 얼마나 높았는지 집계했습니다. "
                "음(−)의 프리미엄도 포함합니다. 결과 화면의 블록 가격은 아래 규칙으로 고른 범위를 씁니다.</p>", unsafe_allow_html=True)
    with ui.card("prem_ref", None, plain=True):
        from src.workbench.public_deploy import premium_public, premium_ref_table
        if M.public_deploy() and not premium_public():     # P7-C3 record; P7-C3b publishes the aggregates
            raise M.PublicDataUnavailable(M.PREMIUM_WITHHELD)
        if not M.public_deploy():
            M.need_db("경영권 프리미엄 표본 집계")
        t = premium_ref_table()
        allr = t["all"]
        st.markdown(f"<div class='wb-find'><div><b>{F.pct(allr['median'], 1)}</b><span>주 표본 중앙값(n={allr['n']})</span></div>"
                    f"<div><b>{F.pct(allr['q25'], 1)}~{F.pct(allr['q75'], 1)}</b><span>사분위 범위</span></div>"
                    f"<div><b>{F.pct(allr['neg'], 0)}</b><span>음(−)의 프리미엄 비율</span></div></div>", unsafe_allow_html=True)
        lab = {"lt25": "지분 25% 미만", "25to50": "25~50%", "gt50": "50% 초과", "strategic": "전략적", "financial": "재무적", "other": "기타"}
        rows = [[r["layer"], lab.get(r["key"], r["key"]), r["n"], F.pct(r["median"], 1), F.pct(r["q25"], 1), F.pct(r["q75"], 1),
                 F.pct(r["neg"], 0), "n<10 주의" if r["warn_n10"] else ""] for r in t["rows"]]
        ui.table(["층", "구간", "n", "중앙값", "하위 25%", "상위 25%", "음(−) 비율", ""], rows, num_cols=(2, 3, 4, 5, 6), min_width=600,
                 caption="대표값 = 문서 신호 직전 20거래일 VWAP 기준 프리미엄(bu20_doc). 집계(건수·분위수)만 보이고 거래별 값·거래 이름은 "
                         "표시하지 않습니다. 출처: 프로젝트 DB(KIND 서식 71207·71209) · 한국거래소 통계정보")
        bd = pd.DataFrame([{"구간": r["key"], "중앙값": r["median"]} for r in t["rows"] if r["layer"] == "시총 백분위 구간"])
        if len(bd):
            st.altair_chart(ch.hbars(bd, "구간", "중앙값", title="시총 백분위 구간별 중앙값"), width="stretch")
    st.markdown("<h2 class='wb-ref-h2'>결과 화면의 범위 고르는 규칙</h2><div class='wb-method'><ul>"
                "<li>KOSPI → 비슷한 거래 이웃 50건의 사분위</li><li>KOSDAQ 시총 백분위 상위 20% → 이웃 50건</li>"
                "<li>그 밖은 분위 회귀(사전 등록 기준을 넘음), 회귀와 이웃 중앙값이 10%p 넘게 다르면 이웃</li>"
                "<li>회귀 미채택이면 시총 백분위 구간 표</li></ul></div>", unsafe_allow_html=True)


def _guide(c: nav.Ctx) -> None:
    """이용 안내 (config/p7c3.yaml public_app.notice)."""
    st.markdown("<p class='wb-eyebrow'>KVI 밸류에이션 워크벤치</p><h1 class='wb-ref-title'>이용 안내</h1>"
                "<p class='wb-ref-lead'>공개 자료와 정한 규칙으로 상장사 주식가치 초안을 만들고, 사람이 판단할 곳을 주당 영향이 큰 순서로 "
                "보여 주는 작업 도구입니다. 결과는 가정 하의 추정 내재가치(예시)이며 투자 권유가 아닙니다.</p>", unsafe_allow_html=True)
    secs = [
        ("쓰는 법", ["1단계에서 회사를 고르고 평가를 시작합니다(자동 초안 → 새 세션)",
                   "2~4단계에서 자료와 가정을 확인하고, 판단 목록의 후보를 고르거나 직접 입력하거나 그대로 유지합니다",
                   "5단계에서 주가·VWAP을 넣고 확정하면 수식이 살아 있는 엑셀 모델과 보고서 초안을 내려받습니다"]),
        ("데이터 출처", ["재무·공시: DART 전자공시(금융감독원) — 숫자마다 공시 접수번호 링크",
                      "금리: 한국은행 ECOS(국고채·회사채 금리, 기준일 값)",
                      "시세: 한국거래소 시세는 이 공개 화면에 없습니다. 대상 회사 종가·20일 VWAP(그리고 상장 종속회사·우선주 종가)은 사용하는 사람이 직접 넣습니다",
                      "피어 정보는 이름·포함 여부와 집계값(무부채 베타 중앙값·배수 사분위 등)만 보여 줍니다"]),
        ("직접 넣은 시세", ["넣은 값의 정확성과 출처 확인은 입력한 사람의 책임입니다",
                         "넣은 값은 이 브라우저 작업 공간과 내려받은 파일에만 남습니다"]),
        ("공개 범위", ["회사 목록은 개발·검증에 이미 쓴 회사로 한정합니다(평가 가능 회사와 자동 평가 범위 밖 회사). 새 회사의 초안은 PC 모드에서 만듭니다",
                     "경영권 프리미엄은 집계(건수·분위수·구간 표)만 보여 주고 거래별 값·거래 이름은 보이지 않습니다. 시총 백분위는 기준일 값으로 "
                     "고정되고(입력한 주가로 바뀌지 않음), 블록 1주당 가격은 20일 VWAP을 넣을 때만 계산합니다",
                     "피어 구성을 바꾸는 계산(피어 빼기)은 피어별 시세가 있어야 해서 PC 모드에서만 합니다. 무부채 베타·D/E는 직접 넣을 수 있습니다"]),
        ("저장", ["세션은 이 브라우저 창의 임시 작업 공간에만 있고, 새로 고치거나 6시간 동안 쓰지 않으면 지워집니다",
                 "1단계의 세션 파일 내려받기·불러오기로 이어서 작업합니다(파일에 서명이 있어 바뀐 파일은 불러오지 않습니다)"]),
        ("면책", ["투자 권유가 아닙니다. 특정 종목의 가치·가격에 대한 의견이 아니며 정확성·완전성을 보증하지 않습니다",
                 "자동 생성 초안이므로 평가방법 선택 근거·주요 가정의 합리성·평가상 한계는 사람이 작성합니다",
                 "금융투자업(투자자문·투자일임) 등록·신고를 하지 않은 개인 학습·포트폴리오 프로젝트입니다"]),
        ("문의", ["GitHub 저장소의 이슈로 남겨 주세요(개인 연락처는 받지 않습니다)"]),
    ]
    with ui.card("guide", None, plain=True):
        st.markdown("<div class='wb-method'>" + "".join(
            f"<h2 class='wb-ref-h2'>{ui.esc(t)}</h2><ul>" + "".join(f"<li>{ui.esc(x)}</li>" for x in items) + "</ul>" for t, items in secs)
            + "</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='wb-kpi-note'>공개 저장소: <a href='{REPO_URL}' target='_blank' rel='noopener'>{REPO_URL}</a></p>",
                    unsafe_allow_html=True)


REPO_URL = "https://github.com/Mevius-Skyblue/korea-valuation-insights"


def _method(c: nav.Ctx) -> None:
    st.markdown("<p class='wb-eyebrow'>KVI 밸류에이션 워크벤치</p><h1 class='wb-ref-title'>방법론</h1>"
                "<p class='wb-ref-lead'>이 도구는 정답 주가를 자동으로 내는 기계가 아니라, 공개 자료로 초안을 빠르게 만들고 "
                "사람이 판단할 곳을 주당 영향이 큰 순서로 보여 주는 작업 도구입니다.</p>", unsafe_allow_html=True)
    secs = [
        ("1. 흐름", ["회사 선택 → 자동 초안(공시 수집·피어 선택·평가) → 판단 목록 처리 → 확정 → 엑셀 모델·보고서 초안",
                   "변경 1건마다 새 버전이 생기고 감사 기록(시각·항목·전 → 후·이유)이 남습니다. 같은 버전은 언제 다시 계산해도 같은 결과입니다"]),
        ("2. 자동 평가 게이트(G1~G8)", ["G1 금융업, G1b 금융회사형 재무구조 → 범위 밖(현금흐름 할인이 맞지 않음). 비금융 지주회사는 재무구조로 판단",
                                    "G2·G3 최근 3년 적자 → 매출 기준(100억원, 시가총액의 5%)을 넘으면 적자 경로, 아니면 범위 밖",
                                    "G4 매출 100억원 미만, G5 12월 결산 아님 → 범위 밖",
                                    "G6 상장 종속회사가 있으면 SOTP 경로, G7 필수 재무 없음 → 범위 밖, G8 피어 3곳 미만 → 피어 배수는 계산 불가 + 판단 1순위"]),
        ("3. 평가 경로", ["일반: 연결 DCF − 비지배지분(장부). 기본 예측은 5년 중앙값 이익률에서 피어 이익률 쪽으로 수렴, 출발 성장률은 자기 CAGR과 피어 성장률의 평균",
                       "SOTP: 모회사 별도 DCF(배당금수익 제외) + 상장 종속회사 지분 × 종가(할인 기본 0%) + 비상장 지분 장부",
                       "적자 경로: 피어 EV/Sales 사분위 범위 + 전환 DCF(최근 이익률에서 2032년 피어 이익률로) + 자금 소요 표시"]),
        ("4. 피어 고르기와 완화", ["KSIC 업종 코드 → 시가총액 0.3~3배 → 3년 흑자 → 지주형 제외. 모자라면 0.1~10배, 그다음 업종 코드를 한 자리씩 넓힘",
                               "피어 사업 개요(공시 첫 문단)를 함께 보여 주고, 유사성은 사람이 판단합니다"]),
        ("5. 보류(틀린 숫자보다 평가 불가)", ["주식가치 ≤ 0, 영구가치 비중 > 85%, 피어 중앙값·시장가 양쪽과 3배 이상 차이, 핵심 지표 결측이면 '자동 결과 보류'",
                                       "보류여도 초안은 만들고, 원인 분해(가치 구성·역산)와 1순위 판단을 결과 위에 보여 줍니다. 사람이 확정하면 확정값이 대표값"]),
        ("6. 판단 목록", ["항목마다 주당 영향을 계산해 큰 순서로 정렬(상위 5개가 전체 영향의 대부분을 차지하도록)",
                        "후보 값(이미 계산한 대안)을 누르면 채택, 직접 입력하면 수정, 자동값이 맞으면 그대로 유지. 처리 상태와 전 → 후 주당이 남습니다"]),
        ("7. 모드", ["PC 모드: 한국거래소 통계정보(시세)를 포함한 전체 화면",
                   "공개 모드: 시세는 사용자가 넣은 값만 쓰고 보여 줍니다. 피어별 시가총액·배수·베타 회귀 값은 숨기고 사분위·중앙값만. 내보낸 파일은 한국거래소 원값 검사 0건일 때만 내려받기"]),
        ("8. 숫자의 출처", ["재무: DART 공시(접수번호 링크), 금리: 한국은행 ECOS, 시세: 한국거래소 통계정보(PC) 또는 사용자 입력(공개)",
                          "엑셀 모델은 수식이 살아 있고, 엑셀 수식으로 다시 계산한 값이 계산 엔진 값과 같은지 대조합니다"]),
    ]
    with ui.card("method", None, plain=True):
        st.markdown("<div class='wb-method'>" + "".join(
            f"<h2 class='wb-ref-h2'>{ui.esc(t)}</h2><ul>" + "".join(f"<li>{ui.esc(x)}</li>" for x in items) + "</ul>" for t, items in secs)
            + "</div>", unsafe_allow_html=True)
        st.markdown("<h2 class='wb-ref-h2'>용어</h2>", unsafe_allow_html=True)
        ui.table(["용어", "뜻"], [[k, v] for k, v in tx.GLOSSARY.items()])
