"""Clickable sensitivity tables (P7-U2 config/p7u2.yaml sensitivity, P7-U2F D3·D5): DCF tab WACC × g and growth × margin.

The grid is a block of cell buttons (no table widget: no English column menu, the cells fit the card). Click a cell -> one
line under the grid: the combination -> per share (the engine grid value), Δ to now, [가정에 적용] [✕].
[가정에 적용] carries the combination to the top of the 가정·판단 tab (apply_line): reason box, [반영] / [취소]. Nothing
changes before [반영]; 반영 = the session's own assumption changes (a new version and an audit line per field).

    WACC × g      g -> g_terminal; a WACC step dw through one component the person picks (P7-U2F D3):
                  MRP (default) + dw ÷ ((1 − Wd) × βL), SRP + dw ÷ (1 − Wd), βu + dw ÷ ((1 − Wd) × MRP × βL/βu)
                  (WACC is linear in each; a component outside its input range is disabled with the reason)
    growth × mar  출발 성장률 = now + growth step, 정상 이익률 = now + margin step (the shifts the grid used)
The value after 반영 is computed with the same recalc as the session (it can differ from the grid for g, because the
terminal growth also ends the forecast's growth path - the line says so).
"""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fields as FD
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav

PENDING = "sens_apply"
COMPONENTS = [("mrp", "MRP"), ("srp", "SRP"), ("beta_u", "베타")]


def _vtxt(field: str, v) -> str:
    return f"{float(v):.2f}" if field == "beta_u" else F.p1(v, 2)


def wacc_moves(d: dict, dw: float) -> list[dict]:
    """One entry per component: the value that moves WACC by dw, whether the input range allows it, the reason if not."""
    w = d["wacc"]
    wd, bl, bu = float(w.get("wd") or 0.0), float(w["beta_l"]), float(w["beta_u"])
    mrp, srp = float(w["mrp"]), float(w["srp"])
    k = 1 - wd
    vals = {
        "mrp": mrp + dw / (k * bl) if bl else None,
        "srp": srp + dw / k,
        "beta_u": bu + dw / (k * mrp * (bl / bu)) if bu and mrp else None,
    }
    out = []
    for f, lab in COMPONENTS:
        v = vals[f]
        ok = v is not None and M.spec.check(f, v)[0]
        why = "" if ok else (f"{lab} {_vtxt(f, v)} — 허용 범위 {FD.rng_text(f)} 밖" if v is not None else f"{lab}: 계산 불가")
        out.append({"field": f, "label": lab, "value": v, "ok": ok, "why": why})
    return out


def _pick(kind: str, moves: list[dict]) -> dict | None:
    """The chosen component (MRP first; a disabled choice falls to the next allowed one)."""
    want = st.session_state.get(f"sens_comp_{kind}", "mrp")
    ok = [m for m in moves if m["ok"]]
    return next((m for m in ok if m["field"] == want), ok[0] if ok else None)


def _fields(kind: str, d: dict, i: int, j: int) -> tuple[dict, str, str, str]:
    """({field: value}, label, why-not, audit reason) of a grid cell (WACC × g: with the chosen component)."""
    g = d["grids"]
    if kind == "wg":
        gv, dw = g["g_values"][i], g["wacc_steps"][j]
        out = {"g_terminal": float(gv)}
        lab = f"g {F.p1(gv)} · WACC {F.p1(g['wacc0'] + dw)}"
        reason = f"민감도 표 g {F.p1(gv)} 반영"
        if abs(dw) > 1e-12:
            m = _pick(kind, wacc_moves(d, dw))
            if m is None:
                return out, lab, "WACC 이동을 옮길 수 있는 값이 없음(MRP·SRP·베타 모두 허용 범위 밖)", reason
            out[m["field"]] = float(m["value"])
            reason = f"민감도 표 WACC {F.p1(g['wacc0'] + dw)} 반영 ({m['label']}로 환산) · g {F.p1(gv)}"
        return out, lab, "", reason
    gs, ms = g["growth_shifts"][i], g["margin_shifts"][j]
    dr = d["drivers"]
    out = {}
    if abs(gs) > 1e-12:
        out["g_start"] = float(dr["g0"] + gs)
    if abs(ms) > 1e-12:
        out["normal_margin"] = float(dr["m0"] + ms)
    lab = f"출발 성장률 {F.p1(dr['g0'] + gs)} · 정상 이익률 {F.p1(dr['m0'] + ms)}"
    bad = [f for f, v in out.items() if not M.spec.check(f, v)[0]]
    why = ("허용 범위 밖: " + ", ".join(M.spec.LABEL[f] for f in bad)) if bad else ""
    return out, lab, why, f"민감도 표 {lab} 반영"


def _sel_key(kind: str) -> str:
    return f"sens_sel_{kind}"


def _select(kind: str, v: int, i: int, j: int) -> None:
    st.session_state[_sel_key(kind)] = (v, i, j)


def _set_comp(kind: str, field: str) -> None:
    st.session_state[f"sens_comp_{kind}"] = field


