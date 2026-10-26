"""Navigation of the work screen (P7-U1, config/p7u.yaml screen).

State lives in the address (query params): p = tab / overlay / reference page, sid = session id, m = mode (pc / public).
A browser refresh returns to the same tab, session and latest version (the session file is the source of the values).
Old addresses of the five steps still work (f3 in the moved-location table): data -> fin, assume -> assume,
result -> summary, export -> export, select -> the first screen.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from app.wb import components as ui
from app.wb import jobs as JB
from app.wb import model as M

TABS = [
    ("summary", "요약"),
    ("assume", "가정·판단"),
    ("dcf", "DCF"),
    ("rel", "상대가치"),
    ("premium", "경영권 프리미엄"),
    ("fin", "재무"),
    ("events", "공시·이벤트"),
]
OVERLAYS = [("history", "이력"), ("export", "확정 · 내보내기"), ("sessions", "세션 관리")]
REFS = [
    ("ref_rates", "실무 할인율 관행"),
    ("ref_accuracy", "추정 vs 실적"),
    ("ref_premium", "경영권 프리미엄 참고"),
    ("ref_method", "방법론"),
    ("ref_valid", "검증 결과"),
    ("ref_guide", "이용 안내"),
]
LEGACY = {"data": "fin", "result": "summary", "select": "start"}
TITLES = dict(TABS + OVERLAYS + REFS + [("start", "시작")])
TAB_IDS = [t for t, _ in TABS]


@dataclass
class Ctx:
    page: str
    sid: str | None
    mode: str
    s: dict | None = None
    o: M.Opened | None = None
    public: bool = False  # P7-C3 public deployment: public mode only, no mode choice

    @property
    def mn(self) -> bool:
        """Amounts in 백만원 (unit toggle; 억원 by default)."""
        return st.session_state.get("unit_mn", False)


def state(public: bool = False) -> Ctx:
    qp = st.query_params
    page = qp.get("p", "")
    page = LEGACY.get(page, page)
    sid = qp.get("sid") or None
    if page not in TITLES:
        page = "summary" if sid else "start"
    if page in TAB_IDS + ["history", "export"] and not sid:
        page = "start"
    mode = "public" if public else qp.get("m", "pc")
    if mode not in ("pc", "public"):
        mode = "pc"
    return Ctx(page=page, sid=sid, mode=mode, public=public)


def go(page: str, sid: str | None = None, mode: str | None = None, keep_sid: bool = True) -> None:
    """Callback: change page (and session / mode). Runs before the rerun, so no st.rerun() is needed."""
    qp = st.query_params
    cur_sid = qp.get("sid")
    page = LEGACY.get(page, page)
    new = {"p": page, "m": "public" if M.public_deploy() else (mode or qp.get("m", "pc"))}
    s_ = sid if sid is not None else (cur_sid if keep_sid else None)
    if s_:
        new["sid"] = s_
    qp.clear()
    qp.update(new)


def link(page: str, label: str, c: Ctx, anchor: str = "") -> str:
    """HTML link to another page of the app (full reload keeps the address state)."""
    q = f"?p={page}&m={c.mode}" + (f"&sid={c.sid}" if c.sid else "")
    return f'<a href="{q}{anchor}" target="_self">{ui.esc(label)}</a>'


@st.cache_resource(max_entries=12, show_spinner=False)
def _opened(sid: str, key: str, no_db: bool, ws: str) -> M.Opened:
    return M.Opened(sid)


def open_session(c: Ctx) -> None:
    """Load the session file (every run) and the cached heavy part of an open session."""
    if not c.sid:
        return
    try:
        c.s = M.load(c.sid)
    except FileNotFoundError:
        st.warning("세션을 찾을 수 없습니다(삭제됨). 검색창에서 다시 고르세요.")
        c.sid = None
        return
    if c.page in ("start", "sessions") or c.page.startswith("ref_"):
        return
    c.o = _opened(c.sid, M.open_key(c.s), M.no_db(), str(M.S.workspace() or ""))  # P7-C3: per workspace
    if c.mode == "public" and not c.s.get("public_inputs"):
        # P7-U2F D2: the first open in public mode starts from the example prices (marked example, as the button does);
        # the user's own values replace them
        M.S.set_public_inputs(c.s, M.example_inputs(c.o))
        c.s = M.load(c.sid)
    if (c.mode == "pc" or c.public) and JB.prepare_on():
        JB.standby(c.sid)  # prepared confirmation: the Excel model of the current state (C2-F3)
    JB.ensure_warm()  # a pre-started job process for the next 확정 (fix C4-F1)
