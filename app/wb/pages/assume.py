"""3 가정: the 15 assumptions of the session (src/workbench/spec) in groups, each with its auto value, allowed range and a
practice reference; a rejected input shows set_assumption's reason verbatim and the session stays unchanged. Right
panel: WACC against the practice band, per-share at SRP 0·1·2%, assumptions that differ from practice, plan check,
version. Every accepted change is a new version (recalculation only - no Excel)."""

from __future__ import annotations

import time

import streamlit as st

from app.wb import charts as ch
from app.wb import components as ui
from app.wb import fields as FD
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx
from app.wb.pages import judge_panel

PREM_LAB = {
    "lt25": "25% 미만",
    "25to50": "25~50%",
    "gt50": "50% 초과",
    "strategic": "전략적 인수자",
    "financial": "재무적 인수자",
    "other": "기타 인수자",
    "2015-2026": "2015~2026",
    "2010-2014": "2010~2014",
}
WIDE = {"rf_tenor", "srp", "peers", "premium", "sotp_discount"}
TERM = {
    "rf_tenor": "Rf",
    "mrp": "MRP",
    "beta_u": "βu",
    "de": "D/E",
    "kd": "Kd",
    "srp": "SRP",
    "g_terminal": "영구성장률",
    "sotp_discount": "SOTP",
    "nci_mn": "비지배지분",
}


def render(c: nav.Ctx) -> None:
    nav.header(c, "가정")
    st.markdown(
        "<p class='wb-sub'>기본값은 규칙으로 채워져 있습니다. 바꾸면(Enter) 오른쪽이 바로 다시 계산되고 새 버전이 생깁니다.</p>",
        unsafe_allow_html=True,
    )
    if c.mode == "public" and M.public_missing(c.o, c.s):
        nav.public_inputs(c, "assume")
    judge_panel.expander(c)
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.text_input("변경 이유(선택, 다음 변경에 기록)", key="chg_reason", placeholder="예: 한공회 가이던스 적용")
        for g, fields in FD.GROUPS:
            with ui.card(f"grp_{g}", g):
                wide = [f for f in fields if f in WIDE and M.applicable(c.o, f)]
                narrow = [f for f in fields if f not in WIDE and M.applicable(c.o, f)]
                for f in [x for x in wide if x in ("rf_tenor",)]:
                    _field(c, f)
                for i in range(0, len(narrow), 2):  # two text fields per row (design: 2-column grid)
                    cols = st.columns(2)
                    for col, f in zip(cols, narrow[i : i + 2]):
                        with col:
                            _field(c, f)
                for f in [x for x in wide if x not in ("rf_tenor",)]:
                    _field(c, f)
    with right:
        with st.container(key="sticky_panel"):
            _panel(c)
    ui.footer(c.mode, M.AS_OF)


def _ref(c: nav.Ctx, f: str) -> str:
    p = M.practice()
    full, late = p["full"], p["late"]
    link = nav.link("ref_rates", "실무 할인율 관행", c)
    if f == "rf_tenor":
        return f"실무 의견서 {p['rf10']}/{p['rf_marked']}건이 10년 · {link}"
    if f == "mrp":
        return f"실무 2023~ 중앙값 {F.pct(late['mrp']['median'])}(n={int(late['mrp']['n'])}), 전체 사분위 {F.pct(full['mrp']['q1'])}~{F.pct(full['mrp']['q3'])} · {link}"
    if f == "srp":
        return (
            f"실무 중앙값 {F.pct(full['srp']['median'])}(n={int(full['srp']['n'])}) · 대상 회사의 규모 구간 표는 미확보 · {link}"
        )
    if f == "g_terminal":
        return f"실무 중앙값 {F.pct(full['g']['median'])}, 사분위 {F.pct(full['g']['q1'])}~{F.pct(full['g']['q3'])} · {link}"
    if f == "beta_u":
        return "피어 무부채 베타 중앙값(Blume·Hamada). 설명력 낮으면 근거 확인"
    if f == "de":
        return "자체 과거 시점 평균(Hamada로 다시 레버)"
    if f == "kd":
        return "이자비용 ÷ 평균 차입금(하한 Rf). 등급 금리로 바꿀 수 있음"
    if f == "g_start":
        return "자기 매출 CAGR과 피어 성장률의 평균 → 2030년까지 g로 체감 · " + nav.link("ref_accuracy", "추정 vs 실적", c)
    if f == "normal_margin":
        return "5년 중앙값 → 2032년까지 피어 이익률 쪽 50% 수렴"
    if f == "scenario_width":
        return "비관·낙관에서 성장률·이익률을 각각 ± 이동"
    if f == "sotp_discount":
        return "상장 종속회사 지분 시가에 적용(기본 0%, 민감도 30·50%)"
    if f == "cash_adjust_mn":
        return "현금성 중 고객 자금 등 영업에 묶인 금액(현금성에서 뺌)"
    if f == "nci_mn":
        return "비지배지분 가치를 직접 정함(비례법·P/B 후보는 판단 목록)"
    if f == "premium":
        return "경영권 프리미엄 조건(블록 1주당 가격) · " + nav.link("ref_premium", "경영권 프리미엄", c)
    if f == "peers":
        return "자동 초안 피어 중 포함·제외(새 피어 추가는 재수집 필요)"
    return ""


