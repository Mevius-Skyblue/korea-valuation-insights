"""Output sheets: Peers, Premium, Scenarios, Football, Checks.

Peers      multiples from the Inputs peer table, N/M when the denominator <= 0, QUARTILE.INC (= pandas linear quantile)
           -> SOTP per share (p3c1.sotp_from_multiple definitions)
Premium    D6 application rule rebuilt as a formula (method + reason) -> block price per share = 20-day VWAP x (1 + q)
Scenarios  live 4 scenarios x 3 SRP table (Scen_Calc) + engine-value tables (labelled, not formulas)
Football   ranges by method, scatter chart reading the table cells, close price line
Checks     check list and the master check (all OK -> OK). INFO rows compare with the engine (stale after input edits)
"""

from __future__ import annotations

from src.excel.context import Ctx
from src.excel.writer import a1, col


def _v(s, r, label, formula, kind, unit="", name=None, note="", bold=False, c0=0):
    s.text(r, c0, label, "bold" if bold else "label")
    if unit:
        s.text(r, c0 + 1, unit, "note")
    ref = s.fx(r, c0 + 2, formula, kind, name=name, bold=bold)
    if note:
        s.text(r, c0 + 3, note, "note")
    return ref


# ---------------------------------------------------------------- Peers

MULTS = [
    ("EV/Sales", "ev", "revenue", "ev_sales"),
    ("EV/EBITDA", "ev", "ebitda", "ev_ebitda"),
    ("PER", "equity", "ni", "per"),
    ("PBR", "equity", "equity", "pbr"),
]


def peers(c: Ctx):
    d, s = c.d, c.sheet("Peers")
    cap = d["type"] == "scenario_capex"
    pre = any("ebitda_pre" in p for p in d["peers"])
    s.widths({0: 16, 1: 9, 2: 6, **{j: 11 for j in range(3, 28)}})
    s.text(0, 0, "Peers — 피어 배수 (LTM, " + ("SOTP 구조로" if cap else "연결 브리지로") + " 주당 환산)", "title")
    s.text(
        1,
        0,
        "배수 = EV(또는 시가총액) ÷ LTM 지표. 분모 ≤ 0이면 N/M, 배수 ≤ 0(음의 EV)은 통계에서 제외(엔진과 같음). 포함 = core+extended. "
        "사분위 = QUARTILE.INC(pandas 선형 보간과 같음)",
        "note",
    )
    if d.get("peer_relax"):  # P7-B5 peer_relax step shown
        s.text(2, 0, d["peer_relax"], "note")
    if d.get("public"):  # P7-C1 public mode: quartile multiples from Inputs 표 P (no per-peer rows)
        return _peers_public(c, s, cap)
    hdr = [
        "회사",
        "등급",
        "포함",
        "시가총액",
        "총차입금",
        "현금성",
        "비영업",
        "비지배",
        "EV",
        "매출",
        "EBITDA",
        "지배순이익",
        "지배지분",
        "EV/Sales",
        "EV/EBITDA",
        "PER",
        "PBR",
        "EV/Sales 포함",
        "EV/EBITDA 포함",
        "PER 포함",
        "PBR 포함",
        "엔진 EV/Sales",
        "엔진 EV/EBITDA",
        "엔진 PER",
        "엔진 PBR",
    ] + (["EV/EBITDA(D&A 보완 전)", "보완 전 포함"] if pre else [])
    for j, h in enumerate(hdr):
        s.text(3, j, h, "header")
    rows = c.layout["peer_rows"]
    r0 = 4
    for i, ir in enumerate(rows):
        r = r0 + i
        p = d["peers"][i]
        s.fx(r, 0, f"=Inputs!{a1(ir, 0)}", "gen")
        s.fx(r, 1, f"=Inputs!{a1(ir, 1)}", "gen")
        s.fx(r, 2, f"=Inputs!{a1(ir, 2)}", "int")
        for j, cc in zip(range(3, 8), range(4, 9)):
            s.fx(r, j, f"=Inputs!{a1(ir, cc)}", "mn")
        s.fx(r, 8, f"={a1(r, 3)}+{a1(r, 4)}-{a1(r, 5)}-{a1(r, 6)}+{a1(r, 7)}", "mn")
        for j, cc in zip(range(9, 13), range(9, 13)):
            s.fx(r, j, f"=Inputs!{a1(ir, cc)}", "mn")
        num = {"ev": a1(r, 8), "equity": a1(r, 3)}
        den = {"revenue": a1(r, 9), "ebitda": a1(r, 10), "ni": a1(r, 11), "equity": a1(r, 12)}
        for m, (_nm, kind, dk, ek) in enumerate(MULTS):
            dd = den[dk]
            s.fx(r, 13 + m, f'=IF(AND(ISNUMBER({dd}),{dd}>0),{num[kind]}/{dd},"N/M")', "x")
            # P7-B F2: only positive multiples count, as in the engine (p3c1.multiple_stats); a negative EV is excluded
            s.fx(r, 17 + m, f'=IF(AND({a1(r, 2)}=1,ISNUMBER({a1(r, 13 + m)}),N({a1(r, 13 + m)})>0),{a1(r, 13 + m)},"")', "x")
            s.eng(r, 21 + m, p["engine"][ek], "x")
        if pre:
            e2 = f"Inputs!{a1(ir, 14)}"
            s.fx(r, 25, f'=IF(AND(ISNUMBER({e2}),N({e2})>0),{a1(r, 8)}/{e2},"N/M")', "x")
            s.fx(r, 26, f'=IF(AND({a1(r, 2)}=1,ISNUMBER({a1(r, 25)}),N({a1(r, 25)})>0),{a1(r, 25)},"")', "x")
    r1 = r0 + len(rows) - 1
    s.engine_range(r0, 21, r1, 24)
    r = r1 + 2
    M = _peer_metrics(c, s, r)
    r = M.pop("_next")
    s.text(r, 0, "배수 요약 → 주당 가치", "subtitle")
    hdr2 = [
        "배수",
        "",
        "n",
        "q25",
        "중앙값",
        "q75",
        "대상 지표",
        "주당 q25(원)",
        "주당 중앙값(원)",
        "주당 q75(원)",
        "경고",
        "엔진 주당 q25",
        "엔진 주당 중앙값",
        "엔진 주당 q75",
    ]
    for j, h in enumerate(hdr2):
        s.text(r + 1, j, h, "header")
    out = {}
    eng = d["engine"]["multiples"]
    specs = [(nm, kind, dk, 17 + m) for m, (nm, kind, dk, ek) in enumerate(MULTS)]
    if pre:
        specs.append(("EV/EBITDA(보완 전)", "ev", "ebitda", 26))
    for m, (nm, kind, dk, cc) in enumerate(specs):
        rr = r + 2 + m
        rng = f"{a1(r0, cc)}:{a1(r1, cc)}"
        s.text(rr, 0, nm, "bold")
        s.fx(rr, 2, f"=COUNT({rng})", "int")
        nn = a1(rr, 2)
        s.fx(rr, 3, f'=IF({nn}=0,"N/M",_xlfn.QUARTILE.INC({rng},1))', "x")
        s.fx(rr, 4, f'=IF({nn}=0,"N/M",MEDIAN({rng}))', "x", name="PeerEvEbitdaMed" if nm == "EV/EBITDA" else None)
        s.fx(rr, 5, f'=IF({nn}=0,"N/M",_xlfn.QUARTILE.INC({rng},3))', "x")
        s.fx(rr, 6, f"={M[dk]}", "mn")
        for q in range(3):
            mu = a1(rr, 3 + q)
            add = "BridgeAdj" if kind == "ev" else "EqAddOn"  # EV route: + items outside EV; equity route: + listed stake (SOTP)
            # P7-B2 B2-F2: a multiple applied to a non-positive own metric is N/M (as in the engine)
            s.fx(
                rr,
                7 + q,
                f'=IF(OR({nn}=0,NOT(ISNUMBER({a1(rr, 6)})),N({a1(rr, 6)})<=0),"N/M",({mu}*{a1(rr, 6)}+{add})*MnToWon/Shares)',
                "won",
            )
        s.fx(rr, 10, f'=IF({nn}<PeerNWarn,"n<"&PeerNWarn,"")', "gen")
        if nm in eng:
            for q, qk in enumerate(("ps_q25", "ps_median", "ps_q75")):
                s.eng(rr, 11 + q, eng[nm][qk], "won")
            s.engine_range(rr, 11, rr, 13)
        out[nm] = {
            "row": rr,
            "n": f"Peers!{a1(rr, 2, True)}",
            **{q: f"Peers!{a1(rr, 7 + i, True)}" for i, q in enumerate(("q25", "med", "q75"))},
            "mult": {q: f"Peers!{a1(rr, 3 + i, True)}" for i, q in enumerate(("q25", "med", "q75"))},
        }
    c.range_name("PeerSummary", "Peers", a1(r + 2, 0), a1(r + 1 + len(specs), 10))
    s.text(
        r + 2 + len(specs),
        0,
        (
            "EV 배수: 배수 × 모회사 지표 + EV 밖 항목(종속회사 지분 시가 + 모회사 순현금 + 비영업). "
            "PER·PBR: 배수 × 모회사 순이익(자본 − 종속기업투자) + 지분 시가"
        )
        if cap
        else (
            "EV 배수: 배수 × 대상 LTM 지표 + EV 밖 항목(− 순차입금 + 비영업 − 비지배, Bridge). PER × 지배순이익, PBR × 지배지분. "
            "보완 전 = P3-C2 피어 표(EBITDA n=5), 수렴 시험의 사전 고정 1차 판정에 쓴 표"
        ),
        "note",
    )
    c.layout["peer_out"] = out


