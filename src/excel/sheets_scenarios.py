"""Scenarios sheet of the Excel model (split out of sheets_output.py in P7-C4): scenario x SRP block, the engine tables
(WACC x g, growth x margin, reverse DCF, Rf 10-year), the G table (Rf x SRP + quoted SRP) and the What-If data tables.
"""

from __future__ import annotations

import math
import re

from src.excel.context import Ctx
from src.excel.sheets_output import ENGINE_METRICS
from src.excel.writer import a1


def scenarios(c: Ctx):
    d, s = c.d, c.sheet("Scenarios")
    keys, labels = d["excel"]["scenarios"], d["excel"]["scenario_labels"]
    srps = d["rates"]["srp_list"]
    ns = len(srps)
    s.widths({0: 30, **{j: 12 for j in range(1, 20)}})
    s.text(0, 0, "Scenarios — 시나리오 × SRP (가정 하의 추정 내재가치, 예시)", "title")
    s.text(
        1, 0, "A 표·C·D 데이터 표는 살아 있는 수식(Scen_Calc, 엑셀 What-If). 회색 표는 엔진 계산값(수식 아님) — 대조용", "note"
    )
    cells = c.layout["scen_cells"]
    r = 3
    grids = {}
    for title, key, kind in (
        ("A-1. 주당 가치(원, Gordon) — 살아 있는 수식", "ps", "won"),
        ("A-2. WACC", "wacc", "pct3"),
        ("A-3. RONIC(적용)", "ronic", "pct"),
        ("A-4. 영구가치 비중", "tv", "pct1"),
    ):
        s.text(r, 0, title, "subtitle")
        s.text(r + 1, 0, "시나리오 \\ SRP", "header")
        for j in range(ns):
            s.fx(r + 1, 1 + j, f"=SRP_{j + 1}", "pct")
        for i, k in enumerate(keys):
            s.text(r + 2 + i, 0, labels[k])
            for j in range(ns):
                s.fx(r + 2 + i, 1 + j, f"={cells[(k, j)][key]}", kind)
        grids[key] = (r + 2, 1, r + 1 + len(keys), ns)
        if key == "ps":
            s.text(r + 1, ns + 2, "기준일 종가 대비", "header")
            for i in range(len(keys)):
                for j in range(ns):
                    s.fx(r + 2 + i, ns + 2 + j, f"={a1(r + 2 + i, 1 + j)}/Close-1", "pct1")
        r += 3 + len(keys)
    g0 = grids["ps"]
    c.range_name("ScenGridPS", "Scenarios", a1(g0[0], 1), a1(g0[2], ns))
    gw = grids["wacc"]
    c.range_name("ScenGridWACC", "Scenarios", a1(gw[0], 1), a1(gw[2], ns))
    gt = grids["tv"]
    c.range_name("ScenGridTV", "Scenarios", a1(gt[0], 1), a1(gt[2], ns))
    s.text(r, 0, "선택 칸(시나리오·SRP)의 표 값", "bold")
    s.fx(r, 2, "=INDEX(ScenGridPS,ScenIdx,MATCH(SRP_Sel,SRP_List,0))", "won", name="ScenSelPS")
    s.text(r, 3, "= Bridge 주당 가치와 같아야 한다(Checks)", "note")
    c.layout["scen_grids"] = grids
    r += 2
    # ---- engine tables
    eg = d["engine"]["grid"]
    s.text(r, 0, "B. 엔진 값(수식 아님) — rf_dcf2.value, P3-C3 규칙. Checks의 INFO 대조에 쓴다", "subtitle")
    r += 1
    eng_ref = {}
    for m, lab, kind, live in ENGINE_METRICS:
        s.text(r, 0, f"엔진: {lab}", "header")
        for j in range(ns):
            s.eng(r, 1 + j, srps[j], "pct")
        for i, k in enumerate(keys):
            s.text(r + 1 + i, 0, labels[k])
            for j, sv in enumerate(srps):
                s.eng(r + 1 + i, 1 + j, eg[(k, sv)][m], kind)
        s.engine_range(r, 1, r + len(keys), ns)
        eng_ref[m] = (f"Scenarios!{a1(r + 1, 1, True)}:{a1(r + len(keys), ns, True)}", live, lab)
        r += 2 + len(keys)
    c.layout["engine_tables"] = eng_ref
    s.text(r, 0, "살아 있는 표 − 엔진 표 (주당, 원)", "header")
    for i, k in enumerate(keys):
        s.text(r + 1 + i, 0, labels[k])
        for j in range(ns):
            live = a1(g0[0] + i, 1 + j)
            engc = eng_ref["per_share"][0].split("!")[1].split(":")[0].replace("$", "")
            mm = re.fullmatch(r"([A-Z]+)(\d+)", engc)
            ec = a1(int(mm.group(2)) - 1 + i, 1 + j)
            s.fx(r + 1 + i, 1 + j, f"={live}-{ec}", "won")
    c.range_name("ScenDiff", "Scenarios", a1(r + 1, 1), a1(r + len(keys), ns))
    r += 2 + len(keys)
    r = _data_tables(c, s, r)
    e = d["engine"]
    gr = d["excel"]["grids"]
    if d["type"] == "scenario_capex":
        s.text(
            r,
            0,
            f"E. 역DCF — 기준일 종가({e['price']:,.0f}원)를 맞추는 2027~2032 같은 성장률 (기본 구조, SRP 0%) — 엔진 값",
            "subtitle",
        )
        s.text(r + 1, 0, "정상 이익률", "header")
        s.text(r + 1, 1, "필요 성장률", "header")
        s.text(r + 1, 2, "2032 매출 함의(백만원)", "header")
        for i, m in enumerate(gr["reverse_margins"]):
            g = e["reverse"][m]
            s.eng(r + 2 + i, 0, m, "pct")
            s.eng(r + 2 + i, 1, g, "pct1")
            s.eng(r + 2 + i, 2, None if g is None else d["scenarios"]["base"]["rev_2026"] * (1 + g) ** 6, "mn")
        s.engine_range(r + 2, 0, r + 1 + len(gr["reverse_margins"]), 2)
        c.range_name("ReverseTable", "Scenarios", a1(r + 2, 0), a1(r + 1 + len(gr["reverse_margins"]), 2))
        c.layout["reverse_cells"] = {m: f"Scenarios!{a1(r + 2 + i, 1, True)}" for i, m in enumerate(gr["reverse_margins"])}
        r += 3 + len(gr["reverse_margins"])
        s.text(r, 0, "F. 재현값(엔진)", "subtitle")
        s.text(r + 1, 0, "C2(RONIC 출발점 mixed) 기본·SRP 0% 주당")
        s.eng(r + 1, 1, e["c2_base"], "won")
        s.text(r + 1, 2, "Inputs의 RONIC 출발점을 mixed로 바꾸면 A 표 기본·SRP 0%가 이 값과 같아야 한다", "note")
        s.text(r + 2, 0, "연결 교차 확인 주당(기본·SRP 0%)")
        s.eng(r + 2, 1, e["cross"]["per_share"], "won")
        s.engine_range(r + 1, 1, r + 2, 1)
        c.layout["c2_engine"] = f"Scenarios!{a1(r + 1, 1, True)}"
        c.layout["cross_engine"] = f"Scenarios!{a1(r + 2, 1, True)}"
        r += 4
    else:
        rv = e["reverse"]
        s.text(
            r,
            0,
            f"E. 역DCF — 기준일 종가({e['price']:,.0f}원)를 맞추는 값 (기본 경로, SRP 0%, 하나씩만 바꿈) — 엔진 값",
            "subtitle",
        )
        items = [
            ("출발 성장률 g_2026(2030년까지 g로 체감, 탐색 −30%~+60%)", rv["g_start"], "pct1"),
            ("보조: 같은 경로·이익률에서의 WACC", rv["wacc"], "pct"),
            ("보조: 기본 성장·WACC에서 필요한 정상 이익률", rv["margin"], "pct"),
        ]
        c.layout["reverse_cells"] = {}
        for i, (lab, v, kind) in enumerate(items):
            s.text(r + 1 + i, 0, lab)
            s.eng(r + 1 + i, 1, v, kind)
            c.layout["reverse_cells"][lab] = f"Scenarios!{a1(r + 1 + i, 1, True)}"
        s.engine_range(r + 1, 1, r + len(items), 1)
        c.range_name("ReverseTable", "Scenarios", a1(r + 1, 0), a1(r + len(items), 1))
        c.layout["c2_engine"] = None
        c.layout["cross_engine"] = None
        r += 2 + len(items)
    _rf_srp(c, s, r)


