"""P7-U2 Valuation Summary PDF (config/p7u2.yaml summary_pdf): one A4 page from the numbers the work screen shows.

Content: company · valuation date · draft mark, the six KPI values (Base), the football field (same rows as the summary tab),
the top-5 judgement items with their status, the WACC × g sensitivity (3 × 3 around the base), sources and the disclaimer.
Drawn with matplotlib (already a requirement) and the Pretendard TrueType subset in app/static (SIL OFL, Type 42 embedded).
Public mode = the values of the public screen (the user's prices); no other market value goes in.

    build(o, s, mode) -> (pdf bytes, text lines)   the lines are every string on the page (tests and the bundle check)
"""

from __future__ import annotations

import io
from pathlib import Path

import streamlit as st

from app.wb import fmt as F
from app.wb import model as M
from app.wb import text as T_

STATIC = Path(__file__).resolve().parents[1] / "static"
DISCLAIMER = "가정 하의 추정 내재가치(예시) · 투자 권유 아님 · 자동 생성 초안 — 평가방법 선택 근거, 주요 가정의 합리성, 평가상 한계는 평가자가 작성"


def _fonts():
    from matplotlib.font_manager import FontProperties

    return (
        FontProperties(fname=str(STATIC / "Pretendard-Regular.subset.ttf")),
        FontProperties(fname=str(STATIC / "Pretendard-SemiBold.subset.ttf")),
    )


def content(o, s, mode: str) -> dict:
    """Every value on the page (Base scenario), from the screen's own functions."""
    from app.wb import values as V

    k = V.kpi(o, s, mode, "base")
    r, mk = k["r"], k["mk"]
    br = k.get("bridge") or {}
    d = V.dcf_detail(o, s, mode)
    ff = V.football(o, s, mode, "base")
    st_ = M.status(o, s)
    hold = st_["hold"] and st_["label"] != "확정"
    g = d["tv"]["g"] if not d.get("error") else None
    ver = M.version(s)
    rows = sorted((x for x in M.judgement_rows(s) if x.get("rank") is not None), key=lambda x: x["rank"])[:5]
    grid = None
    if not d.get("error"):
        gd = d["grids"]
        gi = next((i for i, x in enumerate(gd["g_values"]) if abs(x - g) < 1e-9), None)
        wj = next((j for j, x in enumerate(gd["wacc_steps"]) if abs(x) < 1e-12), None)
        if gi is not None and wj is not None:
            ii = [i for i in (gi - 1, gi, gi + 1) if 0 <= i < len(gd["g_values"])]
            jj = [j for j in (wj - 1, wj, wj + 1) if 0 <= j < len(gd["wacc_steps"])]
            grid = {
                "cols": [F.p1(gd["wacc0"] + gd["wacc_steps"][j]) for j in jj],
                "rows": [F.p1(gd["g_values"][i]) for i in ii],
                "vals": [[gd["wacc_g"][i][j] for j in jj] for i in ii],
                "center": (ii.index(gi), jj.index(wj)),
            }
    cfg = o.cfg
    price_src = (
        "사용자 입력 시세" + (" (예시 입력 — 실제 종가 아님)" if ff.get("example") else "")
        if mode == "public"
        else "한국거래소 통계정보"
    )
    return {
        "name": cfg["target"]["name"],
        "code": cfg["target"].get("stock_code") or s["code"],
        "market": cfg["target"].get("market", ""),
        "as_of": cfg["meta"]["as_of"],
        "bs_date": cfg["meta"]["bs_date"],
        "version": ver["v"],
        "status": st_["label"],
        "hold": hold,
        "kpi": [
            ("주당가치 (DCF · Base)", "Hold" if hold else F.won0(r.get("per_share")) + "원"),
            ("기업가치 (EV)", "—" if hold else F.amt(r.get("ev")) + "억원"),
            ("주주가치 (Equity)", "—" if hold else F.amt(r.get("equity")) + "억원"),
            (
                "주가 (" + ("입력" if mode == "public" else "기준일") + ")",
                F.won0(mk.get("close")) + "원" if F.ok(mk.get("close")) else "—",
            ),
            ("WACC / g", f"{F.p1(r.get('wacc'))} / {F.p1(g)}"),
            ("영구가치 비중 (TV / EV)", F.p1(r.get("tv_share"), 0)),
        ],
        "net_cash": (br.get("cash_like") or 0) - (br.get("total_debt") or 0) if br else None,
        "football": ff,
        "judgements": [
            (
                T_.plain_words(x.get("category") or ""),
                T_.plain_words(str(x.get("item") or ""))[:40],
                x.get("status") or "",
                x.get("impact"),
            )
            for x in rows
        ],
        "grid": grid,
        "sources": [
            "재무: DART 정기보고서(접수번호는 엑셀 FS_Hist 출처 칸) · 재무상태표 " + cfg["meta"]["bs_date"],
            "금리: 한국은행 ECOS 국고채·회사채 · MRP 한공회 가이던스",
            "시세: " + price_src,
            f"세션 v{ver['v']} · 엔진 = 작업 화면과 같은 계산",
        ],
    }