def _peers_public(c: Ctx, s, cap: bool):
    """Public mode: n and quartile multiples are Inputs cells (PC aggregates); the per-share formulas are the same as PC mode."""
    d = c.d
    s.text(2, 0, "공개 모드: 피어별 시가총액·배수는 표시하지 않고 사분위 배수만 입력 칸(Inputs 표 P)으로 둔다", "note")
    M = _peer_metrics(c, s, 4)
    r = M.pop("_next")
    s.text(r, 0, "배수 요약 → 주당 가치", "subtitle")
    hdr2 = [
        "배수",
        "",
        "n",
        "q25",
        "중앙값",
        "q75",
        "대상 지표",
        "주당 q25(원)",
        "주당 중앙값(원)",
        "주당 q75(원)",
        "경고",
        "엔진 주당 q25",
        "엔진 주당 중앙값",
        "엔진 주당 q75",
    ]
    for j, h in enumerate(hdr2):
        s.text(r + 1, j, h, "header")
    out = {}
    eng = d["engine"]["multiples"]
    pr = c.layout["peer_pub_rows"]
    kinds = {nm: (kind, dk) for nm, kind, dk, ek in MULTS} | {"EV/EBITDA(보완 전)": ("ev", "ebitda")}
    for m, nm in enumerate(pr):
        kind, dk = kinds[nm]
        rr, ir = r + 2 + m, pr[nm]
        s.text(rr, 0, nm, "bold")
        s.fx(rr, 2, f"=Inputs!{a1(ir, 1)}", "int")
        nn = a1(rr, 2)
        for q in range(3):
            s.fx(
                rr,
                3 + q,
                f'=IF(OR({nn}=0,NOT(ISNUMBER(Inputs!{a1(ir, 2 + q)}))),"N/M",Inputs!{a1(ir, 2 + q)})',
                "x",
                name="PeerEvEbitdaMed" if (nm == "EV/EBITDA" and q == 1) else None,
            )
        s.fx(rr, 6, f"={M[dk]}", "mn")
        for q in range(3):
            mu = a1(rr, 3 + q)
            add = "BridgeAdj" if kind == "ev" else "EqAddOn"
            s.fx(
                rr,
                7 + q,
                f'=IF(OR({nn}=0,NOT(ISNUMBER({a1(rr, 6)})),N({a1(rr, 6)})<=0),"N/M",({mu}*{a1(rr, 6)}+{add})*MnToWon/Shares)',
                "won",
            )
        s.fx(rr, 10, f'=IF({nn}<PeerNWarn,"n<"&PeerNWarn,"")', "gen")
        if nm in eng:
            for q, qk in enumerate(("ps_q25", "ps_median", "ps_q75")):
                s.eng(rr, 11 + q, eng[nm][qk], "won")
            s.engine_range(rr, 11, rr, 13)
        out[nm] = {
            "row": rr,
            "n": f"Peers!{a1(rr, 2, True)}",
            **{q: f"Peers!{a1(rr, 7 + i, True)}" for i, q in enumerate(("q25", "med", "q75"))},
            "mult": {q: f"Peers!{a1(rr, 3 + i, True)}" for i, q in enumerate(("q25", "med", "q75"))},
        }
    c.range_name("PeerSummary", "Peers", a1(r + 2, 0), a1(r + 1 + len(pr), 10))
    s.text(
        r + 2 + len(pr),
        0,
        "EV 배수: 배수 × 대상 LTM 지표 + EV 밖 항목(− 순차입금 + 비영업 − 비지배, Bridge). PER × 지배순이익, PBR × 지배지분",
        "note",
    )
    c.layout["peer_out"] = out