def _rf_srp(c: Ctx, s, r):
    """P6-A G: Rf tenor x SRP. G-1 live data table (rows Rf 국고채 5년 / 10년 -> RfOvr, columns SRP 열 1~3 and the
    한공회 quoted SRP -> SrpOvr; current scenario). G-2 engine: every scenario x SRP with Rf 10년 (per share, WACC) and
    the live A-1 table minus G-2 (meaningful only while Inputs 'Rf 만기 선택' = 10). Defaults are not changed."""
    d = c.d
    e = d["engine"]
    keys, labels = d["excel"]["scenarios"], d["excel"]["scenario_labels"]
    srps = d["rates"]["srp_list"]
    ns = len(srps)
    cite = e["srp_cite"]
    s.text(r, 0, "G. Rf 만기 × SRP (P6-A) — 기본 결과(A 표)는 그대로. 10년·인용 SRP는 민감도", "subtitle")
    s.text(r + 1, 0, "Rf 입력 칸(G 표 열 입력) — 비워 둔다")
    s.inp(r + 1, 1, None, "pct3", name="RfOvr")
    rf_cell = a1(r + 1, 1)
    srp_cell = c.book.reg.names["SrpOvr"][1]
    hr = r + 3
    s.text(
        hr - 1,
        0,
        "G-1. 살아 있는 데이터 표(주당 원, 현재 선택 시나리오). 행 = Rf 국고채 5년 / 10년, 열 = SRP 열 1~3 / 한공회 인용 참고값",
        "bold",
    )
    s.fx(hr, 0, "=PerShare", "won")
    tops = [f"=SRP_{j + 1}" for j in range(ns)] + ["=SRP_Cite"]
    for j, f in enumerate(tops):
        s.fx(hr, 1 + j, f, "pct")
    tenors = (5, 10)
    for i, t in enumerate(tenors):
        s.fx(hr + 1 + i, 0, f"=Rf_{t}Y", "pct3")
        for j, sv in enumerate([*srps, cite]):
            s.ws.write_number(hr + 1 + i, 1 + j, float(e["rf_srp"][(t, sv)]), c.book.fmt("calc", "won"))
    nr, nc = len(tenors), ns + 1
    first, last = a1(hr + 1, 1), a1(hr + nr, nc)
    c.book.reg.engine.append(("Scenarios", first, last))  # cached values until Excel recalculates
    c.range_name("DT_G", "Scenarios", first, last)
    c.range_name("DT_G_Top", "Scenarios", a1(hr, 1), a1(hr, nc))
    c.range_name("DT_G_Left", "Scenarios", a1(hr + 1, 0), a1(hr + nr, 0))
    c.book.reg.datatables.append({"sheet": "Scenarios", "first": first, "ref": f"{first}:{last}", "r1": srp_cell, "r2": rf_cell})
    ec0 = nc + 2
    s.text(hr, ec0, "엔진(기본 시나리오)", "header")
    for j, sv in enumerate([*srps, cite]):
        s.eng(hr, ec0 + 1 + j, sv, "pct")
    grid = {}
    for i, t in enumerate(tenors):
        s.eng(hr + 1 + i, ec0, d["rates"]["rf" if t == 5 else "rf10"], "pct3")
        for j, sv in enumerate([*srps, cite]):
            grid[(i, j)] = e["rf_srp"][(t, sv)]
            s.eng(hr + 1 + i, ec0 + 1 + j, grid[(i, j)], "won")
    s.engine_range(hr, ec0, hr + nr, ec0 + nc)
    dc0 = ec0 + nc + 2
    s.text(hr, dc0, "표 − 엔진(원)", "header")
    for i in range(nr):
        for j in range(nc):
            e_ = a1(hr + 1 + i, ec0 + 1 + j)  # P7-X2a X2a-F3: an N/M engine cell (WACC <= g) has no difference
            s.fx(hr + 1 + i, dc0 + 1 + j, f'=IF(ISNUMBER({e_}),{a1(hr + 1 + i, 1 + j)}-{e_},"")', "won")
    diff = f"Scenarios!{a1(hr + 1, dc0 + 1, True)}:{a1(hr + nr, dc0 + nc, True)}"
    c.layout["dt"].append(
        {
            "key": "G",
            "title": "Rf 만기 × SRP",
            "range": f"Scenarios!{first}:{last}",
            "diff": diff,
            "first_rc": (hr + 1, 1),
            "shape": (nr, nc),
            "engine": grid,
            "center": f"Scenarios!{a1(hr + 1, 1, True)}",
            "engine_center": f"Scenarios!{a1(hr + 1, ec0 + 1, True)}",
        }
    )
    c.layout["dt_g_cite"] = {"cell": f"Scenarios!{a1(hr + 1, nc, True)}", "cell10": f"Scenarios!{a1(hr + 2, nc, True)}"}
    s.text(
        hr + nr + 1,
        0,
        "SRP 인용 참고값 주당(Rf 5년, 현재 시나리오) — 위 표 마지막 열. SRP 기본 열(0·1·2%, 결정 D4)은 바꾸지 않는다",
        "note",
    )
    # ---- G-2 engine: Rf 10년 x every scenario x SRP
    r2 = hr + nr + 3
    rf10 = e["rf10"]
    eng10 = {}
    for m, lab, kind in (("per_share", "주당 가치(원, Gordon)", "won"), ("wacc", "WACC", "pct3")):
        s.text(r2, 0, f"G-2. 엔진: Rf 국고채 10년 — {lab}", "header")
        for j in range(ns):
            s.eng(r2, 1 + j, srps[j], "pct")
        for i, k in enumerate(keys):
            s.text(r2 + 1 + i, 0, labels[k])
            for j, sv in enumerate(srps):
                s.eng(r2 + 1 + i, 1 + j, rf10[(k, sv)][m], kind)
        s.engine_range(r2, 1, r2 + len(keys), ns)
        eng10[m] = (r2 + 1, 1)
        r2 += 2 + len(keys)
    c.range_name("Rf10GridPS", "Scenarios", a1(eng10["per_share"][0], 1), a1(eng10["per_share"][0] + len(keys) - 1, ns))
    c.range_name("Rf10GridWACC", "Scenarios", a1(eng10["wacc"][0], 1), a1(eng10["wacc"][0] + len(keys) - 1, ns))
    g0 = c.layout["scen_grids"]["ps"]
    s.text(r2, 0, "G-3. A-1 표 − G-2 주당(원) — Inputs 'Rf 만기 선택' = 10일 때만 값이 나온다", "header")
    for i, k in enumerate(keys):
        s.text(r2 + 1 + i, 0, labels[k])
        for j in range(ns):
            s.fx(r2 + 1 + i, 1 + j, f'=IF(RfTenor=10,{a1(g0[0] + i, 1 + j)}-{a1(eng10["per_share"][0] + i, 1 + j)},"")', "won")
    c.range_name("Rf10Diff", "Scenarios", a1(r2 + 1, 1), a1(r2 + len(keys), ns))


