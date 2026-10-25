"""확정 · 내보내기 (top button, P7-U1): the six report boxes the evaluator writes, purpose / premise / evaluator, the
pre-confirmation check (pending judgements, written boxes, hold, market price), confirm (a second confirmation when
judgements are still pending) -> Excel model as soon as it is written, report and session file; the Excel <-> engine
reconciliation and the report run in the background and the status refreshes by itself. Public mode: the user's market
inputs -> public export -> KRX scan of the outputs (download only with 0 hits; the deployment keeps files 6 hours)."""

from __future__ import annotations

import time

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import jobs as JB
from app.wb import model as M
from app.wb import nav

MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}
MEMOS = [
    ("method", "평가방법 선택 근거·채택·가중치", "DCF 채택 이유, 상대가치·경영권 거래의 역할"),
    ("norm", "정상화 조정 (비경상 손익)", "과거 이익의 일회성 손익·영업 외 항목 처리"),
    ("contingent", "우발채무·비영업자산 명세", "소송·지급보증·약정, '기타 금융자산' 분류"),
    ("dlom", "DLOM·경영권 프리미엄 조정", "평가 목적상 조정 필요 여부, 블록 띠 사용"),
    ("reason", "주요 가정의 합리성", "실무 관행과 다른 가정의 근거"),
    ("limit", "평가상 한계 보완", "데이터 한계·모델 단순화"),
]


def render(c: nav.Ctx) -> None:
    a, b = st.columns(2, gap="medium")
    with a:
        with ui.card("memos"):
            memos(c)
    with b:
        with ui.card("confirm"):
            ui.h2("확정 · 내보내기")
            with st.expander("평가 목적 · 전제 · 평가자", expanded=not bool(c.s.get("engagement"))):
                _engagement(c)
            preflight(c)
            if c.mode == "pc":
                _confirm(c)
            else:
                _public(c)
        with ui.card("live", plain=True):
            if c.mode == "pc":
                _live(c)
    with ui.card("outputs"):
        _outputs(c)


def memos(c: nav.Ctx) -> None:
    s = c.s
    cur = s.get("memos") or {}
    done = sum(1 for k, _, _ in MEMOS if cur.get(k))
    ui.h2("보고서 작성 칸", "평가자 작성", f"{done}/6 작성")
    d = M.differs_from_practice(s, M.result(c.o, s, c.mode), c.o) if c.o else []
    with st.form("memo_form", border=False):
        vals = {}
        for k, title, ph in MEMOS:
            hint = ph
            if k == "reason" and d:
                hint = f"{ph}: " + ", ".join(f"{x['item']} {x['ours']}" for x in d)
            with st.expander(f"{title} · {'작성' if cur.get(k) else '미작성'}", expanded=False):
                vals[k] = st.text_area(
                    title, value=cur.get(k, ""), key=f"memo_{k}", placeholder=hint, label_visibility="collapsed", height=110
                )
        ok = st.form_submit_button("작성 칸 저장")
    if ok:
        r = M.S.set_memos(M.load(c.sid), vals)
        if not r.get("noop"):
            st.rerun()


def _engagement(c: nav.Ctx) -> None:
    """P7-X2b: the three engagement fields of the session (saved with an audit entry; no new version)."""
    e = c.s.get("engagement") or {}
    purpose = st.text_input("평가 목적", value=e.get("purpose", ""), key="eng_purpose", placeholder="방법론 예시(기본)")
    premise = st.text_input("평가 전제", value=e.get("premise", ""), key="eng_premise", placeholder="계속기업(기본)")
    who = st.text_input("평가자", value=e.get("evaluator", ""), key="eng_evaluator", placeholder="(비워 두면 표시 안 함)")
    if st.button("저장", key="eng_save"):
        r = M.S.set_engagement(M.load(c.sid), {"purpose": purpose, "premise": premise, "evaluator": who})
        if not r.get("noop"):
            st.rerun()


