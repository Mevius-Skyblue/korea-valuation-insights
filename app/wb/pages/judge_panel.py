"""판단 목록 패널: the ranked judgement list as work items (src/workbench/judge). Open from steps 2~4 and the sidebar.

Each item: rank, category, explanation, per-share impact (auto draft), candidate buttons (judge.candidates), direct input of
the linked assumption, '그대로 유지', reason. Processing recalculates at once (session.set_assumption via judge.resolve)
and the item shows its status (미처리 / 채택 / 수정 / 그대로 유지) and the per-share before -> after.
"""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fields as FD
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx

STATUS_CLS = {"미처리": "warn", "채택": "ok", "수정": "ok", "그대로 유지": ""}


def expander(c: nav.Ctx) -> None:
    n = M.S.pending(c.s)
    with st.expander(f"사람 판단 목록 — 미처리 {n}건 (주당 영향 큰 순)", expanded=bool(st.session_state.get("judge_open"))):
        panel(c, compact=True)


def _ps(c: nav.Ctx, v: int | None):
    """Per-share of a version in the current mode (public: recalculated with the user's inputs)."""
    if v is None:
        return None
    try:
        return M.result(c.o, c.s, c.mode, v).get("per_share")
    except M.NeedInput:
        return None


def panel(c: nav.Ctx, compact: bool = False) -> None:
    s = c.s
    rows = M.judgement_rows(s)
    n = M.S.pending(s)
    computed = [r for r in rows if r.get("rank") is not None]  # ranked items (rank 1 may have no amount: a hold)
    other = [r for r in rows if r.get("rank") is None]
    ui.head(
        f"{tx.term('판단 목록', '사람 판단 필요')}",
        f"주당 영향 큰 순(자동 초안 기준 영향) · 전체 {len(rows)}건",
        ui.badge(f"미처리 {n}건", "warn" if n else "ok"),
    )
    flash = st.session_state.pop("judge_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])
    pre = "c" if compact else "f"
    show_all = st.toggle("확인형 항목까지 모두 보기", key=f"j_all_{pre}", value=False)
    items = computed + (
        other if show_all else [r for r in other if r["status"] != "미처리" or r["category"] in ("SOTP 가드", "피어 직접 지정")]
    )
    top, rest = items[:TOP_N], items[TOP_N:]  # P7-C3 polish long_list: the top 5 open, the rest folded
    for r in top:
        _item(c, r, compact)
    if rest:
        pend = [r["id"] for r in rest if r["status"] == "미처리"]
        a, b = st.columns([3, 2])
        more = a.toggle(f"나머지 {len(rest)}건 보기(영향 작은 항목)", key=f"j_more_{pre}", value=False)
        if pend:
            b.button(
                f"영향 작은 항목 {len(pend)}건 한 번에 그대로 유지",
                key=f"j_keepall_{pre}",
                on_click=_keep_rest,
                args=(c.sid, pend),
                help="자동값을 그대로 둡니다. 감사 기록에는 항목마다 한 줄씩 남습니다",
                width="stretch",
            )
        if more:
            for r in rest:
                _item(c, r, compact)
    if not show_all and len(other):
        st.markdown(
            f"<p class='wb-kpi-note'>주당 영향을 계산할 수 없는 확인형 항목 {len(other)}건은 위 스위치로 봅니다"
            "(D&A 추정·우선주·보고서 사람 작성 칸 등).</p>",
            unsafe_allow_html=True,
        )


TOP_N = 5


def _keep_rest(sid: str, ids: list[str]) -> None:
    s = M.load(sid)
    n = M.keep_many(s, ids, "영향 작은 항목 일괄 확인(그대로 유지)")
    st.session_state["judge_flash"] = (True, f"영향 작은 항목 {n}건을 그대로 유지했습니다(항목별 감사 기록).")


def _item(c: nav.Ctx, r: dict, compact: bool) -> None:
    if c.mode == "public":  # market-derived amounts in the auto texts are not shown
        r = {**r, **{k: tx.public_mask(r.get(k)) for k in ("item", "detail", "alternative")}}
    r = {**r, **{k: tx.plain_words(r.get(k)) for k in ("category", "item", "detail", "alternative")}}  # P7-C3 plain words
    jid = r["id"]
    pre = "c" if compact else "f"
    imp = r.get("impact")
    st_ = r["status"]
    ba = ""
    if r.get("changed_v") is not None:
        b, a = _ps(c, r["changed_v"] - 1), _ps(c, r["changed_v"])
        ba = f" · 주당 {F.won(b)} → {F.won(a)}"
    title = (
        f"{r.get('rank') or '·'}. [{r['category']}] {str(r['item'])[:70]} — 영향 "
        f"{F.won(imp, sign=True) + '(자동 진단 대안 기준)' if imp is not None else '계산 안 함'} · {st_}{ba}"
    )
    with st.expander(title, expanded=(not compact and st_ == "미처리" and (r.get("rank") or 99) <= 3)):
        st.markdown(
            f"{ui.badge(st_, STATUS_CLS.get(st_, ''))} <span class='wb-kpi-note'>{ui.esc(r.get('detail') or '')[:400]}</span>",
            unsafe_allow_html=True,
        )
        if r.get("alternative"):
            st.markdown(f"<p class='wb-kpi-note'>자동 진단의 대안: {ui.esc(r['alternative'])}</p>", unsafe_allow_html=True)
        if r.get("resolution"):
            res = r["resolution"]
            st.markdown(
                f"<p class='wb-kpi-note'>처리: {ui.esc(res.get('action'))} · v{res.get('v')} · 이유: {ui.esc(res.get('reason') or '(없음)')}</p>",
                unsafe_allow_html=True,
            )
        st.text_input("이유(선택)", key=f"jr_{pre}_{jid}", placeholder="예: 주석 확인 결과 일회성 손익")
        cands = r.get("candidates") or []
        if cands:
            st.markdown(
                "<p class='wb-kpi-note' style='margin-bottom:4px'>후보 값(누르면 바로 반영 · 버튼마다 '지금 주당 → 반영 뒤 주당')</p>",
                unsafe_allow_html=True,
            )
            cols = st.columns(min(len(cands), 3))
            for i, cd in enumerate(cands):
                val = M.spec.fmt(cd["field"], cd["value"]) if cd["field"] != "peers" else f"{len(cd['value'])}곳"
                pv = M.candidate_preview(c.o, c.s, c.mode, cd["field"], cd["value"])  # P7-C3 polish candidate_preview
                prev = (
                    f"주당 {F.won(pv['before'])} → {F.won(pv['after'])}"
                    if pv.get("after") is not None
                    else (pv.get("error") or "계산 불가")
                )
                cols[i % len(cols)].button(
                    f"{tx.plain_words(cd['label'])} ({val}) · {prev}",
                    key=f"jc_{pre}_{jid}_{i}",
                    on_click=_do,
                    args=(c.sid, jid, "candidate"),
                    kwargs={"candidate": i, "rkey": f"jr_{pre}_{jid}"},
                    width="stretch",
                    disabled=pv.get("after") is None and "시세 입력" not in str(pv.get("error")),
                )
        fields = r.get("direct_fields") or []
        if fields:
            a, b, d = st.columns([2, 2, 1])
            fld = a.selectbox("직접 입력할 가정", fields, format_func=lambda f: M.spec.LABEL[f], key=f"jf_{pre}_{jid}")
            if fld == "peers":
                names = c.o.ctx.peers_all()
                b.multiselect("피어", names, default=M.current_value(c.o, c.s, "peers"), key=f"jv_{pre}_{jid}")
            elif fld == "premium":
                b.selectbox("지분 구간", ["lt25", "25to50", "gt50"], key=f"jv_{pre}_{jid}")
            else:
                unit = " (%)" if fld in FD.PCT_FIELDS else (" (백만원)" if fld.endswith("_mn") else "")
                b.text_input(f"값{unit}", value=FD.to_text(fld, M.current_value(c.o, c.s, fld)), key=f"jv_{pre}_{jid}")
            d.button(
                "적용",
                key=f"jd_{pre}_{jid}",
                on_click=_do,
                args=(c.sid, jid, "direct"),
                kwargs={"fkey": f"jf_{pre}_{jid}", "vkey": f"jv_{pre}_{jid}", "rkey": f"jr_{pre}_{jid}"},
                width="stretch",
            )
        st.button(
            "그대로 유지(자동값 확인)",
            key=f"jk_{pre}_{jid}",
            on_click=_do,
            args=(c.sid, jid, "keep"),
            kwargs={"rkey": f"jr_{pre}_{jid}"},
        )


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
        kw.update({"field": fld, "value": raw if fld in ("peers", "premium") else FD.parse(fld, raw)})
    item = s["judgements"][jid]["item"]
    r = M.resolve(s, jid, action, **kw)
    if r["ok"]:
        msg = f"'{str(item)[:40]}' 처리: {s['judgements'][jid]['status']}"
        if action != "keep":
            msg += f" → v{M.version(s)['v']}"
            if st.query_params.get("m", "pc") == "pc":  # public mode: the per-share shown is the public recalculation
                msg += f" 주당 {F.won((r.get('result') or {}).get('per_share'))}"
        st.session_state["judge_flash"] = (True, msg + (f" (주의: {r['reason']})" if r.get("reason") else ""))
    else:
        st.session_state["judge_flash"] = (False, f"반영 안 됨: {r['reason']}")