def _label(f: str) -> str:
    lab = M.spec.LABEL[f]
    return lab


def _apply(sid: str, f: str, key: str) -> None:
    """on_change: range check + new version, or the rejection message under the field (session unchanged)."""
    s = M.load(sid)
    raw = st.session_state.get(key)
    if f == "srp" and raw == "직접":
        return
    if f == "premium":
        raw = {
            "stake_band": st.session_state.get(f"{key}_sb"),
            "buyer_group": st.session_state.get(f"{key}_bg"),
            "period": st.session_state.get(f"{key}_pd"),
        }
        val = raw
    elif f == "peers":
        val = list(raw or [])
    elif f in ("rf_tenor",):
        val = raw
    elif f in ("srp", "sotp_discount") and isinstance(raw, float):
        val = raw
    else:
        val = FD.parse(f, raw)
    reason = (st.session_state.get("chg_reason") or "").strip() or None
    t0 = time.time()
    r = M.set_value(s, f, val, reason)
    st.session_state["recalc_s"] = round(time.time() - t0, 3)
    if r["ok"]:
        st.session_state[f"msg_{f}"] = (True, r.get("reason") or "")
        st.session_state["chg_reason"] = ""
        st.session_state["last_change"] = f
    else:
        st.session_state[f"msg_{f}"] = (False, r["reason"])


