"""The work screen body shared by the PC entry (app/Workbench.py) and the public deployment (app/Home.py, P7-C3).

run(public=False)   PC: PC / public modes, DB market data (P7-C2)
run(public=True)    public deployment: public mode only, the public snapshot (no DB), a workspace per browser session
"""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import nav, style
from app.wb.pages import assume, data, export, ref, result, select


def run(public: bool = False) -> None:
    if public:
        from app.wb import public_ui

        public_ui.begin()  # workspace of this browser session, cleanup, hidden diagnostics
        if public_ui.diag_requested():
            public_ui.diag()
            return
    c = nav.state(public)
    is_ref = c.page.startswith("ref_")
    style.inject("ref" if is_ref else "work")
    if c.sid and not is_ref:
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
    if not is_ref:
        nav.sidebar(c)
    if c.page != "select" and not is_ref and c.o is None:
        st.markdown('<h1 class="wb-title">세션을 먼저 고르세요</h1>', unsafe_allow_html=True)
        if public:
            st.markdown(
                "<p class='wb-kpi-note'>공개 배포에서는 브라우저를 새로 고치면 작업 공간이 새로 만들어집니다. "
                "1단계의 <b>세션 파일 불러오기</b>로 이어서 작업할 수 있습니다.</p>",
                unsafe_allow_html=True,
            )
        st.button("1단계 회사 선택으로", key="to_select", on_click=nav.go, args=("select",), type="primary")
    else:
        {
            "select": select.render,
            "data": data.render,
            "assume": assume.render,
            "result": result.render,
            "export": export.render,
            "ref_rates": ref.render,
            "ref_accuracy": ref.render,
            "ref_premium": ref.render,
            "ref_method": ref.render,
            "ref_valid": ref.render,
            "ref_guide": ref.render,
        }[c.page](c)
