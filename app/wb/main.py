"""The work screen body shared by the PC entry (app/Workbench.py) and the public deployment (app/Home.py, P7-C3).

P7-U1 structure (config/p7u.yaml screen): top row (search, version, 이력, ⋯, 확정 · 내보내기) and sub row, the KPI band,
seven work tabs (only the selected tab is drawn), the overlays 이력 / 확정 · 내보내기 / 세션 관리, the reference pages
behind ⋯, and the first screen without a company.

run(public=False)   PC: PC / public modes, DB market data (P7-C2)
run(public=True)    public deployment: public mode only, the public snapshot (no DB), a workspace per browser session
"""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import model as M
from app.wb import nav, shell, style


def _pages() -> dict:
    from app.wb.pages import (
        assume_tab,
        dcf_tab,
        events_tab,
        export,
        fin_tab,
        history,
        premium_tab,
        ref,
        rel_tab,
        sessions,
        summary,
    )

    return {
        "summary": summary.render,
        "assume": assume_tab.render,
        "dcf": dcf_tab.render,
        "rel": rel_tab.render,
        "premium": premium_tab.render,
        "fin": fin_tab.render,
        "events": events_tab.render,
        "history": history.render,
        "export": export.render,
        "sessions": sessions.render,
        **{pid: ref.render for pid, _ in nav.REFS},
    }


def run(public: bool = False) -> None:
    if public:
        from app.wb import public_ui

        public_ui.begin()  # workspace of this browser session, cleanup, hidden diagnostics
        if public_ui.diag_requested():
            public_ui.diag()
            return
    st.session_state["_run_no"] = st.session_state.get("_run_no", 0) + 1  # P7-U2F: one-per-run notices
    st.session_state["_copy_n"] = 0  # P7-U3: copy-button keys count from 0 in every run (stable keys)
    c = nav.state(public)
    is_ref = c.page.startswith("ref_")
    style.inject("ref" if is_ref else "work")
    if not is_ref:
        from app.wb import client

        client.inject()  # P7-U2: fixed KPI bar, shortcuts, close warning (one script in the app document)
    if c.page == "calc":
        from app.wb import public_ui

        public_ui.calculator(c.mode)
        return
    if c.sid:
        try:
            nav.open_session(c)
        except Exception as e:  # noqa: BLE001 - the page says why instead of a stack trace
            from app.wb.model import PublicDataUnavailable

            if isinstance(e, PublicDataUnavailable):
                st.info(f"이 기능은 PC 모드 또는 사용자 입력이 필요합니다. ({e})")
            else:
                ui._log("open_session", e)
                st.error(f"세션을 열지 못했습니다(실패). 사유: {type(e).__name__}: {e}")
            c.s, c.o = None, None
    if is_ref:
        _pages()[c.page](c)
        return
    shell.top(c)
    if c.page == "sessions":
        _pages()["sessions"](c)
        ui.footer(c.mode, M.AS_OF)
        return
    if c.o is None:
        shell.first_screen(c)
        ui.footer(c.mode, M.AS_OF)
        return
    shell.toast(c)
    shell.kpi_band(c)
    shell.tabs(c)
    bar = c.page in shell.BAR_TABS
    if bar:
        shell.mini_bar(c)
    from app.wb import client

    client.state(c.page, bar, shell.dirty(c.s), c.mode == "public")
    page = c.page if c.page in _pages() else "summary"
    st_ = M.status(c.o, c.s)
    if st_["hold"] and st_["label"] != "확정" and page in nav.TAB_IDS and page != "summary":
        st.markdown(
            "<div class='wb-band-top'>평가 보류 — 아래 숫자는 보류 전 계산값(대표값 아님). 확인 뒤 확정하면 확정값이 대표값</div>",
            unsafe_allow_html=True,
        )
    if page == "summary" and st_["hold"] and st_["label"] != "확정":
        from app.wb.pages import hold

        hold.render(c, st_)
    else:
        with ui.card(f"tab_{page}", plain=True):
            _pages()[page](c)
    if page != "assume":
        from app.wb import values as V

        V.warm_deltas(c.o, c.s, c.mode)  # P7-U2: the 가정·판단 tab's Δ column, ready before it is opened
    ui.footer(c.mode, M.AS_OF)
