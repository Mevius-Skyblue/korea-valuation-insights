"""Page 3: user-input DCF calculator. All inputs are typed by the user (no market data, no listed company's value);
calculation = the project engine's pure functions (app/lib/calc.py -> src/valuation/dcf.py, wacc.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib.calc import DEFAULTS, calculate  # noqa: E402
from app.lib.common import footer, load, pct  # noqa: E402

st.title("DCF 계산기 (사용자 입력형)")
st.caption("가정 하의 계산 예시. 금액 단위는 사용자가 정한다(기본 억원). 시세·특정 회사 자료는 넣지 않는다.")
D = DEFAULTS
left, right = st.columns([3, 2])
with left:
    st.subheader("1. 매출·이익 경로")
    c = st.columns(2)
    rev0 = c[0].number_input("기준 연도 매출(억원)", value=D["revenue0"], min_value=0.0, step=100.0)
    first = c[1].number_input("첫 추정 연도", value=D["first_year"], min_value=2000, max_value=2100, step=1)
    path = pd.DataFrame({"매출 성장률(%)": [g * 100 for g in D["growth"]], "영업이익률(%)": [m * 100 for m in D["margin"]]})
    path = st.data_editor(path, num_rows="dynamic", width="stretch", key="path")
    path = path.dropna()
    c = st.columns(3)
    dna = c[0].number_input("D&A(매출 대비 %)", value=D["dna_pct"] * 100, step=0.5)
    capex = c[1].number_input("CAPEX(매출 대비 %)", value=D["capex_pct"] * 100, step=0.5)
    nwc = c[2].number_input("운전자본(매출 증가분 대비 %)", value=D["nwc_pct"] * 100, step=1.0)
    st.subheader("2. 할인율")
    c = st.columns(4)
    rf = c[0].number_input("Rf(%)", value=D["rf"] * 100, step=0.1)
    mrp = c[1].number_input("MRP(%)", value=D["mrp"] * 100, step=0.5)
    bu = c[2].number_input("βu(언레버)", value=D["beta_u"], step=0.05)
    srp = c[3].number_input("SRP(%)", value=D["srp"] * 100, step=0.5)
    c = st.columns(4)
    de = c[0].number_input("목표 D/E(배)", value=D["de"], min_value=0.0, step=0.05)
    kd = c[1].number_input("세전 Kd(%)", value=D["kd"] * 100, step=0.25)
    tax = c[2].number_input("법인세율(%, 단일)", value=D["tax"] * 100, step=1.0)
    g = c[3].number_input("영구성장률 g(%)", value=D["g"] * 100, step=0.25)
    c = st.columns(4)
    exm = c[0].number_input("Exit EV/EBITDA(배, 0 = 안 씀)", value=D["exit_multiple"], min_value=0.0, step=0.5)
    mid = c[1].checkbox("mid-year 할인", value=D["mid_year"])
    nd = c[2].number_input("순차입금(억원)", value=D["net_debt"], step=10.0)
    sh = c[3].number_input("주식수(주, 0 = 주당 계산 안 함)", value=D["shares"], min_value=0.0, step=1000.0)

inp = {**D, "revenue0": rev0, "first_year": int(first), "growth": [v / 100 for v in path["매출 성장률(%)"]],
       "margin": [v / 100 for v in path["영업이익률(%)"]], "dna_pct": dna / 100, "capex_pct": capex / 100, "nwc_pct": nwc / 100,
       "rf": rf / 100, "mrp": mrp / 100, "beta_u": bu, "srp": srp / 100, "de": de, "kd": kd / 100, "tax": tax / 100, "g": g / 100,
       "exit_multiple": exm, "mid_year": mid, "net_debt": nd, "shares": sh}
st.session_state["calc_inputs"] = inp
with right:
    st.subheader("결과 (가정 하의 계산 예시)")
    try:
        if len(inp["growth"]) < 2:
            raise ValueError("추정 연도를 2개 이상 넣어야 한다")
        r = calculate(inp)
    except ValueError as e:                     # e.g. WACC <= g
        st.error(f"계산할 수 없다: {e}")
        r = None
    st.session_state["calc_result"] = r
    if r:
        c = st.columns(2)
        c[0].metric("WACC", pct(r["wacc"], 2))
        c[1].metric("Ke (βL " + f"{r['beta_l']:.3f})", pct(r["ke"], 2))
        c = st.columns(2)
        c[0].metric("EV(Gordon, 억원)", f"{r['ev']:,.1f}")
        c[1].metric("영구가치 비중", pct(r["tv_share"]))
        c = st.columns(2)
        c[0].metric("함의 EV/EBITDA", "—" if r["implied_multiple"] is None else f"{r['implied_multiple']:.2f}배")
        c[1].metric("Exit EV(억원) / 함의 g", "—" if r["ev_exit"] is None else f"{r['ev_exit']:,.1f} / {pct(r['implied_g'], 2)}")
        c = st.columns(2)
        c[0].metric("주식가치(억원) = EV − 순차입금", f"{r['equity']:,.1f}")
        c[1].metric("주당(원)", "—" if r["per_share"] is None else f"{r['per_share']:,.0f}")
    st.subheader("참고: 예측 매출 CAGR 구간")
    cb = load("cagr_bands.csv")
    if r and r["cagr5"] is not None:
        x = r["cagr5"]
        band = 1 + sum(x >= cb.cagr_lo.iloc[k] for k in (1, 2, 3))
        row = cb[cb.band == band].iloc[0]
        st.write(f"입력 경로의 예측 매출 CAGR(첫 추정 연도부터 최대 5개 연도) **{pct(x)}** → **{row.label}**")
        st.write("그 구간의 스팩 합병 외부평가 추정 매출 달성률 중앙값: "
                 + " · ".join(f"{h}차 {pct(row[f'h{h}_median'])}(n={row[f'h{h}_n']})" for h in (1, 2, 3)))
        st.caption("참고값만(자동 감액·경고 없음). 달성률은 예측이 분모라 높은 예측일수록 낮게 나오는 기계적 성분이 있다. 「외부평가 추정 vs 실적」 화면과 같은 규칙.")

if r:
    st.subheader("민감도: WACC × 영구성장률 → EV(Gordon, 억원)")
    gr = pd.DataFrame([[r["grid"][(dw, gg)] for gg in inp["g_values"]] for dw in inp["wacc_steps"]],
                      index=[pct(r["wacc"] + dw, 2) for dw in inp["wacc_steps"]], columns=[pct(gg, 1) for gg in inp["g_values"]])
    gr.index.name = "WACC \\ g"
    st.dataframe(gr.style.format("{:,.1f}", na_rep="WACC ≤ g"), width="stretch")
    st.subheader("FCFF 표")
    t = r["table"][["label", "ebit", "tax", "nopat", "dna", "capex", "dnwc", "fcff", "t", "discount_factor", "pv"]].rename(columns={
        "label": "연도", "ebit": "EBIT", "tax": "법인세", "nopat": "NOPAT", "dna": "D&A", "capex": "CAPEX", "dnwc": "ΔNWC", "fcff": "FCFF",
        "t": "할인 기간(년)", "discount_factor": "현가계수", "pv": "현재가치"})
    st.dataframe(t.style.format({c: "{:,.1f}" for c in ("EBIT", "법인세", "NOPAT", "D&A", "CAPEX", "ΔNWC", "FCFF", "현재가치")}
                                | {"할인 기간(년)": "{:.2f}", "현가계수": "{:.4f}"}), hide_index=True, width="stretch")
    st.caption("계산식: FCFF = EBIT × (1 − t) + D&A − CAPEX − ΔNWC, 영구가치 = FCFF_N × (1 + g) ÷ (WACC − g)(mid-year면 × (1 + WACC)^0.5), "
               "WACC = E/V × (Rf + βL × MRP + SRP) + D/V × Kd × (1 − t), βL = βu × (1 + (1 − t) × D/E). 할인 기준일 = 첫 추정 연도 전년 말.")
footer()
