"""재무 tab (P7-U1): only the metrics the valuation uses (FY 5 years + LTM) and the data checks (zero receivables /
payables, reconciliation, automatic corrections)."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import values as V


def render(c: nav.Ctx) -> None:
    with ui.card("fin"):
        table(c)


def table(c: nav.Ctx) -> None:
    o, s, mn = c.o, c.s, c.mn
    f = V.fin_table(o, s, c.mode)
    ys = f["years"]
    col = f["cols"]
    head = [F.unit(mn)] + [f"FY{y}" for y in ys] + ["LTM"]

    def amt(k):
        return [F.amt(col[y][k], mn) for y in ys]

    def pct(k):
        return [F.p1(col[y][k], paren=True) for y in ys]

    def days(k):
        return [f"{col[y][k]:.0f}일" if F.ok(col[y][k]) else "—" for y in ys]

    rc = [
        f"{col[y]['dso']:.0f} · {col[y]['dpo']:.0f}일" + (" ⚠" if col[y]["rec"] == 0 and col[y]["pay"] == 0 else "") for y in ys
    ]
    lt = f["ltm"]
    rows = [
        {"c": ["매출", *amt("revenue"), F.amt(lt["revenue"], mn)], "strong": True},
        ["매출 성장률", *pct("growth"), ""],
        {"c": ["영업이익", *amt("op"), F.amt(lt["op"], mn)], "strong": True},
        ["영업이익률", *pct("margin"), F.p1(lt["margin"], paren=True)],
        ["EBITDA 이익률", *pct("ebitda_margin"), ""],
        ["ROE", *pct("roe"), ""],
        {"c": ["CAPEX ÷ 매출", *pct("capex_ratio"), ""], "top": True},
        ["D&A ÷ 매출", *pct("dna_ratio"), ""],
        ["재고자산 회전일수", *days("dio"), ""],
        [("매출채권·매입채무 회전일수", "DSO = 매출채권 ÷ 매출 × 365 · DPO = 매입채무 ÷ 매출원가 × 365"), *rc, ""],
        {"c": [f"순현금 ({f['bs_date'][5:].replace('-', '/')})", *[""] * len(ys), F.amt(lt["net_cash"], mn)], "top": True},
        ["차입금 (리스 포함)", *amt("debt"), F.amt(lt["debt"], mn)],
    ]
    ui.title_copy("주요 재무지표", "", ui.esc(f"{f['fs']} · {F.unit(mn)} · DART 정기보고서 · 엑셀 FS_Hist"), ui.tsv(head, rows))
    ui.tbl(head, rows, shade=(len(head) - 1,), min_width=720)
    warns = []
    if f["zero_rec"] or f["zero_pay"]:
        what = "·".join(x for x, z in (("매출채권", f["zero_rec"]), ("매입채무", f["zero_pay"])) if z)
        warns.append(f"{what} 전 기간 0 — 원문 확인(데이터 점검 D-1)")
    rec = (o.summ.get("checks") or {}).get("S4_recon") or {}
    bad = len(rec.get("bad") or [])
    if bad:
        warns.append(f"공시 대사 불일치 {bad}건 — 이력 > 검증")
    cr = M.corrections(o)
    est = [d for d in cr["dna"] if d.get("estimated")]
    if cr["debt_reclass"] or est or cr["basis_fill"]:
        warns.append(
            f"자동 보정·추정 {len(cr['debt_reclass']) + len(est) + len(cr['basis_fill'])}건 — 이력 > 검증 > 자동 보정·추정 기록"
        )
    if warns:
        st.markdown(
            "<div style='font-size:14px;color:#7C2D12;padding:10px 12px;background:#FFF1E6;border-radius:8px'><span style='font-weight:600'>데이터 검증</span> "
            + " · ".join(ui.esc(w) for w in warns)
            + "</div>",
            unsafe_allow_html=True,
        )
