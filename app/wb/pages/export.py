"""5 내보내기: confirm the current version (a second confirmation when judgements are still pending) -> the Excel model as
soon as it is written; the Excel <-> engine reconciliation and the report run in the background and the status refreshes
by itself. Public mode: the user's market inputs -> public export -> KRX scan of the outputs (download only with 0 hits).
Outputs table and the disclaimer."""

from __future__ import annotations

import time

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import jobs as JB
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx

MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}


def render(c: nav.Ctx) -> None:
    nav.header(c, "내보내기")
    with ui.card(
        "engagement",
        "평가 목적·전제·평가자",
        "보고서 '1. 평가 개요'와 엑셀 표지에 들어갑니다. 비워 두면 기본 문구(방법론 예시, 계속기업)를 씁니다",
    ):
        _engagement(c)
    if c.mode == "pc":
        with ui.card(
            "confirm",
            "확정하고 엑셀·보고서 만들기",
            "확정 버전의 가정이 엑셀 Inputs '사람 확정값' 칸과 Judgements 시트, 보고서 '사람 판단 반영 내역'에 들어갑니다",
        ):
            _confirm(c)
        with ui.card("live", None, plain=True):
            _live(c)
    else:
        if c.public:
            from app.wb import public_ui

            public_ui.banner()
        nav.public_inputs(c, "export")
        sub = (
            "피어·베타·D/E 시점 행 대신 집계값을 입력 칸으로 두고 나머지는 살아 있는 수식(공개 스냅샷으로 계산)"
            if c.public
            else "피어·베타·D/E 시점 행 대신 집계값을 입력 칸으로 두고 나머지는 살아 있는 수식. 산출물의 모든 숫자를 한국거래소 원값과 대조"
        )
        with ui.card("public", "공개 모드로 내보내기", sub):
            _public(c)
    with ui.card(
        "outputs",
        "산출물",
        "이 브라우저 작업 공간의 파일(6시간 뒤 또는 새로 고치면 삭제 — 내려받아 두세요)"
        if c.public
        else "이 세션에서 만든 파일(outputs/workbench, git 제외)",
    ):
        _outputs(c)
    ui.footer(c.mode, M.AS_OF)


def _engagement(c: nav.Ctx) -> None:
    """P7-X2b: the three engagement fields of the session (saved with an audit entry; no new version)."""
    e = c.s.get("engagement") or {}
    a, b, d = st.columns(3)
    purpose = a.text_input("평가 목적", value=e.get("purpose", ""), key="eng_purpose", placeholder="방법론 예시(기본)")
    premise = b.text_input("평가 전제", value=e.get("premise", ""), key="eng_premise", placeholder="계속기업(기본)")
    who = d.text_input("평가자", value=e.get("evaluator", ""), key="eng_evaluator", placeholder="(비워 두면 표시 안 함)")
    if st.button("저장", key="eng_save"):
        r = M.S.set_engagement(M.load(c.sid), {"purpose": purpose, "premise": premise, "evaluator": who})
        if not r.get("noop"):
            st.rerun()


def _confirm(c: nav.Ctx) -> None:
    s = c.s
    v = M.version(s)["v"]
    n = M.S.pending(s)
    conf = s.get("confirmed") or {}
    job = JB.job(c.sid, "pc")
    if conf.get("v") == v:
        st.markdown(
            f"<p style='font-size:14px'>{ui.badge('확정', 'ok')} v{v}는 이미 확정했습니다({ui.esc(conf.get('at', ''))}). "
            "가정을 바꾸면 새 버전이 생기고 다시 확정할 수 있습니다.</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        f"<p style='font-size:14px'>확정할 버전: <b>v{v}</b> · 미처리 판단 {ui.badge(f'{n}건', 'warn' if n else 'ok')}</p>",
        unsafe_allow_html=True,
    )
    busy = bool(job and job["alive"])
    ps = JB.prepared_state(c.sid)
    if ps and ps.get("state") in ("building", "ready") and not busy:
        st.markdown(
            f"<p class='wb-kpi-note'>미리 만든 엑셀: v{ps.get('v')} {'준비됨' if ps['state'] == 'ready' else '만드는 중'}</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<p class='wb-kpi-note'>세션을 열면 지금 상태의 엑셀을 미리 만들어 둡니다. 확정을 누르기 전에는 세션에 기록하지 않고 내려받을 수도 "
        "없으며, 그 사이 가정·판단이 바뀌면 미리 만든 것은 버리고 새로 만듭니다.</p>",
        unsafe_allow_html=True,
    )
    if st.session_state.get("confirm_ask") == v and n:
        st.warning(f"미처리 판단이 {n}건 남아 있습니다. 그래도 v{v}를 확정할까요? (남은 항목은 보고서에 '미처리'로 기록됩니다)")
        a, b = st.columns(2)
        go_ = a.button(f"예, 미처리 {n}건을 남긴 채 확정", key="confirm_yes", type="primary", disabled=busy)
        if b.button("취소", key="confirm_no"):
            st.session_state.pop("confirm_ask", None)
            st.rerun()
    else:
        go_ = False
        if st.button(f"v{v} 확정하고 엑셀 만들기", key="confirm_btn", type="primary", disabled=busy):
            if n:
                st.session_state["confirm_ask"] = v
                st.rerun()
            go_ = True
    if go_:
        st.session_state.pop("confirm_ask", None)
        JB.start_confirm(M.load(c.sid), "pc")  # own process: the screen stays responsive (fix C2-F2)
        st.rerun()


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
    )
    return True


