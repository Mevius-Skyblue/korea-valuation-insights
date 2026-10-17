"""1 회사 선택: search, as-of date, mode, 'can this be valued automatically' (gates G1~G8 and the path), saved sessions
(open / clone / delete with two confirmations) and a new company's first draft with stage-by-stage progress."""
from __future__ import annotations

import time
from datetime import date

import streamlit as st

from app.wb import components as ui
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx

STAGE = {"draft": "자동 초안(수집·피어·적재 전체)", "draft.gate_a": "게이트 A(업종·적자·매출·구조) 확인", "draft.collect_target": "대상 회사 공시 수집",
         "draft.select_peers": "피어 고르기", "draft.collect_peers": "피어 공시 수집", "draft.load_db": "DB 적재(재무·D&A)",
         "draft.config": "설정 초안 쓰기", "gate_b": "게이트 B(재무 자료·피어 3곳)", "valuation": "피어 표",
         "session_tables": "세션 표", "engine": "평가 계산(DCF·상대가치·프리미엄)", "first_draft": "신호·판단 목록"}


def _gate_card(code: str, name: str) -> dict:
    ds = M.draft_state(code)
    gv = M.gate_view(ds["summary"])
    if not ds["summary"]:
        with ui.card("gate", "자동 평가 가능 여부", right=ui.badge("초안 없음")):
            st.markdown(f"<p class='wb-kpi-note'>{ui.esc(name)}({code})는 아직 자동 초안이 없습니다. <b>평가 시작</b>을 누르면 공시를 모아 "
                        "초안을 만듭니다(보통 30~60초, DART 호출 약 20~40회). 게이트에 걸리면 숫자 없이 사유만 보여 줍니다.</p>",
                        unsafe_allow_html=True)
        return {"ok": True, "has_draft": False, "gv": gv}
    passed = gv["passed"]
    with ui.card("gate", "자동 평가 가능 여부", right=ui.badge("통과" if passed else "범위 밖", "ok" if passed else "warn")):
        rows = []
        for r in gv["rows"]:
            mark = {"✓": ui.badge("✓ 통과", "ok"), "✗": ui.badge("✗ 걸림", "warn"), "→": ui.badge("→ 경로", "dark"),
                    "확인 전": ui.badge("확인 전")}[r["status"]]
            rows.append([r["id"], r["label"], ("html", mark), r["value"]])
        ui.table(["게이트", "항목", "결과", "값·경로"], rows)
        st.markdown(f"<p style='margin:8px 0 0 0;font-size:14px'>{tx.term('게이트', '판정')} 경로: <b>{ui.esc(gv['path'])}</b></p>",
                    unsafe_allow_html=True)
        if not passed:
            st.markdown("<p class='wb-h2' style='margin-top:12px'>이 회사가 범위 밖인 이유</p>", unsafe_allow_html=True)
            for f in gv["fails"]:
                st.markdown(f"<p style='font-size:14px;margin:4px 0'><b>{f['id']} {ui.esc(f['label'])}</b> — {ui.esc(f['why'])}"
                            f"<br><span class='wb-kpi-note'>값: {ui.esc(f['value'])}</span></p>", unsafe_allow_html=True)
            st.markdown("<p class='wb-kpi-note'>범위 밖이면 평가 숫자를 내지 않습니다. 억지로 낸 숫자는 실무에서 신뢰를 잃기 때문입니다.</p>",
                        unsafe_allow_html=True)
    return {"ok": bool(passed), "has_draft": True, "gv": gv}


