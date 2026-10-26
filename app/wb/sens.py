"""P7-U2 clickable sensitivity tables (config/p7u2.yaml sensitivity): DCF tab WACC × g and growth × margin.

Click a cell -> one line under the table: the combination -> per share (the engine grid value), Δ to now, [가정에 적용] [✕].
[가정에 적용] carries the combination to the top of the 가정·판단 tab (apply_line): reason box, [반영] / [취소]. Nothing
changes before [반영]; 반영 = the session's own assumption changes (a new version and an audit line per field).

    WACC × g      g -> g_terminal; a WACC step dw -> SRP + dw ÷ (1 − Wd) (WACC is linear in SRP), only inside the SRP range
    growth × mar  출발 성장률 = now + growth step, 정상 이익률 = now + margin step (the shifts the grid used)
The value after 반영 is computed with the same recalc as the session (it can differ from the grid for g, because the
terminal growth also ends the forecast's growth path - the line says so).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx

PENDING = "sens_apply"


def _fields(kind: str, d: dict, i: int, j: int) -> tuple[dict, str, str]:
    """({field: value}, label, why-not) of a grid cell."""
    g = d["grids"]
    if kind == "wg":
        gv, dw = g["g_values"][i], g["wacc_steps"][j]
        out = {"g_terminal": float(gv)}
        why = ""
        lab = f"g {F.p1(gv)} · WACC {F.p1(g['wacc0'] + dw)}"
        if abs(dw) > 1e-12:
            wd = float(d["wacc"].get("wd") or 0.0)
            srp = float(d["wacc"]["srp"]) + dw / (1 - wd)
            ok, msg, _v = M.spec.check("srp", srp)
            if ok:
                out["srp"] = srp
            else:
                why = f"WACC 이동을 SRP로 옮기면 {F.p1(srp, 2)} — {tx.plain_words(msg)}"
        return out, lab, why
    gs, ms = g["growth_shifts"][i], g["margin_shifts"][j]
    dr = d["drivers"]
    out = {}
    if abs(gs) > 1e-12:
        out["g_start"] = float(dr["g0"] + gs)
    if abs(ms) > 1e-12:
        out["normal_margin"] = float(dr["m0"] + ms)
    lab = f"출발 성장률 {F.p1(dr['g0'] + gs)} · 정상 이익률 {F.p1(dr['m0'] + ms)}"
    bad = [f for f, v in out.items() if not M.spec.check(f, v)[0]]
    return out, lab, ("허용 범위 밖: " + ", ".join(M.spec.LABEL[f] for f in bad)) if bad else ""


def table(
    c: nav.Ctx, d: dict, kind: str, cols: list[str], rows_lab: list[str], vals: list[list], center: tuple[int, int], corner: str
) -> None:
    """The grid as a selectable table + the preview line of the clicked cell."""
    v = M.version(c.s)["v"]
    nonce = st.session_state.get(f"sens_nonce_{kind}", 0)
    key = f"sens_{kind}_v{v}_{nonce}"
    df = pd.DataFrame([[F.won0(x) if F.ok(x) else "계산 불가" for x in rv] for rv in vals], index=rows_lab, columns=cols)
    df.index.name = corner

    def hl(frame):
        out = pd.DataFrame("", index=frame.index, columns=frame.columns)
        if 0 <= center[0] < len(frame.index) and 0 <= center[1] < len(frame.columns):
            out.iloc[center[0], center[1]] = "background-color: #FFF1E6; color: #9A3412"
        return out

    ev = st.dataframe(df.style.apply(hl, axis=None), key=key, on_select="rerun", selection_mode="single-cell", width="stretch")
    cells = list(getattr(getattr(ev, "selection", None), "cells", None) or [])
    if not cells:
        return
    r0, col = cells[0][0], cells[0][1]
    i = int(r0) if not isinstance(r0, str) else rows_lab.index(r0)
    j = cols.index(col) if isinstance(col, str) else int(col)
    val = vals[i][j]
    now = M.result(c.o, c.s, c.mode).get("per_share")
    fields, lab, why = _fields(kind, d, i, j)
    dtxt = F.signed(val - now) + "원" if F.ok(val) and F.ok(now) else "—"
    st.markdown(
        f"<div class='wb-sens-pv'>{ui.esc(lab)} → 주당 <b>{F.won0(val)}원</b> · 현재 대비 {ui.esc(dtxt)}"
        f" <span class='wb-kpi-note'>엔진 값(표)</span>{' · ' + ui.esc(why) if why else ''}</div>",
        unsafe_allow_html=True,
    )
    b, x, _r = st.columns([2.2, 0.8, 3], vertical_alignment="center")  # buttons on their own line (narrow cards)
    if fields and not why:
        b.button(
            "가정에 적용",
            key=f"sens_go_{kind}",
            type="primary",
            on_click=_carry,
            args=(c.sid, kind, lab, fields, val),
            width="stretch",
        )
    x.button("✕", key=f"sens_x_{kind}", on_click=_clear, args=(kind,), help="미리보기 닫기")


def _clear(kind: str) -> None:
    st.session_state[f"sens_nonce_{kind}"] = st.session_state.get(f"sens_nonce_{kind}", 0) + 1


def _carry(sid: str, kind: str, lab: str, fields: dict, table_ps) -> None:
    st.session_state[PENDING] = {"sid": sid, "kind": kind, "label": lab, "fields": fields, "table_ps": table_ps}
    _clear(kind)
    nav.go("assume")


def _after(c: nav.Ctx, fields: dict):
    from src.workbench import recalc as R

    ver = M.version(c.s)
    try:
        ctx = M.public_ctx(c.o, c.s) if c.mode == "public" else c.o.ctx
        with M.LOCK:
            return R.recalc(c.o.cfg_path, {**ver["overrides"], **fields}, ctx=ctx).get("per_share")
    except (M.NeedInput, M.PublicDataUnavailable):
        return None


def apply_line(c: nav.Ctx) -> None:
    """Top of the 가정·판단 tab: the carried combination · reason · [반영] [취소]."""
    p = st.session_state.get(PENDING)
    if not p or p.get("sid") != c.sid:
        return
    after = _after(c, p["fields"])
    with st.container(key="sensapply"):
        a, b, d, e = st.columns([5, 3, 1.1, 1.0], vertical_alignment="bottom")
        ftxt = " · ".join(f"{M.spec.LABEL[f]} {M.spec.fmt(f, v)}" for f, v in p["fields"].items())
        a.markdown(
            f"<div class='wb-sens-pv'><b>민감도에서 가져온 조합</b> {ui.esc(p['label'])} ({ui.esc(ftxt)}) · 표 값 {F.won0(p['table_ps'])}원"
            f" · 반영 시 {F.won0(after)}원"
            + (
                " <span class='wb-kpi-note'>영구성장률은 예측 성장 경로 끝값에도 쓰여 표 값과 다를 수 있음</span>"
                if "g_terminal" in p["fields"]
                else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        b.text_input("변경 이유", key="sens_reason", placeholder="예: 민감도 표 조합 검토")
        d.button("반영", key="sens_do", type="primary", on_click=_do, args=(c.sid,), width="stretch")
        e.button("취소", key="sens_cancel", on_click=lambda: st.session_state.pop(PENDING, None), width="stretch")


def _do(sid: str) -> None:
    from app.wb import shell

    p = st.session_state.pop(PENDING, None)
    if not p:
        return
    s = M.load(sid)
    why = (st.session_state.get("sens_reason") or "").strip() or f"민감도 표 조합: {p['label']}"
    shell.note_change(s, "민감도 조합")
    msgs = []
    for f, v in p["fields"].items():
        r = M.set_value(s, f, v, why)
        if not r["ok"]:
            msgs.append(f"{M.spec.LABEL[f]}: {r['reason']}")
        s = M.load(sid)
    st.session_state["sens_reason"] = ""
    if msgs:
        st.session_state["judge_flash"] = (False, "반영 안 됨 — " + " · ".join(msgs))
