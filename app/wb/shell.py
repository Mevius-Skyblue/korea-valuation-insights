"""The frame of the P7-U1 work screen (config/p7u.yaml screen): top row (search, version, 이력, ⋯, 확정 · 내보내기), sub row
(valuation date, example badge, DART link, unit toggle, mode badge, snapshot warning), the KPI band, the change notice
(st.toast), the work tabs and the first screen without a company.

The search box holds recent sessions and favourites in its dropdown; the company facts are its tooltip. Picking a
company shows one line 'can it be valued automatically' and [평가 시작]; picking a recent session opens it.
"""

from __future__ import annotations

import json
import time

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx

STAGE = {
    "draft": "자동 초안(수집·Peer·적재 전체)",
    "draft.gate_a": "자동 평가 가능 여부(업종·적자·매출·구조) 확인",
    "draft.collect_target": "대상 회사 공시 수집",
    "draft.select_peers": "Peer 고르기",
    "draft.collect_peers": "Peer 공시 수집",
    "draft.load_db": "DB 적재(재무·D&A)",
    "draft.config": "설정 초안 쓰기",
    "gate_b": "재무 자료·Peer 3곳 확인",
    "valuation": "Peer 표",
    "session_tables": "세션 표",
    "engine": "평가 계산(DCF·상대가치·프리미엄)",
    "first_draft": "신호·판단 목록",
}


# ---------------------------------------------------------------- favourites (per workspace)


def _fav_path():
    return M.S.base().parent / "favorites.json"


