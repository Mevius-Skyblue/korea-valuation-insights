"""P7-B2 Diagnostics sheet: why the number is what it is, and where a person should look first (config/p7b2.yaml).

Values do not change anything in the model. Engine values are grey (src/pipeline/diagnose.py via engine_ref); the
traffic lights are live formulas on the live base-scenario per share (Scenarios A-1 table) and the close.
Sections: A signals · B reverse · C composition · D data anomalies · E normal-margin candidates · F sensitivities ·
G ranked human-review list (same order as summary.json and the report section '결과 해석 주의').
Range names used by the report: DiagSignal*, DiagRevTable, DiagCompTable, DiagFlagTable, DiagCandTable, DiagSensTable,
DiagRankTable, DiagOtherTable.
"""

from __future__ import annotations

from src.excel.context import Ctx
from src.excel.writer import a1

SRC = "config/p7b2.yaml diagnostics · src/pipeline/diagnose.py"


def _row(s, r, label, value, kind="gen", note="", name=None, live=None):
    s.text(r, 0, label)
    if live is not None:
        s.fx(r, 1, live, kind, name=name)
    else:
        s.eng(r, 1, value, kind)
        if name:
            s.book.name(name, s.name, a1(r, 1))
    if note:
        s.text(r, 2, note, "note")


