"""DCF tab (P7-U1, in the order of a valuation model): one line of conventions -> ① forecast drivers -> ② FCFF forecast
(FY actuals + explicit years + fade range) -> ③ terminal value as numbers (+ exit multiple reference) -> ④ EV -> equity
bridge · WACC build-up · working capital -> scenario comparison and the two sensitivity tables. Every number comes from
values.dcf_detail (engine functions on the session's company)."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx
from app.wb import values as V


def render(c: nav.Ctx) -> None:
    d = V.dcf_detail(c.o, c.s, c.mode)
    if d.get("error"):
        with ui.card("dcf_err"):
            st.markdown(f"<p class='wb-kpi-note wb-warn'>{ui.esc(tx.plain_words(d['error']))}</p>", unsafe_allow_html=True)
        return
    mt = d["meta"]
    fd = mt["fade"]
    st.markdown(
        f"<div class='wb-subrow'>평가기준일 <b>{mt['as_of']}</b> · 재무 {mt['bs_date']} · {'기중 할인 (Mid-year)' if mt['mid_year'] else '기말 할인'} · "
        f"명시 {mt['explicit'][0]}~{mt['explicit'][1]} · 수렴 구간 (Fade) {fd[0]}–{fd[1] if fd else ''} · 영구가치 (TV) 항상성장모형 (Gordon Growth)</div>",
        unsafe_allow_html=True,
    )
    with ui.card("drivers"):
        drivers(c, d)
    with ui.card("fcff"):
        fcff(c, d)
    a, b = st.columns(2, gap="medium")
    with a:
        with ui.card("tv"):
            tv(c, d)
        with ui.card("wacc"):
            wacc(c, d)
    with b:
        with ui.card("bridge"):
            bridge(c, d)
        with ui.card("nwc"):
            nwc(c, d)
    x, y, z = st.columns(3, gap="medium")
    with x:
        with ui.card("scen"):
            scenarios(c, d)
    with y:
        with ui.card("sens_wg"):
            sens_wg(c, d)
    with z:
        with ui.card("sens_gm"):
            sens_gm(c, d)


def drivers(c: nav.Ctx, d: dict) -> None:
    v = d["drivers"]
    ui.h2("① 추정 가정")
    ui.cells(
        [
            {"k": "매출 성장률", "v": f"{F.p1(v['g0'])} → {F.p1(v['gT'])} ({v['g_to']})"},
            {"k": "정상화 영업이익률", "v": f"{F.p1(v['m0'])} → {F.p1(v['m_end'])} ({v['m_end_year']})"},
            {
                "k": "Peer 영업이익률 수렴",
                "v": f"{F.p1(v['conv_share'], 0)} · Peer 중앙값 {F.p1(v['peer_margin'])}" if F.ok(v["conv_share"]) else "—",
            },
            {"k": "법인세율", "v": f"{F.p1(v['tax_marginal'])} (한계)"},
            {
                "k": "D&A ÷ 매출",
                "v": F.p1(v["dna_ratio"]) + (" (확정값)" if F.ok(v["auto_ratios"].get("dna_ratio")) else " (3년 평균)"),
            },
            {
                "k": "CAPEX ÷ 매출",
                "v": F.p1(v["capex_ratio"]) + (" (확정값)" if F.ok(v["auto_ratios"].get("capex_ratio")) else " (3년 평균)"),
            },
            {
                "k": "운전자본 회전일수",
                "v": f"재고자산 {v['dio']:.0f}일 · 매출채권 {v['dso']:.0f}일 · 매입채무 {v['dpo']:.0f}일",
                "tip": "DIO · DSO · DPO",
            },
            {
                "k": "수렴 구간 (Fade)",
                "v": f"영구성장률 {F.p1(v['gT'])} · RONIC {F.p1(v['ronic'])}",
                "tip": tx.plain_words(v.get("ronic_why") or ""),
            },
        ]
    )


def _fmt_row(vals, kind: str, mn: bool) -> list:
    out = []
    for x in vals:
        if x is None:
            out.append("")
        elif kind == "pct":
            out.append(F.p1(x, paren=True))
        elif kind == "dec3":
            out.append(f"{x:.3f}" if F.ok(x) else "")
        else:
            out.append(F.amt(x, mn))
    return out


def fcff(c: nav.Ctx, d: dict) -> None:
    mn = c.mn
    cols = d["hist"] + d["explicit"]
    fd = d["fade"]
    head = (
        [F.unit(mn)] + [x["label"] for x in cols] + [f"수렴 구간 {fd[0]['label']}–{fd[-1]['label'][2:]}" if fd else "수렴 구간"]
    )

    def rng(k, kind="amt"):
        if not fd:
            return ""
        a, b = fd[0].get(k), fd[-1].get(k)
        if a is None or b is None:
            return ""
        if kind == "pct":
            return f"{F.p1(a)} → {F.p1(b)}" if abs(a - b) > 1e-9 else F.p1(a)
        if kind == "dec3":
            return f"{a:.3f} → {b:.3f}"
        return f"{F.amt(a, mn)} → {F.amt(b, mn)}"

    spec = [
        ("매출", "revenue", "amt", False, False),
        ("매출 성장률", "growth", "pct", False, False),
        ("EBITDA", "ebitda", "amt", False, False),
        ("EBIT", "ebit", "amt", True, True),
        ("영업이익률", "margin", "pct", False, False),
        ("(−) 법인세", "tax", "amt", False, False),
        ("세후영업이익 (NOPAT)", "nopat", "amt", True, True),
        ("(+) 감가상각비 (D&A)", "dna", "amt", False, False),
        ("(−) 자본적지출 (CAPEX)", "capex", "amt", False, False),
        ("(−) 순운전자본 증가", "dnwc", "amt", False, False),
        ("(−) 재투자", "reinvest", "amt", False, False),
        ("FCFF", "fcff", "amt", True, True),
        ("할인계수", "df", "dec3", False, False),
        ("FCFF 현재가치 (PV)", "pv", "amt", True, False),
    ]
    rows = []
    for lab, k, kind, strong, top in spec:
        vals = [x.get(k) for x in cols]
        if k == "ebitda":
            last = ""
        elif k == "reinvest":
            last = rng("reinvest")
        elif k == "pv":
            last = f"{F.amt(d['pv_fade'], mn)} (합계)"
        elif k in ("dna", "capex", "dnwc"):
            last = ""
        else:
            last = rng(k, kind)
        if k == "reinvest":
            vals = [None] * len(cols)
        rows.append({"c": [lab] + _fmt_row(vals, kind, mn) + [last], "strong": strong, "top": top})
    n_hist = len(d["hist"])
    shade = tuple(range(1, n_hist + 1)) + (len(head) - 1,)
    fj = d.get("fade_jump") or {}
    jump_txt = (
        f"{fj['ratio']:.2f}배"
        if fj.get("ratio") is not None
        else ("부호 바뀜(음 → 양)" if fj.get("sign_flip") else "계산 불가(마지막 명시 FCFF ≤ 0)")
    )
    lin = d.get("fade_rule") == "linear"
    tip = (
        f"명시 → 수렴 FCFF 배수 {jump_txt}(첫 수렴 연도 ÷ 마지막 명시 연도). "
        f"CAPEX ÷ 매출 {F.p1(d['drivers']['capex_ratio'])} vs D&A ÷ 매출 {F.p1(d['drivers']['dna_ratio'])} · "
        + (
            "수렴 구간 재투자율: 마지막 명시 연도 값에서 g ÷ RONIC로 선형 수렴(사람 선택)"
            if lin
            else "수렴 구간 재투자 = NOPAT × g ÷ RONIC(첫해부터)"
        )
        + (
            " · 불연속 → 가정·판단의 'CAPEX ÷ 매출' 후보(A 마지막 해 = 수렴 규칙, B 5년 평균, C 선형 수렴)"
            if fj.get("jump")
            else ""
        )
    )
    mark = f"ⓘ 불연속 {jump_txt}" if fj.get("jump") else f"ⓘ 배수 {jump_txt}"
    ui.title_copy(
        f"② FCFF 추정 <span class='wb-help{' wb-warn' if fj.get('jump') else ''}' title='{ui.esc(tip)}'>{ui.esc(mark)}</span>",
        "",
        ui.esc(
            f"{F.unit(mn)} · 기중 할인 (Mid-year) · 수렴 구간 (Fade) {fd[0]['label']}–{fd[-1]['label']}" if fd else F.unit(mn)
        ),
        ui.tsv(head, rows),
    )
    ui.tbl(head, rows, shade=shade, min_width=1020)


def tv(c: nav.Ctx, d: dict) -> None:
    t, mn = d["tv"], c.mn
    u = F.unit(mn).replace("원", "")
    ui.h2("③ 영구가치 (TV) · 항상성장모형 (Gordon Growth)")
    rows = [
        (f"FCFF {t['year']} = NOPAT × (1 − g ÷ RONIC)", F.amt(t["fcf_next"], mn) + u),
        ("g · 신규투자수익률 (RONIC)", f"{F.p1(t['g'])} · {F.p1(t['ronic'])}", False, tx.plain_words(t.get("ronic_why") or "")),
        ("TV = FCFF ÷ (WACC − g)", F.amt(t["tv_plain"], mn) + u),
    ]
    if t["mid_year"]:
        rows.append(("× (1 + WACC)^0.5 (기중)", F.amt(t["tv"], mn) + u))
    rows += [
        (f"× 할인계수 ({t['t_n']:.1f}년)", f"{t['dfn']:.3f}"),
        ("= 영구가치 현재가치 (PV of TV)", F.amt(t["pv_tv"], mn) + u, True),
        ("내재 영구가치 배수", F.x_(t.get("implied_multiple"))),
    ]
    if t.get("ps_exit"):
        rows.append(
            (
                f"참고: 출구 배수법 (Exit Multiple) {F.x_(t['exit_mult'])}",
                f"TV {F.amt(t['tv_exit'], mn)}{u} · {F.won0(t['ps_exit'])}원",
            )
        )
    else:
        rows.append(("참고: 출구 배수법 (Exit Multiple)", "Peer EV/EBITDA 계산 불가"))
    ui.lines(rows)


def _dilution_row(dl: dict | None, mn: bool, u: str) -> tuple:
    """P7-U1F D-3: the dilutive-securities line (0 in the calculation; balances already in total debt)."""
    base = "주식 수는 발행 − 자기주식 기준. 전환·행사 희석은 반영하지 않음. CB·BW·EB 장부 금액(잔액)은 위 차입금에 포함. 전환형 = 전환사채·신주인수권·교환 관련 공시"
    if dl is None:
        return ("희석증권 (CB·BW·EB·스톡옵션)", "자료 없음(초안을 다시 만들면 표시)", False, base)
    val = f"잔액 {F.amt(dl['balance_eok'], mn)}{u}" + (
        f" · 주식가치의 {F.p1(dl['share_of_equity'])}" if F.ok(dl.get("share_of_equity")) and dl["balance_eok"] else ""
    )
    val += f" · {dl['years']}년 공시 스톡옵션 {dl['stock_option_n']} · 전환형 {dl['convertible_n']}"
    tip = (
        base
        + " · 공시 건수는 거래소공시의 조정·행사·취득 공시 기준(발행결정은 대부분 빠짐)"
        + (" · 판단 목록 '희석증권' 확인 항목" if dl.get("item") else "")
    )
    return ("희석증권 (CB·BW·EB·스톡옵션) — 반영 안 함", val, False, tip)


def _dilution_links(dl: dict | None) -> None:
    if not dl or not dl.get("recent"):
        return
    from src.workbench.events import VIEW

    links = " · ".join(
        f"<a href='{VIEW}{x['rcept_no']}' target='_blank'>{ui.esc(x['date'])} {ui.esc(x['name'][:24])}</a>" for x in dl["recent"]
    )
    st.markdown(f"<p class='wb-kpi-note'>희석증권 관련 최근 공시(원문): {links}</p>", unsafe_allow_html=True)


def bridge(c: nav.Ctx, d: dict) -> None:
    o, s, mn = c.o, c.s, c.mn
    br, sh = d["bridge"], d["shares"]
    u = F.unit(mn).replace("원", "")
    ui.h2("④ EV → 주주가치 조정 (Bridge)", "", ui.esc(f"재무 {d['meta']['bs_date']} 장부"))
    rows = [
        (
            f"FCFF 현재가치 (명시 {F.amt(d['pv_explicit'], mn)} + 수렴 {F.amt(d['pv_fade'], mn)}) + 영구가치 현재가치",
            f"{F.amt(d['pv_explicit'] + d['pv_fade'], mn)} + {F.amt(d['tv']['pv_tv'], mn)}{u}",
        ),
        (
            f"= EV ({d['meta']['bs_date'][5:]} → {d['meta']['as_of'][5:]} 이월)",
            f"{F.amt(d['ev_bs'], mn)} → {F.amt(d['ev'], mn)}{u}",
            True,
        ),
        (
            "+ 현금성자산" + (" (영업용 현금 차감)" if M.version(s)["overrides"].get("cash_adjust_mn") else ""),
            F.amt(br["cash_like"], mn) + u,
            False,
            tx.plain_words(str(br.get("cash_detail") or ""))[:300],
        ),
        ("+ 비영업자산", F.amt(br["non_operating"], mn) + u, False, tx.plain_words(str(br.get("nonop_detail") or ""))[:300]),
    ]
    if br.get("sotp"):
        sp = br["sotp"]
        for k, lab in (("listed", "  상장 종속회사 지분 시가"), ("unlisted", "  비상장 지분 장부")):
            if F.ok(sp.get(k)):
                rows.append((lab, F.amt(sp[k], mn) + u))
    if br.get("assoc"):
        rows.append(("  상장 관계기업 지분 시가", F.amt(br["assoc"].get("market") or br["assoc"].get("add"), mn) + u))
    rows += [
        (
            "− 차입금 (리스 포함) · 비지배지분",
            f"({F.amt(br['total_debt'], mn, paren=False)}) · ({F.amt(br['nci'], mn, paren=False)}){u}",
        ),
        (f"= 주주가치 (Equity) ÷ {sh['out']:,.0f}주", F.amt(d["equity"], mn) + u, True),
        (
            "유통주식수 = 발행 − 자사주" + (" + 우선주" if sh.get("pref_out") else ""),
            f"{(sh.get('common_issued') or 0):,} − {(sh.get('common_treasury') or 0):,}"
            + (f" + {sh['pref_out']:,}" if sh.get("pref_out") else ""),
            False,
            tx.plain_words(sh.get("source") or ""),
        ),
        _dilution_row(d.get("dilution"), mn, u),
        ("= 주당가치", F.won0(d["per_share"]) + "원", True),
    ]
    ui.lines(rows)
    _dilution_links(d.get("dilution"))
    bi = M.bridge_info(o)
    cf = bi.get("customer_funds") or {}
    if bi.get("affiliate_loans"):
        st.markdown(
            f"<p class='wb-kpi-note wb-warn'>계열사 대여금: {ui.esc(tx.plain_words(str(bi['affiliate_loans'])))}</p>",
            unsafe_allow_html=True,
        )
    if cf.get("items") or bi.get("items"):
        with st.expander("고객 자금 성격 부채 · 비영업 판단 항목"):
            if cf.get("items"):
                ui.tbl(
                    ["항목", "금액(억원)", "출처"],
                    [[str(x["label"])[:40], F.amt(x["amount"] / 100), str(x.get("source", ""))[:40]] for x in cf["items"]],
                    tips=False,
                )
                st.markdown(
                    f"<p class='wb-kpi-note'>현금성에서 빼면 주당 {F.signed(cf.get('diff'))}원(자동 초안 기준)</p>",
                    unsafe_allow_html=True,
                )
            for j in bi.get("items") or []:
                st.markdown(
                    f"<p class='wb-kpi-note'>{ui.esc(tx.plain_words(j['item']))} — 주당 {F.signed(j.get('impact'))} (대안: {ui.esc(tx.plain_words(j.get('alternative') or ''))})</p>",
                    unsafe_allow_html=True,
                )
    if c.mode == "public" and (o.subs or getattr(o, "assocs", []) or o.prefs):
        with st.expander("상장 종속회사·관계기업·우선주 종가 입력 (공개 모드)", expanded=bool(M.public_missing(o, s))):
            from app.wb import shell

            shell.public_form(c, "bridge", target_only=False)


def wacc(c: nav.Ctx, d: dict) -> None:
    w = d["wacc"]
    ui.h2("WACC")
    ui.lines(
        [
            (f"무위험이자율 (Rf) · 국고채 {w['tenor']}년", F.p1(w["rf"], 2)),
            (f"베타 βu → βL (부채비율 D/E {F.p1(w['de'])})", f"{w['beta_u']:.2f} → {w['beta_l']:.2f}"),
            ("시장·규모위험프리미엄 (MRP · SRP)", f"{F.p1(w['mrp'])} · {F.p1(w['srp'], 2)}"),
            ("자기자본비용 (Ke)", F.p1(w["ke"], 2)),
            (
                f"타인자본비용 (Kd) · 세전 {F.p1(w['kd'], 2)} · 세율 {F.p1(w['t_kd'])}",
                F.p1(w["kd_after"], 2),
                False,
                tx.plain_words(w.get("kd_label") or ""),
            ),
            (f"부채 비중 D/V {F.p1(w['wd'])}", ""),
            ("WACC", F.p1(w["wacc"], 2), True),
        ]
    )


def nwc(c: nav.Ctx, d: dict) -> None:
    n, mn = d["nwc"], c.mn
    u = F.unit(mn).replace("원", "")
    ui.h2(f"순운전자본 ({d['meta']['bs_date'][5:].replace('-', '/')})")
    zero = n["rec"] == 0 and n["pay"] == 0
    ui.lines(
        [
            ("매출채권 · 매출채권 회전일수", f"{F.amt(n['rec'], mn)}{u} · {n['dso']:.0f}일" + (" ⚠" if n["rec"] == 0 else "")),
            ("재고자산 · 재고자산 회전일수", f"{F.amt(n['inv'], mn)}{u} · {n['dio']:.0f}일"),
            ("매입채무 · 매입채무 회전일수", f"{F.amt(n['pay'], mn)}{u} · {n['dpo']:.0f}일" + (" ⚠" if n["pay"] == 0 else "")),
            ("= 순운전자본", F.amt(n["nwc"], mn) + u, True),
        ]
        + ([("데이터 검증", "매출채권·매입채무 0 — 원문 확인(데이터 점검 D-1)")] if zero else [])
    )


def scenarios(c: nav.Ctx, d: dict) -> None:
    sc, mn = d["scenarios"], c.mn
    names = [k for k in ("pessimistic", "base", "optimistic") if k in sc]
    lab = {"pessimistic": "Bear", "base": "Base", "optimistic": "Bull"}
    head = [""] + [lab[k] for k in names]
    rows = [
        ["출발 성장률"] + [F.p1(sc[k]["g_start"]) for k in names],
        ["정상화 영업이익률"] + [F.p1(sc[k]["margin"]) for k in names],
        [f"EV ({F.unit(mn)})"] + [F.amt(sc[k]["ev"], mn) for k in names],
        ["영구가치 비중 (TV)"] + [F.p1(sc[k]["tv_share"]) for k in names],
        ["내재 영구가치 배수"] + [F.x_(sc[k]["implied_multiple"]) for k in names],
        {"c": ["주당가치 · 항상성장모형"] + [F.won0(sc[k]["per_share"]) for k in names], "strong": True, "top": True},
        ["주당가치 · 출구 배수법"] + [F.won0(sc[k]["per_share_exit"]) if sc[k]["per_share_exit"] else "계산 불가" for k in names],
    ]
    srp = M.result(c.o, c.s, c.mode).get("srp", 0)
    ui.title_copy("시나리오 비교", f"SRP {F.p1(srp, 2)}", "", ui.tsv(head, rows))
    ui.tbl(head, rows)
    cols = M.srp_columns(c.o, c.s, c.mode)
    st.markdown(
        "<p class='wb-kpi-note'>Base · SRP 열: "
        + " · ".join(f"{F.p1(x['srp'], 2)} {F.won0(x['per_share'])}원" + (" (선택)" if x["chosen"] else "") for x in cols)
        + "</p>",
        unsafe_allow_html=True,
    )


def _grid(
    c: nav.Ctx,
    d: dict,
    kind: str,
    title: str,
    sub: str,
    corner: str,
    cols: list[str],
    rows_lab: list[str],
    vals: list[list],
    center: tuple[int, int],
    note: str,
) -> None:
    from app.wb import sens

    head = [corner] + cols
    rows = []
    for i, (rl, rv) in enumerate(zip(rows_lab, vals)):
        rows.append(
            {"c": [rl] + [F.won0(v) if F.ok(v) else "계산 불가" for v in rv], "hl": {center[1] + 1} if i == center[0] else set()}
        )
    ui.title_copy(title, "", ui.esc(sub), ui.tsv(head, rows))
    sens.table(c, d, kind, cols, rows_lab, vals, center, corner)  # P7-U2: a cell click previews and can carry the combination
    st.markdown(f"<p class='wb-kpi-note'>{ui.esc(note)} · 칸을 누르면 미리보기</p>", unsafe_allow_html=True)


def sens_wg(c: nav.Ctx, d: dict) -> None:
    g = d["grids"]
    w0 = g["wacc0"]
    cols = [F.p1(w0 + dw) for dw in g["wacc_steps"]]
    rl = [F.p1(x) for x in g["g_values"]]
    gT = d["tv"]["g"]
    ci = next((i for i, x in enumerate(g["g_values"]) if abs(x - gT) < 1e-9), None)
    cj = next((j for j, x in enumerate(g["wacc_steps"]) if abs(x) < 1e-12), None)
    vals = g["wacc_g"]
    mid = vals[ci][cj] if ci is not None and cj is not None else None
    spread = (max(r[cj] for r in vals if F.ok(r[cj])) - min(r[cj] for r in vals if F.ok(r[cj]))) / 2 if cj is not None else None
    note = (
        f"RONIC 하한 = WACC → g 영향 ±{abs(spread) / mid * 100:.1f}%"
        if mid and spread is not None and d["drivers"]["ronic"] == w0
        else "원/주 · Base"
    )
    _grid(
        c,
        d,
        "wg",
        "민감도 · WACC × 영구성장률 (g)",
        "원/주 · Base",
        "g \\ WACC",
        cols,
        rl,
        vals,
        (ci if ci is not None else -1, cj if cj is not None else -1),
        note,
    )


def sens_gm(c: nav.Ctx, d: dict) -> None:
    g = d["grids"]

    def pp(x):
        return "0" if abs(x) < 1e-12 else f"{x * 100:+.0f}%p".replace("-", "−")

    cols = [pp(x) for x in g["margin_shifts"]]
    rl = [pp(x) for x in g["growth_shifts"]]
    ci = next((i for i, x in enumerate(g["growth_shifts"]) if abs(x) < 1e-12), -1)
    cj = next((j for j, x in enumerate(g["margin_shifts"]) if abs(x) < 1e-12), -1)
    vals = g["growth_margin"]
    note = "원/주 · 기준 대비"
    if ci >= 0 and cj >= 0 and cj + 1 < len(vals[ci]) and F.ok(vals[ci][cj + 1]) and F.ok(vals[ci][cj]):
        step = g["margin_shifts"][cj + 1] - g["margin_shifts"][cj]
        note = f"영업이익률 ±{step * 100:.0f}%p ≈ ±{abs(vals[ci][cj + 1] - vals[ci][cj]):,.0f}원"
    _grid(
        c,
        d,
        "gm",
        "민감도 · 영업이익률 × 매출 성장률",
        "원/주 · 기준 대비",
        "성장률 \\ 영업이익률",
        cols,
        rl,
        vals,
        (ci, cj),
        note,
    )