def _field(c: nav.Ctx, f: str) -> None:
    o, s = c.o, c.s
    v = M.version(s)["v"]
    key = f"in_{f}_v{v}"
    cur = M.current_value(o, s, f)
    auto = M.auto_value(o, s, f)
    lab = _label(f)
    helptext = tx.GLOSSARY.get(TERM.get(f, ""), None)
    changed = f in M.version(s)["overrides"]
    if f == "rf_tenor":
        rates = o.ctx.c.rates
        opts = [5, 10]
        st.segmented_control(
            lab,
            opts,
            default=int(cur),
            key=key,
            on_change=_apply,
            args=(c.sid, f, key),
            format_func=lambda t: f"국고채 {t}년 {F.pct(rates['KTB5Y' if t == 5 else 'KTB10Y'], 3)}",
            help=helptext,
        )
    elif f == "srp":
        cite = _srp_cite()
        opts = [0.0, 0.01, 0.02] + ([cite] if cite else []) + ["직접"]
        cur_opt = next((x for x in opts if isinstance(x, float) and abs(x - float(cur)) < 1e-9), "직접")
        st.segmented_control(
            lab,
            opts,
            default=cur_opt,
            key=key,
            on_change=_apply,
            args=(c.sid, f, key),
            help=helptext,
            format_func=lambda x: x if isinstance(x, str) else (f"인용값 {x:.2%}(민감도)" if cite and x == cite else f"{x:.0%}"),
        )
        if st.session_state.get(key) == "직접" or cur_opt == "직접":
            st.text_input(
                "SRP 직접 입력(%)", value=FD.to_text(f, cur), key=f"{key}_t", on_change=_apply, args=(c.sid, f, f"{key}_t")
            )
    elif f == "sotp_discount":
        opts = [0.0, 0.3, 0.5]
        cur_opt = next((x for x in opts if abs(x - float(cur or 0)) < 1e-9), None)
        st.segmented_control(
            lab,
            opts,
            default=cur_opt,
            key=key,
            on_change=_apply,
            args=(c.sid, f, key),
            format_func=lambda x: f"{x:.0%}",
            help=helptext,
        )
        st.text_input("직접 입력(%)", value=FD.to_text(f, cur), key=f"{key}_t", on_change=_apply, args=(c.sid, f, f"{key}_t"))
    elif f == "peers":
        names = o.ctx.peers_all()
        st.multiselect(
            f"{lab} ({len(cur or [])}/{len(names)}곳)",
            names,
            default=list(cur or []),
            key=key,
            on_change=_apply,
            args=(c.sid, f, key),
        )
    elif f == "premium":
        from src.premium.predict import PERIODS

        pm = cur or {}
        a, b, d = st.columns(3)
        a.selectbox(
            "지분 구간",
            ["lt25", "25to50", "gt50"],
            index=["lt25", "25to50", "gt50"].index(pm.get("stake_band", "25to50")),
            format_func=PREM_LAB.get,
            key=f"{key}_sb",
            on_change=_apply,
            args=(c.sid, f, key),
        )
        bgs = ["strategic", "financial", "other"]
        b.selectbox(
            "인수자 유형",
            bgs,
            index=bgs.index(pm.get("buyer_group")) if pm.get("buyer_group") in bgs else 0,
            format_func=PREM_LAB.get,
            key=f"{key}_bg",
            on_change=_apply,
            args=(c.sid, f, key),
        )
        per = [x for x in ("2015-2026", "2010-2014") if x in PERIODS]
        d.selectbox(
            "표본 기간",
            per,
            index=per.index(pm.get("period")) if pm.get("period") in per else 0,
            key=f"{key}_pd",
            format_func=lambda x: PREM_LAB.get(x, x),
            on_change=_apply,
            args=(c.sid, f, key),
        )
    else:
        unit = " (%)" if f in FD.PCT_FIELDS else (" (백만원)" if f.endswith("_mn") else "")
        st.text_input(
            lab + unit,
            value=FD.to_text(f, cur),
            key=key,
            on_change=_apply,
            args=(c.sid, f, key),
            help=helptext,
            placeholder="자동값" if cur is None else None,
        )
    note = (
        f"자동값 {M.spec.fmt(f, auto) if auto is not None else '없음'} · 허용 {FD.rng_text(f)}"
        if f not in ("peers", "premium")
        else ""
    )
    st.markdown(
        f"<p class='wb-kpi-note' style='margin-top:-6px'>{'<b>변경됨</b> · ' if changed else ''}{ui.esc(note)}"
        f"{' · ' if note else ''}{_ref(c, f)}</p>",
        unsafe_allow_html=True,
    )
    msg = st.session_state.get(f"msg_{f}")
    if msg and not msg[0]:
        st.markdown(
            f"<p class='wb-kpi-note wb-warn' role='alert'>거부: {ui.esc(msg[1])} (세션 그대로)</p>", unsafe_allow_html=True
        )
    elif msg and msg[1]:
        st.markdown(f"<p class='wb-kpi-note wb-warn'>주의: {ui.esc(msg[1])}</p>", unsafe_allow_html=True)


def _srp_cite() -> float | None:
    k = ("srp_cite",)
    if k not in M._CACHE:
        try:
            M.need_db("SRP 인용값")
            from src.valuation.company_dcf import _close, _con
            from src.workbench.public_deploy import srp_cite_value  # P7-C3: a data seam (replayed in public)

            con = _con()
            try:
                M._CACHE[k] = float(srp_cite_value(con))
            finally:
                _close(con)
        except Exception:  # noqa: BLE001 - the chip is just not offered
            M._CACHE[k] = None
    return M._CACHE[k]


