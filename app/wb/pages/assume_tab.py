"""가정·판단 tab (P7-U1): the judgement list on top (progress, [다음 미처리], sort by impact / category, rows that open with
the reason, every candidate as 'now -> after per share', direct input, change reason, '그대로 유지', bulk keep of the
small items, confirm-type list), then the three assumption tables (discount rate, forecast, bridge: item · applied ·
auto · practice · Δ per share for one unit) and the plan check.

Processing recalculates at once (session.set_assumption via judge.resolve); every change is a new version. The judgement
'기준일 뒤 주요 공시' is handled in the 공시·이벤트 tab (not listed here)."""

from __future__ import annotations

import time

import streamlit as st

from app.wb import components as ui
from app.wb import fields as FD
from app.wb import fmt as F
from app.wb import glossary as G
from app.wb import model as M
from app.wb import nav, shell
from app.wb import text as tx
from app.wb import values as V
from src.workbench import events as E

STATUS_CLS = {"미처리": "", "채택": "ok", "수정": "ok", "그대로 유지": ""}
LABEL = {
    "rf_tenor": "무위험이자율 (Rf) 만기",
    "mrp": "시장위험프리미엄 (MRP)",
    "beta_u": "무부채 베타 (βu)",
    "de": "목표 부채비율 (D/E)",
    "kd": "타인자본비용 (Kd, 세전)",
    "srp": "규모위험프리미엄 (SRP)",
    "g_start": "출발 성장률",
    "normal_margin": "정상화 영업이익률",
    "g_terminal": "영구성장률 (g)",
    "scenario_width": "시나리오 폭",
    "sotp_discount": "상장 지분 할인 (SOTP)",
    "cash_adjust_mn": "영업용 현금",
    "nci_mn": "비지배지분",
}
WIDTHS = [26, 13, 13, 30, 18]


def visible_rows(s: dict) -> list[dict]:
    """Judgement rows of the list (the moved disclosure item left out), ranked items first."""
    return [r for r in M.judgement_rows(s) if r.get("category") != E.MOVED_CATEGORY]


def render(c: nav.Ctx) -> None:
    from app.wb import sens

    sens.apply_line(c)  # P7-U2: a combination carried from a DCF sensitivity table
    with ui.card("judge"):
        panel(c)
    st.text_input("변경 이유 (다음 변경에 기록)", key="chg_reason", placeholder="[변경 이유] 예: 한공회 가이던스 적용")
    for g in ("할인율", "추정", "Bridge"):
        with ui.card(f"grp_{g}"):
            table(c, g)
    with ui.card("plan"):
        plan(c)


# ---------------------------------------------------------------- judgement list


def _clean(c: nav.Ctx, r: dict) -> dict:
    if c.mode == "public":
        r = {**r, **{k: tx.public_mask(r.get(k)) for k in ("item", "detail", "alternative")}}
    return {**r, **{k: tx.plain_words(r.get(k)) for k in ("category", "item", "detail", "alternative")}}


def _ps(c: nav.Ctx, v):
    if v is None:
        return None
    try:
        return M.result(c.o, c.s, c.mode, v).get("per_share")
    except M.NeedInput:
        return None


def _impact(r: dict) -> str:
    imp = r.get("impact")
    return F.signed(imp) if F.ok(imp) else "—"