def _peer_metrics(c: Ctx, s, r) -> dict:
    d = c.d
    fs, L = c.layout["fs_refs"], d["meta"]["ltm_year"]
    fy, h1, h0 = f"FY{L - 1}", f"H1{L}", f"H1{L - 1}"
    M = {}
    if d["type"] == "scenario_capex":
        seg = c.layout["seg_refs"]
        s.text(r, 0, "모회사 LTM 지표 (SOTP 분모)", "subtitle")
        o = lambda a, k: fs[("OFS", k, a)]  # noqa: E731
        ltm_seg = lambda it: f"{seg[('parent', it, 'FY2025')]}+{seg[('parent', it, '1H26')]}-{seg[('parent', it, '1H25')]}"  # noqa: E731
        met = {
            "revenue": ("모회사 매출(부문 LTM)", f"={ltm_seg('revenue')}"),
            "op": ("모회사 영업이익(부문 LTM)", f"={ltm_seg('op')}"),
            "dna": ("모회사 D&A(별도 LTM)", f"={o('dna', fy)}+{o('dna', h1)}-{o('dna', h0)}"),
            "ebitda": ("모회사 EBITDA", "={op}+{dna}"),
            "ni": ("모회사 순이익(별도 LTM)", f"={o('net_income', fy)}+{o('net_income', h1)}-{o('net_income', h0)}"),
            "equity": ("모회사 자본 − 종속기업투자(별도 6/30)", f"={o('total_equity', h1)}-InvSubsBook"),
        }
    else:
        s.text(r, 0, "대상 LTM 지표 (연결, D&A는 점검 규칙 적용)", "subtitle")
        o = lambda a, k: fs[("CFS", k, a)]  # noqa: E731
        lt = lambda a: f"{o(a, fy)}+{o(a, h1)}-{o(a, h0)}"  # noqa: E731
        ok_h1 = (
            f"AND({o('dna_dep', h1)}<>0,{o('dna_dep', h0)}<>0,{o('dna', h1)}/{o('dna', fy)}>=DnaH1Lo,{o('dna', h1)}/{o('dna', fy)}<=DnaH1Hi,"
            f"{o('dna', h0)}/{o('dna', fy)}>=DnaH1Lo,{o('dna', h0)}/{o('dna', fy)}<=DnaH1Hi)"
        )
        met = {
            "revenue": ("매출(연결 LTM)", f"={lt('revenue')}"),
            "op": ("영업이익(연결 LTM)", f"={lt('operating_income')}"),
            "dna": (
                "D&A LTM(반기 값이 3개월로 보이면 FY 값, D&A/매출 1~20% 밖이면 N/M)",
                f'=IF(OR({o("dna_dep", fy)}=0,{o("dna", fy)}/{o("revenue", fy)}<DnaRatioLo,{o("dna", fy)}/{o("revenue", fy)}>DnaRatioHi),"N/M",'
                f"IF({ok_h1},{lt('dna')},{o('dna', fy)}))",
            ),
            "ebitda": ("EBITDA(LTM)", '=IF(ISNUMBER({dna}),{op}+{dna},"N/M")'),
            "ni": (
                "지배주주순이익(LTM, 없으면 당기순이익)",
                f"=IF(({lt('net_income_parent')})<>0,{lt('net_income_parent')},{lt('net_income')})",
            ),
            "equity": (
                "지배주주지분(6/30, 없으면 자본총계 − 비지배)",
                f"=IF({o('equity_parent', h1)}<>0,{o('equity_parent', h1)},{o('total_equity', h1)}-{o('nci', h1)})",
            ),
        }
    for i, (k, (lab, f)) in enumerate(met.items()):
        rr = r + 1 + i
        M[k] = a1(rr, 2)
        _v(s, rr, lab, f.format(op=M.get("op", ""), dna=M.get("dna", "")), "mn", "백만원")
    M["_next"] = r + 2 + len(met)
    return M


# ---------------------------------------------------------------- Premium


def premium(c: Ctx):
    d, s = c.d, c.sheet("Premium")
    s.widths({0: 46, 1: 9, 2: 14, 3: 14, 4: 14, 5: 14, 6: 40})
    if d["premium"].get("withheld"):  # P7-C3 public deployment: no premium aggregates, no block price
        s.text(0, 0, "Premium — 공개 배포에서는 비공개", "title")
        s.text(1, 0, d["premium"]["note"] + ". 블록 1주당 가격·D6 적용 규칙은 PC 모드에서 계산한다", "note")
        r = 3
        s.text(r, 0, "상증법 최대주주 할증 비교 (⚠️ 원문 미확인, 중소·일정 중견기업 제외 가능)", "subtitle")
        _v(s, r + 1, "할증 적용: VWAP × (1 + 할증률)", "=VWAP20*(1+TaxPrem)", "won", "원")
        _v(s, r + 2, "할증 적용: 종가 × (1 + 할증률)", "=Close*(1+TaxPrem)", "won", "원")
        _v(s, r + 3, "할증 제외(VWAP)", "=VWAP20", "won", "원")
        s.text(r + 4, 0, "VWAP·종가는 사용자 입력 값(공개 모드)", "note")
        return
    s.text(0, 0, "Premium — 지배 블록 1주당 가격 범위 (경영권 프리미엄 DB 집계값)", "title")
    s.text(
        1,
        0,
        "블록 1주당 = 20거래일 VWAP × (1 + 프리미엄). 지분 전체·DCF 가치에 (1+프리미엄)을 곱하지 않는다. 프리미엄 DB는 분위수·표본 수만",
        "note",
    )
    r = 3
    s.text(r, 0, "D6 적용 규칙 (config/premium_p2c3.yaml application_rule, 사용자 결정 2026-10-03)", "subtitle")
    rows = [
        ("pct", "시총 백분위", "=Prem_Pct", "days", None),
        ("mkt", "시장", "=Prem_Market", "gen", None),
        ("adopt", "회귀 채택(CV 개선 ≥ 기준, 1=예)", "=IF(Prem_CV>=Prem_Thr,1,0)", "int", None),
        ("gap", "회귀 q50 − 이웃 중앙값(절댓값)", "=ABS(Prem_REG_q50-Prem_NEI_q50)", "pct1", None),
        ("gw", "차이 경고(> 10%p, 1=예)", "=IF(ABS(Prem_REG_q50-Prem_NEI_q50)>Prem_GapWarn,1,0)", "int", None),
        (
            "method",
            "method",
            '=IF(Prem_Market="KOSPI","neighbours",IF(Prem_Pct>=Prem_TopBand,"neighbours",IF({adopt}=1,IF({gw}=1,"neighbours","regression"),"band_table")))',
            "gen",
            "PremMethod",
        ),
        (
            "reason",
            "이유",
            '=IF(Prem_Market="KOSPI","rule_market",IF(Prem_Pct>=Prem_TopBand,"rule_top_band",IF({adopt}=1,IF({gw}=1,"warning","cv_adopted"),"cv_not_adopted")))',
            "gen",
            "PremReason",
        ),
    ]
    V = {k: r + 1 + i for i, (k, *_x) in enumerate(rows)}
    for k, lab, f, kind, nm in rows:
        _v(s, V[k], lab, f.format(adopt=a1(V["adopt"], 2), gw=a1(V["gw"], 2)), kind, "", nm, bold=k in ("method", "reason"))
    s.text(V["method"], 3, "엔진(predict.premium_range)", "note")
    s.eng(V["method"], 4, d["premium"]["method"])
    s.eng(V["reason"], 4, d["premium"]["reason"])
    s.engine_range(V["method"], 4, V["reason"], 4)
    c.layout["prem_engine"] = (f"Premium!{a1(V['method'], 4, True)}", f"Premium!{a1(V['reason'], 4, True)}")
    s.text(
        V["reason"] + 1,
        0,
        "순서: KOSPI → 이웃(rule_market) / KOSDAQ 백분위 ≥ 80 → 이웃(rule_top_band) / 회귀 채택 + 차이 경고 → 이웃(warning) / "
        "회귀 채택 → 회귀(cv_adopted) / 미채택 → 구간 표(cv_not_adopted)",
        "note",
    )
    r = V["reason"] + 3
    for j, h in enumerate(["프리미엄 분위", "", "q25", "q50", "q75", "표본 수"]):
        s.text(r, j, h, "header")
    srcs = [
        ("이웃 50건", "NEI", "=Prem_NB_n"),
        ("분위 회귀(참고, 항상 표시)", "REG", '="회귀"'),
        (f"구간 표 {d['premium']['band']['band']}", "BAN", "=Prem_BAN_n"),
    ]
    for i, (lab, key, nf) in enumerate(srcs):
        rr = r + 1 + i
        s.text(rr, 0, lab)
        for q, qq in enumerate(("q25", "q50", "q75")):
            s.fx(rr, 2 + q, f"=Prem_{key}_{qq}", "pct1")
        s.fx(rr, 5, nf, "int")
    ra = r + 4
    s.text(ra, 0, "적용(D6 method)", "bold")
    for q in range(3):
        nb, rg, bd = a1(r + 1, 2 + q), a1(r + 2, 2 + q), a1(r + 3, 2 + q)
        s.fx(
            ra,
            2 + q,
            f'=IF(PremMethod="neighbours",{nb},IF(PremMethod="regression",{rg},{bd}))',
            "pct1",
            name=f"PremQ{q + 1}",
            bold=True,
        )
    s.fx(
        ra,
        5,
        f'=IF(PremMethod="neighbours",{a1(r + 1, 5)},IF(PremMethod="band_table",{a1(r + 3, 5)},"회귀"))',
        "int",
        name="PremN",
    )
    r = ra + 2
    s.text(r, 0, "블록 1주당 가격 (원)", "subtitle")
    _v(s, r + 1, "20거래일 VWAP(평가기준일까지, 한국거래소 통계정보)", "=VWAP20", "won", "원")
    _v(s, r + 2, "기준일 종가", "=Close", "won", "원")
    for q in range(3):
        _v(
            s,
            r + 3 + q,
            f"블록 1주당 q{(25, 50, 75)[q]} = VWAP × (1 + 프리미엄)",
            f"=VWAP20*(1+PremQ{q + 1})",
            "won",
            "원",
            f"Block_q{q + 1}",
            bold=q == 1,
        )
    eng = d["engine"]["block"]
    for q, k in enumerate(("q25", "q50", "q75")):
        s.text(r + 3 + q, 3, "엔진", "note")
        s.eng(r + 3 + q, 4, eng[k], "won")
    s.engine_range(r + 3, 4, r + 5, 4)
    c.layout["block_engine"] = [f"Premium!{a1(r + 3 + q, 4, True)}" for q in range(3)]
    r += 7
    s.text(r, 0, "상증법 최대주주 할증 비교 (⚠️ 원문 미확인, 중소·일정 중견기업 제외 가능)", "subtitle")
    _v(s, r + 1, "할증 적용: VWAP × (1 + 할증률)", "=VWAP20*(1+TaxPrem)", "won", "원")
    _v(s, r + 2, "할증 적용: 종가 × (1 + 할증률)", "=Close*(1+TaxPrem)", "won", "원")
    _v(s, r + 3, "할증 제외(VWAP)", "=VWAP20", "won", "원")
    s.text(r + 4, 0, "세법 평가액은 평가기준일 전후 2개월 평균 종가가 원칙 — 여기서는 비교용 단순화", "note")
    s.text(r + 6, 0, "엔진 경고(predict.premium_range): " + ("; ".join(d["premium"]["warnings"]) or "없음"), "note")