@st.fragment(run_every=0.5)
def _live(c: nav.Ctx) -> None:
    """Live status of the latest PC confirmation: the Excel download as soon as the model exists, then the
    reconciliation status and the report (polled from the job's output folder; afterwards from the session record)."""
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
        secs = j["excel_seconds"]
        per = None
    elif last:
        outs = last.get("outputs") or {}
        v, xlsx, docx = last.get("v"), outs.get("xlsx") or last.get("excel"), outs.get("docx")
        recon = (last.get("reconcile") or {}).get("status", "")
        head = f"확정 v{v} · {ui.esc(str(last.get('at', '')).replace('T', ' '))}"
        secs, per = last.get("excel_seconds"), last.get("per_share")
    else:
        st.markdown("<p class='wb-kpi-note'>아직 확정하지 않았습니다.</p>", unsafe_allow_html=True)
        return
    cls = "ok" if recon == "일치" else ("warn" if recon == "불일치" or "실패" in str(recon) else "")
    st.markdown(
        f"<div class='wb-card'><span class='wb-kpi-label'>{head}</span>"
        f"<span style='font-size:14px'>엑셀 {'준비됨' if xlsx else '만드는 중'}{f' ({secs:.1f}초)' if secs else ''} · "
        f"{tx.term('대조')} {ui.badge(recon or '대조 대기', cls)} · 보고서 {'준비됨' if docx else ('만드는 중' if j and j['alive'] else '없음')}</span>"
        + (f"<span class='wb-kpi-note'>확정 주당 {F.won(per)}</span>" if per else "")
        + "<span class='wb-kpi-note'>대조 = 엑셀 수식으로 다시 계산한 값과 계산 엔진 값 비교(백그라운드, 약 1분)</span></div>",
        unsafe_allow_html=True,
    )
    a, b, d = st.columns(3)
    with a:
        if xlsx:
            _dl("엑셀 모델 내려받기", xlsx, f"dl_x_{v}_{bool(docx)}", primary=True)
    with b:
        if docx:
            _dl("보고서 초안 내려받기", docx, f"dl_d_{v}")
    with d:
        pdf = docx[:-5] + ".pdf" if docx else None
        if pdf and JB.file_bytes(pdf) is not None:
            _dl("PDF", pdf, f"dl_p_{v}")


def _public(c: nav.Ctx) -> None:
    s = c.s
    miss = M.public_missing(c.o, s)
    job = JB.job(c.sid, "public")
    busy = bool(job and job["alive"])
    if miss:
        st.markdown(
            f"<p class='wb-kpi-note wb-warn'>먼저 위에서 입력하세요: {ui.esc(', '.join(miss))}</p>", unsafe_allow_html=True
        )
    v = M.version(s)["v"]
    n = M.S.pending(s)
    go_ = False
    if c.public and st.session_state.get("confirm_ask") == v and n:  # P7-C3: the public export is the confirmation
        st.warning(f"미처리 판단이 {n}건 남아 있습니다. 그래도 v{v}를 확정할까요? (남은 항목은 보고서에 '미처리'로 기록됩니다)")
        a, b = st.columns(2)
        go_ = a.button(f"예, 미처리 {n}건을 남긴 채 확정", key="confirm_yes", type="primary", disabled=busy or bool(miss))
        if b.button("취소", key="confirm_no"):
            st.session_state.pop("confirm_ask", None)
            st.rerun()
    else:
        label = f"v{v} 확정하고 엑셀 만들기" if c.public else f"v{v} 공개 모드로 내보내기"
        if st.button(label, key="pub_go", type="primary", disabled=bool(miss) or busy):
            if c.public and n:
                st.session_state["confirm_ask"] = v
                st.rerun()
            go_ = True
    if go_:
        st.session_state.pop("confirm_ask", None)
        JB.start_confirm(M.load(c.sid), "public", user=s.get("public_inputs"))
        st.rerun()
    _public_live(c)