def preflight(c: nav.Ctx) -> None:
    from app.wb import shell

    s = c.s
    n = shell.tab_counts(c)["assume"]
    done = sum(1 for k, _, _ in MEMOS if (s.get("memos") or {}).get(k))
    st_ = M.status(c.o, s)
    mk = M.market(c.o, s, c.mode)
    ex = (s.get("public_inputs") or {}).get("example") and c.mode == "public"
    rows = [
        ("미처리 판단", f"{n}건 (보고서에 표시)" if n else "없음", bool(n)),
        ("보고서 작성 칸", f"{done}/6", done < 6),
        ("평가 보류", "있음 · 확정하면 확정값이 대표값" if st_["hold"] else "없음", st_["hold"]),
        ("주가 입력", ("입력됨" + (" · 예시" if ex else "")) if mk.get("close") else "없음 (블록가 제외)", not mk.get("close")),
    ]
    st.markdown(
        "<div class='wb-lines'>"
        + "".join(
            f"<div><span>{ui.esc(k)}</span><span style='color:{'#9A3412' if w else '#1E6B3A'}'>{ui.esc(v)}</span></div>"
            for k, v, w in rows
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _confirm(c: nav.Ctx) -> None:

    s = c.s
    v = M.version(s)["v"]
    n_all = M.S.pending(s)
    conf = s.get("confirmed") or {}
    job = JB.job(c.sid, "pc")
    busy = bool(job and job["alive"])
    if st.session_state.get("confirm_ask") == v and n_all:
        st.warning(f"미처리 {n_all}건 남긴 채 v{v}를 확정할까요? (남은 항목은 보고서에 '미처리'로 기록)")
        a, b = st.columns(2)
        go_ = a.button(f"미처리 {n_all}건 남긴 채 확정", key="confirm_yes", type="primary", disabled=busy, width="stretch")
        if b.button("취소", key="confirm_no", width="stretch"):
            st.session_state.pop("confirm_ask", None)
            st.rerun()
    else:
        go_ = False
        label = f"v{v} 확정됨 · 다시 확정" if conf.get("v") == v else f"v{v} 확정 → 파일 생성"
        if st.button(label, key="confirm_btn", type="primary", disabled=busy, width="stretch"):
            if n_all:
                st.session_state["confirm_ask"] = v
                st.rerun()
            go_ = True
    if go_:
        st.session_state.pop("confirm_ask", None)
        JB.start_confirm(M.load(c.sid), "pc")  # own process: the screen stays responsive (fix C2-F2)
        st.rerun()
    ps = JB.prepared_state(c.sid)
    if ps and ps.get("state") in ("building", "ready") and not busy:
        st.markdown(
            f"<p class='wb-kpi-note' title='세션을 열면 지금 상태의 엑셀을 미리 만들어 둡니다(확정 전에는 기록·내려받기 없음, 가정이 바뀌면 버리고 새로 만듦)'>"
            f"미리 만든 엑셀: v{ps.get('v')} {'준비됨' if ps['state'] == 'ready' else '만드는 중'}</p>",
            unsafe_allow_html=True,
        )


def _dl(label: str, rel: str | None, key: str, primary: bool = False) -> bool:
    data = JB.file_bytes(rel)
    if data is None:
        return False
    name = JB.safe_name(rel)
    ext = name[name.rfind(".") :]
    st.download_button(
        f"{label} ({ext})",
        data,
        file_name=name,
        mime=MIME.get(ext, "application/octet-stream"),
        key=key,
        type="primary" if primary else "secondary",
        width="stretch",
    )
    return True


def _session_file(c: nav.Ctx, key: str) -> None:
    from src.workbench import sessionfile as SF

    st.download_button(
        "세션 파일 (.json)",
        SF.dump(M.load(c.sid)),
        file_name=f"kvi_session_{c.s['code']}_{c.sid[-3:]}.json",
        mime="application/json",
        key=key,
        width="stretch",
        help="이어서 작업(가정·판단 기록·시세 입력, 서명 포함)",
    )


def _queued(j: dict) -> None:
    """Fix C4-F5: more confirmations than the server runs at once -> this one waits its turn."""
    st.markdown(
        f"<p style='font-size:14px'>{ui.badge('대기 중')} 앞에 {j['ahead']}건 — 동시에 만들 수 있는 수를 넘어 차례를 기다립니다({j['elapsed']:.0f}초)</p>",
        unsafe_allow_html=True,
    )


@st.fragment(run_every=0.5)
def _live(c: nav.Ctx) -> None:
    """Live status of the latest PC confirmation: the Excel download as soon as the model exists, then the reconciliation
    status and the report (polled from the job's output folder; afterwards from the session record)."""
    j = JB.job(c.sid, "pc")
    s = M.load(c.sid)
    if j and j.get("queued"):
        _queued(j)
        return
    last = next((x for x in reversed(s.get("confirmations") or []) if x.get("mode") == "pc"), None)
    if j and (
        j["alive"]
        or not last
        or last.get("v") != j["v"]
        or (last.get("at") or "") < time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(j["started"]))
    ):
        if not j["alive"] and j["returncode"]:
            st.error(f"확정 작업 실패(코드 {j['returncode']}). 기록: {JB.safe_name(str(j['log']))}")
            return
        v, xlsx, docx, recon = j["v"], j["xlsx"], j["docx"], j["reconcile"]
        head = f"확정 v{v} · 시작 {j['elapsed']:.0f}초 전"
        secs, per = j["excel_seconds"], None
    elif last:
        outs = last.get("outputs") or {}
        v, xlsx, docx = last.get("v"), outs.get("xlsx") or last.get("excel"), outs.get("docx")
        recon = (last.get("reconcile") or {}).get("status", "")
        head = f"확정 v{v} · {str(last.get('at', '')).replace('T', ' ')}"
        secs, per = last.get("excel_seconds"), last.get("per_share")
    else:
        st.markdown("<p class='wb-kpi-note'>확정하면 버전이 고정되고 파일이 만들어집니다</p>", unsafe_allow_html=True)
        return
    cls = "ok" if recon == "일치" else ("warn" if recon == "불일치" or "실패" in str(recon) else "")
    st.markdown(
        f"<div class='wb-subrow'><b>{ui.esc(head)}</b> · 엑셀 {'준비됨' if xlsx else '만드는 중'}{f' ({secs:.1f}초)' if secs else ''} · "
        f"<span title='엑셀 수식으로 다시 계산한 값과 엔진 값 비교(백그라운드, 약 1분)'>엑셀 ↔ 엔진 대조</span> {ui.badge(recon or '대조 대기', cls)} · "
        f"보고서 {'준비됨' if docx else ('만드는 중' if j and j['alive'] else '없음')}"
        + (f" · 확정 주당 {F.won0(per)}원" if per else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    a, b = st.columns(2)
    d, e = st.columns(2)
    with a:
        if xlsx:
            _dl("엑셀 모델", xlsx, f"dl_x_{v}_{bool(docx)}", primary=True)
    with b:
        if docx:
            _dl("보고서 초안", docx, f"dl_d_{v}")
    with d:
        pdf = docx[:-5] + ".pdf" if docx else None
        if pdf and JB.file_bytes(pdf) is not None:
            _dl("PDF", pdf, f"dl_p_{v}")
    with e:
        _session_file(c, f"dl_s_{v}")


def _public(c: nav.Ctx) -> None:
    from app.wb import shell

    s = c.s
    miss = M.public_missing(c.o, s)
    job = JB.job(c.sid, "public")
    busy = bool(job and job["alive"])
    if miss:
        st.markdown(
            f"<p class='wb-kpi-note wb-warn'>먼저 입력: {ui.esc(', '.join(miss))} (KPI 주가 칸 · DCF Bridge)</p>",
            unsafe_allow_html=True,
        )
        if not c.public:
            shell.public_form(c, "export", target_only=True)
    v = M.version(s)["v"]
    n = M.S.pending(s)
    go_ = False
    if c.public and st.session_state.get("confirm_ask") == v and n:  # P7-C3: the public export is the confirmation
        st.warning(f"미처리 {n}건 남긴 채 v{v}를 확정할까요? (남은 항목은 보고서에 '미처리'로 기록)")
        a, b = st.columns(2)
        go_ = a.button(
            f"미처리 {n}건 남긴 채 확정", key="confirm_yes", type="primary", disabled=busy or bool(miss), width="stretch"
        )
        if b.button("취소", key="confirm_no", width="stretch"):
            st.session_state.pop("confirm_ask", None)
            st.rerun()
    else:
        label = f"v{v} 확정 → 파일 생성" if c.public else f"v{v} 공개 모드로 내보내기"
        if st.button(label, key="pub_go", type="primary", disabled=bool(miss) or busy, width="stretch"):
            if c.public and n:
                st.session_state["confirm_ask"] = v
                st.rerun()
            go_ = True
    if go_:
        st.session_state.pop("confirm_ask", None)
        JB.start_confirm(M.load(c.sid), "public", user=s.get("public_inputs"))
        st.rerun()
    _public_live(c)


@st.fragment(run_every=0.5)
def _public_live(c: nav.Ctx) -> None:
    j = JB.job(c.sid, "public")
    s = M.load(c.sid)
    if j and j.get("queued"):
        _queued(j)
        return
    if j and j["alive"]:
        if c.public:  # P7-C3: the Excel model can be taken as soon as it exists
            st.markdown(
                f"<p style='font-size:14px'>{ui.badge('만드는 중')} 공개 모드 엑셀·대조·보고서({j['elapsed']:.0f}초) · 엑셀 {'준비됨' if j['xlsx'] else '만드는 중'} · "
                f"엑셀 ↔ 엔진 대조 {ui.esc(j['reconcile'])} · 보고서 {'준비됨' if j['docx'] else '만드는 중'}</p>",
                unsafe_allow_html=True,
            )
            if j["xlsx"]:
                _dl("엑셀 모델", j["xlsx"], f"dlp_x_live_{j['v']}", primary=True)
            return
        stage = "엑셀·보고서 만드는 중" if j["reconcile"] != "일치" else "한국거래소 원값 스캔 중"
        st.markdown(
            f"<p style='font-size:14px'>{ui.badge(stage)} 공개 모드 산출물을 만들고 한국거래소 원값을 대조하는 중({j['elapsed']:.0f}초)</p>",
            unsafe_allow_html=True,
        )
        return
    if j and j["returncode"]:
        st.error(f"공개 모드 내보내기 실패(코드 {j['returncode']}). 기록: {JB.safe_name(str(j['log']))}")
    rec = next((x for x in reversed(s.get("confirmations") or []) if x.get("mode") == "public"), None)
    if not rec:
        return
    sc = rec.get("scan")
    outs = rec.get("outputs") or {}
    if sc is None:
        st.markdown(
            "<p class='wb-kpi-note'>스캔 기록 없음 — 다시 내보내면 스캔합니다(내려받기 비활성).</p>", unsafe_allow_html=True
        )
        return
    ok = sc["hits"] == 0
    recon = (rec.get("reconcile") or {}).get("status", "")
    if sc.get("deploy"):
        st.markdown(
            f"<p style='font-size:14px'>v{rec.get('v')} 공개 산출물 · 엑셀 ↔ 엔진 대조 {ui.badge(recon, 'ok' if recon == '일치' else '')} · {ui.esc(sc.get('note', ''))}</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<p style='font-size:14px'>v{rec.get('v')} 공개 산출물 스캔: {ui.badge(f'검출 {sc["hits"]}건', 'ok' if ok else 'warn')} "
            f"(대조한 한국거래소 원값 {sc.get('krx_values')}개) · 대조 {ui.esc(recon)}</p>",
            unsafe_allow_html=True,
        )
    if ok:
        a, b, d = st.columns(3)
        with a:
            _dl("엑셀 모델", outs.get("xlsx"), f"dlp_x_{rec.get('v')}", primary=True)
        with b:
            _dl("보고서 초안", outs.get("docx"), f"dlp_d_{rec.get('v')}")
        with d:
            _session_file(c, f"dlp_s_{rec.get('v')}")
    else:
        ui.tbl(
            ["파일", "위치", "항목"],
            [[h.get("file", ""), h.get("where", ""), h.get("what", "")] for h in sc.get("detail") or []],
            left=(0, 1, 2),
            tips=False,
        )
        st.error("한국거래소 원값이 남아 있어 내려받기를 막았습니다.")


def _outputs(c: nav.Ctx) -> None:
    s = M.load(c.sid)
    rows = []
    for x in reversed(JB.confirmations(s)):
        o = x.get("outputs") or {}
        for k in ("xlsx", "docx"):
            if o.get(k):
                scan = x.get("scan")
                rows.append(
                    [
                        JB.safe_name(o[k]),
                        f"v{x.get('v')}",
                        (x.get("at") or "").replace("T", " ")[:16],
                        "PC" if x.get("mode") == "pc" else "공개",
                        (x.get("reconcile") or {}).get("status", ""),
                        "" if scan is None else f"검출 {scan['hits']}건",
                    ]
                )
    note = (
        "이 브라우저 작업 공간의 파일 · 6시간 뒤 또는 새로 고치면 삭제 — 내려받아 두세요"
        if c.public
        else "outputs/workbench (git 제외)"
    )
    ui.h2("산출물", "", ui.esc(note))
    if rows:
        ui.tbl(
            ["파일", "버전", "생성 시각", "모드", "대조", "공개 스캔"], rows, left=(0, 1, 2, 3, 4, 5), tips=False, min_width=600
        )
    else:
        st.markdown("<p class='wb-kpi-note'>아직 산출물이 없습니다.</p>", unsafe_allow_html=True)