def table(
    c: nav.Ctx, d: dict, kind: str, cols: list[str], rows_lab: list[str], vals: list[list], center: tuple[int, int], corner: str
) -> None:
    """The grid as cell buttons + the preview line of the clicked cell."""
    v = M.version(c.s)["v"]
    sel = st.session_state.get(_sel_key(kind))
    sel = tuple(sel[1:]) if sel and sel[0] == v else None
    with st.container(key=f"sensgrid_{kind}"):
        widths = [1.15] + [1] * len(cols)
        h = st.columns(widths, gap="small")
        h[0].markdown(f"<div class='wb-sg-h'>{ui.esc(corner)}</div>", unsafe_allow_html=True)
        for k_, lab in enumerate(cols):
            h[k_ + 1].markdown(f"<div class='wb-sg-h r'>{ui.esc(lab)}</div>", unsafe_allow_html=True)
        for i, (rl, rv) in enumerate(zip(rows_lab, vals)):
            rc = st.columns(widths, gap="small")
            rc[0].markdown(f"<div class='wb-sg-r'>{ui.esc(rl)}</div>", unsafe_allow_html=True)
            for j, x in enumerate(rv):
                tag = ("_base" if (i, j) == tuple(center) else "") + ("_sel" if sel == (i, j) else "")
                rc[j + 1].button(
                    F.won0(x) if F.ok(x) else "계산 불가",
                    key=f"sc_{kind}_{i}_{j}_v{v}{tag}",
                    on_click=_select,
                    args=(kind, v, i, j),
                    disabled=not F.ok(x),
                    width="stretch",
                    help=f"{rows_lab[i]} · {cols[j]} → 주당 {F.won0(x)}원",
                )
    if not sel:
        return
    i, j = sel
    val = vals[i][j]
    now = M.result(c.o, c.s, c.mode).get("per_share")
    dtxt = F.signed(val - now) + "원" if F.ok(val) and F.ok(now) else "—"
    moves = None
    if kind == "wg" and abs(d["grids"]["wacc_steps"][j]) > 1e-12:
        moves = wacc_moves(d, d["grids"]["wacc_steps"][j])
    fields, lab, why, reason = _fields(kind, d, i, j)
    st.markdown(
        f"<div class='wb-sens-pv'>{ui.esc(lab)} → 주당 <b>{F.won0(val)}원</b> · 현재 대비 {ui.esc(dtxt)}"
        f" <span class='wb-kpi-note'>엔진 값(표)</span>{' · ' + ui.esc(why) if why else ''}</div>",
        unsafe_allow_html=True,
    )
    if moves:  # P7-U2F D3: which component carries the WACC move
        chosen = _pick(kind, moves)
        st.markdown("<div class='wb-sg-r'>WACC 이동을 반영할 값</div>", unsafe_allow_html=True)
        cc = st.columns(3, gap="small")
        for k_, m in enumerate(moves):
            on = chosen is not None and chosen["field"] == m["field"]
            cc[k_].button(
                f"{m['label']} {_vtxt(m['field'], m['value'])}" if m["value"] is not None else m["label"],
                key=f"sens_comp_btn_{kind}_{m['field']}" + ("_on" if on else ""),
                on_click=_set_comp,
                args=(kind, m["field"]),
                disabled=not m["ok"],
                type="primary" if on else "secondary",
                width="stretch",
                help=m["why"] or f"{m['label']}을(를) {_vtxt(m['field'], m['value'])}로 바꾸면 WACC가 표의 값이 됨",
            )
        bad = [m["why"] for m in moves if not m["ok"]]
        if bad:
            st.markdown(f"<p class='wb-kpi-note'>{ui.esc(' · '.join(bad))}</p>", unsafe_allow_html=True)
    b, x, _r = st.columns([2.2, 0.8, 3], vertical_alignment="center")  # buttons on their own line (narrow cards)
    if fields and not why:
        b.button(
            "가정에 적용",
            key=f"sens_go_{kind}",
            type="primary",
            on_click=_carry,
            args=(c.sid, kind, lab, fields, val, reason),
            width="stretch",
        )
    x.button("✕", key=f"sens_x_{kind}", on_click=_clear, args=(kind,), help="미리보기 닫기")


def _clear(kind: str) -> None:
    st.session_state.pop(_sel_key(kind), None)


def _carry(sid: str, kind: str, lab: str, fields: dict, table_ps, reason: str = "") -> None:
    st.session_state[PENDING] = {
        "sid": sid,
        "kind": kind,
        "label": lab,
        "fields": fields,
        "table_ps": table_ps,
        "reason": reason,
    }
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
        ftxt = " · ".join(
            f"{M.spec.LABEL[f]} {_vtxt(f, v) if f in dict(COMPONENTS) else M.spec.fmt(f, v)}" for f, v in p["fields"].items()
        )
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
        b.text_input("변경 이유", key="sens_reason", placeholder=p.get("reason") or "예: 민감도 표 조합 검토")
        d.button("반영", key="sens_do", type="primary", on_click=_do, args=(c.sid,), width="stretch")
        e.button("취소", key="sens_cancel", on_click=lambda: st.session_state.pop(PENDING, None), width="stretch")


def _do(sid: str) -> None:
    from app.wb import shell

    p = st.session_state.pop(PENDING, None)
    if not p:
        return
    s = M.load(sid)
    typed = (st.session_state.get("sens_reason") or "").strip()
    why = (typed + " · " if typed else "") + (p.get("reason") or f"민감도 표 조합: {p['label']}")
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
