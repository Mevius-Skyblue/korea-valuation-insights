"""Verify a generated model: recalculated Excel values vs the P3 engine, formula errors, hard-coded numbers in
calculation sheets, input styles and the KRX data rule.

Run:  python -m src.excel.verify config/valuation_rf.yaml    -> data/interim/p4a_verify.md (+ prints the summary)

combos(model, d, reg)      every scenario x SRP set through the selection cells, recalculated -> compared with
                           src/valuation/rf_dcf2.value (per share 1 원, WACC 1e-6; EV, TV share, RONIC, exit too)
static_scan(path, reg)     formula errors in formula cells, numeric constants on calculation sheets (must be a
                           registered structural constant or inside an engine-value range), input cell styles,
                           KRX rule (registered single values only, no date series)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from src.collect.core import ROOT
from src.excel import recalc
from src.excel.context import CALC_SHEETS, SHEETS

TOL = {
    "per_share": 1.0,
    "per_share_exit": 1.0,
    "wacc": 1e-6,
    "ronic": 1e-6,
    "tv_share": 1e-6,
    "implied_multiple": 1e-6,
    "ev930": 0.01,
    "implied_g": 1e-9,
    "tv_share_exit": 1e-9,
}
LIVE = {
    "per_share": "PerShare",
    "wacc": "WACC",
    "ronic": "RONIC",
    "tv_share": "TVShare",
    "implied_multiple": "ImpliedMultiple",
    "per_share_exit": "PerShareExit",
    "ev930": "EV_930",
    "implied_g": "ImpliedG_Exit",
    "tv_share_exit": "TVShare_Exit",
}


# the cells one scenario x SRP run compares (C4-F7: only these and what they depend on are recalculated)
COMBO_OUT = [*LIVE.values(), "MasterCheck"]


def missing(x) -> bool:
    """A value that is not a number on either side: Excel 'N/M' / 'n/a' text, None or NaN (P7-B2: a missing value on
    both sides is a match). The reconciliation and its pass/fail check (src/pipeline/run.excel_check) use this one rule."""
    return x is None or isinstance(x, str) or x != x


def _diff(xl, en) -> float:
    """P7-B3 B3-F3: the same missing-value rule for every table (rf10, G)."""
    return 0.0 if missing(xl) and missing(en) else (float("inf") if missing(xl) or missing(en) else abs(xl - en))


def combos(m: recalc.Model, d: dict) -> list[dict]:
    """Every scenario x SRP through the selection cells: recalculated Excel values vs the engine grid."""
    labels = d["excel"]["scenario_labels"]
    eg = d["engine"]["grid"]
    rows = []
    for k in d["excel"]["scenarios"]:
        for s in d["rates"]["srp_list"]:
            v = m.calc({"ScenSel": labels[k], "SRP_Sel": s}, outputs=COMBO_OUT)
            row = {"scenario": k, "srp": s}
            ok = True
            for key, nm in LIVE.items():
                xl, en = m.value(v, nm), eg[(k, s)][key]
                diff = _diff(xl, en)
                row[f"{key}_xl"], row[f"{key}_engine"], row[f"{key}_diff"] = xl, en, diff
                ok &= diff <= TOL[key]
            row["master"] = m.value(v, "MasterCheck")
            row["ok"] = bool(ok and row["master"] == "OK")
            rows.append(row)
    return rows


def rf10_combos(m: recalc.Model, d: dict) -> list[dict]:
    """P6-A: Inputs 'Rf 만기 선택' = 10 -> every scenario x SRP per share and WACC vs the engine with ledger tenor 10."""
    labels = d["excel"]["scenario_labels"]
    rows = []
    for k in d["excel"]["scenarios"]:
        for s in d["rates"]["srp_list"]:
            v = m.calc({"ScenSel": labels[k], "SRP_Sel": s, "RfTenor": 10}, outputs=["PerShare", "WACC", "MasterCheck", "Rf"])
            en = d["engine"]["rf10"][(k, s)]
            ps, w = m.value(v, "PerShare"), m.value(v, "WACC")
            dp, dw = _diff(ps, en["per_share"]), _diff(w, en["wacc"])
            rows.append(
                {
                    "scenario": k,
                    "srp": s,
                    "per_share_xl": ps,
                    "per_share_engine": en["per_share"],
                    "per_share_diff": dp,
                    "wacc_diff": dw,
                    "master": m.value(v, "MasterCheck"),
                    "rf_check": m.value(v, "Rf"),
                    "ok": dp <= TOL["per_share"] and dw <= TOL["wacc"] and m.value(v, "MasterCheck") == "OK",
                }
            )
    return rows


def g_table(m: recalc.Model, d: dict) -> list[dict]:
    """P6-A G table cells through its input cells (RfOvr, SrpOvr; base scenario) vs the engine (Rf 5/10 x SRP + quoted)."""
    from src.excel.engine_ref import TENORS

    e = d["engine"]
    rows = []
    for t in TENORS:
        rf = d["rates"]["rf" if t == 5 else "rf10"]
        for sv in [*d["rates"]["srp_list"], e["srp_cite"]]:
            v = m.calc({"RfOvr": rf, "SrpOvr": sv}, outputs=["PerShare"])
            xl, en = m.value(v, "PerShare"), e["rf_srp"][(t, sv)]
            dd = _diff(xl, en)
            rows.append({"tenor": t, "srp": sv, "xl": xl, "engine": en, "diff": dd, "ok": dd <= TOL["per_share"]})
    return rows


def static_scan(path: Path, reg) -> dict:
    """Formula cells, hard-coded numbers on calculation sheets, input styles and the KRX single-value rule."""
    import openpyxl

    wb = openpyxl.load_workbook(path)  # formulas as strings
    eng = {}
    for sh, a, b in reg.engine:
        eng.setdefault(sh, []).append((a, b))
    structural = set(reg.structural)
    inputs = set(reg.inputs)

    def in_range(sh, cell):
        from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

        cl, rw = coordinate_from_string(cell)
        ci = column_index_from_string(cl)
        for a, b in eng.get(sh, []):
            (ca, ra), (cb, rb) = coordinate_from_string(a), coordinate_from_string(b)
            if ra <= rw <= rb and column_index_from_string(ca) <= ci <= column_index_from_string(cb):
                return True
        return False

    hard, formula_cells, bad_style, dates = [], {}, [], {}
    for ws in wb.worksheets:
        n_dates = 0
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if v is None:
                    continue
                key = (ws.title, c.coordinate)
                if isinstance(v, str) and v.startswith("="):
                    formula_cells.setdefault(ws.title, []).append(c.coordinate)
                    if c.font.color is not None and c.font.color.rgb == "FF0000FF":
                        bad_style.append((ws.title, c.coordinate, "formula in input colour"))
                    continue
                if isinstance(v, datetime):
                    n_dates += 1
                if ws.title in CALC_SHEETS and isinstance(v, (int, float)) and not isinstance(v, bool):
                    if key not in structural and key not in inputs and not in_range(ws.title, c.coordinate):
                        hard.append(key)
        dates[ws.title] = n_dates
    for sh, cell in inputs:
        c = wb[sh][cell]
        rgb_font = c.font.color.rgb if c.font.color is not None else None
        rgb_fill = c.fill.fgColor.rgb if c.fill is not None else None
        if rgb_font != "FF0000FF" or rgb_fill != "FFFFF2CC":
            bad_style.append((sh, cell, f"input style font={rgb_font} fill={rgb_fill}"))
    krx_bad = [x for x in reg.krx if x[0] not in ("Inputs",)]
    return {
        "hardcoded": hard,
        "formula_cells": sum(len(v) for v in formula_cells.values()),
        "formula_by_sheet": {k: len(v) for k, v in formula_cells.items()},
        "bad_style": bad_style,
        "date_cells": dates,
        "krx_registered": len(reg.krx),
        "krx_outside_inputs": krx_bad,
        "n_inputs": len(inputs),
        "n_structural": len(structural),
    }


def formula_errors(vals: dict, path: Path | None = None) -> list:
    """Formula cells whose recalculated value is an Excel error (#REF!, #DIV/0! ...)."""
    import openpyxl

    wb = openpyxl.load_workbook(path)
    fcells = {
        (ws.title, c.coordinate)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if isinstance(c.value, str) and c.value.startswith("=")
    }
    return [(k, v) for k, v in vals.items() if isinstance(v, str) and v.startswith("#") and tuple(k.split("!")) in fcells]


def check_rows(vals: dict, reg) -> list[tuple]:
    """Status of every registered check cell (label, kind, OK / WARN / ERR)."""
    return [(label, kind, vals.get(f"{sh}!{cell}")) for sh, cell, label, kind in reg.checks]


def run(cfg_path: str = "config/valuation_rf.yaml", path: Path | None = None, d: dict | None = None, on_built=None) -> dict:
    """Build the workbook (d: model data already computed - P7-B5 first draft) and reconcile it with the engine.
    res['timing'] = {'build': Excel generation incl. cached values, 'reconcile': the formulas recalculations}."""
    import time

    from src.excel.build import build

    t0 = time.time()
    p, c, vals = build(cfg_path, path, d=d)
    t1 = time.time()
    if on_built:  # P7-C1: the workbook exists (cached values written)
        on_built(p, round(t1 - t0, 2))
    m = getattr(c, "recalc_model", None) or recalc.load(p, c.book.reg.names, [s for s, _ in SHEETS])
    base = vals if vals is not None and getattr(c, "recalc_model", None) is not None else m.calc()
    d = c.d
    res = {
        "path": p,
        "combos": combos(m, d),
        "scan": static_scan(p, c.book.reg),
        "errors": formula_errors(base, path=p),
        "checks": check_rows(base, c.book.reg),
        "master": m.value(base, "MasterCheck"),
        "base": base,
        "ctx": c,
    }
    res["rf10"] = rf10_combos(m, d)
    res["g"] = g_table(m, d)
    if d["type"] == "scenario_capex":  # C2 reproduction through the RONIC start switch (RF: only rule that differs)
        v2 = m.calc(
            {"RonicStart": "mixed", "ScenSel": d["excel"]["scenario_labels"]["base"], "SRP_Sel": d["rates"]["srp_list"][0]},
            outputs=["PerShare"],
        )
        res["c2"] = (m.value(v2, "PerShare"), d["engine"]["c2_base"])
    else:
        res["c2"] = None
    # other values compared once (base selection)
    e = d["engine"]
    po = c.layout["peer_out"]
    other = []
    for nm, mu in e["multiples"].items():
        for q, qk in (("q25", "ps_q25"), ("med", "ps_median"), ("q75", "ps_q75")):
            other.append((f"{nm} 주당 {q}", m.value(base, po[nm][q]), mu[qk]))
        for q, qk in (("q25", "q25"), ("med", "median"), ("q75", "q75")):
            other.append((f"{nm} 배수 {q}", m.value(base, po[nm]["mult"][q]), mu[qk]))
    if not d["premium"].get("withheld"):  # P7-C3 public deployment: no block price
        for q, nm in ((1, "q25"), (2, "q50"), (3, "q75")):
            other.append((f"블록 1주당 {nm}", m.value(base, f"Block_q{q}"), e["block"][nm]))
    if e.get("cross"):
        other.append(("연결 교차 확인 주당", m.value(base, "CrossPerShare"), e["cross"]["per_share"]))
        other.append(("모회사 순현금(백만원)", m.value(base, "ParentNetCash"), e["parent_net_cash"]))
    else:
        other.append(("순차입금(백만원)", m.value(base, "NetDebt"), e["net_debt"]))
        other.append(("Kd(세전, 공통 규칙)", m.value(base, "Kd_Pre"), e["kd"]))
        other.append(("목표 D/E(자체 평균)", m.value(base, "DE_Target"), e["de_own"]))
        other.append(("RONIC 상한(과거 3년 ROIC)", m.value(base, "RonicCap"), e["ronic_cap"]))
    other.append(("βu 중앙값", m.value(base, "BetaU"), e["beta_u"]))
    cv = c.layout["conv_cells"]
    other.append(("수렴 시험 C3 기본 DCF 주당", m.value(base, cv["live"][0]["ps"]), e["convergence"]["c3"]["per_share"]))
    other.append(("수렴 시험 EV/EBITDA 주당 q25", m.value(base, cv["live"][0]["q25"]), e["convergence"]["n10"]["q25"]))
    other.append(("수렴 시험 EV/EBITDA 주당 q75", m.value(base, cv["live"][0]["q75"]), e["convergence"]["n10"]["q75"]))
    if e["convergence"]["n5"]:
        other.append(("수렴 시험 보완 전 q25", m.value(base, cv["live"][1]["q25"]), e["convergence"]["n5"]["q25"]))
        other.append(("수렴 시험 보완 전 q75", m.value(base, cv["live"][1]["q75"]), e["convergence"]["n5"]["q75"]))
    loss = (e.get("diagnostics") or {}).get("loss")
    if loss and c.layout.get("fund_row") is not None:  # P7-B3b funding check (live vs engine)
        other.append(("적자 경로 누적 FCF 최저(백만원)", m.value(base, "FundTrough"), loss["funding"]["trough"]))
    res["verdict"] = (m.value(base, cv["live"][0]["verdict"]), e["convergence"]["c3"]["verdict"])
    res["other"] = other
    res["timing"] = {"build": round(t1 - t0, 2), "reconcile": round(time.time() - t1, 2)}
    return res


def report_md(res: dict, d: dict) -> str:
    """The reconciliation result as a Markdown report table."""
    labels = d["excel"]["scenario_labels"]
    out = [
        f"# P4-A 엑셀 vs 엔진 일치 시험 (원본 표)\n\n- 파일: `{res['path'].relative_to(ROOT).as_posix()}`\n- master check: **{res['master']}**\n"
    ]
    out.append(
        "| 시나리오 | SRP | 엑셀 주당 | 엔진 주당 | 차이(원) | 엑셀 WACC | 차이 | EV 차이(백만원) | 영구가치 비중 차이 | RONIC 차이 | Exit 주당 차이 | master |"
    )
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in res["combos"]:
        out.append(
            f"| {labels[r['scenario']]} | {r['srp']:.0%} | {r['per_share_xl']:,.2f} | {r['per_share_engine']:,.2f} | "
            f"{r['per_share_diff']:.2e} | {r['wacc_xl']:.6%} | {r['wacc_diff']:.1e} | {r['ev930_diff']:.1e} | "
            f"{r['tv_share_diff']:.1e} | {r['ronic_diff']:.1e} | {r['per_share_exit_diff']:.1e} | {r['master']} |"
        )
    out.append("\n| 항목 | 엑셀 | 엔진 | 차이 |\n|---|---:|---:|---:|")
    for lab, xl, en in res["other"]:
        out.append(f"| {lab} | {xl:,.4f} | {en:,.4f} | {abs(xl - en):.1e} |")
    c2 = res["c2"]
    if c2:
        out.append(
            f"\n- C2 재현(RONIC 출발점 mixed, 기본, SRP 0%): 엑셀 {c2[0]:,.2f}원 / 엔진 {c2[1]:,.2f}원 / 차이 {abs(c2[0] - c2[1]):.1e}"
        )
    if res.get("rf10"):
        out.append(
            "\n| Rf 10년 선택: 시나리오 | SRP | 엑셀 주당 | 엔진 주당 | 차이(원) | WACC 차이 | master |\n|---|---:|---:|---:|---:|---:|---|"
        )
        for r in res["rf10"]:
            out.append(
                f"| {labels[r['scenario']]} | {r['srp']:.0%} | {r['per_share_xl']:,.2f} | {r['per_share_engine']:,.2f} | "
                f"{r['per_share_diff']:.2e} | {r['wacc_diff']:.1e} | {r['master']} |"
            )
        out.append("\n| G 표(기본 시나리오): Rf | SRP | 엑셀 주당 | 엔진 주당 | 차이(원) |\n|---|---:|---:|---:|---:|")
        for r in res["g"]:
            out.append(f"| {r['tenor']}년 | {r['srp']:.2%} | {r['xl']:,.2f} | {r['engine']:,.2f} | {r['diff']:.2e} |")
    out.append(f"- 수렴 판정(살아 있는 모델 / 엔진 기록 C3): {res['verdict'][0]} / {res['verdict'][1]}")
    sc = res["scan"]
    out.append(
        f"- 수식 셀 {sc['formula_cells']:,}개, 수식 오류 {len(res['errors'])}개, 계산 시트 하드코딩 숫자 {len(sc['hardcoded'])}개 "
        f"(구조 상수 {sc['n_structural']}개·엔진 값 표는 등록 범위), 입력 셀 {sc['n_inputs']}개 중 서식 위반 {len(sc['bad_style'])}개"
    )
    out.append(
        f"- KRX 단일 값 등록 {sc['krx_registered']}개(Inputs 밖 {len(sc['krx_outside_inputs'])}개), 시트별 날짜 상수 셀: {sc['date_cells']}"
    )
    out.append("\n| check | 종류 | 상태 |\n|---|---|---|")
    for lab, kind, st in res["checks"]:
        out.append(f"| {lab} | {kind} | {st} |")
    return "\n".join(out)


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/valuation_rf.yaml"
    r = run(cfg)
    text = report_md(r, r["ctx"].d)
    name = Path(cfg).stem.replace("valuation_", "")
    (ROOT / "data" / "interim").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "interim" / f"p4_verify_{name}.md").write_text(text, encoding="utf-8")
    print(text)