# ---------------------------------------------------------------- Scenarios

ENGINE_METRICS = [
    ("per_share", "주당 가치(원, Gordon)", "won", "PerShare"),
    ("wacc", "WACC", "pct3", "WACC"),
    ("ronic", "RONIC", "pct", "RONIC"),
    ("tv_share", "영구가치 비중", "pct1", "TVShare"),
    ("implied_multiple", "Gordon 함의 EV/EBITDA", "x", "ImpliedMultiple"),
    ("per_share_exit", "주당 가치(원, Exit)", "won", "PerShareExit"),
    ("ev930", "EV(평가기준일, 백만원)", "mn", "EV_930"),
    ("implied_g", "Exit 함의 영구성장률", "pct", "ImpliedG_Exit"),
    ("tv_share_exit", "영구가치 비중(Exit)", "pct1", "TVShare_Exit"),
]


# ---------------------------------------------------------------- Football


def football(c: Ctx):
    d, s = c.d, c.sheet("Football")
    keys, labels = d["excel"]["scenarios"], d["excel"]["scenario_labels"]
    ns = len(d["rates"]["srp_list"])
    s.widths({0: 20, 1: 26, 2: 12, 3: 12, 4: 12, 5: 6, 6: 6, 7: 60})
    s.text(0, 0, "Football — 방법별 주당 범위 (원, 가정 하 추정·참고 범위)", "title")
    s.text(
        1,
        0,
        "막대 = 낮음~높음, 점 = 대표값, 빨간 점선 = 기준일 종가. 투자 권유 아님. 시세 자료 출처: 한국거래소 통계정보",
        "note",
    )
    for j, h in enumerate(["그룹", "항목", "낮음", "높음", "대표", "y", "y", "정의"]):
        s.text(3, j, h, "header")
    g0 = c.layout["scen_grids"]["ps"]
    po = c.layout["peer_out"]
    cap = d["type"] == "scenario_capex"
    grp_dcf = "DCF(SOTP)" if d["meta"]["structure"] == "sotp" else "DCF(연결)"
    grp_rel = "상대가치(SOTP, 피어 LTM)" if d["meta"]["structure"] == "sotp" else "상대가치(연결, 피어 LTM)"
    items = []
    for i, k in enumerate(keys):
        rr = g0[0] + i
        row = f"Scenarios!{a1(rr, 1, True)}:{a1(rr, ns, True)}"
        items.append(
            (
                grp_dcf,
                f"DCF {labels[k]}",
                f"=MIN({row})",
                f"=MAX({row})",
                f"=Scenarios!{a1(rr, 1, True)}",
                "SRP 2%~0% 범위, 대표 = SRP 0%" + (" · 증권사 추정 역산(대표 아님)" if k == "broker" else ""),
            )
        )
    for nm in ("EV/EBITDA", "PER", "EV/Sales", "PBR"):
        p = po[nm]
        items.append(
            (
                grp_rel,
                f'="{nm} (n="&{p["n"]}&")"',
                f"={p['q25']}",
                f"={p['q75']}",
                f"={p['med']}",
                "피어 사분위 × 모회사 지표 + 지분 시가(+순현금)" if cap else "피어 사분위 × 대상 LTM 지표 + EV 밖 항목",
            )
        )
    if not d["premium"].get("withheld"):  # P7-C3 public deployment: no block price
        items.append(
            (
                "블록 거래 가격(참고)",
                "지배 블록 1주당",
                "=Block_q1",
                "=Block_q3",
                "=Block_q2",
                "20일 VWAP × (1 + 프리미엄, D6). 지분 전체 가치 아님",
            )
        )
    items.append(
        (
            "참고",
            "순자산가치(장부)",
            "=NavPerShare",
            "=NavPerShare",
            "=NavPerShare",
            "지배주주지분 장부 ÷ 주식수(재평가 없음, 자산가치 접근 참고)",
        )
    )
    if d.get("broker_targets"):
        items.append(("참고", "증권사 목표주가", "=TP_low", "=TP_high", "=TP_consensus", "2026-08~09 범위(문서 근거 🔸)"))
    r0 = 4
    nrow = len(items)
    for i, (grp, lab, lo, hi, mid, dfn) in enumerate(items):
        r = r0 + i
        s.text(r, 0, grp)
        if lab.startswith("="):
            s.fx(r, 1, lab, "gen")
        else:
            s.text(r, 1, lab)
        s.fx(r, 2, lo, "won")
        s.fx(r, 3, hi, "won")
        s.fx(r, 4, mid, "won")
        s.fx(r, 5, f"=ROWS({a1(r, 1)}:{a1(r0 + nrow - 1, 1, True)})", "int")
        s.fx(r, 6, f"={a1(r, 5)}", "int")
        s.text(r, 7, dfn, "note")
    rc = r0 + nrow + 1
    s.text(rc, 1, "기준일 종가 선", "bold")
    s.fx(rc, 2, "=Close", "won")
    s.fx(rc, 3, "=Close", "won")
    s.const(rc, 5, 0, "int")
    s.fx(rc, 6, f"=ROWS({a1(r0, 1)}:{a1(r0 + nrow - 1, 1)})+1", "int")
    s.fx(rc, 4, '="기준일 종가 "&TEXT(Close,"#,##0")&"원"', "gen")
    c.layout["football_rows"] = (r0, r0 + nrow - 1)
    c.layout["football_items"] = [(it[0], it[1]) for it in items]
    c.range_name("FootballTable", "Football", a1(r0, 0), a1(r0 + nrow - 1, 4))
    ch = c.book.wb.add_chart({"type": "scatter", "subtype": "straight"})
    pal = {grp_dcf: "#2A6F97", grp_rel: "#61A5C2", "블록 거래 가격(참고)": "#E09F3E", "참고": "#9E9E9E"}
    for i, (grp, *_x) in enumerate(items):
        r = r0 + i
        ch.add_series(
            {
                "name": f"=Football!{a1(r, 1, True)}",
                "categories": f"=Football!{a1(r, 2, True)}:{a1(r, 3, True)}",
                "values": f"=Football!{a1(r, 5, True)}:{a1(r, 6, True)}",
                "line": {"color": pal.get(grp, "#888888"), "width": 9},
                "marker": {"type": "none"},
                "data_labels": {
                    "custom": [{"value": f"=Football!{a1(r, 1, True)}"}, {"delete": True}],
                    "position": "left",
                    "font": {"size": 8},
                },
            }
        )
    ch.add_series(
        {
            "name": "대표값",
            "categories": f"=Football!{a1(r0, 4, True)}:{a1(r0 + nrow - 1, 4, True)}",
            "values": f"=Football!{a1(r0, 5, True)}:{a1(r0 + nrow - 1, 5, True)}",
            "line": {"none": True},
            "marker": {"type": "diamond", "size": 7, "fill": {"color": "#000000"}, "border": {"color": "#000000"}},
        }
    )
    ch.add_series(
        {
            "name": "기준일 종가",
            "categories": f"=Football!{a1(rc, 2, True)}:{a1(rc, 3, True)}",
            "values": f"=Football!{a1(rc, 5, True)}:{a1(rc, 6, True)}",
            "line": {"color": "#C00000", "width": 1.5, "dash_type": "dash"},
            "marker": {"type": "none"},
            "data_labels": {
                "custom": [{"delete": True}, {"value": f"=Football!{a1(rc, 4, True)}"}],
                "position": "right",
                "font": {"size": 8, "color": "#C00000"},
            },
        }
    )
    ch.set_title({"name": f"{d['meta']['name']} 풋볼필드 (초안, 기준일 {d['meta']['as_of']})", "name_font": {"size": 11}})
    ch.set_x_axis(
        {"name": "주당 원 (가정 하 추정·참고 범위)", "num_format": "#,##0", "min": 0, "major_gridlines": {"visible": True}}
    )
    ch.set_y_axis({"visible": False, "min": 0, "max": nrow + 1, "major_gridlines": {"visible": False}})
    ch.set_legend({"none": True})
    ch.set_size({"width": 860, "height": 470})
    s.ws.insert_chart(rc + 2, 1, ch)


