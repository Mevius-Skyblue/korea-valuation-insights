"""요약 tab (P7-U1): Football Field (left) | evaluation summary - three signals and four implied multiples, no verdict
sentence - and the control-premium tiles (right); below, the top 5 judgements with their candidates and Δ."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx
from app.wb import values as V
from app.wb.style import T

LIGHT = {"초록": "g", "노랑": "y", "빨강": "r", "회색": "", "입력 전": ""}


def render(c: nav.Ctx) -> None:
    left, right = st.columns([1.35, 1], gap="medium")
    with left:
        with ui.card("football"):
            football(c)
    with right:
        with ui.card("evalsum"):
            evaluation(c)
        with ui.card("premsum"):
            premium_tiles(c)
    with ui.card("top5"):
        top5(c)


def _ff_text(ff: dict) -> str:
    head = ["방법", "구분", "1사분위·하단", "중앙값·대표", "3사분위·상단"]
    rows = [[r["label"], r["sub"], F.won0(r["lo"]), F.won0(r["rep"]), F.won0(r["hi"])] for r in ff["rows"]]
    if ff.get("price"):
        rows.append(["주가", "평가기준일" if not ff["example"] else "예시", "", F.won0(ff["price"]), ""])
    return ui.tsv(head, rows)


def football(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    ff = V.football(o, s, c.mode)
    r = M.result(o, s, c.mode)
    ps, price = r.get("per_share"), ff.get("price")
    pr_txt = ""
    if price:
        diff = f"{(ps / price - 1) * 100:+.1f}%" if F.ok(ps) else "—"
        tip = f"DCF {F.won0(ps)}원 = 주가 대비 {diff} · 주가는 {'사용자 입력(공개)' if c.mode == 'public' else '한국거래소 통계정보(PC)'}"
        pr_txt = (
            f"<span class='wb-legend' title='{ui.esc(tip)}'><span style='width:0;height:14px;border-left:2px dashed {T['blue_line']}'></span>"
            f"주가 {F.won0(price)}원{' (예시)' if ff['example'] else ''}</span>"
        )
    ui.title_copy(
        tx.term("IQR", "평가방법별 주당가치") if False else "평가방법별 주당가치",
        "",
        pr_txt,
        _ff_text(ff),
    )
    vals = [x for rr in ff["rows"] for x in (rr["lo"], rr["hi"]) if F.ok(x)] + ([price] if price else [])
    if not vals:
        st.markdown("<p class='wb-kpi-note'>계산 가능한 방법이 없습니다.</p>", unsafe_allow_html=True)
        return
    top = max(vals) * 1.06
    step = 10 ** max(len(str(int(top))) - 2, 0)
    top = (int(top / (2 * step)) + 1) * 2 * step
    lo_ax = min(0.0, min(vals))

    def pct(v):
        return f"{(max(lo_ax, min(v, top)) - lo_ax) / (top - lo_ax) * 100:.2f}%"

    colors = {"dcf": (T["dcf_bar"], T["accent"]), "peer": (T["band"], T["text"]), "block": (T["block_bar"], T["block_mark"])}
    html = ["<div class='wb-ff'>"]
    for rr in ff["rows"]:
        bar = mark = ""
        if F.ok(rr["lo"]) and F.ok(rr["hi"]):
            b, m = colors[rr["kind"]]
            bar = f"<div style='position:absolute;top:4px;height:12px;border-radius:3px;left:{pct(rr['lo'])};width:calc({pct(rr['hi'])} - {pct(rr['lo'])});background:{b}'></div>"
            if F.ok(rr["rep"]):
                mark = f"<div style='position:absolute;top:0;height:20px;width:3px;margin-left:-1px;border-radius:2px;left:{pct(rr['rep'])};background:{m}'></div>"
        pline = (
            f"<div style='position:absolute;top:-6px;height:32px;width:0;border-left:2px dashed {T['blue_line']};z-index:1;left:{pct(price)}'></div>"
            if price
            else ""
        )
        tip = f"{rr['label']} {rr['sub']}: {F.won0(rr['lo'])} ~ {F.won0(rr['hi'])} (대표 {F.won0(rr['rep'])})"
        if rr.get("cut"):
            tip = f"{rr['label']}: Peer 5곳 미만(공개 모드 비표시)"
        sub = rr["sub"] + (f" · n {rr['n']}" if rr.get("n") else "")
        html.append(
            f"<div class='row' title='{ui.esc(tip)}'><div class='lab'><b>{ui.esc(rr['label'])}</b><span>{ui.esc(sub)}</span></div>"
            f"<div class='track'>{bar}{mark}{pline}</div><span class='val'>{F.won0(rr['rep']) if F.ok(rr['rep']) else '—'}</span></div>"
        )
    ticks = "".join(f"<span>{F.won0(lo_ax + (top - lo_ax) * i / 4)}</span>" for i in range(5))
    html.append(
        f"<div class='row'><span></span><div class='ticks'>{ticks}</div><span class='wb-kpi-note' style='text-align:right'>원</span></div></div>"
    )
    st.markdown("".join(html), unsafe_allow_html=True)


def evaluation(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    ui.h2("평가 요약")
    sig = M.signals(o, s, c.mode)
    r = M.result(o, s, c.mode)
    rel = M.relative(o, s, c.mode)
    ps = r.get("per_share")
    q25, q75, med = sig.get("q25"), sig.get("q75"), sig.get("peer_median")
    if sig.get("light_peer") == "회색" or not (F.ok(q25) and F.ok(q75)) or ps is None:
        conv, cc = "수렴 판정 불가", ""
    else:
        conv, cc = ("수렴", "g") if q25 <= ps <= q75 else ("미수렴", "y")
    basis = sig.get("peer_basis") or "EV/EBITDA"
    rp = ps / med if F.ok(ps) and F.ok(med) and med > 0 else None
    inval = "; ".join(sig.get("peer_invalid") or []).replace("q25", "1사분위").replace("q75", "3사분위")
    chips = [
        (
            conv,
            cc,
            f"DCF가 Peer {basis} IQR(1~3사분위, 주당 {F.won0(q25)} ~ {F.won0(q75)}) 안이면 수렴"
            + (f" · 해석 불가: {inval}" if inval else ""),
        ),
        (
            f"Peer {rp:.2f}x" if rp else "Peer 계산 불가",
            LIGHT.get(sig.get("light_peer"), ""),
            f"DCF ÷ Peer {basis} 중앙값 주당 · 신호 {sig.get('light_peer', '—')}",
        ),
        (
            f"시장 {sig['ratio_market']:.2f}x" if sig.get("ratio_market") else "시장 —",
            LIGHT.get(sig.get("light_market"), ""),
            "DCF ÷ 주가 · 신호 " + str(sig.get("light_market", "—")),
        ),
    ]
    st.markdown(
        "<div class='wb-chips'>"
        + "".join(f"<span class='wb-chip {k}' title='{ui.esc(t)}'>{ui.esc(x)}</span>" for x, k, t in chips)
        + "</div>",
        unsafe_allow_html=True,
    )
    m = rel["multiples"]

    def metric(nm):
        v = (m.get(nm) or {}).get("metric")
        return v / 100 if F.ok(v) and v > 0 else None  # 백만원 -> 억원

    ev, eq = r.get("ev"), r.get("equity")
    eb, ni, be = metric("EV/EBITDA"), metric("PER"), metric("PBR")
    try:
        d = V.dcf_detail(o, s, c.mode)
        tv = d.get("tv") or {}
    except (M.NeedInput, M.PublicDataUnavailable):
        tv = {}

    def peer_med(nm):
        x = (m.get(nm) or {}).get("median")
        return F.x_(x) if F.ok(x) else "계산 불가"

    items = [
        {"k": "내재 EV/EBITDA (LTM)", "v": f"{F.x_(ev / eb) if eb else '계산 불가'} · Peer {peer_med('EV/EBITDA')}"},
        {"k": "내재 PER (LTM)", "v": f"{F.x_(eq / ni) if ni else '계산 불가'} · Peer {peer_med('PER')}"},
        {"k": "내재 PBR", "v": f"{F.x_(eq / be) if be else '계산 불가'} · Peer {peer_med('PBR')}"},
        {
            "k": "출구 배수법 (Exit Multiple)",
            "v": f"{F.won0(tv.get('ps_exit'))}원 ({F.x_(tv.get('exit_mult'))})" if tv.get("ps_exit") else "계산 불가",
            "tip": "TV = 마지막 해 EBITDA × Peer EV/EBITDA 중앙값(참고)",
        },
    ]
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 14px;padding:12px;background:#F7F7F5;border-radius:8px'>"
        + "".join(
            f"<div title='{ui.esc(x.get('tip', ''))}' style='display:flex;flex-direction:column;gap:1px'><span class='wb-kpi-note' style='font-size:12px'>{ui.esc(x['k'])}</span>"
            f"<span style='font-size:15px;font-weight:500'>{ui.esc(x['v'])}</span></div>"
            for x in items
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def premium_tiles(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    a, b = st.columns([3, 1], vertical_alignment="center")
    a.markdown(
        f"<p class='wb-h2'><span class='wb-term' title='{ui.esc('과거 최대주주 지분 거래 집계 · 기준가 = 공시 전 20일 VWAP · 거래별 값 비공개')}'>경영권 프리미엄 (CP)</span></p>",
        unsafe_allow_html=True,
    )
    b.button("상세 →", key="to_premium", type="tertiary", on_click=nav.go, args=("premium",))
    pm = M.premium(o, s, c.mode)
    blk = pm.get("block")
    st.markdown(
        "<div class='wb-prem'>"
        + "".join(
            f"<div><span class='k'>{lab}</span><span class='v'>{F.pct_signed(pm[q])}</span><span class='s'>{F.won0(blk[q]) + '원' if blk else '—'}</span></div>"
            for lab, q in (("1사분위", "q25"), ("중앙값", "q50"), ("3사분위", "q75"))
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    note = f"블록 주당가 중앙값 {F.won0(blk['q50'])}원" if blk else "VWAP 입력 시 블록 주당가"
    st.markdown(f"<p class='wb-kpi-note'>{note} · {ui.esc(METHOD.get(pm['method'], pm['method']))}</p>", unsafe_allow_html=True)


METHOD = {"regression": "분위 회귀", "neighbours": "이웃 50건", "band_table": "시총 백분위 구간표"}


def top5(c: nav.Ctx) -> None:
    from app.wb.pages import assume_tab as AT

    rows = AT.visible_rows(c.s)
    ranked = [r for r in rows if r.get("rank") is not None][:5]
    a, b, d = st.columns([6, 1.2, 1], vertical_alignment="center")
    a.markdown("<p class='wb-h2'>주요 판단<span class='wb-h2-sub'>상위 5</span></p>", unsafe_allow_html=True)
    b.button(f"전체 {len(rows)} →", key="to_assume", type="tertiary", on_click=nav.go, args=("assume",))
    d.button("초기화", key="reset_v0", help="자동 초안(v0)의 가정으로 새 버전(기록은 그대로)", on_click=_reset, args=(c.sid,))
    for r in ranked:
        AT.compact_row(c, r)


def _reset(sid: str) -> None:
    from app.wb import shell

    s = M.load(sid)
    if M.version(s)["v"] == 0:
        return
    shell.note_change(s, "초기화")
    M.revert(s, 0, "초기화(자동 초안)")
