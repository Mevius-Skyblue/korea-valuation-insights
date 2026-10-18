"""2 데이터 확인: what the draft collected, with sources (DART filing links), and the items a person must judge.
Mode rules: PC shows KRX values ('한국거래소 통계정보'); public shows the user's inputs only and peer aggregates only."""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui
from app.wb import fmt as F
from app.wb import model as M
from app.wb import nav
from app.wb import text as tx
from app.wb.pages import judge_panel


def render(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    nav.header(c, "데이터 확인")
    st.markdown("<p class='wb-sub'>자동으로 모은 데이터를 확인하고, 표시된 항목만 판단하면 됩니다.</p>", unsafe_allow_html=True)
    if c.mode == "public" and M.public_missing(o, s):
        nav.public_inputs(c, "data")
    judge_panel.expander(c)
    with ui.card("kpis", None, plain=True):
        _kpis(c)
    a, b = st.columns(2)
    with a:
        with ui.card("peers", None):
            _peers(c)
    with b:
        with ui.card("beta", None):
            _beta(c)
    a, b = st.columns(2)
    with a:
        with ui.card("bridge", None):
            _bridge(c)
    with b:
        with ui.card("history", "과거 평균 (예측 출발점)", "자동 초안의 기본 방식이 쓰는 값과 3년 평균 방식(이전 기본값)의 값"):
            _history(c)
    with ui.card("fixes", "자동 보정·추정 표시", "자동 초안이 고치거나 추정한 곳 — 사람 확인 대상"):
        _corrections(c)
    st.button("다음: 가정 →", key="to_assume", type="primary", on_click=nav.go, args=("assume",))
    ui.footer(c.mode, M.AS_OF)


def _kpis(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    f = M.data_facts(o)
    rec = f["recon"] or {}
    cnt = rec.get("counts") or {}
    bad = len(rec.get("bad") or [])
    checks = [
        j
        for j in M.judgement_rows(s)
        if j["category"] in ("D&A 추정", "계정 오표기", "재무 기준 혼합", "주식 수", "이력 짧음") and j["status"] == "미처리"
    ]
    yrs = rec.get("years") or []
    sh = f["shares"]
    kd = f["kd"]
    mk = M.market(o, s, c.mode)
    rcp_fy = (M.rcepts(f["structure_source"]) or [""])[0]
    rcp_sh = (M.rcepts(sh.get("source")) or [""])[0]
    basis = "연결" if f["fs_div"] == "CFS" else "별도"
    items = [
        {
            "label": "원문 " + tx.term("대조", "대사") + " 일치",
            "value": f"{cnt.get('exact', 0)}/{rec.get('rows', 0)}",
            "badge": ui.badge(f"확인 필요 {bad + len(checks)}건", "warn" if bad or checks else "ok"),
            "note": f"매출·영업이익 등 공시 원문과 원 단위 대조(FY{yrs[0]}~{yrs[-1]})" if yrs else "대조 기록 없음",
        },
        {
            "label": f"매출 ({'연결' if o.summ.get('facts', {}).get('multi_fs', 'CFS') == 'CFS' else '별도'}, FY2025)",
            "value": F.eok(f["revenue_2025_eok"], unit=False),
            "unit": "억원",
            "note": f"평가 기준({basis}{', 배당금수익 제외' if o.sotp else ''}) "
            + tx.term("LTM")
            + f" {F.eok(f['ltm_rev_eok'])}"
            + (" · " + tx.dart_link(rcp_fy, "사업보고서") if rcp_fy else ""),
        },
        {
            "label": "유통주식수 (보통 + 우선)",
            "value": f"{int(f['shares_out']):,}",
            "unit": "주",
            "note": f"보통 발행 {sh['common_issued']:,} · 자사주 {sh['common_treasury']:,} · 우선 {f['pref_out']:,}"
            + (" · " + tx.dart_link(rcp_sh, "주식의 총수") if rcp_sh else ""),
        },
        {
            "label": "신용등급 · " + tx.term("Kd"),
            "value": kd.get("rating") or "미확인",
            "note": ui.esc(kd.get("basis") or kd.get("rating_source") or ""),
            "cls": "" if kd.get("rating") else "wb-warn",
        },
    ]
    if c.mode == "pc":
        items.append(
            {
                "label": "시장가 (기준일 종가 · 20일 " + tx.term("VWAP") + ")",
                "value": F.won(mk["close"], unit=False),
                "unit": "원",
                "note": f"VWAP {F.won(mk['vwap'])} · 한국거래소 통계정보",
            }
        )
    else:
        items.append(
            {
                "label": "시장가 (사용자 입력)",
                "value": F.won(mk["close"], unit=False) if mk["close"] else "입력 전",
                "unit": "원" if mk["close"] else "",
                "note": f"VWAP {F.won(mk['vwap'])} · 사용자 입력" if mk["vwap"] else "공개 모드: 직접 입력",
            }
        )
    ui.kpis(items)


def _peers(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    rows = M.peer_rows(o, s, c.mode)
    inc = [r for r in rows if r["include"]]
    ps = o.summ.get("peer_screen") or o.cfg.get("peer_screen") or {}
    step = ps.get("relax_step")
    relax = {None: "", 0: "완화 없음", 1: "완화 1단계(시가총액 0.1~10배)", 2: "완화 2단계(업종 코드 한 자리 넓게)"}.get(
        step, f"완화 {step}단계"
    )
    ui.head(
        f"{tx.term('피어')} {len(inc)}곳 (후보 {len(rows)}곳)",
        f"KSIC·시가총액·3년 흑자 규칙으로 자동 선택 · {relax}",
        ui.badge("사람 검토", "warn"),
    )
    if c.mode == "pc":
        body = [
            [
                r["name"],
                r["code"],
                "포함" if r["include"] else "제외",
                F.eok(r.get("mktcap_eok")),
                F.multiple(r.get("ev_ebitda"), 1),
                F.multiple(r.get("ev_sales"), 2),
                F.beta(r.get("beta_raw")),
                F.beta(r.get("r2")),
            ]
            for r in rows
        ]
        ui.table(
            ["피어", "코드", "포함", "시가총액", "EV/EBITDA", "EV/Sales", "β(원)", "R²"],
            body,
            num_cols=(3, 4, 5, 6, 7),
            caption="시가총액·배수·베타 회귀 값: 한국거래소 통계정보 기반",
            min_width=560,
        )
    else:
        rel = M.relative(o, s, c.mode)
        body = [[r["name"], r["code"], "포함" if r["include"] else "제외"] for r in rows]
        ui.table(["피어", "코드", "포함"], body)
        m = rel["multiples"]
        st.markdown(
            "<p class='wb-kpi-note'>공개 모드: 피어별 시가총액·배수·베타 회귀 값은 표시하지 않고 사분위·중앙값만 보여 줍니다.</p>",
            unsafe_allow_html=True,
        )
        ui.table(
            ["배수", "n", "하위 25%", "중앙값", "상위 25%"],
            [[k, v["n"], F.times(v["q25"]), F.times(v["median"]), F.times(v["q75"])] for k, v in m.items()],
            num_cols=(1, 2, 3, 4),
        )
    with st.expander("피어 편집 · 사업 개요(공시 원문 첫 문단)"):
        names = [r["name"] for r in rows]
        cur = [r["name"] for r in rows if r["include"]]
        pick = st.multiselect("포함할 피어", names, default=cur, key=f"peeredit_{M.version(s)['v']}")
        reason = st.text_input("변경 이유(선택)", key=f"peerwhy_{M.version(s)['v']}")
        if st.button("피어 목록 적용", key="peer_apply", disabled=sorted(pick) == sorted(cur)):
            _apply_peers(c, pick, cur, reason)
        for r in rows:
            st.markdown(
                f"<div style='font-size:13px;margin-top:6px'><b>{ui.esc(r['name'])}</b> — {ui.esc(r['reason'].split(' — ')[0])}"
                f"{tx.quote(r['overview'], 220) if r['overview'] else ''}</div>",
                unsafe_allow_html=True,
            )
    st.markdown(
        "<p class='wb-kpi-note'>피어를 빼거나 넣으면 βu·피어 배수·출발 성장률(피어 성장률 혼합)이 함께 바뀝니다. "
        "판단 목록의 '피어 유사성' 항목과 연결됩니다.</p>",
        unsafe_allow_html=True,
    )


def _apply_peers(c: nav.Ctx, pick: list[str], cur: list[str], reason: str) -> None:
    """Peer edit = an assumption change linked to the matching '피어 유사성' judgement items (first one via resolve,
    the others marked 수정 with the same version)."""
    s = M.load(c.sid)
    removed = [x for x in cur if x not in pick]
    items = [
        j for j in M.judgement_rows(s) if j["category"] in ("피어 유사성", "피어 직접 지정") and j["item"] in (removed or pick)
    ]
    if items:
        r = M.resolve(s, items[0]["id"], "direct", field="peers", value=pick, reason=reason or "피어 편집")
        if r["ok"]:
            for j in items[1:]:
                s["judgements"][j["id"]].update(
                    {
                        "status": "수정",
                        "resolution": {
                            "action": "direct",
                            "field": "peers",
                            "value": pick,
                            "reason": reason or "피어 편집",
                            "at": M.S._now(),
                            "v": M.version(s)["v"],
                        },
                    }
                )
            M.S.save(s)
    else:
        r = M.set_value(s, "peers", pick, reason or "피어 편집")
    if r["ok"]:
        st.success(f"피어 {len(pick)}곳으로 바꿨습니다(v{M.version(s)['v']}).")
        st.rerun()
    else:
        st.error(r["reason"])


def _beta(c: nav.Ctx) -> None:
    o, s = c.o, c.s
    b = M.beta_info(o, s, c.mode)
    ui.head(
        "베타",
        f"주간 2년 회귀 · 지수 {b['index']} · 피어 {b['n']}곳",
        ui.badge("확인 필요", "warn") if b["warn"] else ui.badge("기준 통과", "ok"),
    )
    src = {"peer": "피어 중앙값", "override": "사람 확정값"}.get(b["src"], b["src"])
    ui.kpis(
        [
            {"label": tx.term("βu") + f" ({src})", "value": F.beta(b["beta_u"])},
            {"label": "R² 중앙값", "value": F.beta(b["r2_median"]), "note": "설명력(0~1)", "cls": "wb-warn" if b["warn"] else ""},
            {
                "label": "목표 " + tx.term("D/E"),
                "value": F.times(b["de"], 3),
                "note": "자체 과거 시점 평균" + (" · 시점별 시가총액은 공개 모드에서 숨김" if c.mode == "public" else ""),
            },
        ]
    )
    if b["warn"]:
        st.markdown(
            "<p class='wb-kpi-note wb-warn'>주간 회귀의 설명력이 낮습니다(R² 중앙값 0.10 미만). 할인율에 큰 영향을 주는 값이라 "
            "근거 확인이 필요합니다(3단계에서 βu 직접 입력 가능).</p>",
            unsafe_allow_html=True,
        )
    if c.mode == "pc":
        de = o.ctx.c.market["de_points"]
        if len(de):
            ui.table(
                ["시점", "차입(억원)", "시가총액(억원)", "D/E"],
                [[r.date, F.eok(r.debt + r.lease, False), F.eok(r.mktcap, False), F.times(r.de, 3)] for r in de.itertuples()],
                num_cols=(1, 2, 3),
                caption="D/E 시점별 값(시가총액: 한국거래소 통계정보)",
            )


def _bridge(c: nav.Ctx) -> None:
    o = c.o
    bi = M.bridge_info(o)
    comp = bi["composition"]
    pend = [j for j in bi["items"]]
    ui.head(
        f"{tx.term('순차입금')} 브리지 ({o.cfg['meta']['bs_date']})",
        "기업가치 → 주식가치(자동 초안 기준, 억원)",
        ui.badge("확인 필요", "warn") if pend or bi["customer_funds"] else "",
    )
    rows = []
    for k, lab in (
        ("ev", "기업가치(EV)"),
        ("cash_like", "+ 현금성 자산"),
        ("non_operating", "+ 비영업 자산"),
        ("debt", "− 총차입금(리스 포함)"),
        ("nci", "− 비지배지분"),
        ("equity", "= 주식가치"),
    ):
        if comp.get(k) is not None:
            rows.append([lab, F.mn_eok(comp[k], False)])
    if rows:
        ui.table(["항목", "억원"], rows, num_cols=(1,))
    cf = bi["customer_funds"] or {}
    if cf.get("items"):
        st.markdown(
            "<p class='wb-h2' style='font-size:15px;margin-top:8px'>고객 자금 성격 부채(판단 대상)</p>", unsafe_allow_html=True
        )
        ui.table(
            ["항목", "금액(억원)", "출처"],
            [[x["label"][:40], F.mn_eok(x["amount"], False), x.get("source", "")] for x in cf["items"]],
            num_cols=(1,),
            caption=f"현금성에서 빼면 주당 {F.won(cf.get('diff'), sign=True)}(자동 초안 기준)",
        )
    if bi["affiliate_loans"]:
        st.markdown(
            f"<p class='wb-kpi-note wb-warn'>계열사 대여금 표시: {ui.esc(bi['affiliate_loans'])}</p>", unsafe_allow_html=True
        )
    for j in pend:
        st.markdown(
            f"<p class='wb-kpi-note'><span class='wb-dot'></span>{ui.esc(j['item'])} — 주당 영향 {F.won(j.get('impact'), sign=True)} "
            f"(대안: {ui.esc(j.get('alternative') or '')})</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<p class='wb-kpi-note'>현금처럼 빼면 과대평가될 수 있는 항목은 회수 가능성을 사람이 판단합니다(3단계 '영업용 현금' 칸).</p>",
        unsafe_allow_html=True,
    )


def _history(c: nav.Ctx) -> None:
    h = M.history_info(c.o)
    y = h["years"] or []
    cy = h["cagr_years"] or []
    ui.table(
        ["항목", "값", "쓰임"],
        [
            [f"매출 CAGR FY{cy[0]}→{cy[-1]}" if cy else "매출 CAGR", F.pct(h["cagr"]), "3년 평균 방식의 출발 성장률"],
            [
                "자기 CAGR · 피어 성장률 중앙값",
                f"{F.pct(h['own_cagr'])} · {F.pct(h['peer_growth'])}",
                "기본 방식 출발 성장률 = 둘의 평균(−10%~+25%)",
            ],
            ["기본 방식 출발 성장률", F.pct(h["g0"]), "기본 방식"],
            [
                f"영업이익률 {('FY' + str(y[0]) + '~' + str(y[-1])) if y else ''} 평균",
                F.pct(h["margin"]),
                "3년 평균 방식의 정상 이익률",
            ],
            ["기본 방식 출발 이익률", F.pct(h["m0"]), ui.esc(tx.plain_words(h["m0_src"] or ""))],
            ["피어 LTM 영업이익률 중앙값", F.pct(h["peer_margin"]), "2032년까지 차이의 50% 수렴"],
            ["매출원가율", F.pct(h["cogs_ratio"], 1), "3년 평균"],
            ["DSO · DIO · DPO", f"{F.days(h['dso'])} · {F.days(h['dio'])} · {F.days(h['dpo'])}", "운전자본 회전일수 3년 평균"],
            ["D&A ÷ 매출 · CAPEX ÷ 매출", f"{F.pct(h['dna_ratio'], 1)} · {F.pct(h['capex_ratio'], 1)}", "3년 평균"],
        ],
        num_cols=(1,),
    )


def _corrections(c: nav.Ctx) -> None:
    cr = M.corrections(c.o)
    rows = []
    for x in cr["debt_reclass"]:
        rows.append(
            [
                "계정 오표기 수정",
                f"{x.get('year', '')} {x.get('period', '')}",
                ui.esc(str(x.get("label") or x.get("name") or x)[:80]),
            ]
        )
    est = [d for d in cr["dna"] if d.get("estimated")]
    for d in est:
        rows.append(["D&A 추정", f"{d['year']} {d['period']}", f"{d.get('source', '')} {F.mn_eok(d.get('total'))}"])
    src = sorted({d.get("source", "") for d in cr["dna"]})
    if cr["dna"] and not est:
        rows.append(["D&A 출처", f"{len(cr['dna'])}개 기간", ", ".join(src) + " (추정 없음)"])
    for y, p, other in cr["basis_fill"]:
        rows.append(["재무 기준 혼합", f"{y} {p}", f"{other} 값으로 채움"])
    if cr["shares_note"]:
        n = cr["shares_note"]
        rows.append(["주식 수 사건", "기준일", f"보고서 발행 {n['report_issued']:,}주 → 기준일 상장 {n['asof_listed']:,}주"])
    if rows:
        ui.table(["종류", "기간", "내용"], rows)
    else:
        st.markdown("<p class='wb-kpi-note'>오표기 수정·D&A 추정·재무 기준 혼합 없음.</p>", unsafe_allow_html=True)