def _start(code: str, mode: str) -> None:
    """New session (first draft with progress if needed) -> step 2."""
    box = st.status("초안을 만들고 세션을 여는 중", expanded=True)
    lines, t0 = [], time.time()
    ph = box.empty()

    def on_step(name, state_, secs):
        if state_ == "start" and name != "draft":
            lines.append([STAGE.get(name, name), "진행 중", ""])
        elif state_ in ("ok", "fail"):
            lab = STAGE.get(name, name)
            hit = next((x for x in reversed(lines) if x[0] == lab), None)
            if hit is None:
                hit = [lab, "", ""]
                lines.append(hit)
            hit[1], hit[2] = ("완료" if state_ == "ok" else "실패"), f"{secs:.1f}초"
        ph.markdown("".join(f"<div class='wb-step'><span>{ui.esc(a)}</span><span>{ui.esc(b)} {ui.esc(c)}</span></div>"
                            for a, b, c in lines) + f"<p class='wb-kpi-note'>경과 {time.time() - t0:.0f}초</p>", unsafe_allow_html=True)
    try:
        with M.LOCK:
            s = M.S.create(code, on_step=on_step)
    except ValueError as e:
        box.update(label="자동 평가 범위 밖", state="error")
        st.error(f"초안을 만들 수 없습니다: {e}")
        return
    except Exception as e:                        # noqa: BLE001 - shown, the page stays
        ui._log("create", e)
        box.update(label="실패", state="error")
        st.error(f"실패: {type(e).__name__}: {e}")
        st.button("다시 시도", key="retry_create")
        return
    box.update(label=f"세션 {s['session_id']} 준비 완료({time.time() - t0:.0f}초)", state="complete")
    nav.go("data", sid=s["session_id"], mode=mode)
    st.rerun()


def render(c: nav.Ctx) -> None:
    ui.page_title(f"평가기준일 {M.AS_OF}", "평가할 회사를 고르세요")
    if c.public:
        from app.wb import public_ui
        public_ui.banner()
    with ui.card("search", None):
        uni = M.universe()
        codes = [u["code"] for u in uni]
        lab = {u["code"]: f"{u['name']} ({u['code']}) · {u['market']}" for u in uni}
        a, b = st.columns([3, 1])
        code = a.selectbox("종목명 또는 종목코드", codes, index=None, format_func=lambda x: lab.get(x, x), key="pick_code",
                           placeholder="예: JW중외제약 또는 001060",
                           help=("공개 범위: 개발·검증에 쓴 회사 " + f"{len(codes)}곳(평가 가능 + 범위 밖)") if c.public
                           else "KOSPI·KOSDAQ 보통주. 입력하면 목록이 좁혀집니다")
        d = b.date_input("평가기준일", value=date(2026, 9, 30), key="pick_date", format="YYYY-MM-DD")
        mode = c.mode
        if not c.public:                          # P7-C3: the public deployment is public mode only (no choice shown)
            mode_lab = {"pc": "PC (전체)", "public": "공개 (시세 직접 입력)"}
            mode = st.segmented_control("데이터 모드", ["pc", "public"], default=c.mode, format_func=mode_lab.get, key="pick_mode",
                                        help="공개 모드에서는 주가·시가총액을 직접 입력하고, 피어별 시세 값은 보이지 않습니다") or c.mode
            if mode != c.mode:
                st.query_params["m"] = mode
                c.mode = mode
        else:
            st.markdown("<p class='wb-kpi-note'>공개 배포: 회사 범위는 개발·검증에 이미 쓴 회사로 한정합니다(새 회사 초안은 PC 모드). "
                        "주가·VWAP은 직접 넣습니다.</p>", unsafe_allow_html=True)
        if d != date(2026, 9, 30):
            st.warning("자동 초안은 지금 평가기준일 2026-09-30만 지원합니다(다른 기준일은 시세·재무 기준 시점 규칙을 새로 고정한 뒤).")
        st.markdown(f"<span class='wb-kpi-note'>최근 세션: {ui.esc(', '.join(dict.fromkeys(r['name'] for r in M.sessions()[:4])))}</span>",
                    unsafe_allow_html=True)
    gate = None
    if code:
        name = lab.get(code, code).split(" (")[0]
        left, right = st.columns([3, 2])
        with left:
            gate = _gate_card(code, name)
        with right:
            with ui.card("rule", "자동 평가에서 제외되는 회사"):
                st.markdown("<ul style='font-size:14px;line-height:1.7;margin:0;padding-left:18px'>"
                            "<li>금융업(은행·보험·증권)·금융회사형 재무구조 — 평가 방법이 다름</li>"
                            "<li>최근 3년 영업이익이 모두 적자이고 매출도 작음</li><li>매출 100억원 미만</li>"
                            "<li>12월 결산이 아님</li><li>지원하지 않는 지배구조</li></ul>"
                            "<p class='wb-kpi-note'>제외되면 숫자를 내지 않고 사유만 보여 줍니다. " + nav.link("ref_method", "방법론 보기", c) + "</p>",
                            unsafe_allow_html=True)
        can = gate is None or gate["ok"] or (not gate["has_draft"] and not c.public)
        if st.button("평가 시작(새 세션)", key="start", type="primary", disabled=not can or d != date(2026, 9, 30),
                     help="자동 초안으로 새 평가 세션을 만들고 2단계로 갑니다"):
            _start(code, mode)
    _sessions(c)
    if c.public:
        with ui.card("session_files", "세션 파일", "내려받기 · 불러오기"):
            from app.wb import public_ui
            public_ui.session_files(c)
    ui.footer(c.mode, M.AS_OF)


