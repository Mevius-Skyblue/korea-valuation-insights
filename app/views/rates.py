"""Page 1: discount-rate assumptions in practice (P5-B, 157 opinions). Aggregates by valuation year and group:
MRP / SRP / WACC / g / terminal-value share / Rf (median, quartiles, n), Rf tenor, source classes, 한공회 SRP quotes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib.common import SMALL_N, footer, grey_small, load, small_n_note  # noqa: E402

LABEL = {"mrp": "MRP", "srp": "SRP", "wacc": "WACC", "g": "영구성장률 g", "tv_share": "영구가치 비중", "rf": "Rf"}

st.title("실무 할인율 가정")
st.caption("증권신고서(합병) 외부평가 의견서의 할인율 표를 집계했다. 연도 = 평가기준일 연도. 값을 읽지 못한 칸은 n에서 빠진다.")
ar = load("assumptions_range.csv")
years = sorted(set(ar.year_from))
c1, c2 = st.columns([3, 2])
y0, y1 = c1.select_slider("평가기준 연도", options=years, value=(years[0], years[-1]))
group = c2.radio("합병 유형", ["전체", "스팩", "비스팩"], horizontal=True)

# ---- selected range: one row per metric
sel = ar[(ar.year_from == y0) & (ar.year_to == y1) & (ar.group == group)].set_index("metric").loc[list(LABEL)]
tab = pd.DataFrame({"항목": [LABEL[k] for k in sel.index], "n": sel.n.astype(int), "중앙값": sel["median"], "Q1": sel.q1, "Q3": sel.q3})
st.subheader(f"{y0}\\~{y1} · {group}: 중앙값과 사분위")
st.dataframe(grey_small(tab).format({"중앙값": "{:.2%}", "Q1": "{:.2%}", "Q3": "{:.2%}"}, na_rep="—"), hide_index=True,
             width="stretch")
small_n_note(tab)

# ---- by year (single-year rows)
st.subheader("연도별 추이")
metric = st.selectbox("항목", list(LABEL), format_func=LABEL.get, index=0)
yr = ar[(ar.year_from == ar.year_to) & (ar.group == group) & (ar.metric == metric) & ar.year_from.between(y0, y1)].copy()
yr["연도"] = yr.year_from.astype(str)
yr["표본"] = yr.n.map(lambda n: f"n<{SMALL_N}" if n < SMALL_N else f"n≥{SMALL_N}")
base = alt.Chart(yr[yr.n > 0])
band = base.mark_area(opacity=0.2).encode(x=alt.X("연도:O", title="평가기준 연도", axis=alt.Axis(labelAngle=0)), y=alt.Y("q1:Q", axis=alt.Axis(format="%"), title=LABEL[metric]),
                                          y2="q3:Q")
line = base.mark_line(color="#1f77b4").encode(x="연도:O", y="median:Q")
pts = base.mark_circle(size=70, opacity=1).encode(
    x="연도:O", y="median:Q", color=alt.Color("표본:N", scale=alt.Scale(domain=[f"n≥{SMALL_N}", f"n<{SMALL_N}"], range=["#1f77b4", "#bdbdbd"])),
    tooltip=["연도", alt.Tooltip("median:Q", format=".2%"), "n"])
st.altair_chart(band + line + pts, width="stretch")
st.caption("선 = 중앙값, 띠 = 사분위(Q1~Q3), 회색 점 = n < 10".replace("~", r"\~"))
show = yr[["연도", "n", "median", "q1", "q3"]].rename(columns={"median": "중앙값", "q1": "Q1", "q3": "Q3"})
st.dataframe(grey_small(show).format({"중앙값": "{:.2%}", "Q1": "{:.2%}", "Q3": "{:.2%}"}, na_rep="—"), hide_index=True,
             width="stretch")
small_n_note(show)

# ---- Rf tenor
st.subheader("Rf 만기 표시")
rt = load("rf_tenor.csv")
rt = rt[(rt.group == group) & rt.year.between(y0, y1)]
tot = rt.groupby("tenor")["count"].sum()
st.write(" · ".join(f"{k} {int(tot.get(k, 0))}건" for k in ("10년", "5년", "기타", "미표시")) + " (만기를 적은 의견서 대부분이 국고채 10년)")
st.altair_chart(alt.Chart(rt.assign(연도=rt.year.astype(str))).mark_bar().encode(
    x=alt.X("연도:O"), y=alt.Y("count:Q", title="건수"), color=alt.Color("tenor:N", title="만기")), width="stretch")

# ---- source classes
st.subheader("출처 분류 변화")
item = st.radio("항목 ", ["MRP", "Rf", "SRP"], horizontal=True)
so = load("sources.csv")
so = so[(so.group == group) & (so.item == item) & so.year.between(y0, y1) & (so.source_class != "값 미확인")]
st.altair_chart(alt.Chart(so.assign(연도=so.year.astype(str))).mark_bar().encode(
    x="연도:O", y=alt.Y("count:Q", title="건수", stack="normalize", axis=alt.Axis(format="%")),
    color=alt.Color("source_class:N", title="출처 분류"), tooltip=["연도", "source_class", "count"]), width="stretch")
st.caption("값을 읽은 의견서만(값 미확인 제외). 2015\\~2022는 Bloomberg 과거 평균형 MRP가 많고 2023년 이후는 한공회 가이던스 8%가 대부분이다. 분류는 프로젝트 규칙(🔸).")

# ---- SRP quotes
st.subheader("한공회 규모위험 프리미엄 인용 연표 🔸 (의견서 2차 인용)")
sc = load("srp_cites.csv").rename(columns={"cited_year": "인용 기준 연도", "band": "구간 이름(의견서 표기)", "srp": "값", "count": "건수",
                                           "filed_years": "신고서 연도"})
st.dataframe(sc.style.format({"값": "{:.2%}"}), hide_index=True, width="stretch")
st.caption("같은 구간 이름도 기준 연도마다 값이 다르다. 구간 경계(규모 기준)는 원문 미확인이다. 연도·유형 필터와 무관한 전체 표.")
footer()
