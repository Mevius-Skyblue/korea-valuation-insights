"""상대가치 tab (P7-U1): peer multiples with a two-level header ('Peer 배수' quartiles | target LTM | '주당가치 (원)'
quartiles), target vs peer aggregates, the Peer Set toggles (a change = a new version) and, folded, the per-peer details
(PC only: market cap, β, R²; both modes: business overview, relax step, change reason)."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav, shell
from app.wb import text as tx
from app.wb import values as V

ORDER = ["EV/EBITDA", "PER", "EV/Sales", "PBR"]
METRIC = {"EV/EBITDA": "EBITDA", "PER": "지배순이익", "EV/Sales": "매출", "PBR": "지배지분"}


def render(c: nav.Ctx) -> None:
    with ui.card("mult"):
        multiples(c)
        vs(c)
        peer_set(c)


def multiples(c: nav.Ctx) -> None:
    o, s, mn = c.o, c.s, c.mn
    rel = M.relative(o, s, c.mode)
    head = ["배수", "n", "1사분위", "중앙값", "3사분위", "대상 LTM", "1사분위", "중앙값", "3사분위"]
    rows = []
    for nm in ORDER:
        m = rel["multiples"].get(nm) or {}
        metric = m.get("metric")
        mt = f"{METRIC[nm]} {F.amt(metric / 100, mn)}{'백만' if mn else '억'}" if F.ok(metric) else f"{METRIC[nm]} 계산 불가"
        if m.get("public_cut"):
            rows.append({"c": [nm, m.get("n"), "Peer 5곳 미만", "", "", mt, "", "", ""], "strong": nm == "EV/EBITDA"})
            continue
        rows.append(
            {
                "c": [
                    nm,
                    m.get("n"),
                    F.x_(m.get("q25")),
                    F.x_(m.get("median")),
                    F.x_(m.get("q75")),
                    mt,
                    F.won0(m.get("ps_q25")),
                    F.won0(m.get("ps_median")),
                    F.won0(m.get("ps_q75")),
                ],
                "strong": nm == "EV/EBITDA",
            }
        )
    ksic = V.vs_peer(o, s, c.mode)["ksic"]
    ui.title_copy("유사기업 배수", "Trading Comps · LTM", ui.esc(f"KSIC {ksic} · 엑셀 Peers"), ui.tsv(head, rows))
    ui.tbl(
        head,
        rows,
        groups=[("", 2, False), ("Peer 배수", 3, False), ("", 1, False), ("주당가치 (원)", 3, True)],
        shade=(6, 7, 8),
        min_width=820,
    )
    st.markdown(
        "<p class='wb-kpi-note'>주당 = 배수 × LTM 지표 + 순현금·비영업 − 비지배"
        + (" · 공개 모드: Peer별 배수·시가총액 숨김, 집계는 Peer 5곳 이상만" if c.mode == "public" else "")
        + "</p>",
        unsafe_allow_html=True,
    )


def vs(c: nav.Ctx) -> None:
    v = V.vs_peer(c.o, c.s, c.mode)

    def pair(t):
        a, b, n = t
        return F.p1(a), (F.p1(b) if b is not None else ("Peer 5곳 미만" if c.mode == "public" and n else "—"))

    m, g, d = pair(v["margin"]), pair(v["growth"]), pair(v["de"])
    relax = {None: "완화 없음", 0: "완화 없음", 1: "완화 1단계(시가총액 0.1~10배)", 2: "완화 2단계(업종 한 단계 넓게)"}.get(
        v["relax"], f"완화 {v['relax']}단계"
    )
    items = [
        ("영업이익률 (LTM)", m),
        ("매출 성장률 (3년 CAGR)", g),
        ("부채비율 (D/E)", d),
        ("선정 기준", (f"KSIC {v['ksic']}", f"시총 범위 · 3년 흑자 · {relax}")),
    ]
    st.markdown(
        "<div class='wb-cells'>"
        + "".join(
            f"<div><span class='k'>{ui.esc(k)}</span><span style='font-size:14px'><span style='font-weight:500'>{ui.esc(a)}</span> "
            f"<span class='wb-kpi-note'>{'vs Peer ' if k != '선정 기준' else ''}{ui.esc(b)}</span></span></div>"
            for k, (a, b) in items
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def peer_set(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    rows = M.peer_rows(o, s, c.mode)
    names = [r["name"] for r in rows]
    cur = [r["name"] for r in rows if r["include"]]
    v = M.version(s)["v"]
    key = f"peerset_v{v}"
    st.pills(
        f"Peer Set ({len(cur)}/{len(names)})",
        names,
        selection_mode="multi",
        default=cur,
        key=key,
        on_change=_apply,
        args=(c.sid, key, cur),
        help="누르면 제외·포함 → 다시 계산(새 버전). βu·Peer 배수·출발 성장률(Peer 성장률 혼합)이 함께 바뀝니다",
    )
    msg = st.session_state.pop("peer_msg", None)
    if msg:
        (st.success if msg[0] else st.error)(msg[1])
    ps = o.summ.get("peer_screen") or o.cfg.get("peer_screen") or {}
    step = ps.get("relax_step")
    with st.expander("Peer 상세 · 사업 개요 · 선정 완화 단계 · 변경 이유"):
        st.text_input("Peer 변경 이유 (다음 변경에 기록)", key="peerwhy")
        st.markdown(
            f"<p class='wb-kpi-note'>선정 완화 단계: {ui.esc({None: '완화 없음', 0: '완화 없음', 1: '1단계(시가총액 0.1~10배)', 2: '2단계(업종 한 단계 넓게)'}.get(step, str(step)))}</p>",
            unsafe_allow_html=True,
        )
        if c.mode == "pc":
            ui.tbl(
                ["Peer", "코드", "포함", "시가총액(억원)", "EV/EBITDA", "EV/Sales", "β", "R²"],
                [
                    [
                        r["name"],
                        r["code"],
                        "포함" if r["include"] else "제외",
                        F.amt(r.get("mktcap_eok")),
                        F.x_(r.get("ev_ebitda")),
                        F.x_(r.get("ev_sales")),
                        f"{r['beta_raw']:.2f}" if F.ok(r.get("beta_raw")) else "—",
                        f"{r['r2']:.2f}" if F.ok(r.get("r2")) else "—",
                    ]
                    for r in rows
                ],
                tips=False,
                min_width=640,
            )
            st.markdown(
                "<p class='wb-kpi-note'>시가총액·배수·β·R²: 한국거래소 통계정보 기반(PC 모드만)</p>", unsafe_allow_html=True
            )
        for r in rows:
            st.markdown(
                f"<div style='font-size:14px;margin-top:6px'><b style='font-weight:500'>{ui.esc(r['name'])}</b> — {ui.esc(tx.plain_words(r['reason'].split(' — ')[0]))}"
                f"{tx.quote(r['overview'], 220) if r['overview'] else ''}</div>",
                unsafe_allow_html=True,
            )


def _apply(sid: str, key: str, cur: list[str]) -> None:
    """Peer edit = an assumption change linked to the matching peer-similarity judgement items (as P7-C2)."""
    s = M.load(sid)
    pick = list(st.session_state.get(key) or [])
    if sorted(pick) == sorted(cur):
        return
    reason = (st.session_state.get("peerwhy") or "").strip()
    removed = [x for x in cur if x not in pick]
    items = [
        j for j in M.judgement_rows(s) if j["category"] in ("피어 유사성", "피어 직접 지정") and j["item"] in (removed or pick)
    ]
    shell.note_change(s, "Peer Set")
    if items:
        r = M.resolve(s, items[0]["id"], "direct", field="peers", value=pick, reason=reason or "Peer 편집")
        if r["ok"]:
            for j in items[1:]:
                s["judgements"][j["id"]].update(
                    {
                        "status": "수정",
                        "resolution": {
                            "action": "direct",
                            "field": "peers",
                            "value": pick,
                            "reason": reason or "Peer 편집",
                            "at": M.S._now(),
                            "v": M.version(s)["v"],
                        },
                    }
                )
            M.S.save(s)
    else:
        r = M.set_value(s, "peers", pick, reason or "Peer 편집")
    if r["ok"]:
        st.session_state["peer_msg"] = (True, f"Peer {len(pick)}곳으로 바꿨습니다(v{M.version(s)['v']}).")
    else:
        st.session_state.pop("toast_from", None)
        st.session_state["peer_msg"] = (False, r["reason"])
