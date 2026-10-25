"""경영권 프리미엄 tab (P7-U1): conditions (stake band, buyer type, sample period) and the market-cap percentile, the three
ways the D6 rule chooses from (neighbours / band table / quantile regression, rule and warnings behind ⓘ), the block
price table (CP, block per share, implied DLOC, DCF x (1 + CP) as a reference) and stake -> deal amount.
Aggregates only (quartiles and counts); no deal names, dates or per-deal values. Block prices only with a market price
(PC = 한국거래소 통계정보, public = the user's VWAP)."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav, shell

LAB = {
    "lt25": "25% 미만",
    "25to50": "25~50%",
    "gt50": "50% 초과",
    "strategic": "전략적",
    "financial": "재무적",
    "other": "기타",
    "2015-2026": "2015–26",
    "2010-2014": "2010–14",
}
METHOD = {"regression": "분위 회귀", "neighbours": "이웃 (시총 근접)", "band_table": "시총 백분위 구간표"}


def warn_ko(w: str) -> str:
    """predict.premium_range warnings in plain Korean (same content)."""
    import re

    m = re.match(r"regression q50 (-?[\d.]+%) vs neighbour median (-?[\d.]+%)", w)
    if m:
        return f"회귀 중앙값 {m.group(1)}과 이웃 50건 중앙값 {m.group(2)}의 차이가 10%p 초과(규칙: 이웃 사용)"
    m = re.match(r"extrapolation: (\w+) sample percentile range ([\d.]+)~([\d.]+)", w)
    if m:
        return f"표본 밖 외삽({m.group(1)} 표본 시총 백분위 {m.group(2)}~{m.group(3)})"
    m = re.match(r"cell n<10: (\d+)", w)
    if m:
        return f"같은 시장·지분 구간·인수자·기간 거래 {m.group(1)}건(n<10)"
    m = re.match(r"neighbours filled from the other market: (\d+)", w)
    if m:
        return f"이웃 50건 중 {m.group(1)}건은 다른 시장 거래로 채움"
    m = re.match(r"band table cell n<10: (\d+)", w)
    if m:
        return f"시총 구간표 칸 거래 {m.group(1)}건(n<10)"
    if w.startswith("quantile crossing"):
        return "이 지점에서 회귀 분위가 교차(순서가 뒤바뀜)"
    return w


def render(c: nav.Ctx) -> None:
    with ui.card("prem_cond"):
        conditions(c)
        methods(c)
    with ui.card("prem_block"):
        block(c)


def _set(sid: str, key_prefix: str) -> None:
    s = M.load(sid)
    val = {
        "stake_band": st.session_state.get(f"{key_prefix}_sb"),
        "buyer_group": st.session_state.get(f"{key_prefix}_bg"),
        "period": st.session_state.get(f"{key_prefix}_pd"),
    }
    shell.note_change(s, "경영권 프리미엄 조건")
    r = M.set_value(s, "premium", val, (st.session_state.get("chg_reason") or "").strip() or None)
    if not r["ok"]:
        st.session_state.pop("toast_from", None)
        st.session_state["prem_msg"] = r["reason"]


def conditions(c: nav.Ctx) -> None:
    from src.premium.predict import PERIODS

    o, s = c.o, c.s
    pm_cur = M.current_value(o, s, "premium") or {}
    v = M.version(s)["v"]
    kp = f"prem_v{v}"
    a, b, d, e = st.columns([1.3, 1.3, 1.1, 1.2], vertical_alignment="bottom")
    with a:
        st.segmented_control(
            "지분 구간",
            ["lt25", "25to50", "gt50"],
            default=pm_cur.get("stake_band", "25to50"),
            format_func=LAB.get,
            key=f"{kp}_sb",
            on_change=_set,
            args=(c.sid, kp),
            required=True,
        )
    with b:
        bgs = ["strategic", "financial", "other"]
        st.segmented_control(
            "인수자 유형",
            bgs,
            default=pm_cur.get("buyer_group") if pm_cur.get("buyer_group") in bgs else "strategic",
            format_func=LAB.get,
            key=f"{kp}_bg",
            on_change=_set,
            args=(c.sid, kp),
            required=True,
        )
    with d:
        per = [x for x in ("2010-2014", "2015-2026") if x in PERIODS]
        st.segmented_control(
            "표본 기간",
            per,
            default=pm_cur.get("period") if pm_cur.get("period") in per else per[-1],
            format_func=lambda x: LAB.get(x, x),
            key=f"{kp}_pd",
            on_change=_set,
            args=(c.sid, kp),
            required=True,
        )
    pm = M.premium(o, s, c.mode)
    with e:
        st.markdown(
            f"<div style='display:flex;flex-direction:column;gap:4px'><span class='wb-kpi-note'>시총 백분위 ({ui.esc(o.cfg['target']['market'])})</span>"
            f"<span style='font-size:15px;font-weight:500;height:40px;display:flex;align-items:center'>{pm['pct']:.1f}"
            f"{' · 기준일 고정' if pm.get('pct_fixed') else ''}</span></div>",
            unsafe_allow_html=True,
        )
    msg = st.session_state.pop("prem_msg", None)
    if msg:
        st.error(msg)


def methods(c: nav.Ctx) -> None:
    pm = M.premium(c.o, c.s, c.mode)
    nb, bd, rg = pm.get("neighbour") or {}, pm.get("band") or {}, pm.get("regression") or {}
    cv = pm.get("cv_improvement")
    pub = c.mode == "public"
    band_cut = pub and (bd.get("n") or 0) < 10
    rows = [
        {
            "c": [
                "이웃 (시총 근접)",
                nb.get("n", "—"),
                F.pct_signed(nb.get("q25")),
                F.pct_signed(nb.get("q50")),
                F.pct_signed(nb.get("q75")),
                "대표" if pm["method"] == "neighbours" else "—",
            ],
            "strong": pm["method"] == "neighbours",
        },
        {
            "c": [
                f"시총 백분위 구간 {bd.get('band', '')}".strip(),
                bd.get("n", "—"),
                *(
                    ["n<10 비표시"] * 3
                    if band_cut
                    else [F.pct_signed(bd.get("q25")), F.pct_signed(bd.get("q50")), F.pct_signed(bd.get("q75"))]
                ),
                "대표" if pm["method"] == "band_table" else "—",
            ],
            "strong": pm["method"] == "band_table",
            "dim": (bd.get("n") or 0) < 10,
        },
        {
            "c": [
                "분위 회귀",
                "—",
                F.pct_signed(rg.get("q25")),
                F.pct_signed(rg.get("q50")),
                F.pct_signed(rg.get("q75")),
                ("대표" if pm["method"] == "regression" else (f"CV 개선 {cv:.2%}" if cv is not None else "—")),
            ],
            "strong": pm["method"] == "regression",
        },
    ]
    head = ["방식", "n", "1사분위", "중앙값", "3사분위", "채택"]
    rule = (
        "적용 규칙: KOSPI → 이웃 50건 · KOSDAQ 시총 백분위 P80 이상 → 이웃 50건 · 그 밖은 분위 회귀(회귀·이웃 중앙값 차이 10%p 초과면 이웃) · "
        f"회귀 채택 기준 CV 중앙값 손실 개선 ≥ 5%{f'(지금 {cv:.2%})' if cv is not None else ''}"
    )
    warns = [warn_ko(w) for w in pm.get("warnings") or []]
    tip = rule + (" · 주의: " + "; ".join(warns) if warns else "")
    ui.title_copy(
        "세 방식 비교",
        "과거 최대주주 지분 거래 집계",
        f"<span class='wb-help' title='{ui.esc(tip)}'>ⓘ 대표 = {ui.esc(METHOD.get(pm['method'], pm['method']))} (규칙)</span>",
        ui.tsv(head, rows),
    )
    ui.tbl(head, rows, min_width=640)
    if warns:
        st.markdown(
            f"<p class='wb-kpi-note' title='{ui.esc('; '.join(warns))}'>ⓘ 경고 {len(warns)}건(외삽·n<10 칸·다른 시장 채움·분위 교차)</p>",
            unsafe_allow_html=True,
        )


def block(c: nav.Ctx) -> None:
    o, s, mn = c.o, c.s, c.mn
    pm = M.premium(o, s, c.mode)
    blk = pm.get("block")
    r = M.result(o, s, c.mode)
    ps = r.get("per_share")
    head = ["", "1사분위", "중앙값", "3사분위"]
    qs = ("q25", "q50", "q75")
    rows = [
        {"c": ["경영권 프리미엄 (CP)"] + [F.pct_signed(pm[q]) for q in qs], "strong": True},
        ["블록 거래 주당가"] + ([F.won0(blk[q]) for q in qs] if blk else ["—"] * 3),
        ["내재 소수지분 할인 (DLOC)"] + [F.p1(pm[q] / (1 + pm[q])) for q in qs],
        ["DCF × (1 + CP) (참고)"] + ([F.won0(ps * (1 + pm[q])) for q in qs] if F.ok(ps) else ["—"] * 3),
    ]
    n = pm.get("n_neighbour") if pm["method"] == "neighbours" else (pm.get("band") or {}).get("n")
    ui.title_copy("블록 거래가", f"{METHOD.get(pm['method'], pm['method'])} {n or ''}건 기준".strip(), "", ui.tsv(head, rows))
    ui.tbl(head, rows)
    a, b, d = st.columns([2.2, 1.4, 2.4], vertical_alignment="bottom")
    a.markdown(
        f"<div class='wb-subrow'>20일 거래량가중평균가 (VWAP) <b>{F.won0(pm.get('vwap')) + '원' if pm.get('vwap') else '입력 전'}</b>"
        f"{' · KPI 주가 칸 입력' if c.mode == 'public' else ' · 한국거래소 통계정보'}</div>",
        unsafe_allow_html=True,
    )
    stake = b.text_input("거래 지분율 (%)", key="prem_stake", placeholder="%")
    try:
        sv = float(str(stake).replace("%", "").strip()) if stake else None
    except ValueError:
        sv = None
    if blk and sv:
        amt = o.ctx.c.market["common_out"] * sv / 100 * blk["q50"] / 1e8
        d.markdown(
            f"<div class='wb-subrow'><b>≈ {F.amt(amt, mn)}{'백만' if mn else '억'}</b> (중앙값)</div>", unsafe_allow_html=True
        )
    elif sv and not blk:
        d.markdown("<div class='wb-subrow'>VWAP 입력 시 거래금액</div>", unsafe_allow_html=True)
