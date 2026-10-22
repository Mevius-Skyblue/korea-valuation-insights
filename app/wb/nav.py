"""Navigation, sidebar and the page header of the work screen.

State lives in the address (query params): p = page, sid = session id, m = mode (pc / public). A browser refresh returns
to the same page, the same session and its latest version (the session file is the source of the values).
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from app.wb import components as ui
from app.wb import jobs as JB
from app.wb import model as M
from app.wb import text as tx

STEPS = [("select", "회사 선택"), ("data", "데이터 확인"), ("assume", "가정"), ("result", "결과"), ("export", "내보내기")]
REFS = [
    ("ref_rates", "실무 할인율 관행"),
    ("ref_accuracy", "추정 vs 실적"),
    ("ref_premium", "경영권 프리미엄"),
    ("ref_method", "방법론"),
    ("ref_guide", "이용 안내"),
]
TITLES = dict(STEPS + REFS)


@dataclass
class Ctx:
    page: str
    sid: str | None
    mode: str
    s: dict | None = None
    o: M.Opened | None = None
    public: bool = False  # P7-C3 public deployment: public mode only, no mode choice


def state(public: bool = False) -> Ctx:
    qp = st.query_params
    page = qp.get("p", "select")
    if page not in TITLES:
        page = "select"
    mode = "public" if public else qp.get("m", "pc")
    if mode not in ("pc", "public"):
        mode = "pc"
    sid = qp.get("sid") or None
    return Ctx(page=page, sid=sid, mode=mode, public=public)


def go(page: str, sid: str | None = None, mode: str | None = None, keep_sid: bool = True) -> None:
    """Callback: change page (and session / mode). Runs before the rerun, so no st.rerun() is needed."""
    qp = st.query_params
    cur_sid = qp.get("sid")
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
    """Load the session file (every run) and, except on step 1, the cached heavy part."""
    if not c.sid:
        return
    try:
        c.s = M.load(c.sid)
    except FileNotFoundError:
        st.warning(f"세션 {c.sid}을 찾을 수 없습니다(삭제됨). 1단계에서 다시 고르세요.")
        c.sid = None
        return
    if c.page != "select":
        c.o = _opened(c.sid, M.open_key(c.s), M.no_db(), str(M.S.workspace() or ""))  # P7-C3: per workspace
        if (c.mode == "pc" or c.public) and JB.prepare_on():
            JB.standby(c.sid)  # prepared confirmation: the Excel model of the current state (C2-F3)
        JB.ensure_warm()  # a pre-started job process for the next 확정 (fix C4-F1)


def sidebar(c: Ctx) -> None:
    with st.sidebar:
        st.markdown('<div class="wb-brand"><b>KVI</b><span>밸류에이션 워크벤치</span></div>', unsafe_allow_html=True)
        rows = sorted(M.sessions(), key=lambda r: r["sid"])  # stable order; labels unique (session number)
        ids = [r["sid"] for r in rows]
        # P7-C3 fix C3-F1: labels without the version (Streamlit 1.66 returned an old label as the value after the label changed)
        lab = {r["sid"]: f"{r['name']} ({r['code']}) #{r['sid'][-3:]}" for r in rows}
        if ids:
            idx = ids.index(c.sid) if c.sid in ids else None

            def _pick():
                v = st.session_state.get("side_target")
                if v not in ids:  # never a label or a stale value as a session id (C3-F1)
                    return
                if v:
                    go(c.page if c.page not in ("select",) else "data", sid=v)

            st.selectbox(
                "평가 대상",
                ids,
                index=idx,
                format_func=lambda x: lab.get(x, x),
                key="side_target",
                on_change=_pick,
                placeholder="세션 고르기",
            )
        st.markdown('<span class="wb-side-sub">진행 단계</span>', unsafe_allow_html=True)
        for i, (pid, label) in enumerate(STEPS, start=1):
            st.button(
                f"{i}  {label}",
                key=f"nav_{pid}",
                type="primary" if pid == c.page else "secondary",
                disabled=(pid != "select" and not c.sid),
                on_click=go,
                args=(pid,),
                width="stretch",
            )
        if c.s:
            n = M.S.pending(c.s)
            st.markdown(f'<div class="wb-pending">남은 판단 <b>{n}건</b></div>', unsafe_allow_html=True)

            def _open_judge():
                st.session_state["judge_open"] = True
                go("result")

            st.button(
                "판단 목록 열기",
                key="nav_judge",
                on_click=_open_judge,
                width="stretch",
                help="사람이 확인·결정할 항목(주당 영향 큰 순)",
            )
        st.markdown('<span class="wb-side-sub">참고 자료</span>', unsafe_allow_html=True)
        for pid, label in REFS:
            st.button(
                label,
                key=f"nav_{pid}",
                type="primary" if pid == c.page else "secondary",
                on_click=go,
                args=(pid,),
                width="stretch",
            )
        if c.public:
            st.markdown('<a class="wb-side-link" href="/calculator" target="_self">간이 DCF 계산기 →</a>', unsafe_allow_html=True)
        a, b = tx.MODE_LABEL["deploy" if c.public else c.mode]
        st.markdown(f'<div class="wb-modebox">{a}<br>{b}</div>', unsafe_allow_html=True)


def header(c: Ctx, title: str) -> None:
    """Eyebrow (code · market · KSIC · basis · as-of), title, status badge, version, pending; snapshot warning band."""
    o, s = c.o, c.s
    cfg = o.cfg
    st_ = M.status(o, s)
    v = M.version(s)["v"]
    eyebrow = (
        f"{o.code} · {cfg['target'].get('market', '')} · KSIC {cfg['target'].get('induty_code', '')} · "
        f"{'연결' if cfg['meta']['fs_div'] == 'CFS' else '별도'} · 평가기준일 {cfg['meta']['as_of']} · 세션 {s['session_id']}"
    )
    right = (
        ui.badge(st_["label"], st_["cls"])
        + " "
        + ui.badge(f"버전 v{v}")
        + " "
        + ui.badge(f"미처리 판단 {M.S.pending(s)}건", "warn" if M.S.pending(s) else "ok")
    )
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:flex-end">'
        f'<div><p class="wb-eyebrow">{ui.esc(eyebrow)}</p><h1 class="wb-title">{ui.esc(o.name)} {ui.esc(title)}</h1></div>'
        f'<div style="padding-bottom:8px">{right}</div></div>',
        unsafe_allow_html=True,
    )
    w = o.snapshot_warnings()
    if w:
        st.markdown(
            f'<div class="wb-band-top" role="alert">자료가 바뀌었습니다 — 다시 확인 후 확정 ({ui.esc("; ".join(w))})</div>',
            unsafe_allow_html=True,
        )


def public_inputs(c: Ctx, key: str) -> None:
    """Public mode: the user's market inputs (target close, 20-day VWAP, listed subsidiaries, listed preferred)."""
    o, s = c.o, c.s
    u = s.get("public_inputs") or {}
    miss = M.public_missing(o, s)
    with ui.card(
        f"pubin_{key}",
        "시세 직접 입력(공개 모드)",
        "공개 모드에서는 한국거래소 시세를 쓰지 않습니다. 아래 값을 넣으면 평가 숫자를 계산합니다(넣은 값만 화면에 표시).",
    ):
        with st.form(f"pubform_{key}", border=False):
            a, b = st.columns(2)
            close = a.text_input("대상 종가(원)", value=f"{u['close']:.0f}" if u.get("close") else "", key=f"pub_close_{key}")
            vw = b.text_input(
                "대상 20일 VWAP(원)",
                value=f"{u['vwap20']:.0f}" if u.get("vwap20") else "",
                key=f"pub_vwap_{key}",
                help=tx.GLOSSARY["VWAP"],
            )
            subs = {}
            for x in o.subs:
                cur = (u.get("sub_close") or {}).get(x["stock_code"])
                subs[x["stock_code"]] = st.text_input(
                    f"상장 종속회사 종가(원): {x.get('name', '')}({x['stock_code']})",
                    value=f"{cur:.0f}" if cur else "",
                    key=f"pub_sub_{x['stock_code']}_{key}",
                )
            for x in getattr(o, "assocs", []):  # P7-X2b listed associates (each row asks for its own close)
                cur = (u.get("sub_close") or {}).get(x["stock_code"])
                subs[x["stock_code"]] = st.text_input(
                    f"상장 관계기업 종가(원): {x.get('name', '')}({x['stock_code']})",
                    value=f"{cur:.0f}" if cur else "",
                    key=f"pub_as_{x['stock_code']}_{key}",
                )
            prefs = {}
            for p in o.prefs:
                cur = (u.get("pref") or {}).get(p) or {}
                q1, q2 = st.columns(2)
                prefs[p] = {
                    "close": q1.text_input(
                        f"상장 우선주 {p} 종가(원)",
                        value=f"{cur['close']:.0f}" if cur.get("close") else "",
                        key=f"pub_pc_{p}_{key}",
                    ),
                    "listed": q2.text_input(
                        f"상장 우선주 {p} 상장주식수", value=str(cur.get("listed") or ""), key=f"pub_pl_{p}_{key}"
                    ),
                }
            ok = st.form_submit_button("입력 저장", type="primary")
        if ok:

            def num(x):
                t = str(x).replace(",", "").strip()
                return float(t) if t else None

            try:
                user = {
                    "close": num(close),
                    "vwap20": num(vw),
                    "sub_close": {k: num(v) for k, v in subs.items() if num(v)},
                    "pref": {
                        k: {"close": num(v["close"]), "listed": num(v["listed"])}
                        for k, v in prefs.items()
                        if num(v["close"]) and num(v["listed"])
                    },
                }
                M.S.set_public_inputs(s, user)
                st.success("저장했습니다. 평가 숫자를 사용자 시세로 다시 계산합니다.")
                st.rerun()
            except ValueError as e:
                st.error(f"입력 확인: {e}")
        if miss:
            st.markdown(f'<p class="wb-kpi-note wb-warn">남은 입력: {ui.esc(", ".join(miss))}</p>', unsafe_allow_html=True)