def _panel(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    p = M.practice()
    with ui.card("live_wacc", "지금 가정의 " + tx.term("WACC")):
        r = M.result(o, s, c.mode)
        w = r.get("wacc")
        q1, q3 = p["full"]["wacc"]["q1"], p["full"]["wacc"]["q3"]
        st.markdown(f"<span class='wb-kpi-value' data-testid='live-wacc'>{F.pct(w)}</span>", unsafe_allow_html=True)
        lo, hi = min(w or q1, q1) - 0.01, max(w or q3, q3) + 0.01
        st.altair_chart(ch.band(w, q1, q3, lo, hi, label="이 평가 WACC"), width="stretch")
        st.markdown(
            f"<p class='wb-kpi-note'>회색 띠 = 실무 사분위 {F.pct(q1)}~{F.pct(q3)} · βu {F.beta(r.get('beta_u'))} · D/E "
            f"{F.times(r.get('de'), 3)} · Kd {F.pct(r.get('kd'))}</p>",
            unsafe_allow_html=True,
        )
        if r.get("error"):
            st.error(r["error"])
    with ui.card("live_ps", "주당 추정 내재가치(기본 시나리오)"):
        cols = M.srp_columns(o, s, c.mode)
        rows = [[f"SRP {x['srp']:.2%}" + (" (선택)" if x["chosen"] else ""), F.won(x["per_share"])] for x in cols]
        ui.table(["SRP 열", "주당"], rows, num_cols=(1,))
        sc = r.get("scenarios") or {}
        st.markdown(
            f"<p class='wb-kpi-note'>시나리오(선택 SRP) 비관 {F.won(sc.get('pessimistic'))} · 기본 {F.won(sc.get('base'))} · "
            f"낙관 {F.won(sc.get('optimistic'))} · 영구가치 비중 {F.pct(r.get('tv_share'), 1)}</p>",
            unsafe_allow_html=True,
        )
        lc = st.session_state.get("last_change")
        if lc:
            st.markdown(
                f"<p class='wb-kpi-note'>마지막 변경 {ui.esc(M.spec.LABEL.get(lc, lc))} · 다시 계산 {st.session_state.get('recalc_s', 0):.2f}초</p>",
                unsafe_allow_html=True,
            )
    with ui.card("live_diff", "실무 관행과 다른 가정"):
        d = M.differs_from_practice(s, r, o)
        if d:
            st.markdown(
                "<ul class='wb-list'>"
                + "".join(
                    f"<li><span><span class='wb-dot'></span>{ui.esc(x['item'])} {ui.esc(x['ours'])}</span><span class='wb-kpi-note'>실무 {ui.esc(x['practice'])}</span></li>"
                    for x in d
                )
                + "</ul>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<p class='wb-kpi-note'>다르다고 틀린 것은 아닙니다. 보고서에 이유를 적을 항목입니다. 실무 표본은 스팩 합병 중심.</p>",
            unsafe_allow_html=True,
        )
    with ui.card("live_plan", "사업계획 점검"):
        pc = M.plan_check(o, s, c.mode)
        b = pc["band"]
        if b:
            st.markdown(
                f"<p style='font-size:14px;margin:0'>예측 매출 {tx.term('CAGR')}(FY2026→2030) {F.pct(pc['cagr'])} → <b>{ui.esc(b['label'])}</b>"
                f" ({F.pct(b['cagr_lo'], 1)}~{F.pct(b['cagr_hi'], 1)}){'' if b['inside'] else ' · 표본 범위 밖(참고만)'}</p>"
                f"<p style='font-size:14px;margin:4px 0'>비슷한 계획의 매출 달성률 중앙값 <b>{F.pct(b['h1_median'], 1)} · {F.pct(b['h2_median'], 1)} · "
                f"{F.pct(b['h3_median'], 1)}</b></p><p class='wb-kpi-note'>1·2·3차연도(n={int(b['h1_n'])}·{int(b['h2_n'])}·{int(b['h3_n'])}) · "
                f"스팩 합병 외부평가 추정 기준 참고값 · 출발 성장률 {F.pct(pc['g0'])} · {nav.link('ref_accuracy', '추정 vs 실적', c)}</p>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<p class='wb-kpi-note'>예측 매출 CAGR을 계산할 수 없습니다.</p>", unsafe_allow_html=True)
    v = M.version(s)
    st.markdown(
        f"<p class='wb-kpi-note'>지금 버전 v{v['v']} · {ui.esc(v['created'].replace('T', ' '))}</p>", unsafe_allow_html=True
    )
    st.button("결과 보기 →", key="to_result", type="primary", on_click=nav.go, args=("result",), width="stretch")
