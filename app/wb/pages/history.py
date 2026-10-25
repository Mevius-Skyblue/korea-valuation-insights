"""이력 (top button, P7-U1): versions, change log, version compare, revert (with a reason; a new version, nothing is
deleted), the auto-hold record, and the checks: filing reconciliation (with the mismatch list), peer selection,
eligibility, model consistency (Excel <-> engine), automatic corrections and the credit rating / Kd."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav, shell
from app.wb import text as tx


def render(c: nav.Ctx) -> None:
    with ui.card("versions"):
        versions(c)
    with ui.card("audit"):
        audit(c)
    st_ = M.status(c.o, c.s)
    if st_["hold"]:
        with ui.card("hold_record"):
            ui.h2("자동 결과 보류 기록")
            st.markdown(
                "<p class='wb-kpi-note'>"
                + ui.esc("; ".join(tx.plain_words(x) for x in st_["headline"].get("reasons") or []))
                + (
                    " — 확정 버전의 값이 대표값(보류 사유는 기록으로 남김)"
                    if st_["label"] == "확정"
                    else " — 확정 전까지 대표값 보류"
                )
                + "</p>",
                unsafe_allow_html=True,
            )
    with ui.card("checks"):
        checks(c)


def versions(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    vt = M.versions_table(o, s, c.mode)
    reasons = {}
    for a in s["audit"]:
        if a.get("field"):
            reasons.setdefault(a["v"], a.get("reason") or "")
    head = ["버전", "시각", "주당가치", "변경", "이유"]
    rows = [
        {
            "c": [
                f"v{x['v']}" + (f" (v{x['reverted_to']}로 되돌림)" if x.get("reverted_to") is not None else ""),
                x["created"][5:16],
                F.won0(x["per_share"]),
                tx.plain_words(x["change"])[:80],
                reasons.get(x["v"], "—") or "—",
            ],
            "strong": x["v"] == vt[-1]["v"],
        }
        for x in reversed(vt)
    ]
    ui.title_copy("버전 · 감사 기록", "변경 1건 = 새 버전 · 기록은 지우지 않음", "", ui.tsv(head, rows))
    ui.tbl(head, rows, left=(0, 3, 4), tips=False, min_width=600)
    a, b = st.columns(2, gap="medium")
    with a, st.expander("버전 비교"):
        vs = [x["v"] for x in s["versions"]]
        x1, x2 = st.columns(2)
        va = x1.selectbox("버전 A", vs, index=0, key="cmp_a", format_func=lambda v: f"v{v}")
        vb = x2.selectbox("버전 B", vs, index=len(vs) - 1, key="cmp_b", format_func=lambda v: f"v{v}")
        diff = M.compare(s, va, vb)
        pa = next(x["per_share"] for x in vt if x["v"] == va)
        pb = next(x["per_share"] for x in vt if x["v"] == vb)
        st.markdown(
            f"<p style='font-size:14px'>주당 v{va} {F.won0(pa)} → v{vb} {F.won0(pb)}원 ({F.signed((pb - pa) if F.ok(pa) and F.ok(pb) else None)})</p>",
            unsafe_allow_html=True,
        )
        if diff:
            ui.tbl(["가정", f"v{va}", f"v{vb}"], [[tx.plain_words(d["field"]), d["a"], d["b"]] for d in diff], tips=False)
        else:
            st.markdown("<p class='wb-kpi-note'>두 버전의 가정이 같습니다.</p>", unsafe_allow_html=True)
    with b, st.expander("되돌리기"):
        vs = [x["v"] for x in s["versions"]][:-1]
        if not vs:
            st.markdown("<p class='wb-kpi-note'>되돌릴 이전 버전이 없습니다.</p>", unsafe_allow_html=True)
        else:
            tv = st.selectbox("되돌릴 버전", vs, index=len(vs) - 1, key="rev_v", format_func=lambda v: f"v{v}")
            why = st.text_input("이유", key="rev_why", placeholder="[되돌리는 이유]")
            if st.button(f"v{tv}의 가정으로 새 버전 만들기", key="rev_go"):
                s2 = M.load(c.sid)
                shell.note_change(s2, f"v{tv}로 되돌림")
                rr = M.revert(s2, tv, why or None)
                if rr["ok"]:
                    st.rerun()
                else:
                    st.session_state.pop("toast_from", None)
                    st.error(rr["reason"])


def audit(c: nav.Ctx) -> None:
    s = c.s
    head = ["시각", "버전", "항목", "전 → 후", "이유", "판단 항목"]
    rows = []
    for a in reversed(s["audit"]):
        j = (s.get("judgements") or {}).get(a.get("judgement") or "", {})
        rows.append(
            [
                a["at"].replace("T", " ")[5:16],
                f"v{a['v']}",
                tx.plain_words(a["label"]),
                f"{a.get('before_text', '')} → {a.get('after_text', '')}" if (a.get("field") or a.get("after_text")) else "",
                a.get("reason") or "",
                tx.plain_words(str(j.get("item") or ""))[:30],
            ]
        )
    ui.title_copy("변경 기록", "항목별", "", ui.tsv(head, rows) if rows else None)
    if rows:
        ui.tbl(head, rows, left=(0, 2, 3, 4, 5), tips=False, min_width=680)
    else:
        st.markdown("<p class='wb-kpi-note'>아직 변경이 없습니다(v0 = 자동 초안).</p>", unsafe_allow_html=True)


def checks(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    ui.h2("검증")
    f = M.data_facts(o)
    rec = f["recon"] or {}
    cnt = rec.get("counts") or {}
    yrs = rec.get("years") or []
    with st.expander(f"공시 대사 · {cnt.get('exact', 0)}/{rec.get('rows', 0)} 일치"):
        st.markdown(
            f"<p class='wb-kpi-note'>{'FY' + str(yrs[0]) + '~' + str(yrs[-1]) if yrs else ''} · 원 단위 · 매출·영업이익 등 공시 원문 대조</p>",
            unsafe_allow_html=True,
        )
        bad = rec.get("bad") or []
        if bad:
            ui.tbl(["불일치"], [[str(x)[:120]] for x in bad], tips=False)
    rows = M.peer_rows(o, s, c.mode)
    ps = o.summ.get("peer_screen") or o.cfg.get("peer_screen") or {}
    lv = (ps.get("levels") or [{}])[-1] if ps.get("levels") else {}
    with st.expander(
        f"유사기업 선정 · {sum(r['include'] for r in rows)}개사 · KSIC {lv.get('ksic') or o.cfg['target'].get('induty_code', '')}"
    ):
        st.markdown(
            f"<p class='wb-kpi-note'>같은 업종(KSIC)·시가총액 범위·3년 흑자 · 후보 {lv.get('candidates', '—')} → 통과 {lv.get('pass', '—')}"
            f" · 완화 단계 {ps.get('relax_step') if ps.get('relax_step') else '없음'}</p>",
            unsafe_allow_html=True,
        )
    gv = M.gate_view(o.summ)
    with st.expander(f"평가 적격성 · {'통과' if gv['passed'] else '범위 밖'} · {tx.plain_words(gv['path'])}"):
        ui.tbl(
            ["항목", "결과", "값·경로"],
            [
                [
                    shell.GATE_LABEL.get(r["id"], r["label"]),
                    {"✓": "통과", "✗": "걸림", "→": "경로", "확인 전": "확인 전"}[r["status"]],
                    tx.plain_words(r["value"]),
                ]
                for r in gv["rows"]
            ],
            left=(0, 1, 2),
            tips=False,
        )
    last = next((x for x in reversed(s.get("confirmations") or []) if x.get("mode") == c.mode), None)
    with st.expander(f"모델 정합성 (엑셀 ↔ 엔진) · {((last or {}).get('reconcile') or {}).get('status') or '확정 전'}"):
        st.markdown(
            "<p class='wb-kpi-note'>확정하면 엑셀 수식으로 다시 계산한 값과 엔진 값을 비교합니다(시나리오 × SRP 조합 전체)."
            + (f" 마지막 확정 v{last.get('v')} · 엑셀 {last.get('excel_seconds') or 0:.1f}초" if last else "")
            + "</p>",
            unsafe_allow_html=True,
        )
    cr = M.corrections(o)
    est = [d for d in cr["dna"] if d.get("estimated")]
    n_cr = len(cr["debt_reclass"]) + len(est) + len(cr["basis_fill"]) + (1 if cr["shares_note"] else 0)
    with st.expander(
        f"자동 보정·추정 기록 · {n_cr}건" if n_cr else f"자동 보정·추정 기록 · D&A {len(cr['dna'])}개 기간 원문/XBRL"
    ):
        rws = []
        for x in cr["debt_reclass"]:
            rws.append(
                ["계정 오표기 수정", f"{x.get('year', '')} {x.get('period', '')}", str(x.get("label") or x.get("name") or x)[:80]]
            )
        for d in est:
            rws.append(["D&A 추정", f"{d['year']} {d['period']}", f"{d.get('source', '')} {F.mn_eok(d.get('total'))}"])
        src = sorted({d.get("source", "") for d in cr["dna"]})
        if cr["dna"] and not est:
            rws.append(["D&A 출처", f"{len(cr['dna'])}개 기간", ", ".join(src) + " (추정 없음)"])
        for y, p, other in cr["basis_fill"]:
            rws.append(["재무 기준 혼합", f"{y} {p}", f"{other} 값으로 채움"])
        if cr["shares_note"]:
            n = cr["shares_note"]
            rws.append(["주식 수 사건", "기준일", f"보고서 발행 {n['report_issued']:,}주 → 기준일 상장 {n['asof_listed']:,}주"])
        if rws:
            ui.tbl(["종류", "기간", "내용"], rws, left=(0, 1, 2), tips=False)
        else:
            st.markdown("<p class='wb-kpi-note'>오표기 수정·D&A 추정·재무 기준 혼합 없음</p>", unsafe_allow_html=True)
    kd = f["kd"]
    with st.expander(f"신용등급 · 타인자본비용 (Kd) · {kd.get('rating') or '등급 미확인'}"):
        st.markdown(
            f"<p class='wb-kpi-note'>{ui.esc(tx.plain_words(kd.get('basis') or kd.get('rating_source') or 'OpenDART 등급 정보 없음 → 이자비용 ÷ 평균 차입금(하한 Rf)'))} · 가정·판단 탭에서 등급 금리로 변경</p>",
            unsafe_allow_html=True,
        )
