"""세션 관리 (⋯ > 모든 세션, P7-U1): every saved session (open / clone / delete with two confirmations) and the session
file download / upload (public deployment: the browser workspace is deleted after 6 hours or on refresh)."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import model as M
from app.wb import nav


def render(c: nav.Ctx) -> None:
    rows = M.sessions()
    with ui.card("sessions"):
        ui.h2("모든 세션", f"{len(rows)}개", "세션 = 회사·기준일·자료 스냅샷·가정·버전·감사 기록")
        if not rows:
            st.markdown("<p class='wb-kpi-note'>아직 세션이 없습니다.</p>", unsafe_allow_html=True)
        show = rows if st.session_state.get("sess_all") else rows[:20]
        for r in show:
            sid = r["sid"]
            a, b, cc, dd = st.columns([4, 3, 1.1, 1.8], vertical_alignment="center")
            a.markdown(
                f"<div style='font-size:14px'><b style='font-weight:500'>{ui.esc(r['name'])}</b> {r['code']} · #{sid[-3:]} · 기준일 {r['as_of']}</div>",
                unsafe_allow_html=True,
            )
            stat = (
                ui.badge(r["status"], "ok" if r["status"] == "확정" else "")
                + " "
                + ui.badge(f"미처리 {r['pending']}", "warn" if r["pending"] else "ok")
            )
            b.markdown(
                f"<div style='font-size:13px'>v{r['version']} {stat} <span class='wb-kpi-note'>{r['modified']}{' · 자동 결과 보류' if r['auto'] == '자동 결과 보류' else ''}</span></div>",
                unsafe_allow_html=True,
            )
            cc.button("열기", key=f"open_{sid}", on_click=nav.go, args=("summary", sid, c.mode), width="stretch")
            with dd:
                x1, x2 = st.columns(2)
                x1.button("복제", key=f"clone_{sid}", on_click=_clone, args=(sid,), width="stretch")
                x2.button("삭제", key=f"del_{sid}", on_click=_del_step, args=(sid, 1), width="stretch")
            step = st.session_state.get(f"delstep_{sid}", 0)
            if step == 1:
                st.warning(
                    f"{r['name']} #{sid[-3:]}을 삭제할까요? 세션 파일과 감사 기록이 지워집니다(산출물 파일은 남음). 확인 1/2"
                )
                st.button("삭제 확인(1/2)", key=f"del1_{sid}", on_click=_del_step, args=(sid, 2))
            elif step == 2:
                st.error("정말 영구 삭제합니까? 되돌릴 수 없습니다. 확인 2/2")
                y1, y2 = st.columns(2)
                y1.button("영구 삭제(2/2)", key=f"del2_{sid}", on_click=_del_do, args=(sid,), type="primary")
                y2.button("취소", key=f"delx_{sid}", on_click=_del_step, args=(sid, 0))
        if len(rows) > 20:
            st.toggle("모두 보기", key="sess_all")
        msg = st.session_state.pop("sess_msg", None)
        if msg:
            st.success(msg)
    with ui.card("session_files"):
        ui.h2("세션 저장 · 불러오기", "세션 파일(.json)")
        from app.wb import public_ui

        public_ui.session_files(c)


def _clone(sid: str) -> None:
    s2 = M.S.clone(sid)
    st.session_state["sess_msg"] = f"복제했습니다: #{s2['session_id'][-3:]} (가정·버전·감사 기록 포함, 확정 기록 제외)."


def _del_step(sid: str, n: int) -> None:
    st.session_state[f"delstep_{sid}"] = n


def _del_do(sid: str) -> None:
    M.S.delete(sid)
    st.session_state[f"delstep_{sid}"] = 0
    st.session_state["sess_msg"] = f"#{sid[-3:]}을 삭제했습니다."
    if st.query_params.get("sid") == sid:
        st.query_params.pop("sid", None)
