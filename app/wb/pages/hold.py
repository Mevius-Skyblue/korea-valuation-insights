"""평가 보류 (Hold, P7-U1 Hold.dc.html): shown in the summary tab when the auto draft held its headline value and the
current version is not confirmed. One reason sentence, the checks to do first, a value input -> recalculation (the top
judgement's own fields / candidates), and the pre-hold values folded. The hold rule is unchanged: the value becomes the
representative value when the person confirms."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx
from app.wb.pages import assume_tab as AT


def render(c: nav.Ctx, st_: dict) -> None:
    o, s = c.o, c.s
    hl = dict(st_["headline"])
    reasons = [tx.plain_words(x) for x in hl.get("reasons") or []]
    top = {k: tx.plain_words(v) if isinstance(v, str) else v for k, v in (hl.get("top_judgement") or {}).items()}
    if c.mode == "public":
        reasons = [tx.public_mask(x) for x in reasons]
        top = {k: tx.public_mask(v) if isinstance(v, str) else v for k, v in top.items()}
    rc = (M.rcepts(str((o.summ.get("facts") or {}).get("structure_source", ""))) or [""])[0]
    st.markdown(
        "<div class='wb-hold'>"
        f"{ui.badge('평가 보류 (Hold)', 'warn')} <span class='wb-kpi-note'>확인 전까지 대표값 미표시</span>"
        f"<h1>{ui.esc('; '.join(reasons) or '자동 결과 보류')}</h1>"
        f"<p class='wb-kpi-note'>{ui.esc(str(top.get('category') or ''))} · {ui.esc(str(top.get('item') or ''))}</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    a, b, d = st.columns(3, gap="medium")
    with a, ui.card("hold_do1"):
        st.markdown("<span class='wb-kpi-note'>먼저 할 일 1</span>", unsafe_allow_html=True)
        st.markdown(
            f"<p style='font-weight:600'>{ui.esc(str(top.get('alternative') or top.get('item') or '원문 확인'))}</p>",
            unsafe_allow_html=True,
        )
        if rc:
            st.markdown(tx.dart_link(rc, "공시 원문 열기"), unsafe_allow_html=True)
    with b, ui.card("hold_do2"):
        st.markdown("<span class='wb-kpi-note'>먼저 할 일 2</span>", unsafe_allow_html=True)
        st.markdown("<p style='font-weight:600'>기준일 전 주식 수 변동(병합·분할·증자) 공시 확인</p>", unsafe_allow_html=True)
        st.button("공시·이벤트 탭 →", key="hold_events", type="tertiary", on_click=nav.go, args=("events",))
    with d, ui.card("hold_do3"):
        st.markdown("<span class='wb-kpi-note'>확인한 값 입력 → 다시 계산</span>", unsafe_allow_html=True)
        row = next((r for r in AT.visible_rows(s) if r.get("rank") == 1), None)
        if row and (row.get("candidates") or row.get("direct_fields")):
            AT._item(c, row)
        else:
            st.markdown(
                "<p class='wb-kpi-note'>이 보류는 값 하나로 풀리지 않습니다(구조 확인). 확인 뒤 판단 목록에서 처리하고 확정하면 확정값이 대표값이 됩니다.</p>",
                unsafe_allow_html=True,
            )
            st.button("가정·판단 탭 →", key="hold_assume", type="tertiary", on_click=nav.go, args=("assume",))
    r = M.result(o, s, c.mode)
    d_ = o.summ.get("diagnostics") or {}
    comp = d_.get("composition_share") or {}
    with ui.card("hold_pre"):
        with st.expander("참고: 보류 전 계산값 (대표값·엑셀 표지에 미사용)"):
            ui.lines(
                [
                    (
                        "주당가치 (계산값)",
                        F.won0(r.get("per_share")) + "원"
                        if F.ok(r.get("per_share"))
                        else tx.plain_words(r.get("error") or "계산 불가"),
                    ),
                    (
                        "시나리오 Bear ~ Bull",
                        f"{F.won0((r.get('scenarios') or {}).get('pessimistic'))} ~ {F.won0((r.get('scenarios') or {}).get('optimistic'))}",
                    ),
                    ("WACC · 영구가치 비중 (TV)", f"{F.p1(r.get('wacc'), 2)} · {F.p1(r.get('tv_share'))}"),
                ]
                + [
                    (f"원인 분해 · {lab}", F.p1(comp[k]))
                    for k, lab in (
                        ("explicit", "예측 기간 가치"),
                        ("tv", "영구가치"),
                        ("cash_like", "현금성"),
                        ("non_operating", "비영업자산"),
                        ("debt", "차입금"),
                        ("nci", "비지배지분"),
                    )
                    if comp.get(k) is not None
                ]
            )
            rev = d_.get("reverse") or {}
            if rev.get("target"):

                def rv(x):
                    return F.p1(x, 2) if F.ok(x) else "이 값만 바꿔서는 맞출 수 없음"

                st.markdown(
                    f"<p class='wb-kpi-note'>Peer 중앙값({ui.esc(tx.plain_words(rev.get('basis')))}) 주당 {F.won0(rev['target'])}원을 맞추려면: 정상 이익률 {rv(rev.get('margin'))}"
                    f" · 출발 성장률 {rv(rev.get('start_growth'))} · WACC {rv(rev.get('wacc'))}</p>",
                    unsafe_allow_html=True,
                )