def _data_tables(c: Ctx, s, r) -> int:
    """C·D: live Excel data tables (What-If). Their input cells must be on this sheet (Excel rule), so the override
    cells live here, blank - the model uses them only while a table is calculating. Result cells carry the engine
    grid as cached values (shown by viewers that do not recalculate); Excel recalculates them (F9 / on open)."""
    d = c.d
    gr = d["excel"]["grids"]
    e = d["engine"]
    eg = e["grid"]
    srps = d["rates"]["srp_list"]
    cap = d["type"] == "scenario_capex"
    s.text(
        r,
        0,
        "데이터 표 입력 칸 — 비워 둔다(데이터 표가 계산할 때만 값이 들어간다). 값을 넣으면 모델 전체가 그 값으로 바뀐다",
        "subtitle",
    )
    ovr = [("WaccOvr", "WACC 입력 칸(C 표 행 입력)", "pct3"), ("GOvr", "영구성장률 입력 칸(C 표 열 입력)", "pct")]
    ovr += (
        [
            ("MarginOvr", "정상 이익률 입력 칸(D 표 행 입력)", "pct"),
            ("GrowthOvr", "2027~2030 성장률 입력 칸(D 표 열 입력)", "pct"),
        ]
        if cap
        else [
            ("MarginShiftOvr", "이익률 이동 입력 칸(D 표 행 입력)", "pct"),
            ("GrowthShiftOvr", "출발 성장률 이동 입력 칸(D 표 열 입력)", "pct"),
        ]
    )
    ovr += [("SrpOvr", "SRP 입력 칸(M 표 행 입력)", "pct"), ("MrpOvr", "MRP 입력 칸(M 표 열 입력)", "pct")]
    cell = {}
    for i, (nm, lab, kind) in enumerate(ovr):
        rr = r + 1 + i // 2
        cc = 0 if i % 2 == 0 else 3
        s.text(rr, cc, lab)
        s.inp(rr, cc + 1 if cc else 1, None, kind, name=nm)
        cell[nm] = a1(rr, cc + 1 if cc else 1)
    r += 1 + (len(ovr) + 1) // 2 + 1
    w0 = eg[("base", srps[0])]["wacc"]
    base_lab = d["excel"]["scenario_labels"]["base"]
    specs = [
        (
            "C",
            "WACC × 영구성장률 g",
            "WaccOvr",
            "GOvr",
            [("이동폭", st) for st in gr["wacc_steps"]],
            gr["g_values"],
            e["wacc_g"],
            lambda i, j: (gr["wacc_steps"][j], gr["g_values"][i]),
            [w0 + st for st in gr["wacc_steps"]],
            "pct1",
            "pct",
        )
    ]
    if cap:
        specs.append(
            (
                "D",
                "2027~2030 매출 성장률 × 정상 이익률",
                "MarginOvr",
                "GrowthOvr",
                [("이익률", m) for m in gr["margin_values"]],
                gr["growth_values"],
                e["growth_margin"],
                lambda i, j: (gr["growth_values"][i], gr["margin_values"][j]),
                None,
                "pct",
                "pct",
            )
        )
    else:
        specs.append(
            (
                "D",
                "출발 성장률 이동 × 정상 이익률 이동",
                "MarginShiftOvr",
                "GrowthShiftOvr",
                [("이익률 이동", m) for m in gr["margin_shifts"]],
                gr["growth_shifts"],
                e["growth_margin"],
                lambda i, j: (gr["growth_shifts"][i], gr["margin_shifts"][j]),
                None,
                "pct",
                "pct",
            )
        )
    mrps = sorted({k[0] for k in e["mrp_srp"]})
    specs.append(
        (
            "M",
            "MRP × SRP (기본 시나리오)",
            "SrpOvr",
            "MrpOvr",
            [("SRP", sv) for sv in srps],
            mrps,
            e["mrp_srp"],
            lambda i, j: (mrps[i], srps[j]),
            None,
            "pct",
            "pct",
        )
    )
    c.layout["dt"] = []
    for key, title, rin, cin, top_vals, left_vals, grid, gkey, eng_top, lfmt, tfmt in specs:
        s.text(
            r,
            0,
            f"{key}. {title} — 살아 있는 데이터 표(주당 원, 현재 선택 "
            + ("시나리오" if key == "M" else "시나리오·SRP")
            + " 기준). 오른쪽은 엔진 격자(기본"
            + ("" if key == "M" else "·SRP 0%")
            + ")",
            "subtitle",
        )
        if key == "C":
            s.text(r + 1, 0, "WACC 이동폭(입력)")
            for j, (_, v) in enumerate(top_vals):
                s.inp(r + 1, 1 + j, v, "pct")
        hr = r + 2
        s.fx(hr, 0, "=PerShare", "won")
        for j, (_, v) in enumerate(top_vals):
            if key == "C":
                s.fx(hr, 1 + j, f"=WaccCalc+{a1(r + 1, 1 + j)}", "pct")
            else:
                s.inp(hr, 1 + j, v, tfmt)
        for i, v in enumerate(left_vals):
            s.inp(hr + 1 + i, 0, v, lfmt)
            for j in range(len(top_vals)):
                val = grid[gkey(i, j)]
                if val is None or not math.isfinite(float(val)):  # P7-X2a X2a-F3: WACC <= g cell (P7-B5 B5-F1) is N/M
                    s.ws.write_string(hr + 1 + i, 1 + j, "N/M", c.book.fmt("calc", "won"))
                else:
                    s.ws.write_number(hr + 1 + i, 1 + j, float(val), c.book.fmt("calc", "won"))
        nr, nc = len(left_vals), len(top_vals)
        first, last = a1(hr + 1, 1), a1(hr + nr, nc)
        c.book.reg.engine.append(("Scenarios", first, last))  # cached values until Excel recalculates
        c.range_name(f"DT_{key}", "Scenarios", first, last)
        c.range_name(f"DT_{key}_Top", "Scenarios", a1(hr, 1), a1(hr, nc))
        c.range_name(f"DT_{key}_Left", "Scenarios", a1(hr + 1, 0), a1(hr + nr, 0))
        c.book.reg.datatables.append(
            {"sheet": "Scenarios", "first": first, "ref": f"{first}:{last}", "r1": cell[rin], "r2": cell[cin]}
        )
        # engine grid (same layout) and difference
        ec0 = nc + 2
        s.text(hr, ec0, "엔진(기본·SRP 0%)", "header")
        for j, (_, v) in enumerate(top_vals):
            s.eng(hr, ec0 + 1 + j, eng_top[j] if eng_top else v, tfmt)
        for i, v in enumerate(left_vals):
            s.eng(hr + 1 + i, ec0, v, lfmt)
            for j in range(nc):
                s.eng(hr + 1 + i, ec0 + 1 + j, grid[gkey(i, j)], "won")
        s.engine_range(hr, ec0, hr + nr, ec0 + nc)
        dc0 = ec0 + nc + 2
        s.text(hr, dc0, "표 − 엔진(원)", "header")
        for i in range(nr):
            for j in range(nc):
                e_ = a1(hr + 1 + i, ec0 + 1 + j)  # P7-X2a X2a-F3: an N/M engine cell (WACC <= g) has no difference
                s.fx(hr + 1 + i, dc0 + 1 + j, f'=IF(ISNUMBER({e_}),{a1(hr + 1 + i, 1 + j)}-{e_},"")', "won")
        diff = f"Scenarios!{a1(hr + 1, dc0 + 1, True)}:{a1(hr + nr, dc0 + nc, True)}"
        # centre cell: no change in the overridden input (WACC step 0 / g = base g; growth & margin = base values)
        if key == "C":
            gb = d["scenarios"]["base"]["g_terminal"] if cap else d["mech"]["g_terminal"]
            ctr = (left_vals.index(gb), [v for _, v in top_vals].index(0.0)) if gb in left_vals else None
        elif key == "M":
            m0 = d["rates"]["mrp"]
            ctr = (left_vals.index(m0), 0) if m0 in left_vals else None
        else:
            if cap:
                ctr = None  # base path is not uniform 2027~2030, so no grid cell equals the base model
            else:
                ctr = (left_vals.index(0.0), [v for _, v in top_vals].index(0.0))
        c.layout["dt"].append(
            {
                "key": key,
                "title": title,
                "range": f"Scenarios!{first}:{last}",
                "diff": diff,
                "first_rc": (hr + 1, 1),
                "shape": (nr, nc),
                "engine": {(i, j): grid[gkey(i, j)] for i in range(nr) for j in range(nc)},
                "center": None if ctr is None else f"Scenarios!{a1(hr + 1 + ctr[0], 1 + ctr[1], True)}",
                "engine_center": None if ctr is None else f"Scenarios!{a1(hr + 1 + ctr[0], ec0 + 1 + ctr[1], True)}",
            }
        )
        if key == "C":
            c.layout["waccg_center"] = c.layout["dt"][-1]["engine_center"]
        r = hr + nr + 2
    s.text(
        r - 1,
        0,
        f"데이터 표는 현재 선택({base_lab}·SRP {srps[0]:.0%}이 기본)으로 계산된다. 엔진 격자는 기본·SRP 0% 값이라 선택이 같을 때만 비교한다. "
        "엑셀 계산 옵션이 '데이터 표 제외 자동'이면 F9로 다시 계산",
        "note",
    )
    return r + 1
