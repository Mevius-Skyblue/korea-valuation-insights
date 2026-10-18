"""4 결과: per-share value with its status (초안 / 보류 / 확정), WACC and terminal share against practice, signals, the
football field and the methods table, the premium card, the judgement panel, versions and the audit trail (compare two
versions, revert = a new version with an earlier version's assumptions; nothing is deleted)."""

from __future__ import annotations

import streamlit as st

from app.wb import charts as ch
from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx
from app.wb.pages import judge_panel


def warn_ko(w: str) -> str:
    """predict.premium_range warnings in plain Korean (same content)."""
    import re

    m = re.match(r"regression q50 (-?[\d.]+%) vs neighbour median (-?[\d.]+%)", w)
    if m:
        return f"회귀 중앙값 {m.group(1)}과 이웃 50건 중앙값 {m.group(2)}의 차이가 10%p를 넘음(범위 고르는 규칙: 이웃 사용)"
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
        return f"시총 구간 표 칸 거래 {m.group(1)}건(n<10)"
    if w.startswith("quantile crossing"):
        return "이 지점에서 회귀 분위가 교차(하위·중앙·상위 순서가 뒤바뀜)"
    return w


LIGHT = {"초록": "ok", "노랑": "warn", "빨강": "warn", "회색": "", "입력 전": ""}
METHOD = {"regression": "분위 회귀", "neighbours": "비슷한 거래 이웃 50건", "band_table": "시총 백분위 구간 표"}