def build(o, s, mode: str) -> tuple[bytes, list[str]]:
    """One A4 page; returns the PDF bytes and every text line drawn (in order)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matplotlib.rcParams["pdf.fonttype"] = 42
    fr, fb = _fonts()
    c = content(o, s, mode)
    lines: list[str] = []
    fig = plt.figure(figsize=(8.27, 11.69))

    def tx(x, y, text, size=9, bold=False, color="#15171B", ha="left"):
        lines.append(str(text))
        fig.text(x, y, str(text), fontproperties=fb if bold else fr, fontsize=size, color=color, ha=ha, va="top")

    tx(0.06, 0.965, f"{c['name']} ({c['code']}) · Valuation Summary", 15, True)
    tx(
        0.06,
        0.935,
        f"평가기준일 {c['as_of']} · 재무 {c['bs_date']} · {c['market']} · 세션 v{c['version']} · {c['status']}",
        9,
        color="#5A5E66",
    )
    tx(0.94, 0.965, "자동 생성 초안", 9, True, "#9A3412", "right")
    # KPI
    for i, (k, v) in enumerate(c["kpi"]):
        x = 0.06 + (i % 3) * 0.30
        y = 0.895 - (i // 3) * 0.06
        tx(x, y, k, 8, color="#5A5E66")
        tx(x, y - 0.018, v, 13, True)
    # football field
    tx(0.06, 0.76, "평가방법별 주당가치 (Football Field)", 11, True)
    ff = c["football"]
    rows = [x for x in ff["rows"] if F.ok(x.get("lo")) and F.ok(x.get("hi"))]
    ax = fig.add_axes([0.24, 0.56, 0.68, 0.18])
    lab = []
    for j, x in enumerate(rows):
        ax.barh(j, x["hi"] - x["lo"], left=x["lo"], height=0.5, color="#F7C9A6" if x["kind"] == "dcf" else "#D9DAD6")
        if F.ok(x.get("rep")):
            ax.plot([x["rep"], x["rep"]], [j - 0.3, j + 0.3], color="#15171B", lw=1.2)
        lab.append(f"{x['label']} · {x['sub']}")
        lines.append(f"{x['label']} {F.won0(x['lo'])} ~ {F.won0(x['hi'])}")
    if F.ok(ff.get("price")):
        ax.axvline(ff["price"], color="#C2410C", lw=1, ls="--")
        lines.append(f"주가 {F.won0(ff['price'])}")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(lab, fontproperties=fr, fontsize=8)
    ax.invert_yaxis()
    for t in ax.get_xticklabels():
        t.set_fontproperties(fr)
        t.set_fontsize(7)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    tx(
        0.24,
        0.527,
        "막대 = 범위(DCF Bear~Bull, Peer 1~3사분위, 경영권 거래 블록), 세로선 = 대표값, 점선 = 주가("
        + ("입력" if mode == "public" else "기준일")
        + ")",
        7,
        color="#5A5E66",
    )
    # judgements
    tx(0.06, 0.505, "주요 판단 (영향 순 상위 5)", 11, True)
    y = 0.48
    for cat, item, status, imp in c["judgements"] or [("", "판단 항목 없음", "", None)]:
        tx(0.06, y, cat, 8, color="#5A5E66")
        tx(0.22, y, item, 8)
        tx(0.74, y, status, 8)
        tx(0.94, y, F.signed(imp) + "원" if F.ok(imp) else "—", 8, ha="right")
        y -= 0.022
    # sensitivity
    tx(0.06, 0.37, "민감도 · WACC × 영구성장률 (주당, 원)", 11, True)
    gr = c["grid"]
    if gr:
        tx(0.06, 0.345, "g \\ WACC", 8, color="#5A5E66")
        for j, h in enumerate(gr["cols"]):
            tx(0.30 + j * 0.16, 0.345, h, 8, color="#5A5E66", ha="right")
        for i, (rl, rv) in enumerate(zip(gr["rows"], gr["vals"])):
            yy = 0.322 - i * 0.022
            tx(0.06, yy, rl, 8)
            for j, v in enumerate(rv):
                tx(0.30 + j * 0.16, yy, F.won0(v) if F.ok(v) else "계산 불가", 8, (i, j) == gr["center"], ha="right")
    else:
        tx(0.06, 0.345, "계산 불가", 8, color="#5A5E66")
    # sources and disclaimer
    tx(0.06, 0.235, "출처", 11, True)
    for i, src in enumerate(c["sources"]):
        tx(0.06, 0.21 - i * 0.02, src, 8, color="#5A5E66")
    tx(0.06, 0.10, DISCLAIMER, 7.5, color="#9A3412")
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="pdf",
        metadata={
            "Title": None,
            "Author": None,
            "Subject": None,
            "Keywords": None,
            "Creator": None,
            "Producer": None,
            "CreationDate": None,
        },
    )
    plt.close(fig)
    return buf.getvalue(), lines


def button(c, where: str) -> None:
    """[Summary PDF 만들기] -> download button for the current version (made on request; ~1 s)."""
    if not c.s or not c.o:
        return
    key = ("summary_pdf", c.sid, M.version(c.s)["v"], c.mode, M.ukey(c.s) if c.mode == "public" else "")
    have = st.session_state.get("_pdf") if st.session_state.get("_pdf_key") == key else None
    if have is None:
        if st.button("Summary PDF (1쪽) 만들기", key=f"pdf_make_{where}", width="stretch"):
            try:
                data, _ = build(c.o, c.s, c.mode)
                st.session_state["_pdf"], st.session_state["_pdf_key"] = data, key
                have = data
            except M.NeedInput:
                st.info("공개 모드: 시세를 입력하면 만들 수 있습니다")
            except Exception as e:  # noqa: BLE001 - shown instead of a stack trace
                st.error(f"Summary PDF를 만들지 못했습니다: {type(e).__name__}")
    if have is not None:
        st.download_button(
            "Summary PDF 내려받기 (.pdf)",
            data=have,
            file_name=f"{c.s['code']}_summary_v{M.version(c.s)['v']}.pdf",
            mime="application/pdf",
            key=f"pdf_dl_{where}",
            width="stretch",
        )