def _queued(j: dict) -> None:
    """Fix C4-F5: more confirmations than the server runs at once -> this one waits its turn."""
    st.markdown(
        f"<p style='font-size:14px'>{ui.badge('대기 중')} 앞에 {j['ahead']}건 — 동시에 만들 수 있는 수를 넘어 차례를 "
        f"기다립니다({j['elapsed']:.0f}초). 순서가 오면 자동으로 시작합니다.</p>",
        unsafe_allow_html=True,
    )


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
                f"<p style='font-size:14px'>{ui.badge('만드는 중')} 공개 모드 엑셀·대조·보고서({j['elapsed']:.0f}초) · "
                f"엑셀 {'준비됨' if j['xlsx'] else '만드는 중'} · {tx.term('대조')} {ui.esc(j['reconcile'])} · "
                f"보고서 {'준비됨' if j['docx'] else '만드는 중'}</p>",
                unsafe_allow_html=True,
            )
            if j["xlsx"]:
                _dl("공개 엑셀 내려받기", j["xlsx"], f"dlp_x_live_{j['v']}", primary=True)
            return
        stage = "엑셀·보고서 만드는 중" if j["reconcile"] != "일치" else "한국거래소 원값 스캔 중"
        st.markdown(
            f"<p style='font-size:14px'>{ui.badge(stage)} 공개 모드 산출물을 만들고 한국거래소 원값을 대조하는 중"
            f"({j['elapsed']:.0f}초) — 스캔이 끝나야 내려받을 수 있습니다</p>",
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
    if sc.get("deploy"):
        st.markdown(
            f"<p style='font-size:14px'>v{rec.get('v')} 공개 산출물 · {tx.term('대조')} "
            f"{ui.badge((rec.get('reconcile') or {}).get('status', ''), 'ok' if (rec.get('reconcile') or {}).get('status') == '일치' else '')}"
            f" · {ui.esc(sc.get('note', ''))}</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<p style='font-size:14px'>v{rec.get('v')} 공개 산출물 스캔: {ui.badge(f'검출 {sc["hits"]}건', 'ok' if ok else 'warn')} "
            f"(대조한 한국거래소 원값 {sc.get('krx_values')}개, {ui.esc(str(sc.get('at', '')).replace('T', ' '))}) · 대조 "
            f"{ui.esc((rec.get('reconcile') or {}).get('status', ''))}</p>",
            unsafe_allow_html=True,
        )
    if ok:
        a, b = st.columns(2)
        with a:
            _dl("공개 엑셀 내려받기", outs.get("xlsx"), f"dlp_x_{rec.get('v')}", primary=True)
        with b:
            _dl("공개 보고서 내려받기", outs.get("docx"), f"dlp_d_{rec.get('v')}")
    else:
        ui.table(
            ["파일", "위치", "항목"], [[h.get("file", ""), h.get("where", ""), h.get("what", "")] for h in sc.get("detail") or []]
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
                        (x.get("at") or "").replace("T", " "),
                        "PC" if x.get("mode") == "pc" else "공개",
                        (x.get("reconcile") or {}).get("status", ""),
                        "" if scan is None else f"검출 {scan['hits']}건",
                    ]
                )
    if rows:
        ui.table(["파일", "버전", "생성 시각", "모드", "대조", "공개 스캔"], rows, min_width=600)
    else:
        st.markdown("<p class='wb-kpi-note'>아직 산출물이 없습니다.</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='wb-kpi-note'>{ui.esc(tx.DISCLAIMER)}</p>", unsafe_allow_html=True)