def diagnostics(c: Ctx):
    d, s = c.d, c.sheet("Diagnostics")
    e = d["engine"]
    dg = e.get("diagnostics") or {}
    sig = dg.get("signals") or {}
    labels = d["excel"]["scenario_labels"]
    s.widths({0: 46, 1: 16, 2: 16, 3: 16, 4: 44, 5: 16, 6: 12})
    s.text(0, 0, "Diagnostics — 결과 신뢰도 진단과 사람 판단 우선순위 (값은 바꾸지 않음)", "title")
    s.text(
        1,
        0,
        f"회색 = 엔진 계산값({SRC}), 신호등은 살아 있는 수식. 대안은 후보·민감도일 뿐 기본값은 그대로(사전 고정 0dad3cc)",
        "note",
    )

    # ---- A signals
    r = 3
    s.text(r, 0, "A. 신호등(기본 시나리오 · SRP 열 1)", "subtitle")
    rows = [
        (
            "DCF 주당(원, Scenarios A-1 기본 · SRP 열 1)",
            None,
            "won",
            "",
            "DiagDcf",
            f'=INDEX(ScenGridPS,MATCH("{labels["base"]}",ScenNames,0),1)',
        ),
        ("  엔진 기록 DCF 주당(원)", sig.get("dcf"), "won", "", "DiagDcfEngine", None),
        ("피어 범위 기준 배수", sig.get("peer_basis") or "n/a", "gen", "EV/EBITDA n < 3이면 EV/Sales", "DiagPeerBasis", None),
        ("피어 사분위 q25 주당(원)", sig.get("q25"), "won", "Peers 시트와 같은 정의(엔진 값)", "DiagQ25", None),
        ("피어 중앙값 주당(원)", sig.get("peer_median"), "won", "", "DiagPeerMed", None),
        ("피어 사분위 q75 주당(원)", sig.get("q75"), "won", "", "DiagQ75", None),
        ("피어 n", sig.get("peer_n"), "int", "", "DiagPeerN", None),
        (
            "피어 범위 유효(1 = 해석 가능, 0 = 해석 불가)",
            1 if sig.get("peer_valid", True) else 0,
            "int",
            "; ".join(sig.get("peer_invalid") or []) or "config/p7b3.yaml peer_validity",
            "DiagPeerValid",
            None,
        ),
        ("기준일 종가(원)", None, "won", "한국거래소 통계정보", "DiagPrice", "=Close"),
        ("DCF ÷ 종가", None, "ratio", "", "DiagMktRatio", "=DiagDcf/Close"),
        ("임계값: 피어 노랑 하한 배수(× q25)", 0.67, "ratio", "사전 고정", "DiagThPLo", None),
        ("임계값: 피어 노랑 상한 배수(× q75)", 1.5, "ratio", "사전 고정", "DiagThPHi", None),
        ("임계값: 시장 초록 [하한, 상한]", 0.67, "ratio", "상한 1.5", "DiagThMGLo", None),
        ("  시장 초록 상한", 1.5, "ratio", "", "DiagThMGHi", None),
        ("임계값: 시장 노랑 [하한, 상한]", 0.5, "ratio", "상한 2.0", "DiagThMYLo", None),
        ("  시장 노랑 상한", 2.0, "ratio", "", "DiagThMYHi", None),
    ]
    for i, (lab, v, kind, note, nm, live) in enumerate(rows):
        _row(s, r + 1 + i, lab, v, kind, note, nm, live)
    r += 1 + len(rows)
    lp = (
        '=IF(OR(DiagPeerValid=0,NOT(ISNUMBER(DiagQ25)),NOT(ISNUMBER(DiagQ75)),N(DiagPeerN)<3),"회색",IF(AND(DiagDcf>=DiagQ25,DiagDcf<=DiagQ75),"초록",'
        'IF(OR(AND(DiagDcf>=DiagThPLo*DiagQ25,DiagDcf<DiagQ25),AND(DiagDcf>DiagQ75,DiagDcf<=DiagThPHi*DiagQ75)),"노랑","빨강")))'
    )
    lm = (
        '=IF(AND(DiagMktRatio>=DiagThMGLo,DiagMktRatio<=DiagThMGHi),"초록",IF(AND(DiagMktRatio>=DiagThMYLo,DiagMktRatio<=DiagThMYHi),'
        '"노랑","빨강"))'
    )
    lo = (
        '=IF(OR(DiagLightPeer="빨강",DiagLightMkt="빨강"),"빨강",IF(OR(DiagLightPeer="노랑",DiagLightMkt="노랑"),"노랑",'
        'IF(AND(DiagLightPeer="회색",DiagLightMkt="회색"),"회색","초록")))'
    )
    _row(s, r, "신호: DCF vs 피어 범위", None, "gen", "초록 = 사분위 안", "DiagLightPeer", lp)
    _row(s, r + 1, "신호: DCF ÷ 종가", None, "gen", "", "DiagLightMkt", lm)
    _row(s, r + 2, "종합 신호(나쁜 쪽)", None, "gen", "", "DiagLight", lo)
    _row(s, r + 3, "  엔진 판정", sig.get("light") or "n/a", "gen", "", "DiagLightEngine", None)
    _row(
        s,
        r + 4,
        "  엔진 판정 = 살아 있는 판정",
        None,
        "gen",
        "OK / DIFF",
        "DiagLightCheck",
        '=IF(DiagLight=DiagLightEngine,"OK","DIFF")',
    )
    r += 6

    # ---- B reverse
    rev = dg.get("reverse")
    s.text(r, 0, "B. 역산 — 피어 중앙값 주당을 맞추려면(하나만 움직임, 엔진 값)", "subtitle")
    for j, h in enumerate(["항목", "기본 값", "필요 값", "차이"]):
        s.text(r + 1, j, h, "header")
    rr = r + 2
    if rev:
        items = [
            ("목표 주당(원) — " + str(rev.get("basis")), None, rev.get("target"), "won"),
            ("정상 영업이익률", rev.get("margin_base"), rev.get("margin"), "pct"),
            ("출발 성장률", rev.get("start_growth_base"), rev.get("start_growth"), "pct"),
            ("WACC", rev.get("wacc_base"), rev.get("wacc"), "pct"),
            ("역산 정확도: 다시 계산한 주당 − 목표(원, 최대 절댓값)", None, rev.get("max_abs_error"), "won"),
        ]
        for i, (lab, b, v, kind) in enumerate(items):
            s.text(rr + i, 0, lab)
            s.eng(rr + i, 1, b, kind)
            s.eng(rr + i, 2, v if v is not None else "범위 안 해 없음", kind)
            s.eng(rr + i, 3, (v - b) if (v is not None and b is not None) else None, kind)
        c.range_name("DiagRevTable", "Diagnostics", a1(rr, 0), a1(rr + len(items) - 1, 3))
        rr += len(items)
    else:
        s.text(rr, 0, "RF 전용 경로: 역산은 Scenarios E 표(역DCF) 참고", "note")
        c.range_name("DiagRevTable", "Diagnostics", a1(rr, 0), a1(rr, 3))
        rr += 1
    r = rr + 1

    # ---- C composition
    comp, cs = dg.get("composition"), dg.get("composition_share") or {}
    s.text(r, 0, "C. 주식가치 구성(백만원, 평가기준일)", "subtitle")
    for j, h in enumerate(["항목", "금액(백만원)", "주식가치 대비"]):
        s.text(r + 1, j, h, "header")
    rr = r + 2
    if comp:
        lab = {
            "ev": "EV",
            "tv": "  영구가치 현재가치(Gordon)",
            "explicit": "  명시·체감 기간 현재가치",
            "cash_like": "+ 현금성",
            "non_operating": "+ 비영업자산",
            "debt": "− 총차입금(리스 포함)",
            "nci": "− 비지배지분",
            "equity": "= 주식가치",
        }
        keys = ["ev", "tv", "explicit", "cash_like", "non_operating", "debt", "nci", "equity"]
        for i, k in enumerate(keys):
            s.text(rr + i, 0, lab[k])
            s.eng(rr + i, 1, comp[k], "mn")
            s.eng(rr + i, 2, cs.get(k, 1.0 if k == "equity" else None), "pct")
        c.range_name("DiagCompTable", "Diagnostics", a1(rr, 0), a1(rr + len(keys) - 1, 2))
        rr += len(keys)
    else:
        s.text(rr, 0, "RF 전용 경로: Bridge 시트 참고", "note")
        c.range_name("DiagCompTable", "Diagnostics", a1(rr, 0), a1(rr, 2))
        rr += 1
    r = rr + 1

    # ---- D anomalies
    fl = dg.get("anomalies") or []
    s.text(r, 0, "D. 데이터 이상 신호(사전 고정 기준)", "subtitle")
    for j, h in enumerate(["신호", "해당", "값"]):
        s.text(r + 1, j, h, "header")
    rr = r + 2
    for i, x in enumerate(fl):
        s.text(rr + i, 0, x["text"], "wrap")
        s.eng(rr + i, 1, "해당" if x["on"] else "-")
        v = x["value"]
        s.eng(rr + i, 2, v if isinstance(v, (int, float)) or v is None else str(v), "ratio" if isinstance(v, float) else "gen")
    if not fl:
        s.text(rr, 0, "RF 전용 경로: 해당 없음", "note")
    c.range_name("DiagFlagTable", "Diagnostics", a1(rr, 0), a1(rr + max(len(fl), 1) - 1, 2))
    r = rr + max(len(fl), 1) + 1

    # ---- E candidates
    cands = dg.get("margin_candidates") or []
    s.text(r, 0, "E. 정상 이익률 후보(표시만, 기본값은 과거 3년 평균 그대로)", "subtitle")
    for j, h in enumerate(["후보", "이익률", "주당(원)", "기본 대비(원)"]):
        s.text(r + 1, j, h, "header")
    rr = r + 2
    for i, x in enumerate(cands):
        s.text(rr + i, 0, x["label"], "wrap")
        s.eng(rr + i, 1, x["margin"], "pct")
        s.eng(rr + i, 2, x["per_share"], "won")
        s.eng(rr + i, 3, x["diff"], "won")
    if not cands:
        s.text(rr, 0, "RF 전용 경로: 해당 없음", "note")
    c.range_name("DiagCandTable", "Diagnostics", a1(rr, 0), a1(rr + max(len(cands), 1) - 1, 3))
    r = rr + max(len(cands), 1) + 1

    # ---- F sensitivities
    se = dg.get("sensitivities")
    s.text(r, 0, "F. 민감도(기본값 그대로, 다른 선택의 주당)", "subtitle")
    for j, h in enumerate(["항목", "값", "주당(원)", "기본 대비(원)"]):
        s.text(r + 1, j, h, "header")
    rr = r + 2
    srows = []
    if se:
        cf, nc = se["customer_funds"], se["nci"]
        detail = "; ".join(f"{x['label']} {x['amount']:,.0f}" for x in cf["items"]) or "없음"
        srows = [
            ("고객 자금 성격 부채(백만원): " + detail[:120], cf["liabilities"], None, None, "mn"),
            (
                "영업용 현금 = min(현금성, 고객 자금 부채) → 브리지에서 뺌(백만원)",
                cf["operating_cash"],
                cf["per_share"],
                cf["diff"],
                "mn",
            ),
            ("비지배 장부(백만원) — 기본", nc["book"], None, None, "mn"),
            ("(a) 비례법: 비지배 장부 ÷ 자본총계", nc["share_book"], nc["a_per_share"], nc["a_diff"], "pct"),
            ("(b) 비지배 장부 × 피어 P/B 중앙값", nc["peer_pbr"], nc["b_per_share"], nc["b_diff"], "ratio"),
        ]
        for i, (lab, v, ps, df, kind) in enumerate(srows):
            s.text(rr + i, 0, lab, "wrap")
            s.eng(rr + i, 1, v, kind)
            s.eng(rr + i, 2, ps, "won")
            s.eng(rr + i, 3, df, "won")
    else:
        s.text(rr, 0, "RF 전용 경로: 해당 없음", "note")
    c.range_name("DiagSensTable", "Diagnostics", a1(rr, 0), a1(rr + max(len(srows), 1) - 1, 3))
    r = rr + max(len(srows), 1) + 1

    # ---- G ranked list
    rk = e.get("review_ranked") or {"computed": [], "other": []}
    s.text(r, 0, "G. 사람 판단 목록 — 다른 선택의 주당 영향이 큰 순(★ = 상위 5)", "subtitle")
    for j, h in enumerate(["순위", "범주", "항목", "다른 선택", "", "주당 차이(원)", "기본 대비"]):
        if h:
            s.text(r + 1, j, h, "header")
    rr = r + 2
    comp_ = rk["computed"]
    for i, x in enumerate(comp_):
        s.eng(rr + i, 0, f"{x['rank']}{' ★' if x['top5'] else ''}")
        s.text(rr + i, 1, x["category"])
        s.text(rr + i, 2, x["item"][:80], "wrap")
        s.text(rr + i, 3, x["alternative"][:120], "wrap")
        s.eng(rr + i, 5, x["impact"], "won")
        s.eng(rr + i, 6, x["impact_pct"], "pct")
    c.range_name("DiagRankTable", "Diagnostics", a1(rr, 0), a1(rr + max(len(comp_), 1) - 1, 6))
    # P7-B5 top5_share (config/p7b5.yaml): how much of the computed impact the first five items carry
    s.text(rr + max(len(comp_), 1), 0, "상위 5 항목 주당 영향 비중(영향 값 있는 항목 기준, P7-B5)", "note")
    s.eng(rr + max(len(comp_), 1), 6, rk.get("share_top5"), "pct")
    s.book.name("DiagTop5Share", s.name, a1(rr + max(len(comp_), 1), 6))
    r = rr + max(len(comp_), 1) + 1
    s.text(r, 0, "계산할 수 없는 항목(원래 순서)", "subtitle")
    oth = rk["other"]
    for i, x in enumerate(oth):
        s.text(r + 1 + i, 1, x["category"])
        s.text(r + 1 + i, 2, x["item"][:80], "wrap")
        s.text(r + 1 + i, 3, str(x.get("detail", ""))[:150], "wrap")
    c.range_name("DiagOtherTable", "Diagnostics", a1(r + 1, 1), a1(r + max(len(oth), 1), 3))

    # ---- H validity guard, I v2 vs v1, J D&A sources (P7-B2b, config/p7b2b.yaml)
    r = r + max(len(oth), 1) + 2
    gd = dg.get("guard") or {"status": "표시", "reasons": []}
    s.text(r, 0, "H. 대표값 판정(유효성 가드, 사전 고정 91a84dd)", "subtitle")
    _row(s, r + 1, "대표값", gd["status"], "gen", "보류면 화면·요약에는 숫자 대신 사유와 1순위 판단", "DiagHeadline")
    for i, x in enumerate(gd["reasons"]):
        s.text(r + 2 + i, 0, "  사유: " + x["text"])
    c.range_name("DiagGuardTable", "Diagnostics", a1(r + 1, 0), a1(r + 1 + max(len(gd["reasons"]), 0), 1))
    r = r + 3 + len(gd["reasons"])
    v1 = dg.get("v1")
    s.text(r, 0, "I. 기본 경로 v2 vs v1(대안) — 기본 시나리오·SRP 열 1", "subtitle")
    if v1:
        v2i = dg.get("v2") or {}
        rows_i = [
            ("v2 주당(원, 이 모델)", sig.get("dcf"), "won", "DiagV2PS"),
            ("v1 주당(원, 3년 평균 이익률·5년 CAGR)", v1["per_share"], "won", "DiagV1PS"),
            ("v2 출발 이익률(5년 중앙값)", v2i.get("m0"), "pct", "DiagV2M0"),
            ("v2 피어 이익률 중앙값", v2i.get("peer_margin"), "pct", "DiagV2PM"),
            ("v2 2032 이동 폭", v2i.get("conv_amt"), "pct", "DiagV2Conv"),
            ("v2 출발 성장률", v2i.get("g0"), "pct", "DiagV2G0"),
            ("v1 신호(피어/시장)", f"{v1['signals']['light_peer']}/{v1['signals']['light_market']}", "gen", "DiagV1Light"),
        ]
        for i, (lab, v, kind, nm) in enumerate(rows_i):
            _row(s, r + 1 + i, lab, v, kind, "", nm)
        r += len(rows_i) + 2
    else:
        s.text(r + 1, 0, "v1 경로 회사(수기 설정·RF): 해당 없음", "note")
        r += 3
    dna = dg.get("dna") or []
    s.text(r, 0, "J. D&A 출처(기간별, 백만원) — 원문/XBRL → 보완 원문 → 추정", "subtitle")
    for j, h in enumerate(["기간", "D&A", "출처", "추정"]):
        s.text(r + 1, j, h, "header")
    for i, x in enumerate(dna):
        s.text(r + 2 + i, 0, f"{x['period']}{x['year']}")
        s.eng(r + 2 + i, 1, x["total"], "mn")
        s.text(r + 2 + i, 2, x["source"][:90], "wrap")
        s.text(r + 2 + i, 3, "추정" if x["estimated"] else "")
    if not dna:
        s.text(r + 2, 0, "수기 설정·RF: DB fs_dna(P1 파서) 그대로", "note")
    c.range_name("DiagDnaTable", "Diagnostics", a1(r + 2, 0), a1(r + 1 + max(len(dna), 1), 3))

    # ---- K general SOTP (P7-B3, config/p7b3.yaml sotp)
    st = dg.get("sotp")
    r = r + 3 + max(len(dna), 1)
    s.text(r, 0, "K. SOTP 구성(백만원) — 모회사(별도) 영업가치 + 종속회사 지분", "subtitle")
    if st:
        rows_k = [
            ("모회사 영업가치(EV, 별도 기준)", st["parent_ev"], "mn", "DiagSotpParentEV"),
            ("상장 종속회사 지분 시가(할인 전)", st["listed"], "mn", "DiagSotpListed"),
            ("비상장 종속회사 장부가", st["unlisted"], "mn", "DiagSotpUnlisted"),
            ("'종속' 투자 줄 합계(비영업에서 뺌)", st["sub_lines"], "mn", "DiagSotpSubLines"),
            ("주식가치", st["equity"], "mn", "DiagSotpEquity"),
            ("상장 지분이 주식가치에서 차지하는 비중", st["listed_share"], "pct", "DiagSotpListedShare"),
            ("모회사(종속회사 제외)가 차지하는 비중", st["parent_share"], "pct", "DiagSotpParentShare"),
        ]
        for x in st["sens"]:
            rows_k.append(
                (
                    f"상장 지분 할인 {x['discount']:.0%}일 때 주당(원)",
                    x["per_share"],
                    "won",
                    f"DiagSotpDisc{int(round(x['discount'] * 100))}",
                )
            )
        for i, (lab, v, kind, nm) in enumerate(rows_k):
            _row(s, r + 1 + i, lab, v, kind, "", nm)
        c.range_name("DiagSotpTable", "Diagnostics", a1(r + 1, 0), a1(r + len(rows_k), 1))
    else:
        s.text(r + 1, 0, "SOTP 아님", "note")

    # ---- L loss path, turnaround, SOTP guard, account mis-tag (P7-B3b, config/p7b3b.yaml)
    r = r + 3 + (len(rows_k) if st else 1)
    s.text(r, 0, "L. 적자 경로·실적 전환·SOTP 가드·계정 오표기(사전 고정 401c38d)", "subtitle")
    rows_l = []
    lo = dg.get("loss")
    if lo:
        ev, fu = lo["ev_sales"], lo["funding"]
        rows_l += [
            ("적자 경로", lo["fixed_text"], "gen", "DiagLossText"),
            ("(a) 피어 EV/Sales 주당 q25(원)", ev["q25"], "won", "DiagLossQ25"),
            ("(a) 피어 EV/Sales 주당 q75(원)", ev["q75"], "won", "DiagLossQ75"),
            (
                "(a) 범위 해석",
                "가능" if ev["valid"] else "불가: " + ("; ".join(ev["invalid"]) or "피어 부족"),
                "gen",
                "DiagLossValid",
            ),
            ("(b) 전환 DCF 주당(원, 기본·SRP 열 1)", lo["dcf"], "won", "DiagLossDcf"),
            ("(b) 출발 LTM 영업이익률", lo["ltm_margin"], "pct", "DiagLossM0"),
            ("(b) 2032년 도달 이익률(피어 중앙값)", lo["target_margin"], "pct", "DiagLossMT"),
            ("(c) 명시 기간 누적 FCF 최저(백만원)", fu["trough"], "mn", "DiagLossTrough"),
            ("(c) 현금성(백만원)", fu["cash_like"], "mn", "DiagLossCash"),
            ("(c) 추가 자금 필요(희석 위험)", "예" if fu["need"] else "아니오", "gen", "DiagLossNeed"),
        ]
    tn = dg.get("turnaround")
    if tn:
        rows_l += [
            ("실적 전환: LTM 영업이익률", tn["ltm_margin"], "pct", "DiagTurnLtm"),
            ("실적 전환: 5년 중앙값(기본 출발값)", tn["m0"], "pct", "DiagTurnM0"),
            ("실적 전환: LTM 출발 후보 주당(원)", tn["per_share"], "won", "DiagTurnPS"),
        ]
    if st:
        rows_l.append(("SOTP 가드", "; ".join(x["text"] for x in st.get("guard") or []) or "해당 없음", "gen", "DiagSotpGuard"))
    for i, (lab, v, kind, nm) in enumerate(rows_l):
        _row(s, r + 1 + i, lab, v, kind, "", nm)
    if not rows_l:
        s.text(r + 1, 0, "적자 경로·실적 전환·SOTP 가드 해당 없음", "note")
    r = r + 2 + max(len(rows_l), 1)
    mt = d.get("debt_reclass") or []
    s.text(r, 0, "계정 오표기(원문 대조 재분류, 총차입금에 더함·FS_Hist 값에 포함, 백만원)", "subtitle")
    for j, h in enumerate(["기간", "금액", "원문 줄", "API 줄(접수번호)"]):
        s.text(r + 1, j, h, "header")
    for i, x in enumerate(mt):
        s.text(r + 2 + i, 0, f"{x['period']}{x['year']}")
        s.eng(r + 2 + i, 1, x["amount"] / 1e6, "mn")
        s.text(r + 2 + i, 2, x["text_label"])
        s.text(r + 2 + i, 3, f"{x['api_label']}({x['rcept']})", "wrap")
    if not mt:
        s.text(r + 2, 0, "없음", "note")
    c.range_name("DiagMistagTable", "Diagnostics", a1(r + 2, 0), a1(r + 1 + max(len(mt), 1), 3))