def render(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    nav.header(c, "평가 결과")
    st_ = M.status(o, s)
    if st_["hold"] and st_["label"] != "확정":
        with ui.card("hold", None, plain=True):
            _hold(c, st_)
    with ui.card("kpis", None, plain=True):
        _kpis(c, st_)
    a, b = st.columns([2, 1], gap="medium")
    with a:
        with ui.card("football", "가치 범위 (풋볼필드)", "방법별 주당가치 범위와 대표값 · 단위 원"):
            _football(c)
    with b:
        with ui.card("premium", tx.term("경영권 프리미엄"), None):
            _premium(c)
    with ui.card("judge", None):
        judge_panel.panel(c)
    with ui.card("history", "버전 · 감사 기록", "변경 1건 = 새 버전. 기록은 지우지 않습니다"):
        _history(c)
    if st_["label"] == "확정" and st_["hold"]:
        with ui.card("hold_record", "자동 결과 보류 기록(확정 전)"):
            st.markdown(
                "<p class='wb-kpi-note'>"
                + ui.esc("; ".join(st_["headline"].get("reasons") or []))
                + " — 확정 버전의 값이 대표값입니다(보류 사유는 기록으로 남김).</p>",
                unsafe_allow_html=True,
            )
    st.button("다음: 내보내기 →", key="to_export", type="primary", on_click=nav.go, args=("export",))
    ui.footer(c.mode, M.AS_OF)


def _hold(c: nav.Ctx, st_: dict) -> None:
    o = c.o
    hl = dict(st_["headline"])
    hl["reasons"] = [tx.plain_words(x) for x in hl.get("reasons") or []]
    hl["top_judgement"] = {k: tx.plain_words(v) for k, v in (hl.get("top_judgement") or {}).items()}
    if c.mode == "public":
        hl["reasons"] = [tx.public_mask(x) for x in hl.get("reasons") or []]
        hl["top_judgement"] = {
            k: tx.public_mask(v) if isinstance(v, str) else v for k, v in (hl.get("top_judgement") or {}).items()
        }
    d = o.summ.get("diagnostics") or {}
    comp = d.get("composition_share") or {}
    rev = d.get("reverse") or {}
    top = hl.get("top_judgement") or {}
    parts = [
        f"<div class='wb-hold'><h3>왜 보류인가</h3><p style='margin:0 0 6px 0;font-size:14px'>자동 초안이 대표값을 내지 않았습니다: "
        f"<b>{ui.esc('; '.join(hl.get('reasons') or []))}</b>. 틀릴 수 있는 숫자 대신 원인과 1순위 판단을 먼저 보여 줍니다.</p>"
    ]
    if comp:
        lab = {
            "explicit": "예측 기간 가치",
            "tv": "영구가치",
            "cash_like": "현금성",
            "non_operating": "비영업 자산",
            "debt": "차입금",
            "nci": "비지배지분",
        }
        parts.append(
            "<p class='wb-kpi-note'>원인 분해(주식가치 대비 비중, 자동 초안): "
            + " · ".join(f"{lab[k]} {F.pct(comp[k], 1)}" for k in lab if comp.get(k) is not None)
            + "</p>"
        )
    if rev.get("target"):

        def rv(x):  # P7-C3 polish reverse_dash: no '—' for 'cannot be matched'
            return F.pct(x) if F.ok(x) else "이 값만 바꿔서는 맞출 수 없음"

        parts.append(
            f"<p class='wb-kpi-note'>피어 중앙값({ui.esc(tx.plain_words(rev.get('basis')))}) 주당 {F.won(rev['target'])}을 맞추려면: "
            f"정상 이익률 {rv(rev.get('margin'))}(지금 {F.pct(rev.get('margin_base'))}) 또는 출발 성장률 {rv(rev.get('start_growth'))}"
            f"(지금 {F.pct(rev.get('start_growth_base'))}) 또는 WACC {rv(rev.get('wacc'))}(지금 {F.pct(rev.get('wacc_base'))})</p>"
        )
    if top:
        parts.append(
            f"<p style='margin:6px 0 0 0;font-size:14px'>1순위 판단: <b>[{ui.esc(top.get('category'))}] {ui.esc(top.get('item'))}</b>"
            f" — 대안: {ui.esc(top.get('alternative') or '')}</p>"
        )
    parts.append(
        "<p class='wb-kpi-note'>아래 판단 목록에서 처리하고 확정하면 확정값이 대표값이 됩니다(보류 사유는 기록으로 남음).</p></div>"
    )
    st.markdown("".join(parts), unsafe_allow_html=True)


def _kpis(c: nav.Ctx, st_: dict) -> None:
    o, s = c.o, c.s
    r = M.result(o, s, c.mode)
    p = M.practice()
    ps = r.get("per_share")
    mk = M.market(o, s, c.mode)
    srp = r.get("srp", 0)
    note = f"SRP {srp:.2%} · 시나리오 {F.won((r.get('scenarios') or {}).get('pessimistic'))}~{F.won((r.get('scenarios') or {}).get('optimistic'))}"
    if mk.get("close") and ps:
        note += f" · 시장가 대비 {F.ratio_text(ps / mk['close'])}"
    lab = "주당 추정 내재가치 (기본)"
    if st_["label"] == "보류":
        lab += " — 대표값 보류, 계산값 표시"
    wq = p["full"]["wacc"]
    tq = p["full"]["tv_share"]
    w, tv = r.get("wacc"), r.get("tv_share")
    wlo, whi = min(w or 0.05, wq["q1"]) - 0.01, max(w or 0.15, wq["q3"]) + 0.01
    sig = M.signals(o, s, c.mode)
    q25, q75 = sig.get("q25"), sig.get("q75")
    if sig.get("light_peer") == "회색" or not (F.ok(q25) and F.ok(q75)) or ps is None:
        conv = "판정 불가"
    else:
        conv = "수렴" if q25 <= ps <= q75 else "미수렴"
    items = [
        {"label": lab, "value": F.won(ps, unit=False), "unit": "원", "badge": ui.badge(st_["label"], st_["cls"]), "note": note},
        {
            "label": tx.term("WACC"),
            "value": F.pct(w),
            "band": {"lo": ui.pos(wq["q1"], wlo, whi), "hi": ui.pos(wq["q3"], wlo, whi), "mark": ui.pos(w or 0, wlo, whi)},
            "note": f"실무 사분위 {F.pct(wq['q1'])}~{F.pct(wq['q3'])} " + ("안" if w and wq["q1"] <= w <= wq["q3"] else "밖"),
            "cls": "" if w and wq["q1"] <= w <= wq["q3"] else "wb-warn",
        },
        {
            "label": tx.term("영구가치 비중"),
            "value": F.pct(tv, 1),
            "band": {"lo": ui.pos(tq["q1"], -0.1, 1.0), "hi": ui.pos(tq["q3"], -0.1, 1.0), "mark": ui.pos(tv or 0, -0.1, 1.0)},
            "note": f"실무 사분위 {F.pct(tq['q1'], 1)}~{F.pct(tq['q3'], 1)}",
            "cls": "" if tv and tq["q1"] <= tv <= tq["q3"] else "wb-warn",
        },
        {
            "label": tx.term("수렴 시험") + " · 신호",
            "value": conv,
            "badge": ui.badge(f"피어 {sig.get('light_peer', '—')}", LIGHT.get(sig.get("light_peer"), ""))
            + " "
            + ui.badge(f"시장 {sig.get('light_market', '—')}", LIGHT.get(sig.get("light_market"), "")),
            "note": (
                f"피어 {ui.esc(sig.get('peer_basis') or '')} 사분위 {F.won(sig.get('q25'))}~{F.won(sig.get('q75'))}"
                + (f" · DCF ÷ 시장가 {F.ratio_text(sig.get('ratio_market'))}" if sig.get("ratio_market") else "")
                + (" · 해석 불가: " + ui.esc("; ".join(sig.get("peer_invalid") or [])) if sig.get("peer_invalid") else "")
            ),
        },
    ]
    if st_["label"] == "확정":
        conf = st_["confirmed"] or {}
        items[0]["note"] += f" · 확정 v{conf.get('v')} {ui.esc(str(conf.get('at', '')).replace('T', ' '))}"
    ui.kpis(items)


def _football(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    r = M.result(o, s, c.mode)
    rel = M.relative(o, s, c.mode)
    mk = M.market(o, s, c.mode)
    sc = r.get("scenarios") or {}
    rows, table = [], []
    vals = [v for v in sc.values() if v is not None]
    if vals:
        rows.append({"method": "DCF", "lo": min(vals), "hi": max(vals), "rep": r.get("per_share"), "kind": "dcf"})
        table.append(
            [
                "DCF",
                F.won(min(vals), False),
                F.won(r.get("per_share"), False),
                F.won(max(vals), False),
                f"시나리오 비관~낙관 · SRP {r.get('srp', 0):.2%}",
            ]
        )
    for nm, m in rel["multiples"].items():
        if m["n"] and F.ok(m["ps_q25"]) and F.ok(m["ps_q75"]):
            rows.append({"method": f"피어 {nm}", "lo": m["ps_q25"], "hi": m["ps_q75"], "rep": m["ps_median"], "kind": "peer"})
            table.append(
                [
                    f"피어 {nm}",
                    F.won(m["ps_q25"], False),
                    F.won(m["ps_median"], False),
                    F.won(m["ps_q75"], False),
                    f"사분위 · n={m['n']}" + (" (n<5 주의)" if m["n"] < 5 else ""),
                ]
            )
        else:
            table.append([f"피어 {nm}", "—", "—", "—", "계산 불가(대상 지표 ≤ 0 또는 피어 없음)"])
    try:
        pm = M.premium(o, s, c.mode)
        if pm.get("block"):
            b = pm["block"]
            rows.append({"method": "경영권 블록 가격", "lo": b["q25"], "hi": b["q75"], "rep": b["q50"], "kind": "block"})
            table.append(
                [
                    "경영권 블록 가격",
                    F.won(b["q25"], False),
                    F.won(b["q50"], False),
                    F.won(b["q75"], False),
                    f"20일 VWAP × (1 + 프리미엄 사분위) · {METHOD.get(pm['method'], pm['method'])}",
                ]
            )
    except (M.NeedInput, M.PublicDataUnavailable):
        table.append(["경영권 블록 가격", "—", "—", "—", "시장가 입력 시 표시"])
    if mk.get("close"):
        table.append(["시장가", "—", F.won(mk["close"], False), "—", "기준일 종가 · " + mk["source"]])
    if rows:
        st.altair_chart(ch.football(rows, mk.get("close"), "시장가"), width="stretch")
    ui.table(["방법", "하단", "대표", "상단", "근거"], table, num_cols=(1, 2, 3), min_width=520)
    if c.mode == "public" and not mk.get("close"):
        st.markdown(
            "<p class='wb-kpi-note'>공개 모드: 시장가 선·블록 가격·DCF ÷ 시장가는 사용자 주가 입력 시만 표시합니다.</p>",
            unsafe_allow_html=True,
        )


def _premium(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    pm = M.premium(o, s, c.mode)
    st.markdown(
        f"<p class='wb-sub'>{ui.esc(o.cfg['target']['market'])} · {ui.esc(METHOD.get(pm['method'], pm['method']))} "
        f"(범위 고르는 규칙) · 이웃 {pm.get('n_neighbour') or '—'}건</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px'>"
        + "".join(
            f"<div style='background:{bg};border-radius:8px;padding:10px'><span class='wb-kpi-note'>{lab}</span><br>"
            f"<span style='font-size:20px;font-weight:700'>{F.pct(pm[q], 1)}</span></div>"
            for lab, q, bg in (("하위 25%", "q25", "#F4F4F2"), ("중앙값", "q50", "#FFF1E6"), ("상위 25%", "q75", "#F4F4F2"))
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    if pm.get("block"):
        b = pm["block"]
        st.markdown(
            f"<p style='font-size:13px;line-height:1.6'>20일 VWAP {F.won(pm['vwap'])}에 적용하면 경영권 지분 1주 "
            f"{F.won(b['q25'])} / {F.won(b['q50'])} / {F.won(b['q75'])}.</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<p class='wb-kpi-note'>블록 1주당 가격은 시장가가 있을 때만(공개 모드는 사용자 VWAP 입력 시).</p>",
            unsafe_allow_html=True,
        )
    lab = {
        "lt25": "지분 25% 미만",
        "25to50": "지분 25~50%",
        "gt50": "지분 50% 초과",
        "strategic": "전략적 인수자",
        "financial": "재무적 인수자",
        "other": "기타 인수자",
        "all": "인수자 전체",
    }
    st.markdown(
        f"<span class='wb-chip'>{lab.get(pm['stake_band'])}</span><span class='wb-chip'>{lab.get(pm['buyer_group'])}</span>"
        f"<span class='wb-chip'>{'기준일 시총 백분위(고정)' if pm.get('pct_fixed') else '시총 백분위'} {pm['pct']:.1f}</span>"
        f"<span class='wb-chip'>{ui.esc(pm['period'])}</span>",
        unsafe_allow_html=True,
    )
    # P7-C3b: the three ways the rule chooses from (aggregates only: quartiles and counts; no deal names, dates or values)
    nb, bd, rg = pm.get("neighbour") or {}, pm.get("band") or {}, pm.get("regression") or {}
    cv = pm.get("cv_improvement")
    rows = [
        [
            "비슷한 거래 이웃 50건",
            F.pct(nb.get("q25"), 1),
            F.pct(nb.get("q50"), 1),
            F.pct(nb.get("q75"), 1),
            f"{nb.get('n', '—')}건" + (f" (같은 시장 {nb['n_same_market']})" if nb.get("n_same_market") is not None else ""),
        ],
        [
            f"시총 백분위 구간 표 {bd.get('band', '')}",
            F.pct(bd.get("q25"), 1),
            F.pct(bd.get("q50"), 1),
            F.pct(bd.get("q75"), 1),
            f"{bd.get('n', '—')}건" + (" (n<10 주의)" if (bd.get("n") or 0) < 10 else ""),
        ],
        [
            "분위 회귀",
            F.pct(rg.get("q25"), 1),
            F.pct(rg.get("q50"), 1),
            F.pct(rg.get("q75"), 1),
            "채택" if cv is not None and cv >= 0.05 else "미채택",
        ],
    ]
    ui.table(
        ["방식", "하위 25%", "중앙값", "상위 25%", "건수·채택"],
        rows,
        num_cols=(1, 2, 3),
        min_width=480,
        caption=(
            f"대표 출력 = {METHOD.get(pm['method'], pm['method'])}. 분위 회귀 채택 기준: CV 중앙값 손실 개선 ≥ 5%"
            + (f"(지금 {cv:.2%})" if cv is not None else "")
            + ". 거래별 값·거래 이름은 표시하지 않습니다"
        ),
    )
    if pm.get("warnings"):
        st.markdown(
            f"<p class='wb-kpi-note wb-warn'>주의: {ui.esc('; '.join(warn_ko(w) for w in pm['warnings']))[:400]}</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        f"<p class='wb-kpi-note'>과거 최대주주 지분 거래 집계(거래별 값은 표시하지 않음) · {nav.link('ref_premium', '경영권 프리미엄', c)}</p>",
        unsafe_allow_html=True,
    )


def _history(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    t1, t2, t3, t4 = st.tabs(["버전", "변경 기록", "버전 비교", "되돌리기"])
    vt = M.versions_table(o, s, c.mode)
    with t1:
        ui.table(
            ["버전", "만든 시각", "주당", "바뀐 가정"],
            [
                [
                    f"v{x['v']}" + (f" (v{x['reverted_to']}로 되돌림)" if x.get("reverted_to") is not None else ""),
                    x["created"],
                    F.won(x["per_share"]),
                    x["change"],
                ]
                for x in reversed(vt)
            ],
            num_cols=(2,),
            min_width=520,
        )
    with t2:
        rows = []
        for a in reversed(s["audit"]):
            j = (s.get("judgements") or {}).get(a.get("judgement") or "", {})
            rows.append(
                [
                    a["at"].replace("T", " "),
                    f"v{a['v']}",
                    a["label"],
                    f"{a.get('before_text', '')} → {a.get('after_text', '')}" if a.get("field") else "",
                    a.get("reason") or "",
                    str(j.get("item") or "")[:30],
                ]
            )
        if rows:
            ui.table(["시각", "버전", "항목", "전 → 후", "이유", "판단 항목"], rows, min_width=640)
        else:
            st.markdown("<p class='wb-kpi-note'>아직 변경이 없습니다(v0 = 자동 초안).</p>", unsafe_allow_html=True)
    with t3:
        vs = [x["v"] for x in s["versions"]]
        a, b = st.columns(2)
        va = a.selectbox("버전 A", vs, index=0, key="cmp_a", format_func=lambda v: f"v{v}")
        vb = b.selectbox("버전 B", vs, index=len(vs) - 1, key="cmp_b", format_func=lambda v: f"v{v}")
        diff = M.compare(s, va, vb)
        pa = next(x["per_share"] for x in vt if x["v"] == va)
        pb = next(x["per_share"] for x in vt if x["v"] == vb)
        st.markdown(
            f"<p style='font-size:14px'>주당 v{va} {F.won(pa)} → v{vb} {F.won(pb)} "
            f"(차이 {F.won((pb - pa) if F.ok(pa) and F.ok(pb) else None, sign=True)})</p>",
            unsafe_allow_html=True,
        )
        if diff:
            ui.table(["가정", f"v{va}", f"v{vb}"], [[d["field"], d["a"], d["b"]] for d in diff])
        else:
            st.markdown("<p class='wb-kpi-note'>두 버전의 가정이 같습니다.</p>", unsafe_allow_html=True)
    with t4:
        vs = [x["v"] for x in s["versions"]][:-1]
        if not vs:
            st.markdown("<p class='wb-kpi-note'>되돌릴 이전 버전이 없습니다.</p>", unsafe_allow_html=True)
        else:
            tv = st.selectbox("되돌릴 버전", vs, index=len(vs) - 1, key="rev_v", format_func=lambda v: f"v{v}")
            why = st.text_input("이유(선택)", key="rev_why")
            if st.button(f"v{tv}의 가정으로 새 버전 만들기", key="rev_go"):
                rr = M.revert(M.load(c.sid), tv, why or None)
                if rr["ok"]:
                    st.session_state["judge_flash"] = (True, f"v{tv}의 가정으로 새 버전을 만들었습니다(기록은 그대로).")
                    st.rerun()
                else:
                    st.error(rr["reason"])