def unit_scan(path: Path) -> dict:
    """P4-X: every numeric cell whose size does not fit its unit (number format / row unit label).
    백만원 (#,##0.0) >= 1e8 (100조원), 원 (#,##0) >= 1e7 per share-like rows or 0 < |v| < 1, % > 500%, 배 > 1,000.
    Returns suspects and, for transparency, where the 원 <-> 백만원 conversion (MnToWon) is used."""
    import openpyxl

    wf = openpyxl.load_workbook(path)
    wv = openpyxl.load_workbook(path, data_only=True)
    sus, conv = [], []
    for ws in wf.worksheets:
        if ws.title == "Diagnostics":  # P7-B2: differences and shares of sensitivities (tiny 원 / large %), not model amounts
            continue
        vs = wv[ws.title]
        for row in ws.iter_rows():
            for c in row:
                v = vs[c.coordinate].value
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    continue
                f = c.number_format or ""
                is_formula = isinstance(c.value, str) and c.value.startswith("=")
                label = str(ws.cell(c.row, 1).value or "")
                unit = str(ws.cell(c.row, 2).value or "") + str(ws.cell(c.row, 3).value or "")
                why = None
                if f.startswith("#,##0.0;"):
                    if abs(v) >= 1e8:
                        why = "백만원 칸인데 1e8 이상(100조원 이상)"
                elif f.startswith("#,##0;[Red]"):
                    if abs(v) >= 1e7 and ("주당" in label or "종가" in label or "VWAP" in label or "원" in unit):
                        why = "원(주당) 칸인데 1e7 이상"
                    elif 1e-6 < abs(v) < 1:  # below 1e-6 = floating noise in difference tables
                        why = "원 칸인데 1 미만"
                elif "%" in f and abs(v) > 5:
                    why = "% 칸인데 500% 초과"
                elif '"x"' in f and abs(v) > 1000:
                    why = "배 칸인데 1,000배 초과"
                if why:
                    sus.append((ws.title, c.coordinate, label[:40], v, why))
                if is_formula and "MnToWon" in c.value:
                    conv.append((ws.title, c.coordinate, label[:40]))
    return {"suspects": sus, "conversions": conv}