def judgements(c: Ctx):
    """P7-C1 Judgements sheet: what a person changed in the evaluation session (item, auto value, confirmed value, reason,
    version, time). Values are the session record (text and numbers, not formulas); the model reads the confirmed values
    from Inputs '사람 확정값' and the config-native inputs (MRP, Rf tenor, SRP, g, scenario width, peers, SOTP discount)."""
    d = c.d
    wb = d["workbench"]
    s = c.sheet("Judgements")
    s.widths({0: 6, 1: 30, 2: 22, 3: 18, 4: 18, 5: 40, 6: 8, 7: 20})
    s.text(0, 0, f"Judgements — 사람 판단 반영 내역 (평가 세션 {wb.get('session_id')}, 확정 v{wb.get('version')})", "title")
    s.text(
        1,
        0,
        "자동 초안 값 → 사람 확정값. 확정값은 Inputs '사람 확정값' 또는 각 입력 칸에 들어가 계산 시트가 읽는다(살아 있는 수식)",
        "note",
    )
    for j, h in enumerate(["#", "항목", "가정", "자동값", "확정값", "이유", "버전", "시각"]):
        s.text(3, j, h, "header")
    rows = wb.get("changes") or []
    for i, x in enumerate(rows):
        r = 4 + i
        s.text(r, 0, str(i + 1))
        s.text(r, 1, str(x.get("item") or "")[:80], "wrap")
        s.text(r, 2, str(x.get("label") or x.get("field")))
        for j, k in ((3, "before_text"), (4, "after_text")):
            s.text(r, j, str(x.get(k) if x.get(k) is not None else "")[:60])
        s.text(r, 5, str(x.get("reason") or "")[:120], "wrap")
        s.text(r, 6, f"v{x.get('version')}")
        s.text(r, 7, str(x.get("at") or ""))
    c.range_name("JudgeTable", "Judgements", a1(4, 0), a1(4 + max(len(rows), 1) - 1, 7))
    kept = wb.get("kept") or []
    r = 6 + max(len(rows), 1)
    s.text(r, 0, f"그대로 유지한 판단 {len(kept)}건 · 남은 미처리 {wb.get('pending', 0)}건", "subtitle")
    for i, x in enumerate(kept):
        s.text(r + 1 + i, 1, str(x.get("item") or "")[:80], "wrap")
        s.text(r + 1 + i, 5, str(x.get("reason") or "")[:120], "wrap")
    hold = wb.get("auto_hold_reasons") or []
    r2 = r + 2 + len(kept)
    s.text(r2, 0, "자동 초안 대표값 판정(기록): " + ("자동 결과 보류 — " + "; ".join(hold) if hold else "표시"), "note")