# ---------------------------------------------------------------- Convergence

RF_CONV_RULE = (
    "기본 DCF 주당가치(SRP 0%, Gordon)가 피어 EV/EBITDA 사분위 주당 범위 [q25, q75] 안이면 '수렴', 밖이면 '미수렴 → 원인 분해'. "
    "기준일 종가 괴리는 표시만 (P3-C3 보고서 2.4, 기준 그대로)"
)


def convergence(c: Ctx):
    """Pre-registered convergence test: verdicts as recorded by the engine (C2 first pre-registered, C3) next to the same
    test recomputed live. Must be written before Checks (its INFO rows are added there)."""
    d, s = c.d, c.sheet("Convergence")
    e = d["engine"]["convergence"]
    labels = d["excel"]["scenario_labels"]
    s.widths({0: 46, 1: 14, 2: 14, 3: 14, 4: 8, 5: 22, 6: 50})
    s.text(0, 0, "Convergence — 수렴 시험 (사전 고정 기준)", "title")
    s.text(
        1,
        0,
        "판정 = 엔진 기록값(회색). 아래 '살아 있는 모델'은 같은 기준을 지금 엑셀 값으로 다시 계산한 것 — 일치 여부는 Checks INFO",
        "note",
    )
    s.text(3, 0, "기준(사전 고정)", "bold")
    s.text(3, 1, d.get("convergence_rule") or RF_CONV_RULE, "wrap")
    s.ws.set_row(3, 45)
    for j, h in enumerate(["엔진 기록", "DCF 주당(원)", "사분위 q25(원)", "사분위 q75(원)", "n", "판정", "비고"]):
        s.text(5, j, h, "header")
    recs = [
        (
            "C2 — 사전 고정 1차 판정",
            e["c2"],
            e["n5"] or e["n10"],
            "보완 전 피어 표(EBITDA n=5)" if e["n5"] else "P3-B2/C1 규칙(RONIC 출발점 mixed)",
        ),
        ("C3 — 공통 규칙 수정 후", e["c3"], e["n10"], "D&A 보완 후 피어 표" if e["n5"] else "P3-C3 공통 규칙"),
    ]
    cells = {}
    for i, (lab, v, rng, note) in enumerate(recs):
        r = 6 + i
        s.text(r, 0, lab)
        s.eng(r, 1, v["per_share"], "won")
        s.eng(r, 2, rng["q25"], "won")
        s.eng(r, 3, rng["q75"], "won")
        s.eng(r, 4, rng["n"], "int")
        s.eng(r, 5, v["verdict"])
        s.text(r, 6, note, "note")
        cells[i] = {k: f"Convergence!{a1(r, j, True)}" for k, j in (("ps", 1), ("q25", 2), ("q75", 3), ("verdict", 5))}
    s.engine_range(6, 1, 7, 5)
    if e["n5"]:
        s.text(8, 0, "같은 기준, 보완 전 표로 본 C3")
        s.eng(8, 2, e["n5"]["q25"], "won")
        s.eng(8, 3, e["n5"]["q75"], "won")
        s.eng(8, 4, e["n5"]["n"], "int")
        s.engine_range(8, 2, 8, 4)
    r = 10
    s.text(r, 0, "살아 있는 모델(현재 입력)", "subtitle")
    for j, h in enumerate(["항목", "DCF 주당(원)", "사분위 q25(원)", "사분위 q75(원)", "n", "판정"]):
        s.text(r + 1, j, h, "header")
    po = c.layout["peer_out"]
    base_ps = f'INDEX(ScenGridPS,MATCH("{labels["base"]}",ScenNames,0),1)'
    live = [("기본 DCF(SRP 열 1) vs 피어 EV/EBITDA 사분위", po["EV/EBITDA"])]
    if "EV/EBITDA(보완 전)" in po:
        live.append(("기본 DCF(SRP 열 1) vs 보완 전 표 사분위", po["EV/EBITDA(보완 전)"]))
    lv = {}
    for i, (lab, p) in enumerate(live):
        rr = r + 2 + i
        s.text(rr, 0, lab)
        s.fx(rr, 1, f"={base_ps}", "won")
        s.fx(rr, 2, f"={p['q25']}", "won")
        s.fx(rr, 3, f"={p['q75']}", "won")
        s.fx(rr, 4, f"={p['n']}", "int")
        s.fx(
            rr,
            5,
            f'=IF(COUNT({a1(rr, 2)},{a1(rr, 3)})<2,"판정 불가(대상 지표 ≤ 0)",'
            f'IF(AND({a1(rr, 1)}>={a1(rr, 2)},{a1(rr, 1)}<={a1(rr, 3)}),"수렴","미수렴 → 원인 분해"))',
            "gen",
        )
        lv[i] = {k: f"Convergence!{a1(rr, j, True)}" for k, j in (("ps", 1), ("q25", 2), ("q75", 3), ("verdict", 5))}
    rr = r + 3 + len(live)
    s.text(rr, 0, "범위 밖 거리(원, 0 = 안)")
    s.fx(
        rr,
        1,
        f'=IFERROR(IF({lv[0]["ps"]}>{lv[0]["q75"]},{lv[0]["ps"]}-{lv[0]["q75"]},IF({lv[0]["ps"]}<{lv[0]["q25"]},{lv[0]["ps"]}-{lv[0]["q25"]},0)),"N/M")',
        "won",
    )
    s.text(rr + 1, 0, "기준일 종가 대비 기본 DCF(표시만)")
    s.fx(rr + 1, 1, f"={lv[0]['ps']}/Close-1", "pct1")
    note = (d.get("labels") or {}).get("conv_note", "")
    if e["n5"] and note:
        s.text(rr + 3, 0, note, "note")
    chk = [
        (
            f"수렴 시험: 살아 있는 C3 판정 = 엔진 기록({recs[1][0]})",
            f'=IF({lv[0]["verdict"]}={cells[1]["verdict"]},"OK","DIFF")',
            f"={lv[0]['verdict']}",
            f"={cells[1]['verdict']}",
        ),
        (
            "수렴 시험: 살아 있는 기본 DCF = 엔진 C3 주당",
            f'=IF(ABS({lv[0]["ps"]}-{cells[1]["ps"]})<=1,"OK","DIFF")',
            f"={lv[0]['ps']}",
            f"={cells[1]['ps']}",
        ),
        (
            "수렴 시험: 피어 EV/EBITDA 사분위 = 엔진 범위",
            f'=IFERROR(IF(MAX(ABS({lv[0]["q25"]}-{cells[1]["q25"]}),ABS({lv[0]["q75"]}-{cells[1]["q75"]}))<=1,"OK","DIFF"),'
            f'IF(COUNT({lv[0]["q25"]},{lv[0]["q75"]},{cells[1]["q25"]},{cells[1]["q75"]})=0,"OK","DIFF"))',
            f"={lv[0]['q25']}",
            f"={cells[1]['q25']}",
        ),
    ]
    if e["n5"]:
        chk.append(
            (
                "수렴 시험: 보완 전 표 사분위 = 엔진 C2 범위",
                f'=IFERROR(IF(MAX(ABS({lv[1]["q25"]}-{cells[0]["q25"]}),ABS({lv[1]["q75"]}-{cells[0]["q75"]}))<=1,"OK","DIFF"),'
                f'IF(COUNT({lv[1]["q25"]},{lv[1]["q75"]},{cells[0]["q25"]},{cells[0]["q75"]})=0,"OK","DIFF"))',
                f"={lv[1]['q25']}",
                f"={cells[0]['q25']}",
            )
        )
    c.layout["conv_checks"] = chk
    c.range_name("ConvEngine", "Convergence", a1(6, 0), a1(7, 5))
    c.range_name("ConvLive", "Convergence", a1(r + 2, 0), a1(r + 1 + len(live), 5))
    c.layout["conv_cells"] = {"engine": cells, "live": lv}