def favorites() -> list[str]:
    try:
        return list(json.loads(_fav_path().read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []


def toggle_favorite(code: str) -> None:
    f = favorites()
    f = [x for x in f if x != code] if code in f else [code, *f]
    p = _fav_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(f[:20]), encoding="utf-8")


# ---------------------------------------------------------------- search box


def _options(c: nav.Ctx) -> tuple[list[str], dict]:
    uni = M.universe()
    byc = {u["code"]: u for u in uni}
    lab, opts = {}, []
    sess = M.sessions()
    if c.sid and all(r["sid"] != c.sid for r in sess) and c.s:
        sess = [{"sid": c.sid, "code": c.s["code"], "name": c.s["name"]}, *sess]
    for code in favorites():
        if code in byc:
            k = f"f:{code}"
            opts.append(k)
            lab[k] = f"★ {byc[code]['name']} · {code} · {byc[code]['market']}"
    for r in sess[:6]:
        k = f"s:{r['sid']}"
        opts.append(k)
        mk = byc.get(r["code"], {}).get("market", "")
        lab[k] = f"최근 · {r['name']} · {r['code']} {mk} #{r['sid'][-3:]}"
    if c.sid and f"s:{c.sid}" not in opts:
        k = f"s:{c.sid}"
        opts.append(k)
        lab[k] = f"최근 · {c.s['name']} · {c.s['code']} #{c.sid[-3:]}"
    for u in uni:
        k = f"c:{u['code']}"
        opts.append(k)
        lab[k] = f"{u['name']} · {u['code']} · {u['market']}"
    return opts, lab


def _meta_tip(c: nav.Ctx) -> str:
    if not c.o:
        return (
            "회사명 또는 종목코드 · 공개 배포는 개발·검증에 쓴 회사만"
            if c.public
            else "회사명 또는 종목코드(KOSPI·KOSDAQ 보통주)"
        )
    cfg = c.o.cfg
    sh = c.o.ctx.c.market["shares_out"]
    return (
        f"재무 {cfg['meta']['bs_date']} · {'연결' if cfg['meta']['fs_div'] == 'CFS' else '별도'} · "
        f"KSIC {cfg['target'].get('induty_code', '')} · 유통주식 {sh / 1e4:,.0f}만주"
    )


def _on_search() -> None:
    v = st.session_state.get("search")
    if not v:
        return
    kind, val = v.split(":", 1)
    if kind == "s":
        st.session_state.pop("picked_code", None)
        nav.go("summary", sid=val)
    else:
        st.session_state["picked_code"] = val


def search(c: nav.Ctx) -> None:
    opts, lab = _options(c)
    cur = f"s:{c.sid}" if c.sid else None
    if st.session_state.get("picked_code"):
        k = f"c:{st.session_state['picked_code']}"
        cur = k if k in opts else cur
    if True:
        st.selectbox(
            "회사 검색",
            opts,
            index=opts.index(cur) if cur in opts else None,
            format_func=lambda x: lab.get(x, x),
            key="search",
            on_change=_on_search,
            placeholder="회사명 또는 종목코드",
            label_visibility="collapsed",
            help=_meta_tip(c),
        )


# ---------------------------------------------------------------- gate line and start


GATE_LABEL = {
    "G1": "금융업 아님",
    "G1b": "금융회사형 재무구조 아님",
    "G2": "최근 3년 중 흑자 연도",
    "G3": "3년 영업이익 합계 > 0",
    "G4": "FY2025 매출 100억원 이상",
    "G5": "12월 결산",
    "G6": "지원하는 지배구조",
    "G7": "필수 재무 자료",
    "G8": "Peer 3곳 이상",
}
FAIL_LABEL = {
    "G1": "금융업",
    "G1b": "금융회사형 재무구조",
    "G2": "최근 3년 모두 적자(매출 기준 미달)",
    "G3": "3년 영업이익 합계 0 이하",
    "G4": "매출 100억원 미만",
    "G5": "12월 결산 아님",
    "G6": "지원하지 않는 지배구조",
    "G7": "필수 재무 자료 없음",
    "G8": "Peer 3곳 미만",
}
EXCLUDE_TIP = (
    "자동 평가에서 제외: 금융업·금융회사형 재무구조 / 최근 3년 영업이익 모두 적자이고 매출도 작음 / 매출 100억원 미만 / "
    "12월 결산 아님 / 지원하지 않는 지배구조 / 필수 재무 자료 없음 / Peer 3곳 미만 — 제외되면 숫자 없이 사유만"
)


def gate_line(code: str, name: str) -> dict:
    """One line: 통과 / 보류 / 제외 + path or reasons; the full table in the tooltip (labels only)."""
    ds = M.draft_state(code)
    gv = M.gate_view(ds["summary"])
    if not ds["summary"]:
        txt = f"{ui.badge('초안 없음')} 평가 시작 → 공시 수집 후 초안(보통 30~60초)"
        st.markdown(
            f"<div class='wb-subrow' title='{ui.attr(EXCLUDE_TIP)}'>자동 평가 가능 여부 {txt}</div>", unsafe_allow_html=True
        )
        return {"ok": True, "has_draft": False}
    rows = "\n".join(
        f"{GATE_LABEL.get(r['id'], r['label'])}: {r['status']} {tx.plain_words(r['value'])}".strip() for r in gv["rows"]
    )
    hl = (ds["summary"].get("headline") or {}).get("status")
    if not gv["passed"]:
        why = " · ".join(FAIL_LABEL.get(f["id"], f["label"]) for f in gv["fails"]) or "범위 밖"
        b = ui.badge("제외", "warn") + f" · {ui.esc(why)} — 숫자 없이 사유만"
    elif hl == "자동 결과 보류":
        b = ui.badge("보류", "yellow") + f" · {ui.esc(tx.plain_words(gv['path']))} · 확인 항목이 있어 대표값 보류"
    else:
        b = ui.badge("통과", "ok") + f" · {ui.esc(tx.plain_words(gv['path']))}"
    st.markdown(
        f"<div class='wb-subrow' title='{ui.attr(rows + chr(10) + chr(10) + EXCLUDE_TIP)}'>자동 평가 가능 여부 · {b}"
        f" <span class='wb-help'>ⓘ</span></div>",
        unsafe_allow_html=True,
    )
    if not gv["passed"]:
        for f in gv["fails"]:
            st.markdown(
                f"<p class='wb-kpi-note'>{ui.esc(FAIL_LABEL.get(f['id'], f['label']))}: {ui.esc(f['why'])}</p>",
                unsafe_allow_html=True,
            )
    return {"ok": bool(gv["passed"]), "has_draft": True}


def start_block(c: nav.Ctx, code: str) -> None:
    """Gate line + [평가 시작] (+ open buttons of this company's saved sessions)."""
    u = next((x for x in M.universe() if x["code"] == code), {"name": code})
    g = gate_line(code, u["name"])
    can = g["ok"] or (not g["has_draft"] and not c.public)
    same = [r for r in M.sessions() if r["code"] == code][:3]
    cols = st.columns([1.4] + [1] * len(same) + [max(5 - len(same), 1)])
    if cols[0].button("평가 시작", key="start", type="primary", disabled=not can, help="자동 초안으로 새 평가 세션"):
        _start(code, c.mode)
    for i, r in enumerate(same, start=1):
        cols[i].button(
            f"열기 #{r['sid'][-3:]} · v{r['version']}",
            key=f"openc_{r['sid']}",
            on_click=nav.go,
            args=("summary", r["sid"], c.mode),
        )


def _start(code: str, mode: str) -> None:
    """New session (first draft with progress if needed) -> summary tab."""
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
        ph.markdown(
            "".join(
                f"<div class='wb-step'><span>{ui.esc(a)}</span><span>{ui.esc(b)} {ui.esc(c_)}</span></div>" for a, b, c_ in lines
            )
            + f"<p class='wb-kpi-note'>경과 {time.time() - t0:.0f}초</p>",
            unsafe_allow_html=True,
        )

    try:
        with M.LOCK:
            s = M.S.create(code, on_step=on_step)
    except ValueError as e:
        box.update(label="자동 평가 범위 밖", state="error")
        st.error(f"초안을 만들 수 없습니다: {tx.plain_words(str(e))}")
        return
    except Exception as e:  # noqa: BLE001 - shown, the page stays
        ui._log("create", e)
        box.update(label="실패", state="error")
        st.error(f"실패: {type(e).__name__}: {e}")
        st.button("다시 시도", key="retry_create")
        return
    box.update(label=f"세션 준비 완료({time.time() - t0:.0f}초)", state="complete")
    st.session_state.pop("picked_code", None)
    nav.go("summary", sid=s["session_id"], mode=mode)
    st.rerun()


# ---------------------------------------------------------------- top row, sub row


def dirty(s: dict) -> int:
    """P7-U2 save guard: changes after the last confirmation (= versions since it; every change is a saved version)."""
    v = M.version(s)["v"]
    conf = (s.get("confirmed") or {}).get("v")
    return max(v - int(conf), 0) if conf is not None else v


def version_text(c: nav.Ctx) -> tuple[str, str]:
    s = c.s
    v = M.version(s)["v"]
    cf = s.get("confirmed") or {}
    conf = cf.get("v")
    st_ = M.status(c.o, s)
    n = dirty(s)
    if conf == v:  # P7-U3 U3-2d: the confirmed version with its time (Korean time)
        return f"v{v} · 확정 {F.kst(cf.get('at'), clock=True)}".rstrip(), ""
    if st_["hold"]:
        return f"v{v} · 보류" + (f" · 확정 전 변경 {n}건" if n else ""), "warn"
    return (f"v{v} · 확정 전 변경 {n}건" if n else "v0 · 자동 초안"), ""


def menu(c: nav.Ctx) -> None:
    """⋯ : reference pages, the simple DCF calculator, sessions, favourites."""
    with st.popover("더보기", icon=":material/more_horiz:", help="참고 자료 · 간이 DCF 계산기 · 세션 저장·불러오기 · 즐겨찾기"):
        st.markdown(f"<p class='wb-kpi-note'>프로젝트 · {tx.project_links()}</p>", unsafe_allow_html=True)  # P7-U3 U3-4a
        st.markdown("<p class='wb-kpi-note'>참고</p>", unsafe_allow_html=True)
        for pid, label in nav.REFS:
            st.button(label, key=f"menu_{pid}", on_click=nav.go, args=(pid,), width="stretch")
        st.markdown("<p class='wb-kpi-note'>도구</p>", unsafe_allow_html=True)
        if c.s:  # P7-U2: history also here (the only place on a phone), the Summary PDF
            st.button("이력", key="menu_history", on_click=nav.go, args=("history",), width="stretch")
            from app.wb import summary_pdf

            summary_pdf.button(c, "menu")
        st.button("간이 DCF 계산기", key="menu_calc", on_click=nav.go, args=("calc",), width="stretch")
        st.button("모든 세션 · 세션 저장·불러오기", key="menu_sessions", on_click=nav.go, args=("sessions",), width="stretch")
        if c.s:
            code = c.s["code"]
            on = code in favorites()
            st.button(
                "즐겨찾기 해제" if on else "즐겨찾기 추가",
                key="menu_fav",
                on_click=toggle_favorite,
                args=(code,),
                width="stretch",
            )
        from app.wb import client

        st.markdown(f"<p class='wb-kpi-note'>단축키 (?): {ui.esc(client.keys_text())}</p>", unsafe_allow_html=True)


def top(c: nav.Ctx) -> None:
    with st.container(key="topbar"):
        if c.s and c.o:
            a, b, v_, h, m, e = st.columns([2.0, 5.2, 1.7, 0.75, 0.55, 1.55], vertical_alignment="top")
        else:
            a, b, m = st.columns([2.0, 7.4, 0.55], vertical_alignment="top")
        a.markdown("<div class='wb-brand'><b>KVI</b><span>밸류에이션 워크벤치</span></div>", unsafe_allow_html=True)
        with b:
            search(c)
        if c.s and c.o:
            txt, cls = version_text(c)
            note = (  # P7-U3 U3-3a: short (the column is narrow), the whole sentence in the tooltip
                "<div class='wb-ver-note' title='이 브라우저의 작업 공간은 6시간 뒤 지워집니다 — 확정 · 내보내기에서 세션 파일을 "
                "내려받아 두면 이어서 작업할 수 있습니다'>6시간 뒤 삭제 ⓘ</div>"
                if c.mode == "public" and dirty(c.s)
                else ""
            )
            v_.markdown(
                f"<div class='wb-ver {cls}' data-testid='wb-version' title='{ui.attr(txt)}'><span class='n'>{ui.esc(txt)}</span>"
                f"<span class='calc'>계산 중…</span></div>{note}",
                unsafe_allow_html=True,
            )
            h.button("이력", key="top_history", on_click=nav.go, args=("history",), width="stretch")
            with m:
                menu(c)
            e.button(
                "확정 · 내보내기",
                key="top_export",
                type="primary",
                icon=":material/ios_share:",
                on_click=nav.go,
                args=("export",),
                width="stretch",
            )
        else:
            with m:
                menu(c)
        if c.s and c.o:
            sub(c)
        if st.session_state.get("picked_code") and (not c.s or st.session_state["picked_code"] != c.s["code"]):
            start_block(c, st.session_state["picked_code"])


def sub(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    cfg = o.cfg
    rc = list(
        dict.fromkeys(
            M.rcepts(str((cfg.get("shares") or {}).get("source", "")))
            + M.rcepts(str((o.summ.get("facts") or {}).get("structure_source", "")))
        )
    )
    href = tx.DART_VIEW + rc[0] if rc else "https://dart.fss.or.kr/"
    rtip = " · ".join(("반기보고서 " if r[:8] > cfg["meta"]["bs_date"].replace("-", "") else "사업보고서 ") + r for r in rc[:2])
    ex = c.mode == "public" and (s.get("public_inputs") or {}).get("example")
    left, mid, right = st.columns([6.6, 1.7, 1.7], vertical_alignment="center")
    left.markdown(
        "<div class='wb-subrow'><b>평가기준일</b> "
        f"<span title='자동 초안은 이 기준일만 지원(다른 기준일은 시세·재무 기준 시점 규칙을 새로 고정한 뒤)'>{ui.esc(cfg['meta']['as_of'])}</span>"
        + (f" {ui.badge(M.example_prices()['short_label'], 'yellow')}" if ex else "")
        + f" <a href='{href}' target='_blank' rel='noopener' title='{ui.attr(rtip)}'>DART 공시 ↗</a>"
        + (f" {ui.badge(tx.MODE_LABEL['deploy'][0], 'dark')}" if c.public else "")  # P7-U2F D6: on this line, not under ⋯
        + "</div>",
        unsafe_allow_html=True,
    )
    with mid, st.container(key="units"):
        st.segmented_control(
            "단위",
            [False, True],
            default=bool(st.session_state.get("unit_mn", False)),
            format_func=lambda x: "백만원" if x else "억원",
            key="unit_seg",
            on_change=lambda: st.session_state.__setitem__("unit_mn", bool(st.session_state.get("unit_seg"))),
            label_visibility="collapsed",
            required=True,
        )
    with right, st.container(key="modeseg"):
        if not c.public:  # the public deployment's mode badge is on the left of this line (P7-U2F D6)

            def _mode():
                v = st.session_state.get("mode_seg")
                if v and v != c.mode:
                    nav.go(c.page, mode=v)

            st.segmented_control(
                "모드",
                ["pc", "public"],
                default=c.mode,
                format_func=lambda x: "PC" if x == "pc" else "공개",
                key="mode_seg",
                on_change=_mode,
                label_visibility="collapsed",
                required=True,
                help="공개 모드: 주가·VWAP 직접 입력, Peer별 시세 값 숨김",
            )
    w = o.snapshot_warnings()
    if w:
        st.markdown(
            f"<div class='wb-band-top' role='alert'>자료가 바뀌었습니다 — 다시 확인 후 확정 ({ui.esc('; '.join(w))})</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------- KPI band


def _pc(v) -> str:
    """A rate on a sub line: whole % when it is whole ('8%'), else 2 decimals ('3.35%')."""
    if not F.ok(v):
        return "—"
    x = float(v) * 100
    return f"{x:.0f}%" if abs(x - round(x)) < 1e-9 else f"{x:.2f}%"


def _b2(v) -> str:
    return f"{float(v):.2f}" if F.ok(v) else "—"


def _kc(label: str, value: str, sub: str, tip: str, cls: str = "") -> str:
    return (
        f"<div class='wb-kpi' title='{ui.attr(tip)}'><div class='k'>{ui.esc(label)}</div>"
        f"<div class='v {cls}'>{ui.esc(value)}</div><div class='s'>{ui.esc(sub)}</div></div>"
    )


def kpi_band(c: nav.Ctx) -> None:
    from app.wb import values as V

    o, s, mn = c.o, c.s, c.mn
    st_ = M.status(o, s)
    hold = st_["hold"] and st_["label"] != "확정"
    scen = scenario()
    lab_sc = SCEN_LABEL[scen]
    try:
        k = V.kpi(o, s, c.mode, scen)
    except M.NeedInput:
        k = None
    mini = None  # P7-U2: the same numbers for the fixed bar
    with st.container(key="kpiband"):
        cols = st.columns(6)
        if k is None or k["r"].get("per_share") is None:
            err = (k or {}).get("r", {}).get("error") if k else "시세 입력 필요"
            cells = [
                _kc(f"주당가치 (DCF · {lab_sc})", "—", tx.plain_words(err or "계산 불가"), "시세 입력 뒤 계산", "muted"),
                _kc("기업가치 (EV)", "—", "", ""),
                _kc("주주가치 (Equity)", "—", "", ""),
                None,
                _kc("WACC / g", "—", "", ""),
                _kc("영구가치 비중 (TV / EV)", "—", "", ""),
            ]
            mk = M.market(o, s, c.mode)
        else:
            r, r0, mk = k["r"], k["r0"], k["mk"]
            sc = r.get("scenarios") or {}
            ps, ps0 = r.get("per_share"), r0.get("per_share")
            d_ps = F.signed(ps - ps0) if F.ok(ps) and F.ok(ps0) else "—"
            br = k.get("bridge") or {}
            eb = k.get("ltm_ebitda")
            evx = F.x_(r["ev"] / eb) if F.ok(eb) and eb > 0 else "계산 불가"
            u = "백만" if mn else "억"
            src_ps = "주주가치 ÷ 유통주식수 · 엑셀 Bridge · Scenarios"
            if hold:
                c1 = _kc(
                    f"주당가치 (DCF · {lab_sc})",
                    "Hold",
                    "확인 후 산출",
                    f"평가 보류 — 대표값 미표시 · 보류 전 계산값 {F.won0(ps)}원",
                    "accent",
                )
            else:
                c1 = _kc(
                    f"주당가치 (DCF · {lab_sc})",
                    F.won0(ps) + "원",
                    f"{F.won0(sc.get('pessimistic'))} ~ {F.won0(sc.get('optimistic'))}",
                    f"Bear ~ Bull 범위 · {src_ps} · v0 대비 {d_ps}",
                    "accent",
                )
            d_ev = F.signed((r["ev"] - r0["ev"]) * (100 if mn else 1)) if F.ok(r0.get("ev")) else "—"
            d_eq = F.signed((r["equity"] - r0["equity"]) * (100 if mn else 1)) if F.ok(r0.get("equity")) else "—"
            nc = (br.get("cash_like") or 0) - (br.get("total_debt") or 0) if br else None
            w, g = r.get("wacc"), o.ctx.c.cfg["forecast"]["human"]["g_terminal"]
            ver = M.version(s)
            g = float(ver["overrides"].get("g_terminal", o.ctx.base_cfg["forecast"]["human"]["g_terminal"]))
            cells = [
                c1,
                _kc(
                    "기업가치 (EV)",
                    "—" if hold else F.amt(r["ev"], mn) + u,
                    f"EV/EBITDA (LTM) {evx}",
                    f"평가기준일 이월 EV · 엑셀 DCF · v0 대비 {d_ev}",
                ),
                _kc(
                    "주주가치 (Equity)",
                    "—" if hold else F.amt(r["equity"], mn) + u,
                    f"순현금 {F.amt(nc, mn)} · 비영업 {F.amt(br.get('non_operating'), mn)}" if br else "",
                    f"EV − 순차입금 + 비영업자산 − 비지배지분 · 엑셀 Bridge · v0 대비 {d_eq}",
                ),
                None,
                _kc(
                    "WACC / g",
                    f"{F.p1(w)} / {F.p1(g)}",
                    f"베타 {_b2(r.get('beta_u'))} · MRP {_pc(M.current_value(o, s, 'mrp'))} · SRP {_pc(r.get('srp'))}",
                    "g = 영구성장률 · 엑셀 WACC · 한국은행 ECOS 국고채 · MRP 한공회 가이던스",
                ),
                _kc(
                    "영구가치 비중 (TV / EV)",
                    F.p1(r.get("tv_share"), 0),
                    f"내재 영구가치 배수 {F.x_(r.get('implied_multiple'))}",
                    "영구가치 현재가치 ÷ EV · 엑셀 DCF",
                ),
            ]
            mini = [
                ("주당가치", "Hold" if hold else F.won0(ps) + "원", "" if hold else f"v0 대비 {d_ps}"),
                ("EV", "—" if hold else F.amt(r["ev"], mn) + u, ""),
                ("주주가치", "—" if hold else F.amt(r["equity"], mn) + u, ""),
                ("WACC / g", f"{F.p1(w)} / {F.p1(g)}", ""),
                ("영구가치 비중", F.p1(r.get("tv_share"), 0), ""),
            ]
        for i, col in enumerate(cols):
            with col:
                if i == 3:
                    _price_cell(c, mk)
                else:
                    st.markdown(cells[i], unsafe_allow_html=True)
    st.session_state["_mini"] = mini


# ---------------------------------------------------------------- P7-U2 scenario switch and the fixed KPI bar

SCEN_LABEL = {"pessimistic": "Bear", "base": "Base", "optimistic": "Bull"}
BAR_TABS = ("summary", "assume", "dcf", "rel", "premium")  # config/p7u2.yaml kpi_bar.tabs_with_bar
MINI_EMPTY = [("주당가치", "—", ""), ("EV", "—", ""), ("주주가치", "—", ""), ("WACC / g", "—", ""), ("영구가치 비중", "—", "")]


def scenario() -> str:
    """The scenario the KPI band, the bar and the summary show (screen state only; Excel and report stay on Base)."""
    v = st.session_state.get("scen", "base")
    return v if v in SCEN_LABEL else "base"


def _scen_pick(key: str) -> None:
    v = st.session_state.get(key)
    if v in SCEN_LABEL:
        st.session_state["scen"] = v


def scen_switch(key: str) -> None:
    """Bear / Base / Bull. Two copies (tab row and bar) write the same state."""
    st.session_state[key] = scenario()
    st.segmented_control(
        "시나리오",
        list(SCEN_LABEL),
        format_func=SCEN_LABEL.get,
        key=key,
        on_change=_scen_pick,
        args=(key,),
        required=True,
        label_visibility="collapsed",
        help="엔진이 이미 계산한 시나리오 값을 화면에만 보여 줌(확정·엑셀·보고서는 Base 기준)",
    )


def mini_bar(c: nav.Ctx) -> None:
    """The 44px bar (shown by client.py when the KPI band is out of view): tab menu · scenario · numbers · expand."""
    mini = st.session_state.get("_mini") or MINI_EMPTY
    lab = dict(nav.TABS)
    with st.container(key="minibar"):
        a, b, m, d = st.columns([1.5, 2.1, 7.6, 1.2], vertical_alignment="center")
        with a, st.popover(lab.get(c.page, "탭"), width="stretch"):
            for t_id, t_lab in nav.TABS:
                st.button(t_lab, key=f"mb_tab_{t_id}", on_click=nav.go, args=(t_id,), width="stretch", disabled=t_id == c.page)
        with b:
            scen_switch("scen_bar")
        items = "".join(
            f"<span class='i'><span class='k'>{ui.esc(k)}</span><span class='v'>{ui.esc(v)}</span>"
            + (f"<span class='d'>{ui.esc(dd)}</span>" if dd else "")
            + "</span>"
            for k, v, dd in mini
        )
        m.markdown(f"<div class='kvi-mini-items'>{items}</div>", unsafe_allow_html=True)
        d.markdown(
            "<button type='button' class='kvi-exp-btn' title='이 위치에서 지표 6칸 펼치기·접기'>"
            "<span class='o'>▾ 펼치기</span><span class='x'>▴ 접기</span></button>",
            unsafe_allow_html=True,
        )


def _price_cell(c: nav.Ctx, mk: dict) -> None:
    o, s = c.o, c.s
    close = mk.get("close")
    shares = o.ctx.c.market["common_out"]
    u = "백만" if c.mn else "억"
    if c.mode == "pc":
        st.markdown(
            _kc(
                "주가 / 시가총액",
                F.won0(close) + "원" if close else "—",
                f"시총 {F.amt((mk.get('mktcap_won') or 0) / 1e8, c.mn)}{u}" if close else "",
                f"평가기준일 종가 · 20일 VWAP {F.won0(mk.get('vwap'))}원 · 한국거래소 통계정보",
            ),
            unsafe_allow_html=True,
        )
        return
    ex = (s.get("public_inputs") or {}).get("example")
    sub_ = (f"시총 {F.amt(close * shares / 1e8, c.mn)}{u}" + (" · 예시" if ex else "")) if close else "입력 전"
    st.markdown(
        _kc(
            "주가 / 시가총액",
            F.won0(close) + "원" if close else "—",
            sub_,
            "사용자 입력(공개 모드: 한국거래소 시세를 쓰지 않음) · 유통주식수 DART 주식의 총수",
        ),
        unsafe_allow_html=True,
    )
    with st.popover("입력", help="대상 종가·20일 VWAP(공개 모드)"):
        public_form(c, "kpi", target_only=True)


# ---------------------------------------------------------------- public-mode market inputs


def public_form(c: nav.Ctx, key: str, target_only: bool = False) -> None:
    """Public mode: target close and 20-day VWAP (KPI cell) or the listed subsidiaries', associates' and preferred closes
    (DCF bridge). Saving recalculates with the user's prices; 'example values' fills round example prices."""
    o, s = c.o, c.s
    u = s.get("public_inputs") or {}
    ex = M.example_prices()
    if u.get("example"):
        st.markdown(f"<p class='wb-kpi-note wb-warn'>{ui.esc(ex['short_label'])}</p>", unsafe_allow_html=True)
    elif st.button(
        "예시 값으로 채우기",
        key=f"pub_example_{key}",
        help=f"대상 종가 {ex['target_close']:,}원, 20일 VWAP {ex['target_vwap20']:,}원, 상장 종속회사·관계기업·우선주 종가 {ex['other_close']:,}원(둥근 예시 값, 실제 종가 아님)",
    ):
        for k_ in [k_ for k_ in st.session_state if str(k_).startswith("pub_") and str(k_).endswith(f"_{key}")]:
            del st.session_state[k_]
        M.S.set_public_inputs(s, M.example_inputs(o))
        st.rerun()
    import hashlib

    # the input widgets get a key per stored state, so after '예시 값' or a save the boxes show the stored values
    key = f"{key}_{hashlib.sha1(M.ukey(s).encode()).hexdigest()[:6]}"
    with st.form(f"pubform_{key}", border=False):
        close = vw = None
        subs, prefs = dict(u.get("sub_close") or {}), {k_: dict(v_) for k_, v_ in (u.get("pref") or {}).items()}
        if target_only:
            close = st.text_input("대상 종가(원)", value=f"{u['close']:.0f}" if u.get("close") else "", key=f"pub_close_{key}")
            vw = st.text_input(
                "대상 20일 VWAP(원)",
                value=f"{u['vwap20']:.0f}" if u.get("vwap20") else "",
                key=f"pub_vwap_{key}",
                help=tx.GLOSSARY["VWAP"],
            )
        else:
            for x in o.subs:
                cur = (u.get("sub_close") or {}).get(x["stock_code"])
                subs[x["stock_code"]] = st.text_input(
                    f"상장 종속회사 종가(원): {x.get('name', '')}({x['stock_code']})",
                    value=f"{cur:.0f}" if cur else "",
                    key=f"pub_sub_{x['stock_code']}_{key}",
                )
            for x in getattr(o, "assocs", []):
                cur = (u.get("sub_close") or {}).get(x["stock_code"])
                subs[x["stock_code"]] = st.text_input(
                    f"상장 관계기업 종가(원): {x.get('name', '')}({x['stock_code']})",
                    value=f"{cur:.0f}" if cur else "",
                    key=f"pub_as_{x['stock_code']}_{key}",
                )
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
                "close": num(close) if target_only else u.get("close"),
                "vwap20": num(vw) if target_only else u.get("vwap20"),
                "sub_close": {k_: num(v_) for k_, v_ in subs.items() if num(v_)},
                "pref": {
                    k_: {"close": num(v_["close"]), "listed": num(v_["listed"])}
                    for k_, v_ in prefs.items()
                    if num(v_.get("close")) and num(v_.get("listed"))
                },
            }
            if M.is_example(o, user):
                user["example"] = True
            M.S.set_public_inputs(s, user)
            st.rerun()
        except ValueError as e:
            st.error(f"입력 확인: {e}")
    miss = M.public_missing(o, s)
    if miss:
        st.markdown(f"<p class='wb-kpi-note wb-warn'>남은 입력: {ui.esc(', '.join(miss))}</p>", unsafe_allow_html=True)


# ---------------------------------------------------------------- change notice and tabs


def note_change(s: dict, label: str) -> None:
    """Remember the version before a change; the next run shows 'per share a -> b (Δ) · item' (st.toast, 5 s)."""
    st.session_state["toast_from"] = {"v": M.version(s)["v"], "label": label, "sid": s["session_id"]}


def toast(c: nav.Ctx) -> None:
    t = st.session_state.pop("toast_from", None)
    if not t or t.get("sid") != c.sid or not c.o:
        return
    v1 = M.version(c.s)["v"]
    if v1 == t["v"]:
        return
    try:
        a = M.result(c.o, c.s, c.mode, t["v"]).get("per_share")
        b = M.result(c.o, c.s, c.mode).get("per_share")
    except M.NeedInput:
        return
    if F.ok(a) and F.ok(b):
        st.toast(f"주당가치 {F.won0(a)} → {F.won0(b)}원 ({F.signed(b - a)}) · {t['label']}", duration=5)


def tab_counts(c: nav.Ctx) -> dict:
    from src.workbench import events as E

    n_j = sum(
        1 for j in (c.s.get("judgements") or {}).values() if j.get("status") == "미처리" and j.get("category") != E.MOVED_CATEGORY
    )
    try:
        n_e = E.pending(c.o.cfg, c.s)
    except Exception:  # noqa: BLE001 - the count is left out
        n_e = 0
    return {"assume": n_j, "events": n_e}


def tabs(c: nav.Ctx) -> None:
    n = tab_counts(c)
    lab = dict(nav.TABS)

    def fmt(t):
        return f"{lab[t]} {n[t]}" if n.get(t) else lab[t]

    def _pick():
        v = st.session_state.get(f"wbtabs_{c.page}")
        if v and v != c.page:
            nav.go(v)

    a, b = st.columns([8.6, 1.9], vertical_alignment="center")
    with a, st.container(key="wbtabs"):
        st.segmented_control(
            "작업 탭",
            nav.TAB_IDS,
            default=c.page if c.page in nav.TAB_IDS else None,
            format_func=fmt,
            key=f"wbtabs_{c.page}",
            on_change=_pick,
            label_visibility="collapsed",
        )
    with b, st.container(key="scenrow"):
        if c.page in BAR_TABS:
            scen_switch("scen_band")


# ---------------------------------------------------------------- the first screen


def first_screen(c: nav.Ctx) -> None:
    if c.public:
        st.markdown(f"<div class='wb-band-top' role='note'>{tx.PUBLIC_NOTICE}</div>", unsafe_allow_html=True)
    if not st.session_state.get("picked_code"):
        with ui.card("guide"):
            ui.h2("처음 쓰는 경우")
            st.markdown(
                "<div class='wb-cells'>"
                "<div><span class='k'>1</span><span class='v'>검색창에서 회사 고르기</span><span class='s'>자동 평가 가능 여부 한 줄</span></div>"
                "<div><span class='k'>2</span><span class='v'>평가 시작</span><span class='s'>자동 초안 → 요약</span></div>"
                "<div><span class='k'>3</span><span class='v'>가정·판단 탭</span><span class='s'>영향 큰 판단부터 처리</span></div>"
                "<div><span class='k'>4</span><span class='v'>확정 · 내보내기</span><span class='s'>엑셀·보고서·세션 파일</span></div>"
                "</div>",
                unsafe_allow_html=True,
            )
    rows = M.sessions()[:5]
    with ui.card("recent"):
        ui.h2("최근 세션", f"{len(M.sessions())}개")
        if not rows:
            st.markdown("<p class='wb-kpi-note'>아직 세션이 없습니다.</p>", unsafe_allow_html=True)
        for r in rows:
            a, b = st.columns([6, 1.2], vertical_alignment="center")
            a.markdown(
                f"<div class='wb-subrow'><b>{ui.esc(r['name'])}</b> {r['code']} · v{r['version']} · "
                f"{ui.badge(r['status'], 'ok' if r['status'] == '확정' else '')} {ui.badge(f'미처리 {r["pending"]}', 'warn' if r['pending'] else 'ok')} · {r['modified']}</div>",
                unsafe_allow_html=True,
            )
            b.button("열기", key=f"open_{r['sid']}", on_click=nav.go, args=("summary", r["sid"], c.mode), width="stretch")
        st.button("모든 세션 →", key="all_sessions", type="tertiary", on_click=nav.go, args=("sessions",))
