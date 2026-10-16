"""Page 2: opinion forecasts vs actuals (P5-B). Achievement = actual / forecast by account x year after merger x period,
the FSS press figures side by side, and a CAGR-band lookup (same rule and values as the P6-A Excel reference)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib.common import footer, grey_small, load, pct, small_n_note  # noqa: E402

st.title("외부평가 추정 vs 실적")
st.caption("달성률 = 실적 ÷ 의견서 예측. h = 합병 회계연도부터 1·2·3차연도. 일부 기간 연도(부분 연도)는 뺐다.")
with st.expander("해석 주의", expanded=True):
    st.markdown("- 달성률의 분모가 예측이라, 예측이 높을수록 달성률이 낮게 나오는 **기계적 성분**이 있다\n"
                "- 표본은 **스팩 합병 중심**이다(비스팩은 사후정보 비교표 미기재가 많아 n이 작다)\n"
                "- 2017\\~2019 건은 **정정 전 원본 신고서** 숫자다(정정본 원문 미수신)\n"
                "- 개별 거래·회사·평가기관은 표시하지 않는다")
ac = load("achievement.csv")
c1, c2 = st.columns(2)
period = c1.selectbox("기간", ["전체", "2015~2019", "2020~2022", "2023~2026"])
group = c2.radio("합병 유형", ["스팩", "비스팩"], horizontal=True)
d = ac[(ac.period == period) & (ac.group == group)].sort_values(["account", "h"])
tab = d[["account", "h", "n", "shortfall_share", "median", "q1", "q3"]].rename(
    columns={"account": "계정", "h": "차연도", "shortfall_share": "미달 비율", "median": "달성률 중앙값", "q1": "Q1", "q3": "Q3"})
st.dataframe(grey_small(tab).format({c: "{:.1%}" for c in ("미달 비율", "달성률 중앙값", "Q1", "Q3")}, na_rep="—"),
             hide_index=True, width="stretch")
small_n_note(tab)
if len(d):
    ch = alt.Chart(d.assign(차연도=d.h.astype(str) + "차"))
    bars = ch.mark_bar().encode(x=alt.X("차연도:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("median:Q", axis=alt.Axis(format="%"), title="달성률 중앙값"),
                                color=alt.Color("account:N", title="계정"), xOffset="account:N",
                                tooltip=["account", "차연도", alt.Tooltip("median:Q", format=".1%"), "n"])
    err = ch.mark_rule().encode(x="차연도:N", xOffset="account:N", y="q1:Q", y2="q3:Q")
    st.altair_chart(bars + err, width="stretch")
    st.caption("막대 = 중앙값, 세로선 = 사분위(Q1\\~Q3). 100% = 예측대로.")

st.subheader("금감원 보도치와 나란히 (판정에 쓰지 않음)")
fs = load("fss_compare.csv")
st.dataframe(fs.rename(columns={"label": "구분", "scope": "대상", "shortfall_share": "영업이익 미달 비율", "mean_shortfall": "평균 미달률",
                                "status": "상태"}).style.format({"영업이익 미달 비율": "{:.1%}", "평균 미달률": "{:.1%}"}),
             hide_index=True, width="stretch")
st.caption("⚠️ 금감원 수치는 언론 보도 인용이고 정의·기간 원문은 확인하지 못했다. 이 프로젝트 값은 스팩 영업이익 1·2차연도를 합친 행 기준.")

st.subheader("도구: 예측 매출 CAGR → 참고 구간")
cb = load("cagr_bands.csv")
x = st.number_input("예측 매출 CAGR(%) — 첫 추정 연도부터 5개 연도", value=15.0, step=1.0, format="%.1f") / 100
band = 1 + sum(x >= cb.cagr_lo.iloc[k] for k in (1, 2, 3))        # same rule as the Excel PlanBand (P6-A)
row = cb[cb.band == band].iloc[0]
inside = cb.cagr_lo.iloc[0] <= x <= cb.cagr_hi.iloc[-1]
st.metric("해당 구간", f"{row.label}", help=f"구간 CAGR {pct(row.cagr_lo)}\\~{pct(row.cagr_hi)}, 거래 {row.n_deals}건")
cols = st.columns(3)
for i, h in enumerate((1, 2, 3)):
    cols[i].metric(f"{h}차연도 매출 달성률 중앙값", pct(row[f"h{h}_median"]), help=f"n = {row[f'h{h}_n']}")
if not inside:
    st.info("입력값이 표본 범위 밖이다(참고만).")
st.session_state["cagr_lookup"] = {"x": x, "band": int(band), **{f"h{h}": float(row[f"h{h}_median"]) for h in (1, 2, 3)}}
KO = {"label": "구간", "cagr_lo": "CAGR 하한", "cagr_hi": "CAGR 상한", "n_deals": "거래 수",
      **{f"h{h}_median": f"{h}차 달성률 중앙값" for h in (1, 2, 3)}, **{f"h{h}_n": f"{h}차 n" for h in (1, 2, 3)}}
st.dataframe(cb.rename(columns=KO).drop(columns=["band"])
             .style.format({c: "{:.1%}" for c in ("CAGR 하한", "CAGR 상한", *(f"{h}차 달성률 중앙값" for h in (1, 2, 3)))}),
             hide_index=True, width="stretch")
st.caption("스팩 합병 외부평가 추정 기준 참고값이다. 대상 회사와 상황이 다르고, 경고 판정이나 자동 감액에 쓰지 않는다. 구간 = 예측 매출 CAGR 사분위(86건).")
footer()
