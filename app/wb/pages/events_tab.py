"""공시·이벤트 tab (P7-U1, config/p7u.yaml events): three sections separated by dashed lines - after the valuation date
(follow-up events), balance-sheet date -> valuation date, before the balance-sheet date (reference). Rows: filing date ·
title (tooltip) · kind · value-impact tag (link to the tab it touches) · review [반영 · 주석 · 해당 없음] (periodic reports
fixed) · DART original ↗. Four counts and three filters on top. Review marks are recorded in the session (no value is
recalculated: a person adjusts the assumptions or the bridge)."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import model as M
from app.wb import nav
from src.workbench import events as E

MARK_BTN = [("adj", "반영"), ("note", "주석"), ("na", "해당 없음")]


def render(c: nav.Ctx) -> None:
    with ui.card("events"):
        body(c)


def _review(sid: str, rcept: str, mark: str, cfg_path: str) -> None:
    s = M.load(sid)
    cfg = M._load_yaml(cfg_path)
    cur = ((s.get("events_review") or {}).get(rcept) or {}).get("mark", "")
    with M.LOCK:
        E.review(s, rcept, "" if cur == mark else mark, cfg=cfg)


def _lookup(sid: str, cfg_path: str) -> None:
    s = M.load(sid)
    with M.LOCK:
        E.lookup(s, M._load_yaml(cfg_path))


def body(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    ev = E.rows(o.cfg, s)
    st_ = ev["stats"]
    a, b = st.columns([3, 2], vertical_alignment="center")
    a.markdown(
        "<p class='wb-h2'>공시 · 이벤트<span class='wb-h2-sub'>재무기준일 뒤 → 평가기준일 → 후속 사건</span></p>",
        unsafe_allow_html=True,
    )
    with b:
        flt = st.segmented_control(
            "필터",
            ["all", "impact", "todo"],
            default="all",
            format_func={"all": "전체", "impact": "가치 영향", "todo": f"검토 전 {st_['to_review']}"}.get,
            key="ev_filter",
            label_visibility="collapsed",
            required=True,
        )
    lk = ev["sections"][0]["lookup"] or {}
    after_txt = (
        "조회 전"
        if not lk.get("at")
        else (
            f"{st_['after']}건"
            if str(lk.get("status")).startswith("조회됨") or lk.get("status") == "기준일 뒤 기간 없음"
            else "조회 실패"
        )
    )
    if c.mode == "public" or c.public:
        after_txt = "스냅샷 기준"
    ui.cells(
        [
            {"k": "재무기준일 → 평가기준일", "v": f"{st_['bs_to_asof']}건"},
            {
                "k": "가치 영향 태그",
                "v": f"<span style='color:{'#9A3412' if st_['tagged'] else '#1E6B3A'}'>{st_['tagged']}건</span>",
                "html": True,
            },
            {
                "k": "검토 전",
                "v": f"<span style='color:{'#9A3412' if st_['to_review'] else '#1E6B3A'}'>{st_['to_review']}건</span>",
                "html": True,
            },
            {"k": "후속 사건 (기준일 뒤)", "v": after_txt},
        ]
    )
    hc = st.columns([1.1, 3.8, 0.7, 1.3, 3.0, 0.4])
    for col, h in zip(hc, ["접수일", "보고서명", "구분", "가치 영향", "검토", "원문"]):
        col.markdown(f"<div class='wb-kpi-note' style='font-weight:500'>{h}</div>", unsafe_allow_html=True)
    shown = 0
    for sec in ev["sections"]:
        rows = sec["rows"]
        if flt == "impact":
            rows = [r for r in rows if r["tags"]]
        elif flt == "todo":
            rows = [r for r in rows if r["review"] and not r["mark"]]
        st.markdown(f"<div class='wb-evdiv'><span>{ui.esc(sec['label'])}</span><span></span></div>", unsafe_allow_html=True)
        if sec["id"] == "after_asof":
            _after_controls(c, sec)
        for r in rows:
            _row(c, r)
            shown += 1
    if shown == 0 and flt != "all":
        st.markdown("<p class='wb-kpi-note'>해당 행 없음 · 제목 규칙 기준</p>", unsafe_allow_html=True)
    legend = " ".join(f"<span class='wb-chip' title='{ui.attr(t['tip'])}'>{ui.esc(t['name'])}</span>" for t in E.rules()["tags"])
    st.markdown(
        f"<div class='wb-subrow' style='font-size:13px'>태그 기준 {legend}<span style='margin-left:auto'>공시 유형 코드 + 제목 단어 · 본문 미해석</span></div>",
        unsafe_allow_html=True,
    )


def _after_controls(c: nav.Ctx, sec: dict) -> None:
    lk = sec.get("lookup") or {}
    if c.mode == "public" or c.public:
        st.markdown("<p class='wb-kpi-note'>스냅샷 기준 · 조회 안 함(공개 모드)</p>", unsafe_allow_html=True)
        return
    a, b = st.columns([5, 1.2], vertical_alignment="center")
    if lk.get("at"):
        a.markdown(
            f"<p class='wb-kpi-note'>{ui.esc(lk['bgn'])}~{ui.esc(lk['end'])} · {ui.esc(lk['status'])} · 조회 {ui.esc(str(lk['at']).replace('T', ' '))}</p>",
            unsafe_allow_html=True,
        )
    else:
        a.markdown("<p class='wb-kpi-note'>평가기준일 뒤 공시 · [조회]를 누르면 OpenDART 목록 1회</p>", unsafe_allow_html=True)
    b.button(
        "조회",
        key="ev_lookup",
        on_click=_lookup,
        args=(c.sid, c.o.cfg_path),
        help="OpenDART 공시 목록 1회(평가기준일 다음 날 ~ 오늘)",
        width="stretch",
    )


def _row(c: nav.Ctx, r: dict) -> None:
    cols = st.columns([1.1, 3.8, 0.7, 1.3, 3.0, 0.4], vertical_alignment="center")
    cols[0].markdown(f"<span style='font-size:14px'>{r['date']}</span>", unsafe_allow_html=True)
    cols[1].markdown(
        f"<span title='{ui.attr(r['title'])}' style='font-size:14px'>{ui.esc(r['title'][:44])}</span>", unsafe_allow_html=True
    )
    cols[2].markdown(f"<span class='wb-kpi-note' style='font-size:14px'>{ui.esc(r['kind'])}</span>", unsafe_allow_html=True)
    with cols[3]:
        if r["tags"]:
            t = r["tags"][0]
            tab = E.tag_tab(t)
            st.button(
                t + (f" +{len(r['tags']) - 1}" if len(r["tags"]) > 1 else ""),
                key=f"evtag_{r['rcept_no']}",
                type="tertiary",
                help=E.tag_tip(t) + (" · " + " · ".join(r["tags"][1:]) if len(r["tags"]) > 1 else "") + " → 해당 탭",
                on_click=nav.go,
                args=(tab or "summary",),
            )
        elif r["periodic"]:
            st.markdown(f"{ui.badge('재무 기준', 'tag')}", unsafe_allow_html=True)
        else:
            st.markdown("<span style='color:#A0A3A8'>—</span>", unsafe_allow_html=True)
    with cols[4]:
        if r["review"]:
            bc = st.columns(3)
            for i, (m, lab) in enumerate(MARK_BTN):
                bc[i].button(
                    lab,
                    key=f"evm_{r['rcept_no']}_{m}",
                    type="primary" if r["mark"] == m else "secondary",
                    on_click=_review,
                    args=(c.sid, r["rcept_no"], m, c.o.cfg_path),
                    width="stretch",
                )
        else:
            st.markdown(f"<span class='wb-kpi-note' style='font-size:13px'>{ui.esc(r['fixed'])}</span>", unsafe_allow_html=True)
    cols[5].markdown(
        f"<a href='{r['href']}' target='_blank' rel='noopener' title='rcept_no {r['rcept_no']}' style='font-size:15px;text-decoration:none'>↗</a>",
        unsafe_allow_html=True,
    )