def _sessions(c: nav.Ctx) -> None:
    rows = M.sessions()
    with ui.card("sessions", "저장된 세션", f"{len(rows)}개 · 세션 = 회사·기준일·자료 스냅샷·가정·버전·감사 기록"):
        if not rows:
            st.markdown("<p class='wb-kpi-note'>아직 세션이 없습니다.</p>", unsafe_allow_html=True)
            return
        show = rows if st.session_state.get("sess_all") else rows[:12]
        for r in show:
            sid = r["sid"]
            a, b, cc, dd = st.columns([4, 3, 1.1, 1.6])
            a.markdown(f"<div style='font-size:14px'><b>{ui.esc(r['name'])}</b> ({r['code']})<br><span class='wb-kpi-note'>{sid} · 기준일 {r['as_of']}</span></div>",
                       unsafe_allow_html=True)
            stat = ui.badge(r["status"], "ok" if r["status"] == "확정" else "") + " " + ui.badge(
                f"미처리 {r['pending']}", "warn" if r["pending"] else "ok")
            b.markdown(f"<div style='font-size:13px'>v{r['version']} {stat}<br><span class='wb-kpi-note'>마지막 수정 {r['modified']}"
                       f"{' · ' + ui.esc(r['auto']) if r['auto'] == '자동 결과 보류' else ''}</span></div>", unsafe_allow_html=True)
            cc.button("열기", key=f"open_{sid}", on_click=nav.go, args=("data", sid, c.mode), width="stretch")
            with dd:
                x1, x2 = st.columns(2)
                x1.button("복제", key=f"clone_{sid}", on_click=_clone, args=(sid,), width="stretch")
                x2.button("삭제", key=f"del_{sid}", on_click=_del_ask, args=(sid,), width="stretch")
            step = st.session_state.get(f"delstep_{sid}", 0)
            if step == 1:
                st.warning(f"{sid}을 삭제할까요? 세션 파일과 감사 기록이 지워집니다(산출물 파일은 남음). 확인 1/2")
                st.button("삭제 확인(1/2)", key=f"del1_{sid}", on_click=_del_step, args=(sid, 2))
            elif step == 2:
                st.error(f"정말 영구 삭제합니까? 되돌릴 수 없습니다. 확인 2/2")
                y1, y2 = st.columns(2)
                y1.button("영구 삭제(2/2)", key=f"del2_{sid}", on_click=_del_do, args=(sid,), type="primary")
                y2.button("취소", key=f"delx_{sid}", on_click=_del_step, args=(sid, 0))
        if len(rows) > 12:
            st.toggle("모두 보기", key="sess_all")
        msg = st.session_state.pop("sess_msg", None)
        if msg:
            st.success(msg)


def _clone(sid: str) -> None:
    s2 = M.S.clone(sid)
    st.session_state["sess_msg"] = f"{sid}을 {s2['session_id']}로 복제했습니다(가정·버전·감사 기록 포함, 확정 기록 제외)."


def _del_ask(sid: str) -> None:
    st.session_state[f"delstep_{sid}"] = 1


def _del_step(sid: str, n: int) -> None:
    st.session_state[f"delstep_{sid}"] = n


def _del_do(sid: str) -> None:
    M.S.delete(sid)
    st.session_state[f"delstep_{sid}"] = 0
    st.session_state["sess_msg"] = f"{sid}을 삭제했습니다."
    if st.query_params.get("sid") == sid:
        st.query_params.pop("sid", None)