def panel(c: nav.Ctx) -> None:
    s = c.s
    rows = visible_rows(s)
    done = [r for r in rows if r["status"] != "미처리"]
    n = len(rows) - len(done)
    computed = [r for r in rows if r.get("rank") is not None]
    other = [r for r in rows if r.get("rank") is None]
    a, b, d = st.columns([5, 2.2, 1.6], vertical_alignment="center")
    a.markdown(
        f"<p class='wb-h2'>판단 필요<span class='wb-h2-sub'>처리 {len(done)} · 미처리 {n}</span></p>", unsafe_allow_html=True
    )
    with b:
        sort = st.segmented_control(
            "정렬",
            ["impact", "cat"],
            default="impact",
            format_func={"impact": "영향", "cat": "분류"}.get,
            key="j_sort",
            required=True,
        )
    nxt = next((r["id"] for r in computed + other if r["status"] == "미처리"), None)
    d.button(
        "다음 미처리",
        key="j_next",
        disabled=nxt is None,
        on_click=lambda: st.session_state.__setitem__("judge_open", nxt),
        width="stretch",
    )
    pct = len(done) / len(rows) * 100 if rows else 100
    st.markdown(f"<div class='wb-progress'><div style='width:{pct:.1f}%'></div></div>", unsafe_allow_html=True)
    flash = st.session_state.pop("judge_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])
    show_all = st.session_state.get("j_all_f", False)
    items = computed + (
        other
        if show_all
        else [r for r in other if r["status"] != "미처리" or r["category"] in ("SOTP 가드", "Peer 직접 지정", "피어 직접 지정")]
    )
    if sort == "cat":
        items = sorted(items, key=lambda r: (str(r["category"]), r.get("rank") or 99))
    top, rest = items[:10], items[10:]
    for r in top:
        _item(c, r)
    small = [r["id"] for r in rest if r["status"] == "미처리"]
    if rest:
        more = st.toggle(f"나머지 {len(rest)}건 보기 (영향 작은 항목)", key="j_more_f", value=False)
        if more:
            for r in rest:
                _item(c, r)
    a, b = st.columns([4, 2], vertical_alignment="center")
    a.markdown(
        f"<p class='wb-kpi-note'>영향 작은 항목 {len(small)}건 · 확인형 {len(other)}건(보고서 작성 칸·우선주 등)</p>",
        unsafe_allow_html=True,
    )
    if small:
        b.button(
            f"영향 작은 {len(small)}건 일괄 유지",
            key="j_keepall_f",
            on_click=_keep_rest,
            args=(c.sid, small),
            help="자동값을 그대로 둡니다. 감사 기록에는 항목마다 한 줄씩",
            width="stretch",
        )
    st.toggle("확인형 항목까지 모두 보기", key="j_all_f", value=False)


def _keep_rest(sid: str, ids: list[str]) -> None:
    s = M.load(sid)
    n = M.keep_many(s, ids, "영향 작은 항목 일괄 확인(그대로 유지)")
    st.session_state["judge_flash"] = (True, f"영향 작은 항목 {n}건을 그대로 유지했습니다(항목별 감사 기록).")


def _short(label: str) -> str:
    """Candidate label without the repeated prefix ('정상 이익률 후보: ', '3년 평균 방식: ')."""
    t = tx.plain_words(label)
    return t.split(": ", 1)[1] if ": " in t else t


def short_name(label: str) -> str:
    """P7-U3 U3-3b: the button name of a candidate - the prefix, explanations in parentheses (4+ characters; markers like
    '(A)' stay) and a rule's left side ('… = 수렴 규칙(A) …' -> '수렴 규칙(A) …') are left to the tooltip."""
    import re

    t = _short(label)
    t = re.sub(r"\s*\([^()]{4,}\)", "", t)
    if " = " in t:
        t = t.split(" = ", 1)[1]
    return re.sub(r"\s+", " ", t).strip()


def applied(r: dict, cd: dict) -> bool:
    """The candidate this judgement adopted (status 채택/수정 with this field and value) - shown with the orange frame."""
    res = r.get("resolution") or {}
    return r.get("status") in ("채택", "수정") and res.get("field") == cd["field"] and res.get("value") == cd["value"]


def _cand_label(c: nav.Ctx, cd: dict, compact: bool = False) -> tuple[str, bool, str]:
    val = M.spec.fmt(cd["field"], cd["value"]) if cd["field"] != "peers" else f"{len(cd['value'])}곳"
    pv = M.candidate_preview(c.o, c.s, c.mode, cd["field"], cd["value"])
    ok = pv.get("after") is not None or "시세 입력" in str(pv.get("error"))
    full = f"{tx.plain_words(cd['label'])} {val} · " + (
        f"현재 {F.won0(pv['before'])} → 반영 후 {F.won0(pv['after'])}원"
        if pv.get("after") is not None
        else tx.plain_words(pv.get("error") or "계산 불가")
    )
    import re

    # P7-U3 U3-3b: short name (+ the value when the name has no number of its own) · per share after adopting it; the
    # whole sentence (and 'current -> after') is the tooltip. Same rule on the summary and the 가정·판단 tab
    # A long value text (a named rule such as the CAPEX path) stays in the tooltip. The summary's narrower buttons use a
    # fixed two-line form - name / per share - so a long name never wraps into a third line
    sl = short_name(cd["label"])
    head_ = sl if re.search(r"\d", sl) or len(val) > 12 or (compact and len(sl) > 14) else f"{sl} {val}"
    if pv.get("after") is not None:
        ps = f"{F.won0(pv['after'])}원"
        return (f"{head_}  \n{ps}" if compact else f"{head_} · {ps}"), ok, full
    return (head_ if compact else f"{head_} · {tx.plain_words(pv.get('error') or '계산 불가')}"), ok, full


def _item(c: nav.Ctx, r: dict) -> None:
    r = _clean(c, r)
    jid = r["id"]
    st_ = r["status"]
    ba = ""
    if r.get("changed_v") is not None:
        b, a = _ps(c, r["changed_v"] - 1), _ps(c, r["changed_v"])
        ba = f" · {F.won0(b)} → {F.won0(a)}원"
    title = f"{r['category']}  ·  {str(r['item'])[:60]}  ·  {_impact(r)}  ·  {st_}{ba}"
    # P7-U2 speed: the candidate previews (a recalculation each) are computed when the row is opened, not for every row
    xkey = f"jx_{jid}"
    if st.session_state.get("judge_open") == jid:
        st.session_state[xkey] = True
    opened = bool(st.session_state.get(xkey))
    with st.expander(title, key=xkey, on_change="rerun"):
        st.markdown(
            f"{ui.badge(st_, STATUS_CLS.get(st_, ''))} <span class='wb-kpi-note'>{ui.esc(r.get('detail') or '')[:300]}</span>"
            + (
                f"<br><span class='wb-kpi-note'>자동 진단 대안: {ui.esc(r['alternative'])}</span>" if r.get("alternative") else ""
            ),
            unsafe_allow_html=True,
        )
        if r.get("resolution"):
            res = r["resolution"]
            st.markdown(
                f"<p class='wb-kpi-note'>처리 v{res.get('v')} · 이유: {ui.esc(res.get('reason') or '(없음)')}</p>",
                unsafe_allow_html=True,
            )
        cands = r.get("candidates") or []
        if cands:
            cols = st.columns(min(len(cands), 3))
            for i, cd in enumerate(cands):
                if opened:
                    lab, ok, full = _cand_label(c, cd)
                else:
                    lab = f"{short_name(cd['label'])} {M.spec.fmt(cd['field'], cd['value']) if cd['field'] != 'peers' else ''}".strip()
                    ok, full = True, tx.plain_words(cd["label"])
                cols[i % len(cols)].button(
                    lab,
                    help=full,
                    key=f"jc_f_{jid}_{i}" + ("_on" if applied(r, cd) else ""),  # P7-U3 U3-3c: the adopted one framed
                    on_click=_do,
                    args=(c.sid, jid, "candidate"),
                    kwargs={"candidate": i, "rkey": f"jr_f_{jid}"},
                    width="stretch",
                    disabled=not ok,
                )
        fields = r.get("direct_fields") or []
        if fields:
            a, b, d = st.columns([2, 2, 1], vertical_alignment="bottom")
            fld = a.selectbox(
                "직접 입력할 가정", fields, format_func=lambda f: tx.plain_words(LABEL.get(f, M.spec.LABEL[f])), key=f"jf_f_{jid}"
            )
            if fld == "peers":
                b.multiselect("Peer", c.o.ctx.peers_all(), default=M.current_value(c.o, c.s, "peers"), key=f"jv_f_{jid}")
            elif fld == "premium":
                b.selectbox("지분 구간", ["lt25", "25to50", "gt50"], key=f"jv_f_{jid}")
            elif fld == "fade_reinvest":  # P7-U1F D-2 (C): one of two named rules
                b.selectbox("규칙", list(M.spec.FADE_REINVEST), format_func=M.spec.FADE_REINVEST.get, key=f"jv_f_{jid}")
            else:
                unit = " (%)" if fld in FD.PCT_FIELDS else (" (백만원)" if fld.endswith("_mn") else "")
                b.text_input(f"직접 입력{unit}", value=FD.to_text(fld, M.current_value(c.o, c.s, fld)), key=f"jv_f_{jid}")
            d.button(
                "적용",
                key=f"jd_f_{jid}",
                on_click=_do,
                args=(c.sid, jid, "direct"),
                kwargs={"fkey": f"jf_f_{jid}", "vkey": f"jv_f_{jid}", "rkey": f"jr_f_{jid}"},
                width="stretch",
            )
        if r["category"] == "희석증권":  # P7-U1F D-3: a check item - two ways of handling, neither changes a value
            a, b, d = st.columns([3, 1.4, 1.6], vertical_alignment="bottom")
            a.text_input("메모 (기록)", key=f"jr_f_{jid}", placeholder="예: 전환가액·만기 확인, 내가격 아님")
            b.button(
                "부채 처리(지금)",
                key=f"jk_f_{jid}",
                on_click=_do,
                args=(c.sid, jid, "keep"),
                kwargs={"rkey": f"jr_f_{jid}"},
                width="stretch",
                help="CB·BW·EB 장부 금액을 총차입금에 두고 주식 수는 그대로(지금 모델). 그대로 유지로 기록",
            )
            d.button(
                "원문 확인 후 판단",
                key=f"jn_f_{jid}",
                on_click=_do,
                args=(c.sid, jid, "note"),
                kwargs={"rkey": f"jr_f_{jid}"},
                width="stretch",
                help="메모만 감사 기록에 남기고 미처리로 둠(원문 확인 뒤 다시 처리)",
            )
            return
        a, b = st.columns([4, 1.4], vertical_alignment="bottom")
        a.text_input("변경 이유 (기록)", key=f"jr_f_{jid}", placeholder="예: 주석 확인 결과 일회성 손익")
        b.button(
            "그대로 유지",
            key=f"jk_f_{jid}",
            on_click=_do,
            args=(c.sid, jid, "keep"),
            kwargs={"rkey": f"jr_f_{jid}"},
            width="stretch",
        )


def compact_row(c: nav.Ctx, r: dict) -> None:
    """Summary tab: item (reason in the tooltip) · candidate buttons · Δ."""
    r = _clean(c, r)
    a, b, d = st.columns([2.2, 4.2, 1], vertical_alignment="center")
    a.markdown(
        f"<span class='wb-term' style='font-size:15px;font-weight:500' title='{ui.attr((r.get('detail') or '') + ' · ' + r['category'])}'>"
        f"{ui.esc(str(r['item'])[:40])}</span> {ui.badge(r['status'], STATUS_CLS.get(r['status'], ''))}",
        unsafe_allow_html=True,
    )
    cands = (r.get("candidates") or [])[:3]
    with b:
        if cands:
            cols = st.columns(len(cands))
            for i, cd in enumerate(cands):
                lab, ok, full = _cand_label(c, cd, compact=True)
                on = applied(r, cd)  # P7-U2F D4: the candidate now applied gets the orange frame
                cols[i].button(
                    lab,
                    help=full,
                    key=f"jc_s_{r['id']}_{i}" + ("_on" if on else ""),
                    on_click=_do,
                    args=(c.sid, r["id"], "candidate"),
                    kwargs={"candidate": i},
                    disabled=not ok,
                    width="stretch",
                )
        else:
            st.button("가정·판단에서 처리 →", key=f"jgo_{r['id']}", type="tertiary", on_click=_open_in_assume, args=(r["id"],))
    d.markdown(f"<div style='text-align:right;font-size:15px;font-weight:500'>{_impact(r)}</div>", unsafe_allow_html=True)


def _open_in_assume(jid: str) -> None:
    st.session_state["judge_open"] = jid
    nav.go("assume")


def _do(
    sid: str,
    jid: str,
    action: str,
    candidate: int | None = None,
    fkey: str | None = None,
    vkey: str | None = None,
    rkey: str | None = None,
) -> None:
    s = M.load(sid)
    reason = (st.session_state.get(rkey) or "").strip() if rkey else ""
    kw = {"reason": reason or None}
    if action == "candidate":
        kw["candidate"] = candidate
    elif action == "direct":
        fld = st.session_state.get(fkey)
        raw = st.session_state.get(vkey)
        if fld == "premium":
            raw = {"stake_band": raw}
        kw.update({"field": fld, "value": raw if fld in ("peers", "premium", "fade_reinvest") else FD.parse(fld, raw)})
    item = s["judgements"][jid]["item"]
    if action not in ("keep", "note"):
        shell.note_change(s, tx.plain_words(str(item))[:30])
    r = M.resolve(s, jid, action, **kw)
    st.session_state["judge_open"] = jid
    if r["ok"]:
        msg = f"'{tx.plain_words(str(item))[:40]}' 처리: {s['judgements'][jid]['status']}"
        if action == "note":
            msg = f"'{tx.plain_words(str(item))[:40]}' 메모 기록(미처리 유지)"
        elif action != "keep":
            msg += f" → v{M.version(s)['v']}"
        st.session_state["judge_flash"] = (True, msg + (f" (주의: {r['reason']})" if r.get("reason") else ""))
    else:
        st.session_state.pop("toast_from", None)
        st.session_state["judge_flash"] = (False, f"반영 안 됨: {r['reason']}")


# ---------------------------------------------------------------- assumption tables


def _apply(sid: str, f: str, key: str) -> None:
    """on_change: range check + new version, or the rejection message under the row (session unchanged)."""
    s = M.load(sid)
    raw = st.session_state.get(key)
    if f in ("rf_tenor",):
        val = raw
    elif isinstance(raw, float) and f in ("srp", "kd"):
        val = raw
    else:
        val = FD.parse(f, raw)
    reason = (st.session_state.get("chg_reason") or "").strip() or None
    shell.note_change(s, LABEL.get(f, f))
    t0 = time.time()
    r = M.set_value(s, f, val, reason)
    st.session_state["recalc_s"] = round(time.time() - t0, 3)
    if r["ok"]:
        st.session_state[f"msg_{f}"] = (True, r.get("reason") or "")
        st.session_state["chg_reason"] = ""
    else:
        st.session_state.pop("toast_from", None)
        st.session_state[f"msg_{f}"] = (False, r["reason"])


def _set(sid: str, f: str, value, why: str) -> None:
    s = M.load(sid)
    shell.note_change(s, LABEL.get(f, f))
    r = M.set_value(s, f, value, (st.session_state.get("chg_reason") or "").strip() or why)
    st.session_state[f"msg_{f}"] = (r["ok"], r.get("reason") or "")
    if not r["ok"]:
        st.session_state.pop("toast_from", None)


def _practice(c: nav.Ctx, f: str, cur, r: dict) -> tuple[str, bool]:
    p = M.practice()
    full, late = p["full"], p["late"]
    if f == "rf_tenor":
        return f"10년 {p['rf10']}/{p['rf_marked']}건", int(cur or 5) != 10
    if f == "mrp":
        return f"중앙값 {F.p1(late['mrp']['median'], 2)} · IQR {F.p1(full['mrp']['q1'], 2)}~{F.p1(full['mrp']['q3'], 2)}", abs(
            float(cur) - late["mrp"]["median"]
        ) > 0.0005
    if f == "srp":
        cite = _srp_cite()
        return f"중앙값 {F.p1(full['srp']['median'], 2)}" + (f" · 인용 {F.p1(cite, 2)}" if cite else ""), float(cur or 0) < full[
            "srp"
        ]["q1"]
    if f == "g_terminal":
        return f"중앙값 {F.p1(full['g']['median'], 2)}", abs(float(cur) - full["g"]["median"]) > 0.0005
    if f == "beta_u":
        b = M.beta_info(c.o, c.s, c.mode)
        return f"Peer 중앙값 (R² {F.beta(b['r2_median'])[:4] if b['r2_median'] is not None else '비표시'})", bool(b["warn"])
    if f == "de":
        return "자체 과거 평균", False
    if f == "kd":
        kd = c.o.cfg.get("kd") or {}
        rates = c.o.ctx.c.rates
        return f"등급 {kd.get('rating') or '미확인'} · BBB- 3년 {F.p1(rates['CB3Y_BBBm'], 2)}", False
    if f == "g_start":
        return "자사 CAGR · Peer 성장률 평균", False
    if f == "normal_margin":
        pm = (c.o.ctx.base_v2 or {}).get("peer_margin")
        return f"Peer 중앙값 {F.p1(pm, 2)}" if F.ok(pm) else "Peer 중앙값 —", False
    if f == "scenario_width":
        return "—", False
    if f == "sotp_discount":
        return "기본 0% · 민감도 30·50%", False
    if f == "cash_adjust_mn":
        cf = (M.bridge_info(c.o).get("customer_funds") or {}).get("operating_cash")
        return f"고객 자금 성격 후보 {F.amt(cf / 100, c.mn)}{'백만' if c.mn else '억'}" if F.ok(
            cf
        ) else "고객 자금 성격 후보 없음", False
    if f == "nci_mn":
        return "비례법·P/B 후보(판단 목록)", False
    return "", False


_SRP_CITE: dict = {}  # process-wide: the cited SRP is one aggregate of the saved opinions (same for every company)


def _srp_cite() -> float | None:
    k = ("srp_cite", M.S.workspace() is None)
    if k in _SRP_CITE:
        return _SRP_CITE[k]
    if M.SRP_CITE.get("v") is not None and not M.public_deploy():  # read when the session was opened (P7-U2)
        _SRP_CITE[k] = M.SRP_CITE["v"]
        return _SRP_CITE[k]
    if k not in M._CACHE:
        try:
            M.need_db("SRP 인용값")
            from src.valuation.company_dcf import _close, _con
            from src.workbench.public_deploy import srp_cite_value

            con = _con()
            try:
                M._CACHE[k] = float(srp_cite_value(con))
            finally:
                _close(con)
        except Exception:  # noqa: BLE001 - the button is just not offered
            M._CACHE[k] = None
    if M._CACHE[k] is not None:
        _SRP_CITE[k] = M._CACHE[k]
    return M._CACHE[k]


def _auto_tip(c: nav.Ctx, f: str) -> str:
    if f in ("g_start", "normal_margin"):
        h = M.history_info(c.o)
        if f == "g_start":
            return f"기본 방식 = 자사 CAGR {F.p1(h['own_cagr'], 2)}와 Peer 성장률 {F.p1(h['peer_growth'], 2)}의 평균 · 3년 평균 방식 = 매출 CAGR {F.p1(h['cagr'], 2)}"
        return f"기본 방식 = 5년 중앙값에서 Peer 쪽 수렴(출발 {F.p1(h['m0'], 2)}) · 3년 평균 방식 = {F.p1(h['margin'], 2)} · Peer {F.p1(h['peer_margin'], 2)}"
    return ""


def table(c: nav.Ctx, g: str) -> None:
    o, s = c.o, c.s
    fields = [f for f in V.TABLE_FIELDS[g] if M.applicable(o, f)]
    r = M.result(o, s, c.mode)
    p = M.practice()
    if g == "할인율":
        title, note = (
            "할인율",
            f"WACC {F.p1(r.get('wacc'), 2)} · 실무 IQR {F.p1(p['full']['wacc']['q1'], 2)}~{F.p1(p['full']['wacc']['q3'], 2)}",
        )
    elif g == "추정":
        title, note = "추정", f"시나리오 폭 ±{F.p1(M.current_value(o, s, 'scenario_width'), 2).replace('%', '%p')}"
    else:
        title, note = "주주가치 조정 (Bridge)", "EV → 주주가치"
    ui.h2(title, "", ui.esc(note))
    dl = V.deltas(o, s, c.mode, fields)
    hc = st.columns(WIDTHS)
    for col, h in zip(hc, ["항목", "적용값", "자동값", "실무 관행", "Δ 주당 (1단위)"]):
        col.markdown(
            f"<div class='wb-kpi-note' style='font-weight:500;border-bottom:1px solid #15171B;padding-bottom:6px'>{h}</div>",
            unsafe_allow_html=True,
        )
    for f in fields:
        _row(c, f, dl.get(f) or {})
    if g == "할인율":
        with st.expander("무부채 베타 (βu) 근거 · 부채비율 (D/E) 시점"):
            _beta(c)


def _row(c: nav.Ctx, f: str, d: dict) -> None:
    o, s = c.o, c.s
    v = M.version(s)["v"]
    key = f"in_{f}_v{v}"
    cur = M.current_value(o, s, f)
    auto = M.auto_value(o, s, f)
    changed = f in M.version(s)["overrides"]
    cols = st.columns(WIDTHS, vertical_alignment="center")
    tipx = f"{G.tip(LABEL[f].split(' (')[0]) or G.tip(f)} · 허용 {FD.rng_text(f)}".strip(" ·")
    cols[0].markdown(
        f"<span class='wb-term' style='font-weight:500' title='{ui.attr(tipx)}'>{ui.esc(LABEL[f])}</span>", unsafe_allow_html=True
    )
    with cols[1]:
        if f == "rf_tenor":
            st.segmented_control(
                LABEL[f],
                [5, 10],
                default=int(cur),
                key=key,
                on_change=_apply,
                args=(c.sid, f, key),
                format_func=lambda t: f"{t}년",
                label_visibility="collapsed",
                required=True,
            )
        else:
            st.text_input(
                LABEL[f],
                value=FD.to_text(f, cur),
                key=key,
                on_change=_apply,
                args=(c.sid, f, key),
                label_visibility="collapsed",
                placeholder="자동값" if cur is None else None,
                help=f"허용 {FD.rng_text(f)}" + (" · 변경됨" if changed else ""),
            )
    if f == "rf_tenor":
        rates = o.ctx.c.rates
        at = f"{int(auto)}년 ({F.p1(rates['KTB5Y' if int(auto) == 5 else 'KTB10Y'], 3)})"
    elif f.endswith("_mn"):
        at = (F.amt(float(auto) / 100, c.mn) + ("백만" if c.mn else "억")) if auto is not None else "장부"
    else:
        at = (M.spec.fmt(f, auto).replace("배", "x")) if auto is not None else "자동"
    atip = _auto_tip(c, f)
    cols[2].markdown(
        f"<div style='text-align:right;color:#5A5E66' title='{ui.attr(atip)}'>{ui.esc(at)}</div>", unsafe_allow_html=True
    )
    ptxt, gap = _practice(c, f, cur if cur is not None else auto, M.result(o, s, c.mode))
    with cols[3]:
        st.markdown(
            f"<span class='{'wb-warn' if gap else 'wb-kpi-note'}' style='font-size:14px'>{ui.esc(ptxt)}</span>",
            unsafe_allow_html=True,
        )
        if f == "kd":
            rates = o.ctx.c.rates
            b1, b2 = st.columns(2)
            b1.button(
                "BBB- 적용",
                key="kd_bbb",
                type="tertiary",
                on_click=_set,
                args=(c.sid, "kd", float(rates["CB3Y_BBBm"]), "BBB- 3년 회사채 금리"),
            )
            b2.button(
                "AA- 적용",
                key="kd_aa",
                type="tertiary",
                on_click=_set,
                args=(c.sid, "kd", float(rates["CB3Y_AAm"]), "AA- 3년 회사채 금리"),
            )
        if f == "srp" and _srp_cite():
            st.button(
                f"인용 {F.p1(_srp_cite(), 2)} 적용",
                key="srp_cite_btn",
                type="tertiary",
                on_click=_set,
                args=(c.sid, "srp", float(_srp_cite()), "한공회 인용값(민감도)"),
            )
    if d.get("error"):
        dt = f"{d.get('step_label', '')} → {d['error']}"
    elif f == "scenario_width":
        dt = f"{d.get('step_label', '')} → Base 영향 없음"
    else:
        dt = f"{d.get('step_label', '')} → {F.signed(d.get('delta'))}"
    cols[4].markdown(f"<div style='text-align:right;white-space:nowrap'>{ui.esc(dt)}</div>", unsafe_allow_html=True)
    msg = st.session_state.get(f"msg_{f}")
    if msg and not msg[0]:
        st.markdown(
            f"<p class='wb-kpi-note wb-warn' role='alert'>거부: {ui.esc(msg[1])} (세션 그대로)</p>", unsafe_allow_html=True
        )
    elif msg and msg[1]:
        st.markdown(f"<p class='wb-kpi-note wb-warn'>주의: {ui.esc(msg[1])}</p>", unsafe_allow_html=True)


def _beta(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    b = M.beta_info(o, s, c.mode)
    src = {
        "peer": "Peer 중앙값",
        "override": "사람 확정값",
        "public_few_peers": "공개 모드 Peer 부족 → 시장 평균 1.0",
        "market_1": "시장 평균 1.0",
        "target_own": "대상 자기 회귀",
    }.get(b["src"], b["src"])
    ui.cells(
        [
            {"k": "무부채 베타 (βu)", "v": F.beta(b["beta_u"]), "s": src},
            {"k": "회귀", "v": f"주간 2년 · {b['index']}", "s": f"Peer n {b['n'] if b['n'] is not None else '비표시'}"},
            {
                "k": "R² 중앙값",
                "v": F.beta(b["r2_median"]) if b["r2_median"] is not None else "Peer 5곳 미만(공개 모드)",
                "s": "0.10 미만이면 근거 확인" if b["warn"] else "설명력(0~1)",
            },
            {
                "k": "목표 부채비율 (D/E)",
                "v": F.times(b["de"], 3).replace("배", "x"),
                "s": "공개 모드: 시점 5개 미만 → 0" if b.get("de_cut") else "자체 과거 시점 평균",
            },
        ]
    )
    if b["warn"]:
        st.markdown(
            "<p class='wb-kpi-note wb-warn'>R² 중앙값 0.10 미만 — 베타 근거 확인(βu 직접 입력 가능)</p>", unsafe_allow_html=True
        )
    if c.mode == "pc":
        de = o.ctx.c.market["de_points"]
        if len(de):
            ui.tbl(
                ["시점", "차입(억원)", "시가총액(억원)", "D/E"],
                [
                    [str(r.date), F.amt(r.debt + r.lease), F.amt(r.mktcap), F.times(r.de, 3).replace("배", "x")]
                    for r in de.itertuples()
                ],
                tips=False,
            )
            st.markdown("<p class='wb-kpi-note'>시가총액: 한국거래소 통계정보</p>", unsafe_allow_html=True)
    else:
        st.markdown("<p class='wb-kpi-note'>공개 모드: 시점별 시가총액 숨김</p>", unsafe_allow_html=True)


def plan(c: nav.Ctx) -> None:
    pc = M.plan_check(c.o, c.s, c.mode)
    b = pc["band"]
    ui.h2("사업계획 점검", "추정 vs 실적 · 자체 DB")
    if not b:
        st.markdown("<p class='wb-kpi-note'>추정 매출 CAGR 계산 불가</p>", unsafe_allow_html=True)
        return
    ui.cells(
        [
            {
                "k": "추정 매출 연평균 성장률 (CAGR, FY26→30)",
                "v": F.p1(pc["cagr"], 2),
                "s": f"{tx.plain_words(tx.plain_label(b['label']))} ({F.p1(b['cagr_lo'])}~{F.p1(b['cagr_hi'])})"
                + ("" if b["inside"] else " · 표본 범위 밖"),
            },
            {"k": "1차연도 달성률 중앙값", "v": F.p1(b["h1_median"]), "s": f"n {int(b['h1_n'])} · 같은 구간"},
            {"k": "2차연도", "v": F.p1(b["h2_median"]), "s": f"n {int(b['h2_n'])}"},
            {"k": "3차연도", "v": F.p1(b["h3_median"]), "s": f"n {int(b['h3_n'])}"},
        ]
    )