# ---------------------------------------------------------------- Checks


def checks(c: Ctx):
    d, s = c.d, c.sheet("Checks")
    s.widths({0: 5, 1: 56, 2: 9, 3: 16, 4: 16, 5: 8, 6: 50})
    s.text(0, 0, "Checks — 모델 점검", "title")
    s.text(
        1,
        0,
        "ERR가 하나라도 있으면 master check = ERR. WARN은 주의 표시, INFO는 엔진 값 대조(입력을 바꾸면 달라지는 것이 정상)",
        "note",
    )
    for j, h in enumerate(["#", "항목", "상태", "값", "기준·비교", "종류", "설명"]):
        s.text(4, j, h, "header")
    labels = d["excel"]["scenario_labels"]
    F, n = c.layout["fc_rows"], c.layout["n"]
    lastc = col(3 + n - 1)
    t0, t1 = c.layout["tax_rows"]
    taxc = ",".join(
        [f"Inputs!$B${t0 + 1}=0"]
        + [f"Inputs!$B${t0 + 1 + i}=Inputs!$C${t0 + i}" for i in range(1, t1 - t0 + 1)]
        + [f"ISBLANK(Inputs!$C${t1 + 1})"]
    )
    grids = c.layout["scen_grids"]
    wg = grids["wacc"]
    wrng = f"Scenarios!{a1(wg[0], 1, True)}:{a1(wg[2], wg[3], True)}"
    prow, pcol = c.layout["param_rows"], c.layout["param_cols"]
    gt_rng = (
        f"Forecast!{a1(prow['g_terminal'], min(pcol.values()), True)}:{a1(prow['g_terminal'], max(pcol.values()), True)}"
        if "g_terminal" in prow
        else "GTermCfg"
    )
    bv = c.layout["bridge_vals"]
    items = []

    def add(label, status, value="", basis="", kind="check", note=""):
        items.append((label, status, value, basis, kind, note))

    if d.get("sotp"):  # P7-B3 general SOTP checks
        add(
            "SOTP 이중 계산 점검: '종속' 투자 줄은 비영업 분류에 없음(시가·장부로 바꿔 넣음)",
            '=IF(COUNTIFS(BsClass,"non_operating",BsName,"*종속*")=0,"OK","ERR")',
            "=SotpSubLines",
            "=SotpBook",
        )
        add(
            "SOTP 단위 점검: 피투자회사 장부가 합계 ≤ '종속' 줄 × 1.02",
            '=IF(SotpBook<=SotpSubLines*1.02+0.01,"OK","WARN")',
            "=SotpBook",
            "=SotpSubLines",
            "warn",
            "출자현황 금액 단위나 이름 일치가 맞지 않으면 WARN",
        )
        add(
            "SOTP 상장 지분 = 보유 주식수 × 종가(직접 보유)",
            '=IF(ABS(SotpListed-SUMPRODUCT(SubShares,SubClose,SubListedDirect)/MnToWon)<0.001,"OK","ERR")',
            "=SotpListed",
        )
    if d["meta"]["structure"] == "sotp":
        add(
            "SOTP 합계 = 항목 합",
            '=IF(ABS(Equity-(EV_930+StakeValue+ParentNetCash+ParentNonOp-HQ_PV))<0.001,"OK","ERR")',
            "=Equity",
            "",
            "check",
            "Bridge 주식가치",
        )
    else:
        B = lambda k: f"Bridge!$C${bv[k] + 1}"  # noqa: E731
        adj = f"+{B('aff_adj')}" if "aff_adj" in bv else ""
        add(
            "주식가치 = EV − 순차입금 + 비영업 − 비지배(+ 대여금 조정)",
            f'=IF(ABS(Equity-(EV_930-NetDebt+{B("nonop")}-{B("nci")}{adj}))<0.001,"OK","ERR")',
            "=Equity",
            "",
            "check",
        )
        add(
            "순차입금 = 차입금 + 리스 − 현금성",
            f'=IF(ABS(NetDebt-({B("debt")}+{B("lease")}-{B("cash")}))<0.001,"OK","ERR")',
            "=NetDebt",
        )
    if c.layout.get("fund_row") is not None and "cash" in bv:  # P7-B3b loss path funding check (config/p7b3b.yaml c_funding)
        cash_ref = f"Bridge!$C${bv['cash'] + 1}"
        add(
            "적자 경로 자금 소요: −누적 FCF 최저 ≤ 현금성",
            f'=IF(-FundTrough<={cash_ref},"OK","WARN")',
            "=FundTrough",
            f"={cash_ref}",
            "warn",
            "WARN = 추가 자금 필요(희석 위험) — 판단 목록 1순위",
        )
    add(
        "EV ↔ 주식가치 왕복(주당 × 주식수 − EV 밖 항목 = EV)",
        '=IF(ABS(PerShare*Shares/MnToWon-BridgeAdj-EV_930)<0.01,"OK","ERR")',
        "=PerShare*Shares/MnToWon-BridgeAdj",
        "=EV_930",
    )
    add(
        "시나리오 표 선택 칸 = 살아 있는 모델(Bridge 주당)",
        '=IF(ABS(ScenSelPS-PerShare)<0.5,"OK","ERR")',
        "=ScenSelPS",
        "=PerShare",
    )
    add(
        "WACC > g (모든 시나리오·SRP, Gordon 조건)",
        f'=IF(MIN({wrng})>MAX({gt_rng}),"OK","ERR")',
        f"=MIN({wrng})",
        f"=MAX({gt_rng})",
    )
    if d.get("nci_path"):  # P7-B2: no listed subsidiary -> consolidated DCF − NCI (book) is allowed even if the rule says SOTP
        add(
            "구조 판단 규칙 = 설정한 평가 구조(비지배 허용 경로: 상장 종속회사 없음)",
            '=IF(OR(StructureRule=StructureChoice,AND(StructureRule="sotp",ListedSub=0)),"OK","ERR")',
            "=StructureRule",
            "=StructureChoice",
        )
    else:
        add(
            "구조 판단 규칙 = 설정한 평가 구조",
            '=IF(StructureRule=StructureChoice,"OK","ERR")',
            "=StructureRule",
            "=StructureChoice",
        )
    add("법인세 구간 연속(0에서 시작, 상한 = 다음 하한, 마지막 상한 없음)", f'=IF(AND({taxc}),"OK","ERR")')
    add("시나리오 선택이 목록 값", '=IF(ISNUMBER(ScenIdx),"OK","ERR")', "=ScenSel")
    add("SRP 선택이 목록 값", '=IF(ISNUMBER(MATCH(SRP_Sel,SRP_List,0)),"OK","ERR")', "=SRP_Sel")
    add(
        "기간 열 수 = 명시 끝 + 체감 연수(생성 시 고정)",
        f'=IF(Forecast!${lastc}${F["year"] + 1}=ExplicitEnd+FadeYears,"OK","ERR")',
        f"=Forecast!${lastc}${F['year'] + 1}",
        "=ExplicitEnd+FadeYears",
    )
    add(
        "체감 마지막 연도 성장률 = 영구성장률",
        f'=IF(ABS(Forecast!${lastc}${F["g"] + 1}-GTerm_Sel)<1E-12,"OK","ERR")',
        f"=Forecast!${lastc}${F['g'] + 1}",
        "=GTerm_Sel",
    )
    add("명시 기간 첫 연도 = 현금흐름 시작 연도", f'=IF(Forecast!$D${F["year"] + 1}=YEAR(CfStart),"OK","ERR")')
    add("유통주식수 > 0", '=IF(Shares>0,"OK","ERR")', "=Shares")
    if d["meta"]["structure"] == "sotp":
        add(
            "구조 판단 비율 단위 점검: 대상 시가총액 ÷ (종가 × 보통주 ÷ 단위) ≈ 1",
            '=IF(ABS(TargetMC/(Close*(CommonIssued-CommonTreasury)/MnToWon)-1)<0.01,"OK","ERR")',
            "=TargetMC/(Close*(CommonIssued-CommonTreasury)/MnToWon)",
            "1",
            note="P4-X: 원 값에 백만원 라벨이 붙는 오류 방지",
        )
    else:
        add(
            "구조 판단 비율 단위 점검: 시장 주식가치 ÷ (종가 × 주식수 ÷ 단위)가 0.5~2배",
            '=IF(AND(MarketEquity/(Close*Shares/MnToWon)>0.5,MarketEquity/(Close*Shares/MnToWon)<2),"OK","ERR")',
            "=MarketEquity/(Close*Shares/MnToWon)",
            "1",
            note="P4-X: 우선주 가격 차이로 정확히 1은 아님. 단위 오류면 100만 배",
        )
    err_sheets = [
        "Cover",
        "Forecast",
        "WACC",
        "DCF",
        "Bridge",
        "Peers",
        "Premium",
        "Scenarios",
        "Scen_Calc",
        "Football",
        "Convergence",
    ]
    for sh in err_sheets:
        ws = c.sheet(sh).ws
        rng = f"{sh}!$A$1:{a1(max(ws.dim_rowmax or 1, 1), max(ws.dim_colmax or 1, 1), True)}"
        add(
            f"수식 오류 0개: {sh}",
            f'=IF(SUMPRODUCT(--ISERROR({rng}))=0,"OK","ERR")',
            f"=SUMPRODUCT(--ISERROR({rng}))",
            "0",
            note="#REF!·#DIV/0!·#NAME?·#VALUE! 등",
        )
    po = c.layout["peer_out"]
    for nm in ("EV/Sales", "EV/EBITDA", "PER", "PBR"):
        add(f"피어 표본 수: {nm}", f'=IF({po[nm]["n"]}>=PeerNWarn,"OK","WARN")', f"={po[nm]['n']}", "=PeerNWarn", "warn")
    add(
        "베타 신뢰성(피어 R² 중앙값 ≥ 기준)",
        '=IF(BetaR2Median>=BetaR2Warn,"OK","WARN")',
        "=BetaR2Median",
        "=BetaR2Warn",
        "warn",
        "표시만(경로 불변)",
    )
    dv = c.layout["dcf_vals"]
    add("RONIC 계산값 사용(대체 없음)", f'=IF(DCF!$C${dv["flag"] + 1}="계산값 사용","OK","WARN")', "=RONIC", "", "warn")
    if not d["premium"].get("withheld"):
        add(
            "블록 프리미엄 적용 표본 수 ≥ 10",
            '=IF(OR(PremN="회귀",N(PremN)>=PremNWarn),"OK","WARN")',
            "=PremN",
            "=PremNWarn",
            "warn",
        )
    # ---- INFO: engine comparison
    sel = "INDEX({rng},ScenIdx,MATCH(SRP_Sel,SRP_List,0))"
    tol = {"won": 1, "pct3": 1e-6, "pct": 1e-6, "pct1": 1e-6, "x": 1e-4, "mn": 0.01}
    for m, (rng, live, lab) in c.layout["engine_tables"].items():
        kind = {
            "per_share": "won",
            "wacc": "pct3",
            "ronic": "pct",
            "tv_share": "pct1",
            "implied_multiple": "x",
            "per_share_exit": "won",
            "ev930": "mn",
            "implied_g": "pct",
            "tv_share_exit": "pct1",
        }[m]
        add(
            f"엔진 대조(선택 칸): {lab}",
            f'=IF(RfTenor<>5,"N/A",IF(ABS({live}-{sel.format(rng=rng)})<={tol[kind]},"OK","DIFF"))',
            f"={live}",
            f"={sel.format(rng=rng)}",
            "info",
            f"허용 오차 {tol[kind]}" + ("" if m != "per_share" else ". Rf 10년 선택이면 N/A(아래 Rf 10년 대조)"),
        )
    add(
        "엔진 대조: 시나리오 4 × SRP 3 주당 최대 차이(원)",
        '=IF(RfTenor<>5,"N/A",IF(MAX(ABS(MAX(ScenDiff)),ABS(MIN(ScenDiff)))<=1,"OK","DIFF"))',
        "=MAX(ABS(MAX(ScenDiff)),ABS(MIN(ScenDiff)))",
        "1",
        "info",
        "허용 오차 1원",
    )
    add(
        "엔진 대조(Rf 10년 선택 시): 시나리오 × SRP 주당 최대 차이(원)",
        '=IF(RfTenor<>10,"N/A",IF(MAX(ABS(MAX(Rf10Diff)),ABS(MIN(Rf10Diff)))<=1,"OK","DIFF"))',
        '=IF(RfTenor<>10,"",MAX(ABS(MAX(Rf10Diff)),ABS(MIN(Rf10Diff))))',
        "1",
        "info",
        "P6-A. Inputs 'Rf 만기 선택' = 10일 때 A 표 = G-2",
    )
    add("Rf 만기 선택이 5 또는 10", '=IF(OR(RfTenor=5,RfTenor=10),"OK","ERR")', "=RfTenor")
    be_u = c.layout["beta_u_engine"]
    add("엔진 대조: βu 중앙값", f'=IF(ABS(BetaU-{be_u})<1E-9,"OK","DIFF")', "=BetaU", f"={be_u}", "info")
    for nm in ("EV/Sales", "EV/EBITDA", "PER", "PBR"):
        rr = po[nm]["row"]
        # P7-B2: N/M (own metric <= 0) on both sides is a match, not an error
        add(
            f"엔진 대조: {nm} 주당 사분위",
            f"=IFERROR(IF(MAX(ABS(Peers!$H${rr + 1}-Peers!$L${rr + 1}),ABS(Peers!$I${rr + 1}-Peers!$M${rr + 1}),"
            f'ABS(Peers!$J${rr + 1}-Peers!$N${rr + 1}))<=1,"OK","DIFF"),IF(COUNT(Peers!$H${rr + 1}:$J${rr + 1},Peers!$L${rr + 1}:$N${rr + 1})=0,'
            f'"OK","DIFF"))',
            f"=Peers!$I${rr + 1}",
            f"=Peers!$M${rr + 1}",
            "info",
            "허용 오차 1원",
        )
    if not d["premium"].get("withheld"):
        be = c.layout["block_engine"]
        add(
            "엔진 대조: 블록 1주당 띠",
            f'=IF(MAX(ABS(Block_q1-{be[0]}),ABS(Block_q2-{be[1]}),ABS(Block_q3-{be[2]}))<=1,"OK","DIFF")',
            "=Block_q2",
            f"={be[1]}",
            "info",
        )
        pe = c.layout["prem_engine"]
        add(
            "엔진 대조: D6 method·이유",
            f'=IF(AND(PremMethod={pe[0]},PremReason={pe[1]}),"OK","DIFF")',
            "=PremMethod",
            f"={pe[0]}",
            "info",
        )
    base_lab = labels["base"]
    base_sel = f'AND(ScenSel="{base_lab}",SRP_Sel=SRP_1,RonicStart="normal",RfTenor=5)'
    for dt in c.layout.get("dt", []):
        add(
            f"데이터 표 {dt['key']}: 엑셀 계산 값 − 엔진 격자 최대 차이(기본·SRP 0%일 때만)",
            f'=IF({base_sel},IF(MAX(ABS(MAX({dt["diff"]})),ABS(MIN({dt["diff"]})))<=1,"OK","DIFF"),"N/A")',
            f"=MAX(ABS(MAX({dt['diff']})),ABS(MIN({dt['diff']})))",
            "1",
            "info",
            "엑셀이 데이터 표를 다시 계산한 뒤 의미가 있다(formulas 재계산은 데이터 표 미지원 → 저장된 엔진 값)",
        )
        if dt["center"]:
            add(
                f"데이터 표 {dt['key']}: 중심 칸 = 살아 있는 모델 주당(기본·SRP 0%일 때만)",
                f'=IF({base_sel},IF(ABS({dt["center"]}-PerShare)<=1,"OK","DIFF"),"N/A")',
                f"={dt['center']}",
                "=PerShare",
                "info",
            )
    for lab, st, val, basis in c.layout.get("conv_checks", []):
        add(lab, st, val, basis, "info")
    if d.get("affiliate"):
        add(
            "참고: 계열사 대여금을 제외하면 주당 영향(원)",
            '=IF(AffLoanIncl=1,"OK","DIFF")',
            "=AffLoanImpact",
            "=AffLoanIncl",
            "info",
            "토글 1 = 엔진과 같음. 값 칸 = 제외 시 주당 변화",
        )
    if c.layout.get("cross_engine"):
        add(
            "엔진 대조: 연결 교차 확인 주당(기본·SRP 0%일 때만)",
            f'=IF({base_sel},IF(ABS(CrossPerShare-{c.layout["cross_engine"]})<=1,"OK","DIFF"),"N/A")',
            "=CrossPerShare",
            f"={c.layout['cross_engine']}",
            "info",
        )
    if c.layout.get("c2_engine"):
        add(
            "엔진 대조: C2 재현(RONIC mixed·기본·SRP 0%일 때만)",
            f'=IF(AND(ScenSel="{base_lab}",SRP_Sel=SRP_1,RonicStart="mixed",RfTenor=5),IF(ABS(PerShare-{c.layout["c2_engine"]})<=1,"OK","DIFF"),"N/A")',
            "=PerShare",
            f"={c.layout['c2_engine']}",
            "info",
        )
    if c.layout.get("waccg_center"):
        add(
            "엔진 표 중심값(WACC×g) = 살아 있는 표 기본·SRP 0%",
            f'=IF(RfTenor<>5,"N/A",IF(ABS({c.layout["waccg_center"]}-INDEX(ScenGridPS,MATCH("{base_lab}",ScenNames,0),1))<=1,"OK","DIFF"))',
            f"={c.layout['waccg_center']}",
            f'=INDEX(ScenGridPS,MATCH("{base_lab}",ScenNames,0),1)',
            "info",
        )
    r0 = 5
    for i, (label, status, value, basis, kind, note) in enumerate(items):
        r = r0 + i
        s.text(r, 0, str(i + 1))
        s.text(r, 1, label)
        s.check(r, 2, status, label, kind)
        if value:
            if value.startswith("="):
                s.fx(r, 3, value, "gen")
            else:
                s.text(r, 3, value)
        if basis:
            if basis.startswith("="):
                s.fx(r, 4, basis, "gen")
            else:
                s.text(r, 4, basis)
        s.text(r, 5, kind.upper())
        if note:
            s.text(r, 6, note, "note")
    r1 = r0 + len(items) - 1
    stat = f"$C${r0 + 1}:$C${r1 + 1}"
    s.text(2, 1, "MASTER CHECK", "bold")
    s.fx(2, 2, f'=IF(COUNTIF({stat},"ERR")=0,"OK","ERR")', "gen", name="MasterCheck", bold=True)
    s.fx(2, 3, f'="ERR "&COUNTIF({stat},"ERR")&" / WARN "&COUNTIF({stat},"WARN")&" / INFO 차이 "&COUNTIF({stat},"DIFF")', "gen")
    green = c.book.wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})
    red = c.book.wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
    amber = c.book.wb.add_format({"bg_color": "#FFEB9C", "font_color": "#9C5700"})
    for rng in ("C3:C3", f"C{r0 + 1}:C{r1 + 1}"):
        s.ws.conditional_format(rng, {"type": "cell", "criteria": "==", "value": '"OK"', "format": green})
        s.ws.conditional_format(rng, {"type": "cell", "criteria": "==", "value": '"ERR"', "format": red})
        s.ws.conditional_format(rng, {"type": "cell", "criteria": "==", "value": '"WARN"', "format": amber})
        s.ws.conditional_format(rng, {"type": "cell", "criteria": "==", "value": '"DIFF"', "format": amber})
    c.layout["checks_rows"] = (r0, r1)
    c.range_name("CheckTable", "Checks", a1(r0, 1), a1(r1, 5))
