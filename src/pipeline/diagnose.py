"""Result-reliability diagnostics and the ranked human-review list (P7-B2, rules pre-registered in config/p7b2.yaml).

Nothing here changes a valuation value: every alternative is a candidate or a sensitivity next to the default.

    signals(dcf, q25, q75, n, price, rules)      traffic lights: DCF vs the peer per-share range, DCF ÷ close, overall
    mechanical(...)                              everything for one company_dcf company (called from engine_ref):
        reverse          normal margin / start growth / WACC that reproduce the peer EV/EBITDA median per share
        composition      what the equity value is made of (terminal value, explicit + fade, cash, non-operating, debt, NCI)
        anomalies        loss year in the margin window, volatility vs the scenario width, ROIC < WACC, ...
        candidates       normal-margin candidates and their per-share values (display only)
        sensitivities    customer-fund cash, NCI alternatives
        impacts          per-share change of each "other choice" -> rank_review
    customer_funds(con, corp, fs_div)            customer-fund liabilities from the balance sheet and the notes
    rank_review(review, impacts)                 the person's list ordered by impact (top 5 marked), then the rest
Per-share values in 원, amounts in 억원 inside (company_dcf units) and 백만원 in the output dict (Excel units).
"""

from __future__ import annotations

import re
from datetime import date

import numpy as np

from src import yamlio
from src.collect.core import ROOT

CFG = ROOT / "config" / "p7b2.yaml"
EOK = 1e8
LIGHTS = ["초록", "노랑", "빨강"]


def load_rules() -> dict:
    return yamlio.load(CFG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 1 signals (pure)


def light_peer(dcf: float, q25: float | None, q75: float | None, n: int, r: dict) -> str:
    sp = r["signal_peer"]
    if q25 is None or q75 is None or not np.isfinite(q25) or not np.isfinite(q75) or n < sp["min_n"]:
        return "회색"
    if q25 <= dcf <= q75:
        return "초록"
    if sp["yellow_low"] * q25 <= dcf < q25 or q75 < dcf <= sp["yellow_high"] * q75:
        return "노랑"
    return "빨강"


def light_market(dcf: float, price: float, r: dict) -> str:
    sm = r["signal_market"]
    x = dcf / price if price else float("nan")
    if sm["green"][0] <= x <= sm["green"][1]:
        return "초록"
    if sm["yellow"][0] <= x <= sm["yellow"][1]:
        return "노랑"
    return "빨강"


def overall(*lights: str) -> str:
    known = [x for x in lights if x in LIGHTS]
    return max(known, key=LIGHTS.index) if known else "회색"


def signals(dcf: float, peer: dict, price: float, r: dict) -> dict:
    """peer: {'basis', 'q25', 'q75', 'median', 'n'} per-share range of the chosen multiple."""
    lp = light_peer(dcf, peer.get("q25"), peer.get("q75"), int(peer.get("n") or 0), r)
    if peer.get("valid") is False:  # P7-B3 peer-range validity: 'cannot be interpreted' (grey) + reasons
        lp = "회색"
    lm = light_market(dcf, price, r)
    return {
        "dcf": dcf,
        "peer_basis": peer.get("basis"),
        "q25": peer.get("q25"),
        "q75": peer.get("q75"),
        "peer_median": peer.get("median"),
        "peer_n": int(peer.get("n") or 0),
        "price": price,
        "ratio_market": dcf / price if price else None,
        "light_peer": lp,
        "light_market": lm,
        "light": overall(lp, lm),
        "peer_valid": peer.get("valid", True),
        "peer_invalid": peer.get("invalid", []),
    }


def peer_validity(rng: dict, multiples: dict, v: dict | None = None) -> list[str]:
    """config/p7b3.yaml peer_validity: reasons the per-share peer range cannot be interpreted (empty = valid)."""
    v = v or yamlio.load((ROOT / "config" / "p7b3.yaml").read_text(encoding="utf-8"))["peer_validity"]
    q25, q75 = rng.get("q25"), rng.get("q75")
    out = []
    if q25 is not None and np.isfinite(q25) and q25 <= 0:
        out.append(f"범위 하단 ≤ 0(q25 주당 {q25:,.0f}원)")
    elif q25 and q75 and np.isfinite(q25) and np.isfinite(q75) and q75 / q25 > v["spread_ratio"]:
        out.append(f"q75 ÷ q25 = {q75 / q25:.1f} > {v['spread_ratio']:.0f}")
    if rng.get("basis") == "EV/EBITDA":
        eb = (multiples.get("EV/EBITDA") or {}).get("metric")
        rev = (multiples.get("EV/Sales") or {}).get("metric")
        if eb is not None and rev and np.isfinite(eb) and rev > 0 and eb / rev < v["target_metric_small"]:
            out.append(f"대상 EBITDA ÷ 매출 = {eb / rev:.1%} < {v['target_metric_small']:.0%}")
    return out


def peer_range(multiples: dict, r: dict) -> dict:
    """EV/EBITDA per-share quartiles; EV/Sales when EV/EBITDA has n < min_n (P7-B2) or when the target's own EBITDA is
    N/M so the per-share range is missing (P7-B2b, config/p7b2b.yaml structure.peer_signal_fallback)."""

    def ok(v):
        return v is not None and np.isfinite(v)

    for nm in ("EV/EBITDA", "EV/Sales"):
        m = multiples.get(nm) or {}
        if (m.get("n") or 0) >= r["signal_peer"]["min_n"] and ok(m.get("ps_q25")) and ok(m.get("ps_q75")):
            rng = {"basis": nm, "q25": m["ps_q25"], "q75": m["ps_q75"], "median": m["ps_median"], "n": m["n"]}
            bad = peer_validity(rng, multiples)
            return {**rng, "valid": not bad, "invalid": bad}
    m = multiples.get("EV/EBITDA") or {}
    return {
        "basis": "EV/EBITDA",
        "q25": m.get("ps_q25"),
        "q75": m.get("ps_q75"),
        "median": m.get("ps_median"),
        "n": m.get("n") or 0,
    }


# ---------------------------------------------------------------- 2 customer funds


def fund_patterns(rules: dict | None = None) -> tuple[re.Pattern, re.Pattern]:
    """(match, exclude) patterns of customer-fund liability names, with the general fixes recorded after the dev sample."""
    rules = rules or load_rules()
    cf = rules["customer_funds"]
    ex = cf["exclude_regex"]
    for f_ in rules.get("fixes") or []:
        if f_.get("customer_funds_exclude_add"):
            ex += "|" + f_["customer_funds_exclude_add"]
    return re.compile(cf["regex"]), re.compile(ex)


def is_customer_fund(label: str, rules: dict | None = None) -> bool:
    pat, excl = fund_patterns(rules)
    nm = label.replace(" ", "")
    return bool(pat.search(nm)) and not excl.search(nm)


def customer_funds(con, corp: str, fs_div: str, year: int = 2026, reprt: str = "11012") -> dict:
    """Balance-sheet liability lines and note-table rows whose name matches the pre-registered pattern (원)."""
    from src.clean.dna import _num, html_tables, unit_of
    from src.collect.core import RawStore
    from src.collect.doc_text import fs_sections, main_xml
    from src.valuation.peer_p3 import bs_lines

    pat, excl = fund_patterns()
    found: dict[str, tuple[float, str]] = {}
    for r in bs_lines(con, corp, fs_div, year, reprt).itertuples():
        nm = r.account_nm.replace(" ", "")
        if r.section == "L" and pat.search(nm) and not excl.search(nm) and r.amount:
            found.setdefault(nm, (float(r.amount), "재무상태표"))
    rc = con.execute(
        """SELECT DISTINCT rcept_no FROM fs_raw WHERE corp_code=? AND fs_div=? AND bsns_year=? AND reprt_code=?""",
        [corp, fs_div, year, reprt],
    ).fetchone()
    f = ROOT / "data" / "raw" / "dart" / "document.xml" / f"{rc[0]}.zip.gz" if rc else None
    if f is not None and f.exists():
        sec = fs_sections(main_xml(RawStore.load(f))).get(f"{fs_div}_NOTES", "")
        for t in html_tables(sec) if sec else []:
            unit = unit_of(t["before"]) or unit_of(" ".join(" ".join(x) for x in t["rows"][:2]))
            if unit is None:
                continue
            for row in t["rows"]:
                if not row:
                    continue
                nm = row[0]
                if not pat.search(nm) or excl.search(nm) or nm in found:
                    continue
                v = next((x for x in (_num(c) for c in row[1:]) if x is not None), None)
                if v is not None and v > 0:
                    found[nm] = (v * unit, "주석")
    kept = []
    for nm, (v, src) in found.items():  # the same amount under two labels is counted once (0.5%)
        if not any(abs(v - k[1]) <= 0.005 * max(v, k[1]) for k in kept):
            kept.append((nm, v, src))
    return {
        "amount": float(sum(v for _, v, _ in kept)),
        "items": [{"label": n, "amount": v, "source": s} for n, v, s in kept],
        "rcept": rc[0] if rc else None,
    }


# ---------------------------------------------------------------- 3 everything for one company_dcf company


def _bisect(f, lo, hi, n=80):
    from src.valuation.company_dcf import bisect

    try:
        return bisect(f, lo, hi, n)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def peer_inputs(sel, p3, tiers) -> dict:
    """The aggregates of the peer tables mechanical() needs (P7-C3 public snapshot records these, not the rows):
    number of peers with a βu, and the peers' LTM operating-margin median (normal-margin candidate)."""
    pp = p3[p3.tier.isin(tiers)]
    pm = (pp.op / pp.revenue).replace([np.inf, -np.inf], np.nan).dropna()
    de = sel.de_avg.dropna() if len(sel) and "de_avg" in sel.columns else []
    return {
        "n_beta": int(sel.bu_avg.notna().sum()) if len(sel) else 0,
        "peer_margin_median": float(pm.median()) if len(pm) else None,
        "peer_margin_n": int(len(pm)),
        # P7-X2b judgement alternative 'target D/E = peer median' (aggregate; the public cut applies at use)
        "peer_de_median": float(np.median(de)) if len(de) else None,
        "peer_de_n": int(len(de)),
    }


def _customer_funds_of(corp: str, fs: str) -> dict:
    """customer_funds with its own read-only connection (P7-C3 data seam: DART lines and note tables only)."""
    from src.valuation.company_dcf import _close, _con
    from src.workbench.snapdata import seam

    @seam("customer_funds", key=lambda corp, fs: (corp, fs))
    def run(corp, fs):
        con = _con()
        try:
            return customer_funds(con, corp, fs)
        finally:
            _close(con)

    return run(corp, fs)


def _dilution_filings(stock_code: str, as_of: str) -> list[dict]:
    """P7-U1F D-3: stock-option / convertible-type filings of the saved exchange-disclosure list in the years before the
    valuation date (config/p7u1f.yaml d3_dilution filings_rule). Data seam (P7-C3): the public deployment replays it."""
    from src.workbench.snapdata import seam

    @seam("dilution_filings", key=lambda code, d: (code, d))
    def run(code, d):
        import duckdb

        from src.db.build import DB_PATH
        from src.yamlio import load

        yrs = int(load((ROOT / "config" / "p7u1f.yaml").read_text(encoding="utf-8"))["params"]["d3_years"])
        end = date.fromisoformat(d)
        start = end.replace(year=end.year - yrs)
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            df = con.execute(
                "SELECT rcept_no, CAST(rcept_dt AS VARCHAR) AS dt, report_nm FROM disclosure_list "
                "WHERE stock_code = ? AND rcept_dt > ? AND rcept_dt <= ? ORDER BY rcept_dt DESC, rcept_no DESC",
                [code, start, end],
            ).df()
        finally:
            con.close()
        out = []
        for r in df.itertuples():
            nm = str(r.report_nm)
            if re.search(r"자회사의\s*주요경영사항|종속회사의\s*주요경영사항|전환우선주|전환주식|주식교환", nm):
                continue
            if "주식매수선택권" in nm:
                kind = "stock_option"
            elif re.search(r"전환사채|전환가액|전환청구권|신주인수권|교환사채|교환가액|교환청구권", nm):
                kind = "convertible"
            else:
                continue
            out.append({"rcept_no": r.rcept_no, "date": r.dt, "name": re.sub(r"\s+", " ", nm).strip(), "kind": kind})
        return out

    return run(stock_code, as_of)


def dilution(c, eq: float | None) -> dict | None:
    """P7-U1F D-3 (config/p7u1f.yaml d3_dilution): CB / BW / EB book balances at the balance-sheet date (already in total
    debt), the filings of the last years, and the check item when the balance is >= 5% of the equity value or a stock-option
    filing exists. Values of the model do not change. None when the filings are not available (old public snapshot)."""
    from src.valuation.company_dcf import val
    from src.workbench.snapdata import Missing
    from src.yamlio import load

    P = load((ROOT / "config" / "p7u1f.yaml").read_text(encoding="utf-8"))["params"]
    keys = ("cb_current", "cb_noncurrent", "bw_current", "bw_noncurrent", "eb_current", "eb_noncurrent")
    bal = {k: val(c, k, c.Y, c.P) for k in keys}
    total = float(sum(bal.values()))
    code = str(c.cfg["target"].get("stock_code") or c.cfg["target"].get("code") or "")
    try:
        fl = _dilution_filings(code, c.cfg["meta"]["as_of"]) if code else []
    except Missing:
        return None
    so = [x for x in fl if x["kind"] == "stock_option"]
    cv = [x for x in fl if x["kind"] == "convertible"]
    share = total / eq if eq and eq > 0 else None
    flag = (share is not None and share >= float(P["d3_balance_share"])) or (share is None and total > 0) or bool(so)
    out = {
        "balance_eok": total,
        "balance": bal,
        "share_of_equity": share,
        "years": int(P["d3_years"]),
        "stock_option_n": len(so),
        "convertible_n": len(cv),
        "recent": fl[: int(P["d3_links"])],
        "item": None,
    }
    if flag:
        parts = []
        if total > 0:
            parts.append(f"CB·BW·EB 잔액 {total:,.1f}억" + (f"(주식가치의 {share:.1%})" if share is not None else ""))
        if so:
            parts.append(f"주식매수선택권 공시 {len(so)}건")
        if cv:
            parts.append(f"전환·신주인수권·교환 공시 {len(cv)}건")
        out["item"] = {
            "category": "희석증권",
            "item": " · ".join(parts),
            "detail": (
                f"지금 모델: CB·BW·EB 장부 금액은 총차입금(부채), 주식 수는 발행 − 자기주식(희석 미반영). "
                f"공시 건수는 평가기준일 전 {int(P['d3_years'])}년 거래소공시(조정·행사·취득 공시 기준, 발행결정은 대부분 빠짐)"
            ),
            "impact": None,
            "alternative": "부채 처리(지금) 또는 원문 확인 후 판단",
        }
    return out


def in_range(field: str, value) -> bool:
    """P7-E K11 (config/p7e.yaml k11_candidates): a judgement candidate value the work screen accepts - the same check and
    ranges as an input (src.workbench.spec.check). Out-of-range candidates are left out of the impacts and the ranking."""
    from src.pipeline.draft_common import p7e_off

    if p7e_off("k11"):
        return True
    from src.workbench.spec import check

    return bool(check(field, value)[0])


def oor_text(pairs: list[tuple[str, object]]) -> str:
    """'후보 없음(범위 밖: value, ...)' for candidates out of the screen's range."""
    from src.workbench.spec import fmt

    return "후보 없음(범위 밖: " + ", ".join(fmt(f, v) for f, v in pairs) + ")"


def mechanical(c, h, cap, srps, w_base, bu0, de_own, kd, br, multiples, sel, p3, grid, rf_srp, tiers, public=None) -> dict:
    """Diagnostics for a company_dcf company. c: Company, h: history(), grid: engine_ref grid (base, SRP) -> dict.
    public (P7-C3 public snapshot): peer_inputs() recorded on the PC instead of the per-peer tables; the leave-one-peer-out
    βu impacts need per-peer βu and are not computed (config/p7c3.yaml decisions.peer_change_public)."""

    from src.valuation.company_dcf import dcf_value, discount_rate, forecast, val

    r = load_rules()["diagnostics"]
    v2 = getattr(c, "v2", None)
    to_mn_ = 100.0  # 억원 -> 백만원
    m_base = v2["m0"] if v2 else h["margin"]  # start margin of the path in use (v2: 5-year median)
    s0 = srps[0]
    w0 = w_base[s0]
    tb = forecast(c, h)
    v0 = dcf_value(c, h, tb, w0, cap)
    ps0 = v0["per_share"]
    shares = c.market["shares_out"]
    price = c.market["close"]
    peer = peer_range(multiples, r)
    sig = signals(ps0, peer, price, r)

    # reverse: one input at a time reproduces the peer median per share
    target = peer["median"]
    rev = {"target": target, "basis": peer["basis"]}
    if target is not None and np.isfinite(target):
        ms = _bisect(
            lambda x: dcf_value(c, h, forecast(c, h, 0.0, x), w0, cap)["per_share"] - target,
            *r["reverse"]["ranges"]["margin_shift"],
        )
        g0 = _bisect(
            lambda x: dcf_value(c, h, forecast(c, h, g_start_override=x), w0, cap)["per_share"] - target,
            *r["reverse"]["ranges"]["start_growth"],
        )
        wr = _bisect(lambda x: dcf_value(c, h, tb, x, cap)["per_share"] - target, *r["reverse"]["ranges"]["wacc"])
        rev.update(
            {
                "margin": None if ms is None else m_base + ms,
                "margin_base": m_base,
                "start_growth": g0,
                "start_growth_base": v2["g0"] if v2 else h["cagr"],
                "wacc": wr,
                "wacc_base": w0,
            }
        )
        chk = []  # accuracy: recompute with the solved value
        if ms is not None:
            chk.append(dcf_value(c, h, forecast(c, h, 0.0, ms), w0, cap)["per_share"] - target)
        if g0 is not None:
            chk.append(dcf_value(c, h, forecast(c, h, g_start_override=g0), w0, cap)["per_share"] - target)
        if wr is not None:
            chk.append(dcf_value(c, h, tb, wr, cap)["per_share"] - target)
        rev["max_abs_error"] = float(max(abs(x) for x in chk)) if chk else None

    # composition of the equity value (억원 -> 백만원 at the end)
    from datetime import date as _date

    from src.valuation.dcf import roll_forward

    days = (_date.fromisoformat(c.cfg["meta"]["as_of"]) - _date.fromisoformat(c.cfg["meta"]["bs_date"])).days  # P7-X2b (was 92)
    rr = v0["r"]
    tv = roll_forward(rr.pv_tv_gordon, w0, days)
    expl = roll_forward(rr.pv_explicit, w0, days)
    eq = v0["equity"]
    comp = {
        "ev": v0["ev"],
        "tv": tv,
        "explicit": expl,
        "cash_like": br["cash_like"],
        "non_operating": br["non_operating"],
        "debt": -br["total_debt"],
        "nci": -br["nci"],
        "equity": eq,
    }
    comp_share = {k: (v / eq if eq else None) for k, v in comp.items() if k not in ("equity",)}

    # anomalies
    yrs5 = range(c.FY - 4, c.FY + 1)  # FY(Y−5)~FY(Y−1) (P7-X2b: from the config's LTM year)
    margins = [val(c, "operating_income", y) / val(c, "revenue", y) for y in yrs5 if val(c, "revenue", y)]
    revs = [val(c, "revenue", y) for y in range(c.FY - 5, c.FY + 1)]
    growths = [b / a - 1 for a, b in zip(revs, revs[1:]) if a and b]
    an = r["anomalies"]
    avg_ops = [val(c, "operating_income", y) for y in c.cfg["params"]["avg_years"]]
    width = 0.02
    flags = []

    def flag(key, on, value):
        flags.append({"key": key, "text": an[key], "on": bool(on), "value": value})

    flag("loss_year_in_margin", any(o <= 0 for o in avg_ops), ", ".join(f"{o:,.0f}억" for o in avg_ops))
    msd = float(np.std(margins, ddof=1)) if len(margins) > 1 else float("nan")
    gsd = float(np.std(growths, ddof=1)) if len(growths) > 1 else float("nan")
    flag("margin_volatility", np.isfinite(msd) and msd > 2 * width, msd)
    flag("growth_volatility", np.isfinite(gsd) and gsd > 2 * width, gsd)
    flag("roic_below_wacc", cap < w0, cap - w0)
    ts = v0["tv_share"]
    flag("terminal_heavy", ts is not None and (ts > 0.75 or ts < 0), ts)
    big = max((abs(comp[k]) for k in ("cash_like", "non_operating", "debt", "nci")), default=0.0)
    flag("bridge_heavy", eq and big > 0.5 * abs(eq), big / abs(eq) if eq else None)
    neg = [k for k, x in grid.items() if x["per_share"] < 0]
    flag("negative_equity_scenario", bool(neg), len(neg))

    # normal-margin candidates (display only)
    pos = [
        val(c, "operating_income", y) / val(c, "revenue", y)
        for y in c.cfg["params"]["avg_years"]
        if val(c, "operating_income", y) > 0 and val(c, "revenue", y)
    ]
    pin = public if public is not None else peer_inputs(sel, p3, tiers)
    cand_vals = {
        "ex_loss_3y": float(np.mean(pos)) if pos else None,
        "median_5y": float(np.median(margins)) if margins else None,
        "peer_median": pin["peer_margin_median"],
    }
    cands = []
    for cd in r["margin_candidates"]:
        m = cand_vals[cd["id"]]
        ps = None if m is None else dcf_value(c, h, forecast(c, h, 0.0, m - m_base), w0, cap)["per_share"]
        cands.append(
            {"id": cd["id"], "label": cd["label"], "margin": m, "per_share": ps, "diff": None if ps is None else ps - ps0}
        )

    # sensitivities: customer funds, NCI
    from src.valuation.company_dcf import fs_div

    cf = _customer_funds_of(c.cfg["target"]["corp_code"], fs_div(c.cfg))
    op_cash = min(br["cash_like"], cf["amount"] / EOK)
    sens = {
        "customer_funds": {
            "liabilities": cf["amount"] / EOK,
            "items": cf["items"],
            "operating_cash": op_cash,
            "per_share": (eq - op_cash) * EOK / shares,
            "diff": -op_cash * EOK / shares,
        }
    }
    nci = br["nci"]
    teq = val(c, "total_equity", c.Y, c.P)
    pre = eq + nci
    pbr = multiples.get("PBR", {}).get("median")
    alt_a = pre * (1 - nci / teq) if teq else None
    alt_b = pre - nci * pbr if pbr is not None and np.isfinite(pbr) else None
    sens["nci"] = {
        "book": nci,
        "total_equity": teq,
        "share_book": nci / teq if teq else None,
        "peer_pbr": pbr,
        "a_per_share": None if alt_a is None else alt_a * EOK / shares,
        "b_per_share": None if alt_b is None else alt_b * EOK / shares,
        "a_diff": None if alt_a is None else (alt_a - eq) * EOK / shares,
        "b_diff": None if alt_b is None else (alt_b - eq) * EOK / shares,
    }

    # impacts of the other choices (per share minus the default, base scenario, SRP 0%)
    imp = {}
    oor = {}  # P7-E K11: impact key -> '후보 없음(범위 밖: …)' when every alternative is out of the screen's range
    cd_ = [x for x in cands if x["diff"] is not None and in_range("normal_margin", x["margin"])]
    bad_ = [x for x in cands if x["diff"] is not None and not in_range("normal_margin", x["margin"])]
    if bad_ and not cd_:
        oor["normalize"] = oor_text([("normal_margin", x["margin"]) for x in bad_])
    if cd_:
        best = max(cd_, key=lambda x: abs(x["diff"]))
        imp["normalize"] = {"diff": best["diff"], "alt": f"정상 이익률 {best['label']} {best['margin']:.2%}(기본 {m_base:.2%})"}
    if op_cash > 0:
        imp["customer_funds"] = {"diff": sens["customer_funds"]["diff"], "alt": f"영업용 현금 {op_cash:,.0f}억을 브리지에서 뺌"}
    nci_val = {"a": pre * nci / teq if teq else None, "b": nci * pbr if alt_b is not None else None}  # 억원, the candidate
    nd_all = [(k, sens["nci"][f"{k}_diff"]) for k in ("a", "b") if sens["nci"][f"{k}_diff"] is not None]
    nd = [(k, d_) for k, d_ in nd_all if nci_val[k] is not None and in_range("nci_mn", nci_val[k] * 100.0)]
    if nci and nd_all and not nd:
        oor["nci"] = oor_text([("nci_mn", nci_val[k] * 100.0) for k, _ in nd_all if nci_val[k] is not None])
    if nci and nd:
        k, d_ = max(nd, key=lambda x: abs(x[1]))
        imp["nci"] = {
            "diff": d_,
            "alt": "비례법(연결 주식가치 × 지배 장부 비중)" if k == "a" else f"비지배 장부 × 피어 P/B 중앙값 {pbr:.2f}배",
        }
    bbb, aa = c.rates["CB3Y_BBBm"], c.rates["CB3Y_AAm"]
    kd_alt = aa if abs(kd - bbb) < 1e-12 else bbb
    if in_range("kd", kd_alt):
        imp["kd"] = {
            "diff": dcf_value(c, h, tb, discount_rate(c, s0, bu0, de_own, kd_alt), cap)["per_share"] - ps0,
            "alt": f"세전 Kd {kd_alt:.2%}({'AA-' if kd_alt == aa else 'BBB-'} 3년, 기본 {kd:.2%})",
        }
    else:
        oor["kd"] = oor_text([("kd", kd_alt)])
    gp, go = grid[("pessimistic", s0)]["per_share"] - ps0, grid[("optimistic", s0)]["per_share"] - ps0
    imp["scenario"] = {"diff": gp if abs(gp) >= abs(go) else go, "alt": "비관(−2%p)" if abs(gp) >= abs(go) else "낙관(+2%p)"}
    g1, g3 = (dcf_value(c, h, tb, w0, cap, g=g)["per_share"] - ps0 for g in (0.01, 0.03))
    imp["g"] = {"diff": g1 if abs(g1) >= abs(g3) else g3, "alt": "g 1%" if abs(g1) >= abs(g3) else "g 3%"}
    loo = {}
    for nm in [] if public is not None else sel.name:
        rest = sel[sel.name != nm].bu_avg.dropna()
        if len(rest):
            w_ = discount_rate(c, s0, float(rest.median()), de_own, kd)
            loo[nm] = {
                "diff": dcf_value(c, h, tb, w_, cap)["per_share"] - ps0,
                "alt": f"{nm} 빼고 βu {float(rest.median()):.3f}(기본 {bu0:.3f})",
            }
    imp["peers"] = loo
    mk = c.market
    if mk["pref_out"]:
        pref_val = (
            sum(p[0] * p[2] for p in mk["listed_pref"])
            + mk["close"] * max(mk["pref_out"] - sum(p[2] for p in mk["listed_pref"]), 0)
        ) / EOK
        alt = (eq - pref_val) * EOK / mk["common_out"]
        imp["pref"] = {"diff": alt - ps0, "alt": f"우선주 시가 {pref_val:,.0f}억을 빼고 보통주로만 나눔"}
    imp["srp"] = {"diff": grid[("base", srps[-1])]["per_share"] - ps0, "alt": f"SRP {srps[-1]:.0%}"}
    sn = mk.get("shares_note")  # P7-B3 B3-F1: share count changed after the report date
    if sn:
        alt_sh = sn["report_issued"] - c.cfg["shares"]["common_treasury"] + mk["pref_out"]
        imp["shares"] = {
            "diff": eq * EOK / alt_sh - ps0 if alt_sh > 0 else 0.0,
            "alt": f"반기보고서 주식 수 {sn['report_issued']:,}주(기준일 상장 {sn['asof_listed']:,}주 대신)",
        }
    if rf_srp and (10, s0) in rf_srp:
        imp["rf"] = {"diff": rf_srp[(10, s0)] - ps0, "alt": "Rf 국고채 10년"}
    from src.valuation.associates import off as _off
    from src.valuation.company_dcf import is_draft

    if is_draft(c.cfg) and not _off("judge"):  # P7-X2b (config/p7x2b.yaml judgements): the large assumptions ranked
        xi = x2b_impacts(c, h, cap, s0, w0, bu0, de_own, kd, tb, ps0, eq, shares, br, pin, v0)
        oor.update(xi.pop("_oor", {}))
        imp.update(xi)
    # P7-B2b: the v1 path (3-year average margin, 5-year CAGR) next to v2, with its own signals
    v1 = None
    if v2:
        c.v2 = None
        try:
            v1v = dcf_value(c, h, forecast(c, h), w0, cap)
        finally:
            c.v2 = v2
        v1_ps = v1v["per_share"]
        v1 = {"per_share": v1_ps, "tv_share": v1v["tv_share"], "signals": signals(v1_ps, peer, price, r)}
        if in_range("normal_margin", h["margin"]) and in_range("g_start", h["cagr"]):
            imp["v1"] = {
                "diff": v1_ps - ps0,
                "alt": f"기본 경로 v1(3년 평균 이익률 {h['margin']:.2%}, 매출 CAGR {h['cagr']:.2%})",
            }
        else:  # P7-E K11: the v1 path needs both values inside the screen's ranges
            oor["v1"] = oor_text(
                [(f_, v_) for f_, v_ in (("normal_margin", h["margin"]), ("g_start", h["cagr"])) if not in_range(f_, v_)]
            )
    dna_rec = getattr(c, "dna_rec", None)
    dna_rows = (
        []
        if dna_rec is None
        else [
            {
                "year": int(x.fiscal_year),
                "period": x.period,
                "total": float(x.total) / 1e6,
                "source": x.source,
                "estimated": bool(x.estimated),
            }
            for x in dna_rec.itertuples()
        ]
    )
    guard = validity_guard(
        ps0,
        v0["tv_share"],
        peer if peer.get("valid", True) else {**peer, "median": None},
        price,
        c,
        multiples,
        dna_rows,
        market_only=peer.get("valid") is False,
    )
    facts_ = (c.cfg.get("draft_meta") or {}).get("facts") or {}
    struct_forced = (
        structure_items(facts_.get("structure_guard"))
        + share_items(facts_.get("sotp_share_check") if c.sotp else None)
        + share_items(((facts_.get("associates") or {}).get("share_check")) if getattr(c, "assoc", None) else None, "관계기업")
    )
    held_ = [x.pop("_reason") for x in struct_forced if "_reason" in x]
    if held_:  # P7-X2a holding guards (config/p7x2a.yaml holding): hold + the structure check first
        guard["reasons"] += held_
        guard.update({"hold": True, "status": "자동 결과 보류", "structure": True})
    # P7-B3 general SOTP: composition and the listed-stake discount sensitivities
    sp = br.get("sotp")
    sotp = None
    if sp:
        d0 = sp["discount"]
        sotp = {
            "parent_ev": v0["ev"] * to_mn_,
            "listed": sp["listed"] * to_mn_,
            "unlisted": sp["unlisted"] * to_mn_,
            "remainder": sp["remainder"] * to_mn_,
            "sub_lines": sp["sub_lines"] * to_mn_,
            "book_all": sp["book_all"] * to_mn_,
            "discount": d0,
            "unit_ok": sp["unit_ok"],
            "missing_close": sp["missing_close"],
            "equity": eq * to_mn_,
            "sens": [
                {"discount": dd, "per_share": (eq - sp["listed"] * (dd - d0)) * EOK / shares} for dd in c.sotp["sensitivities"]
            ],
        }
        sotp["listed_share"] = sp["listed"] * (1 - d0) / eq if eq else None
        sotp["parent_share"] = (eq - sp["listed"] * (1 - d0) - sp["unlisted"]) / eq if eq else None
        if sotp["sens"]:
            far = max(sotp["sens"], key=lambda x: abs(x["per_share"] - ps0))
            imp["sotp_discount"] = {
                "diff": far["per_share"] - ps0,
                "alt": f"상장 종속회사 지분 할인 {far['discount']:.0%}(기본 {d0:.0%})",
            }
        if sp["missing_close"]:
            guard["reasons"].append(
                {"key": "key_metric_missing", "text": "상장 종속회사 종가 없음", "value": sp["missing_close"]}
            )
            guard.update({"hold": True, "status": "자동 결과 보류"})
    ab_ = br.get("assoc")
    if ab_ and ab_.get("missing_close"):  # P7-X2b: a listed associate without a close (suspended, no price on the date)
        guard["reasons"].append({"key": "key_metric_missing", "text": "상장 관계기업 종가 없음", "value": ab_["missing_close"]})
        guard.update({"hold": True, "status": "자동 결과 보류"})
    # P7-B3b (config/p7b3b.yaml): SOTP guard, turnaround detection, loss path (funding check, EV/Sales range)
    r3 = rules_3b()
    forced = []
    for y, per, other in c.cfg["meta"].get("basis_fill") or []:  # P7-B5 short_history.basis_fill -> first judgement
        forced.append(
            {
                "category": "재무 기준 혼합",
                "item": f"{per}{y}는 {'연결' if other == 'CFS' else '별도'} 값",
                "detail": "config/p7b5.yaml short_history.basis_fill — 연결 범위 변동으로 LTM 범위가 섞임",
                "impact": None,
                "alternative": "기준 재무 확인",
            }
        )
    n_ev = int((multiples.get("EV/EBITDA") or {}).get("n") or 0)  # P7-B5 peer_relax step 3: fewer than 3 usable peers
    n_beta = pin["n_beta"]
    if min(n_ev, n_beta) < 3:
        forced.append(
            {
                "category": "피어 직접 지정",
                "item": f"쓸 수 있는 피어 부족(베타 {n_beta}곳, EV/EBITDA {n_ev}곳)",
                "detail": "config/p7b5.yaml peer_relax — 피어 배수는 참고(N/M), βu는 "
                + ("피어 중앙값" if n_beta else "대체값(대상 자기 회귀 또는 1.0)")
                + ". 피어를 사람이 지정",
                "impact": None,
                "alternative": "피어 직접 지정",
            }
        )
    if sotp:
        dmax = max([sotp["discount"]] + [x["discount"] for x in sotp["sens"]])
        ps_dmax = next((x["per_share"] for x in sotp["sens"] if x["discount"] == dmax), ps0)
        sg = sotp_guard(v0["ev"], ps0, ps_dmax, price, r3["sotp_guard"])
        sotp["guard"] = sg
        if sg:
            guard["reasons"] += sg
            guard.update({"hold": True, "status": "자동 결과 보류"})
            forced.append(
                {
                    "category": "SOTP 가드",
                    "item": "; ".join(x["text"] for x in sg),
                    "detail": "config/p7b3b.yaml sotp_guard — 모회사 영업가치·상장 지분 할인·시장가 차이 원인 확인",
                    "impact": None,
                    "alternative": "대표값 보류",
                }
            )
        if "sotp_discount" in imp:  # the listed-stake discount right after the forced items
            sd = imp.pop("sotp_discount")
            forced.append(
                {
                    "category": "SOTP",
                    "item": "상장 종속회사 지분 할인",
                    "detail": "config/p7b3b.yaml sotp_guard.discount_review",
                    "impact": sd["diff"],
                    "alternative": sd["alt"],
                }
            )
    from src.valuation.company_dcf import ltm

    lrev, lop = ltm(c, "revenue"), ltm(c, "operating_income")
    lt_m = lop / lrev if lrev and lrev > 0 else None
    loss_path = (c.cfg.get("forecast") or {}).get("v2_start") == "ltm"
    turn = None
    if v2 and not loss_path and lt_m is not None and turnaround_hit(lt_m, v2["m0"], r3["turnaround"]):
        pm = v2.get("peer_margin")
        alt = {**v2, "m0": lt_m, "conv_amt": v2["conv_share"] * (pm - lt_m) if pm is not None else 0.0}
        c.v2 = alt
        try:
            tps = dcf_value(c, h, forecast(c, h), w0, cap)["per_share"]
        finally:
            c.v2 = v2
        turn = {
            "ltm_margin": lt_m,
            "m0": v2["m0"],
            "gap": lt_m - v2["m0"],
            "conv_amt": alt["conv_amt"],
            "per_share": tps,
            "diff": tps - ps0,
            "default": "v2(5년 중앙값) 그대로",
        }
        ok_ = in_range("normal_margin", lt_m)  # P7-E K11: the LTM start is a candidate only inside the screen's range
        if not ok_:
            turn["candidate_out_of_range"] = True
        forced.insert(
            0,
            {
                "category": "실적 전환",
                "item": f"LTM 영업이익률 {lt_m:.1%} vs 5년 중앙값 {v2['m0']:.1%}",
                "detail": "config/p7b3b.yaml turnaround — 최근 실적이 과거 분포를 벗어남. 어느 쪽이 정상 이익률인지 판단",
                "impact": tps - ps0 if ok_ else None,
                "alternative": f"LTM 이익률 출발 → 주당 {tps:,.0f}원" if ok_ else oor_text([("normal_margin", lt_m)]),
            },
        )
    loss = None
    if loss_path:
        tab = v0["r"].table
        lab_col = "label" if "label" in tab.columns else tab.columns[0]
        from src.valuation.company_dcf import explicit_years

        expl = [c.first] + [str(y) for y in explicit_years(c)]
        fc = [float(tab.loc[tab[lab_col] == lb, "fcff"].iloc[0]) for lb in expl if (tab[lab_col] == lb).any()]
        fn = funding_need(fc, br["cash_like"])
        evs = multiples.get("EV/Sales") or {}
        rng = {
            "basis": "EV/Sales",
            "q25": evs.get("ps_q25"),
            "q75": evs.get("ps_q75"),
            "median": evs.get("ps_median"),
            "n": evs.get("n"),
        }
        bad = peer_validity(rng, multiples)
        ok_rng = (
            rng["q25"] is not None
            and np.isfinite(rng["q25"])
            and rng["q75"] is not None
            and np.isfinite(rng["q75"])
            and int(rng["n"] or 0) >= r["signal_peer"]["min_n"]
            and not bad
        )
        loss = {
            "ltm_margin": lt_m,
            "target_margin": v2.get("peer_margin") if v2 else None,
            "years": r3["loss_path"]["method"]["b_transition_dcf"]["years"],
            "ev_sales": {**rng, "valid": bool(ok_rng), "invalid": bad},
            "dcf": ps0,
            "dcf_hold": guard["hold"],
            "funding": {
                "trough": fn["trough"] * to_mn_,
                "cash_like": fn["cash_like"] * to_mn_,
                "need": fn["need"],
                "gap": fn["gap"] * to_mn_,
                "cum": [x * to_mn_ for x in fn["cum"]],
                "labels": expl[: len(fc)],
            },
            "fixed_text": r3["loss_path"]["method"]["fixed_text"],
        }
        if fn["need"]:
            forced.insert(
                0,
                {
                    "category": "적자 경로 자금",
                    "item": "추가 자금 필요(희석 위험)",
                    "detail": f"명시 기간 누적 FCF 최저 {fn['trough'] * to_mn_:,.0f}백만원 > 현금성 {fn['cash_like'] * to_mn_:,.0f}백만원",
                    "impact": None,
                    "alternative": "유상증자·CB 등 희석 반영 여부 판단",
                },
            )
    forced = struct_forced + forced
    to_mn = 100.0
    dil = dilution(c, eq)  # P7-U1F D-3: shown and listed as a check item; the value does not change
    return {
        "dilution": dil,
        "v2": None if not v2 else {k: v for k, v in v2.items() if k != "peers"},
        "v1": v1,
        "guard": guard,
        "dna": dna_rows,
        "sotp": sotp,
        "turnaround": turn,
        "loss": loss,
        "forced": forced,
        "ltm_margin": lt_m,
        "signals": sig,
        "reverse": rev,
        "composition": {k: v * to_mn for k, v in comp.items()},
        "composition_share": comp_share,
        "anomalies": flags,
        "margin_candidates": cands,
        "sensitivities": _mn(sens),
        "impacts": imp,
        **({"out_of_range": oor} if oor else {}),
        "base_per_share": ps0,
        "kd_alt": kd_alt,
    }


def _far(alts: list[tuple]) -> tuple | None:
    """The alternative with the largest |impact| (value, impact, label)."""
    ok = [x for x in alts if x[1] is not None and np.isfinite(x[1])]
    return max(ok, key=lambda x: abs(x[1])) if ok else None


def x2b_impacts(c, h, cap, s0, w0, bu0, de_own, kd, tb, ps0, eq, shares, br, pin, v0) -> dict:
    """P7-X2b: per-share impacts (alternative − default, base scenario, SRP column 1) of the assumptions the judgement list
    did not rank (audit packet 4): MRP, target D/E, D&A / CAPEX / working-capital ratios, peer convergence share and year,
    listed-associate discount and market value, the RONIC floor. Each carries its candidate values ('cands') for the
    workbench judgement panel. Values of the model do not change here."""
    from src.valuation.associates import params
    from src.valuation.company_dcf import dcf_value, discount_rate, explicit_end, five_year_ratios, forecast
    from src.workbench import pubcut

    P = params()["judgement_alternatives"]
    out = {}
    oor = {}  # P7-E K11: alternatives outside the screen's range are not candidates

    def ps_at(hh=None, t=None, w=None, ronic=None):
        try:
            return dcf_value(c, hh or h, tb if t is None else t, w0 if w is None else w, cap, ronic_override=ronic)["per_share"]
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

    # MRP 7% / 9% (KICPA guidance range, config/valuation_rf.yaml mrp.options)
    m0 = c.led["mrp"]["value"]
    alts = []
    for mv in P["mrp"]:
        if abs(mv - m0) < 1e-12:
            continue
        if not in_range("mrp", mv):
            oor.setdefault("mrp", []).append(("mrp", mv))
            continue
        c.led["mrp"]["value"] = mv
        try:
            x = ps_at(w=discount_rate(c, s0, bu0, de_own, kd))
        finally:
            c.led["mrp"]["value"] = m0
        alts.append((mv, None if x is None else x - ps0, f"MRP {mv:.0%}"))
    far = _far(alts)
    if far:
        out["mrp"] = {
            "diff": far[1],
            "alt": f"{far[2]}(기본 {m0:.0%}, 한공회 가이던스 7~9%)",
            "cands": [{"label": lab, "field": "mrp", "value": v} for v, _, lab in alts],
        }
    # target D/E = peer median (public mode: the P7-X2a cut, fewer than 5 peers -> not computed)
    dn, dm = int(pin.get("peer_de_n") or 0), pin.get("peer_de_median")
    need = pubcut.params()["peer_min_n"] if pubcut.public_scope(c.cfg) else int(P["peer_de_min_n"])
    if dm is not None and dn >= need and abs(float(dm) - de_own) > 1e-12 and not in_range("de", float(dm)):
        oor["de_target"] = [("de", float(dm))]
    elif dm is not None and dn >= need and abs(float(dm) - de_own) > 1e-12:
        x = ps_at(w=discount_rate(c, s0, bu0, float(dm), kd))
        if x is not None:
            out["de_target"] = {
                "diff": x - ps0,
                "alt": f"피어 D/E 중앙값 {float(dm):.3f}배(기본 자기 평균 {de_own:.3f}배)",
                "cands": [{"label": f"피어 D/E 중앙값 {float(dm):.3f}배", "field": "de", "value": float(dm)}],
            }
    # D&A, CAPEX, working capital: 5-year averages instead of the 3-year ones
    fy = five_year_ratios(c, int(P["five_year_min_years"]))
    lab_y = f"FY{fy['years'][0]}~{fy['years'][-1]}" if fy["years"] else ""
    for k, lab in (("dna_ratio", "D&A ÷ 매출"), ("capex_ratio", "CAPEX ÷ 매출")):
        v = fy.get(k)
        if v is None or not np.isfinite(v) or abs(v - h[k]) < 1e-12:
            continue
        if not in_range(k, float(v)):
            oor[k] = [(k, float(v))]
            continue
        h2 = {**h, k: v}
        x = ps_at(hh=h2, t=forecast(c, h2))
        if x is not None:
            out[k] = {
                "diff": x - ps0,
                "alt": f"{lab} 5년 평균 {v:.2%}({lab_y}, 기본 3년 평균 {h[k]:.2%})",
                "cands": [{"label": f"{lab} 5년 평균 {v:.2%}", "field": k, "value": float(v)}],
            }
    reinvest_fade_candidates(c, h, tb, v0, ps0, ps_at, out, oor)
    nd = fy.get("nwc_days")
    if (
        nd
        and any(abs(nd[k] - h[k]) > 1e-9 for k in ("dso", "dio", "dpo"))
        and not in_range("nwc_days", {k: float(nd[k]) for k in ("dso", "dio", "dpo")})
    ):
        oor["nwc_days"] = [("nwc_days", {k: float(nd[k]) for k in ("dso", "dio", "dpo")})]
    elif nd and any(abs(nd[k] - h[k]) > 1e-9 for k in ("dso", "dio", "dpo")):
        h2 = {**h, **nd}
        x = ps_at(hh=h2, t=forecast(c, h2))
        if x is not None:
            txt = f"DSO {nd['dso']:.0f}·DIO {nd['dio']:.0f}·DPO {nd['dpo']:.0f}일"
            out["nwc_days"] = {
                "diff": x - ps0,
                "alt": f"회전일수 5년 평균 {txt}({lab_y}, 기본 DSO {h['dso']:.0f}·DIO {h['dio']:.0f}·DPO {h['dpo']:.0f}일)",
                "cands": [{"label": f"회전일수 5년 평균 {txt}", "field": "nwc_days", "value": {k: float(nd[k]) for k in nd}}],
            }
    # peer convergence: share and the year the margin path reaches its end value
    v2 = getattr(c, "v2", None)
    if v2 and v2.get("peer_margin") is not None:
        s_now = v2["conv_share"]
        alts = []
        for s in P["conv_share"]:
            if abs(s - s_now) < 1e-12:
                continue
            if not in_range("conv_share", s):
                oor.setdefault("conv_share", []).append(("conv_share", s))
                continue
            c.v2 = {**v2, "conv_share": s, "conv_amt": s * (v2["peer_margin"] - v2["m0"])}
            try:
                x = ps_at(t=forecast(c, h))
            finally:
                c.v2 = v2
            alts.append((s, None if x is None else x - ps0, f"수렴 비율 {s:.0%}"))
        far = _far(alts)
        if far:
            out["conv_share"] = {
                "diff": far[1],
                "alt": f"{far[2]}(기본 {s_now:.0%}, 피어 이익률 중앙값 {v2['peer_margin']:.1%} 쪽)",
                "cands": [{"label": lab, "field": "conv_share", "value": s} for s, _, lab in alts],
            }
        e0 = int(v2.get("conv_end") or explicit_end(c))
        alts = []
        for d in P["conv_end_steps"]:
            e = e0 + int(d)
            if e <= c.Y or e > int(params()["assumptions"]["conv_end"]["max"]):
                continue
            if not in_range("conv_end", e):
                oor.setdefault("conv_end", []).append(("conv_end", e))
                continue
            c.v2 = {**v2, "conv_end": e}
            try:
                x = ps_at(t=forecast(c, h))
            finally:
                c.v2 = v2
            alts.append((e, None if x is None else x - ps0, f"도달 연도 {e}"))
        far = _far(alts)
        if far:
            out["conv_end"] = {
                "diff": far[1],
                "alt": f"{far[2]}(기본 {e0})",
                "cands": [{"label": lab, "field": "conv_end", "value": e} for e, _, lab in alts],
            }
    # listed associates: discount 30% / 50%, and keeping the book instead of the market value
    ab = br.get("assoc")
    if ab and getattr(c, "assoc", None):
        d0 = ab["discount"]
        alts = [
            (dd, (eq - ab["listed"] * (dd - d0)) * EOK / shares - ps0, f"상장 관계기업 지분 할인 {dd:.0%}")
            for dd in c.assoc["sensitivities"]
            if in_range("assoc_discount", dd)
        ]
        far = _far(alts)
        if far:
            out["assoc_discount"] = {
                "diff": far[1],
                "alt": f"{far[2]}(기본 {d0:.0%})",
                "cands": [{"label": lab, "field": "assoc_discount", "value": dd} for dd, _, lab in alts],
            }
        out["assoc_market"] = {"diff": -ab["add"] * EOK / shares, "alt": "상장 관계기업을 장부가로 둠(시가 반영 안 함)"}
    # RONIC floor: the historical-ROIC cap below WACC (the value before the P7-X2b rule)
    # X2b-F4: only a positive historical ROIC is an alternative (RONIC <= 0 has no meaning in FCF = NOPAT x (1 − g / RONIC))
    if (
        np.isfinite(cap)
        and 0 < cap < w0
        and str(v0.get("ronic_why", "")).startswith("과거 ROIC")
        and not in_range("ronic", float(cap))
    ):
        oor["ronic"] = [("ronic", float(cap))]
    elif np.isfinite(cap) and 0 < cap < w0 and str(v0.get("ronic_why", "")).startswith("과거 ROIC"):
        x = ps_at(ronic=float(cap))
        if x is not None:
            out["ronic"] = {
                "diff": x - ps0,
                "alt": f"RONIC = 과거 3년 ROIC {cap:.2%}(규칙 전 값, 기본 = WACC {w0:.2%})",
                "cands": [{"label": f"RONIC 과거 3년 ROIC {cap:.2%}", "field": "ronic", "value": float(cap)}],
            }
    oor = {k: v for k, v in oor.items() if k not in out}
    if oor:
        out["_oor"] = {k: oor_text(v) for k, v in oor.items()}
    return out


def reinvest_fade_candidates(c, h, tb, v0, ps0, ps_at, out: dict, oor: dict) -> None:
    """P7-U1F D-2 (config/p7u1f.yaml d2_reinvest_fade): when the FCFF jumps from the last explicit year to the first fade
    year, the CAPEX ÷ sales item also offers (A) the CAPEX ratio whose last-explicit-year reinvestment equals the fade rule
    (NOPAT × g ÷ RONIC, RONIC of the default) and (C) the linear fade of the reinvestment rate. The item's impact is the
    candidate with the largest |difference| (B = the 5-year average stays first when it exists). Default unchanged."""
    from src.valuation.company_dcf import fade_jump, forecast

    j = fade_jump(v0["r"].table, len(tb))
    if not j["jump"]:
        return
    alts = []  # (field, value, difference, label)
    prev = out.get("capex_ratio")
    if prev:
        cd = prev["cands"][0]
        alts.append((cd["field"], cd["value"], prev["diff"], cd["label"]))
    e, R = v0["r"].table.iloc[len(tb) - 1], v0["ronic"]
    rev, g = float(tb.iloc[len(tb) - 1].revenue), float(tb.iloc[len(tb) - 1].growth)
    if R and rev > 0:
        a = h["dna_ratio"] + (float(e.nopat) * g / R - float(e.dnwc)) / rev
        if not (0 <= a <= 1) or not in_range("capex_ratio", float(a)):
            oor.setdefault("capex_ratio", []).append(("capex_ratio", float(a)))
        else:
            h2 = {**h, "capex_ratio": a}
            x = ps_at(hh=h2, t=forecast(c, h2))
            if x is not None:
                alts.append(("capex_ratio", float(a), x - ps0, f"마지막 명시 연도 재투자 = 수렴 규칙(A) CAPEX ÷ 매출 {a:.2%}"))
    had = "overrides" in c.cfg
    old = dict(c.cfg.get("overrides") or {})
    c.cfg["overrides"] = {**old, "fade_reinvest": "linear"}
    try:
        x = ps_at()
    finally:
        if had:
            c.cfg["overrides"] = old
        else:
            c.cfg.pop("overrides", None)
    if x is not None:
        alts.append(("fade_reinvest", "linear", x - ps0, "수렴 구간 재투자율 선형 수렴(C)"))
    if not alts:
        return
    far = max(alts, key=lambda z: abs(z[2]))
    ratio = f"{j['ratio']:.2f}배" if j["ratio"] is not None else "부호 바뀜"
    out["capex_ratio"] = {
        "diff": far[2],
        "alt": f"{far[3]}(명시 → 수렴 FCFF {ratio}, 기본 CAPEX ÷ 매출 3년 평균 {h['capex_ratio']:.2%})",
        "cands": [{"label": lab, "field": f, "value": v} for f, v, _, lab in alts],
    }


def _eok(x) -> str:
    return "—" if x is None else f"{x / 1e8:,.0f}억"


def structure_items(sg: dict | None) -> list[dict]:
    """P7-X2a: the judgement items (with their hold reason under '_reason') of the gate's structure guards a / b."""
    if not sg:
        return []
    out = []
    if sg.get("a"):
        inv = sg.get("listed_investees") or []
        lst = ", ".join(
            f"{x['name']} 지분 {x['stake']:.1%} 장부 {_eok(x.get('book'))}" for x in inv[:5] if x.get("stake") is not None
        )
        out.append(
            {
                "category": "상장 종속회사 확인",
                "item": f"지주회사({sg.get('holding')})인데 연결 범위 상장 종속회사 0",
                "detail": (
                    f"config/p7x2a.yaml holding.guard_a — 연결 범위 표 {sg.get('scope_rcept') or '없음'}. 출자현황의 상장 피투자회사: "
                    + (lst or "없음")
                    + ". 관계기업·장부가로 남은 상장 지분이 지주 가치의 본체일 수 있음(SOTP·시가 반영 판단)"
                ),
                "impact": None,
                "alternative": "구조 확인(상장 지분 시가·SOTP)",
                "_reason": {
                    "key": "holding_no_listed_sub",
                    "text": "지주회사: 연결 범위 상장 종속회사 0",
                    "value": sg.get("holding"),
                },
            }
        )
    if sg.get("holding") and not sg.get("a") and sg.get("n_assoc"):  # P7-X2b: guard a narrowed - a judgement, no hold
        out.append(
            {
                "category": "상장 관계기업",
                "item": f"지주회사({sg.get('holding')}): 상장 관계기업 {sg['n_assoc']}곳을 시가로 반영",
                "detail": "config/p7x2b.yaml associates.holding_guard_a — 연결 범위 상장 종속회사 0, 상장 관계기업 지분은 보유 주식수 × 종가로 "
                "더하고 관계기업 줄 장부는 뺌. 지분 할인·지배력·이중 계산(영업이익 안 지분법 손익) 확인",
                "impact": None,
                "alternative": "구조 확인(상장 관계기업 시가·지분 할인)",
            }
        )
    if sg.get("b"):
        ms = ", ".join(f"{x['name']} 지분 {x['stake']:.1%} 장부 {_eok(x['book'])}" for x in (sg.get("minority_subs") or [])[:5])
        out.append(
            {
                "category": "비지배지분 확인",
                "item": f"비지배 장부 ÷ 연결 자본 {sg['nci_equity']:.3%}",
                "detail": f"config/p7x2a.yaml holding.guard_b — 지분 90% 이하 종속회사: {ms}. 비지배 장부(단위·계정)와 구조 확인",
                "impact": None,
                "alternative": "비지배지분 원문 확인",
                "_reason": {
                    "key": "nci_book_mismatch",
                    "text": "비지배지분 장부가 종속회사 지분 구조와 맞지 않음",
                    "value": sg.get("nci_equity"),
                },
            }
        )
    return out


def share_items(chk: list[dict] | None, kind: str = "종속회사") -> list[dict]:
    """P7-X2a X2a-F1: SOTP listed subsidiaries (P7-X2b: or listed associates) whose held quantity does not match stake x
    listed shares and no share-count event explains it (config/p7x2b.yaml sotp_quantity) - unresolved."""
    bad = [x for x in chk or [] if not x.get("fixed")]
    if not bad:
        return []
    txt = ", ".join(f"{x['name']} 수량 ÷ (지분율 × 상장주식수) = {x['ratio']:g}" for x in bad[:5])
    sotp = kind == "종속회사"
    return [
        {
            "category": "SOTP 보유 수량 확인" if sotp else "상장 관계기업 보유 수량 확인",
            "item": f"상장 {kind} 보유 수량이 지분율과 맞지 않음",
            "detail": f"config/p7x2a.yaml fixes X2a-F1·config/p7x2b.yaml sotp_quantity — {txt}. 주식 수 변동 공시로 설명되지 않음 — "
            "분할·병합·수량 단위를 원문으로 확인",
            "impact": None,
            "alternative": "보유 수량 확인",
            "_reason": {
                "key": "sotp_share_mismatch" if sotp else "assoc_share_mismatch",
                "text": f"{'SOTP ' if sotp else ''}상장 {kind} 보유 수량 불일치",
                "value": [x["ratio"] for x in bad],
            },
        }
    ]


def validity_guard(
    ps0, tv_share, peer: dict, price: float, c, multiples: dict, dna_rows: list[dict], market_only: bool = False
) -> dict:
    """config/p7b2b.yaml validity_guard for one company (inputs gathered here, rule in guard_reasons).
    market_only: the peer range cannot be interpreted -> far_from_both on the market price alone (p7b3b.yaml PB4-1)."""
    from src.valuation.company_dcf import ltm

    need = {(y, "FY") for y in c.cfg["params"]["avg_years"]} | {
        (c.FY, "FY"),
        (c.FY, c.P),
        (c.Y, c.P),
    }  # periods the value uses (short history too; P7-X2b: from the config's LTM year)
    have = {(x["year"], x["period"]) for x in dna_rows} if dna_rows else None
    miss_dna = sorted(f"{p}{y}" for y, p in need - have) if have is not None else []
    return guard_reasons(
        ps0, tv_share, peer.get("median"), price, ltm(c, "revenue"), ltm(c, "operating_income"), miss_dna, market_only=market_only
    )


def pb41_multiple() -> float:
    """PB4-1 market-only multiple (config/p7b3b.yaml pre_b4_changes PB4-1; P7-X2b: read here, was p7b2b far_from_both)."""
    return float(next(x for x in rules_3b()["pre_b4_changes"] if isinstance(x, dict) and x.get("id") == "PB4-1")["multiple"])


def guard_reasons(
    ps0, tv_share, peer_median, price, ltm_rev, ltm_op, dna_missing: list[str], g: dict | None = None, market_only: bool = False
) -> dict:
    """Pure rule: reasons not to publish the per share as the headline number (pre-registered thresholds)."""
    g = g or yamlio.load((ROOT / "config" / "p7b2b.yaml").read_text(encoding="utf-8"))["validity_guard"]["conditions"]
    reasons = []
    if ps0 is not None and not np.isfinite(ps0):  # P7-X2b X2b-F3: an incomputable per share is never shown as a headline
        reasons.append({"key": "per_share_nan", "text": "주당가치 계산 불가(입력 결측)", "value": None})
    elif ps0 is None or ps0 <= 0:
        reasons.append({"key": "equity_nonpositive", "text": "주식가치 ≤ 0", "value": ps0})
    if tv_share is not None and tv_share > g["terminal_heavy"]:
        reasons.append({"key": "terminal_heavy", "text": f"영구가치 비중 > {g['terminal_heavy']:.0%}", "value": tv_share})
    med = peer_median
    k = np.log(g["far_from_both"])
    if med is not None and np.isfinite(med) and med > 0 and ps0 and ps0 > 0 and price:
        if abs(np.log(ps0 / med)) >= k and abs(np.log(ps0 / price)) >= k:
            reasons.append(
                {
                    "key": "far_from_both",
                    "text": f"피어 중앙값·시장가 양쪽과 {g['far_from_both']:.0f}배 이상 차이",
                    "value": [ps0 / med, ps0 / price],
                }
            )
    elif market_only and ps0 and ps0 > 0 and price and abs(np.log(ps0 / price)) >= np.log(g.get("pb41", pb41_multiple())):
        reasons.append(  # PB4-1 (pre-B4 rule change; its own setting since P7-X2b, same value 3.0)
            {
                "key": "far_from_market",
                "text": f"피어 범위 해석 불가 + 시장가와 {g.get('pb41', pb41_multiple()):.0f}배 이상 차이",
                "value": ps0 / price,
            }
        )
    rev, op, miss_dna = ltm_rev, ltm_op, dna_missing
    if not rev or rev <= 0 or op is None or miss_dna:
        reasons.append(
            {"key": "key_metric_missing", "text": "대상 핵심 지표 결측", "value": {"ltm_revenue": rev, "dna_missing": miss_dna}}
        )
    return {"hold": bool(reasons), "status": "자동 결과 보류" if reasons else "표시", "reasons": reasons}


# ---------------------------------------------------------------- P7-B3b rules (config/p7b3b.yaml, pure)


def rules_3b() -> dict:
    return yamlio.load((ROOT / "config" / "p7b3b.yaml").read_text(encoding="utf-8"))


def turnaround_hit(ltm_margin: float | None, m0: float | None, r: dict | None = None) -> bool:
    """|LTM margin − 5-year median| ≥ threshold, or the signs differ with a gap ≥ the sign-flip minimum."""
    r = r or rules_3b()["turnaround"]
    if ltm_margin is None or m0 is None or not np.isfinite(ltm_margin) or not np.isfinite(m0):
        return False
    gap = abs(ltm_margin - m0)
    flip = (ltm_margin > 0) != (m0 > 0)
    return gap >= r["threshold_pp"] - 1e-12 or (flip and gap >= r["sign_flip_min_pp"] - 1e-12)


def funding_need(fcff: list[float], cash_like: float) -> dict:
    """Cumulative explicit-period FCF: trough below zero larger than the cash-like assets -> extra funding needed."""
    cum, run = [], 0.0
    for x in fcff:
        run += x
        cum.append(run)
    trough = min([0.0] + cum)
    return {"cum": cum, "trough": trough, "cash_like": cash_like, "need": -trough > cash_like, "gap": -trough - cash_like}


def sotp_guard(parent_ev: float, ps0: float, ps_disc_max: float, price: float, r: dict | None = None) -> list[dict]:
    """config/p7b3b.yaml sotp_guard: parent EV ≤ 0; per share (largest discount) ÷ close > k; per share (0%) ÷ close < 1/k."""
    r = r or rules_3b()["sotp_guard"]
    k = r["market_multiple"]
    out = []
    if parent_ev <= 0:
        out.append({"key": "sotp_parent_ev", "text": "SOTP 모회사 영업가치 ≤ 0", "value": parent_ev})
    if price and ps_disc_max / price > k:
        out.append(
            {
                "key": "sotp_market_high",
                "text": f"SOTP 주당(상장 지분 할인 최대) ÷ 종가 > {k:.0f}배",
                "value": ps_disc_max / price,
            }
        )
    if price and ps0 / price < 1 / k:
        out.append({"key": "sotp_market_low", "text": f"SOTP 주당(할인 0%) ÷ 종가 < 1/{k:.0f}", "value": ps0 / price})
    return out


def _mn(sens: dict) -> dict:
    s = {k: dict(v) for k, v in sens.items()}
    for k in ("liabilities", "operating_cash"):
        s["customer_funds"][k] *= 100.0
    s["customer_funds"]["items"] = [{**x, "amount": x["amount"] / 1e6} for x in s["customer_funds"]["items"]]
    for k in ("book", "total_equity"):
        if s["nci"][k] is not None:
            s["nci"][k] *= 100.0
    return s


def capex_signals(e: dict) -> dict:
    """RF (scenario_capex engine): the signals only, from the engine reference values (other parts are company_dcf only)."""
    r = load_rules()["diagnostics"]
    ps0 = e["grid"][("base", e["srps"][0])]["per_share"] if ("base", e["srps"][0]) in e["grid"] else None
    peer = peer_range(e["multiples"], r)
    return {
        "signals": signals(ps0, peer, e["price"], r),
        "reverse": None,
        "composition": None,
        "anomalies": [],
        "margin_candidates": [],
        "sensitivities": None,
        "impacts": {},
        "base_per_share": ps0,
    }


# ---------------------------------------------------------------- 5 ranked review list

KEY_OF = {
    "비경상 손익": "normalize",
    "비영업·현금성 분류(추가)": "customer_funds",
    "Kd 근거": "kd",
    "영구성장률": "g",
    "우선주 처리": "pref",
    "비지배지분": "nci",
    "SOTP": "sotp_discount",
    "상장 관계기업": "assoc_discount",  # P7-X2b
}
AUTO = [
    ("normalize", "정상화(비경상 손익)", "정상 이익률 후보"),
    ("customer_funds", "비영업·현금성 분류", "고객 자금 성격 현금"),
    ("nci", "비지배지분", "비지배지분 차감 방법"),
    ("kd", "Kd 근거", "세전 Kd"),
    ("scenario", "시나리오 폭", "시나리오 이동 폭"),
    ("g", "영구성장률", "영구성장률 g"),
    ("pref", "우선주 처리", "우선주 청구권"),
    ("srp", "할인율", "SRP 열"),
    ("rf", "할인율", "Rf 만기"),
    ("v1", "기본 경로", "기본 경로 v1(대안)"),
    ("sotp_discount", "SOTP", "상장 종속회사 지분 할인"),
    ("shares", "주식 수", "기준일 뒤 주식 수 변동(기준일 상장주식수 사용)"),
    # P7-X2b (config/p7x2b.yaml judgements): the large assumptions that were not ranked before
    ("mrp", "할인율", "MRP"),
    ("de_target", "목표 D/E", "목표 D/E(자기 평균)"),
    ("dna_ratio", "재투자 비율", "D&A ÷ 매출(3년 평균)"),
    ("capex_ratio", "재투자 비율", "CAPEX ÷ 매출(3년 평균)"),
    ("nwc_days", "재투자 비율", "운전자본 회전일수(3년 평균)"),
    ("conv_share", "이익률 수렴", "피어 쪽 수렴 비율"),
    ("conv_end", "이익률 수렴", "수렴 도달 연도"),
    ("assoc_discount", "상장 관계기업", "상장 관계기업 지분 할인"),
    ("assoc_market", "상장 관계기업", "상장 관계기업 시가 반영"),
    ("ronic", "RONIC", "영구 구간 RONIC(하한 WACC)"),
]


def rank_review(
    review: list[dict] | None,
    impacts: dict,
    base_ps: float | None,
    forced: list[dict] | None = None,
    oor: dict | None = None,
    extra_other: list[dict] | None = None,
) -> dict:
    """Merge the draft's list with the computed impacts; computed items by |impact|, then the rest in their order.
    Each computed key is attached once (the first matching item); a key without a draft item becomes its own item."""
    review = [dict(x) for x in (review or [])]
    used = set()
    out_c, out_n = [], []
    for x in review:
        cat = x["category"]
        key = None
        if cat == "피어 유사성" and x["item"] in impacts.get("peers", {}):
            key = ("peers", x["item"])
        elif cat == "시나리오 폭" and x["item"].startswith("±"):
            key = ("scenario", None)
        elif cat in KEY_OF and KEY_OF[cat] in impacts and KEY_OF[cat] != "pref" or (cat == "우선주 처리" and "pref" in impacts):
            key = (KEY_OF[cat], None)
        if key and key not in used:
            used.add(key)
            im = impacts["peers"][key[1]] if key[0] == "peers" else impacts[key[0]]
            out_c.append(
                {**x, "impact": im["diff"], "alternative": im["alt"], **({"cands": im["cands"]} if im.get("cands") else {})}
            )
        else:
            k_ = KEY_OF.get(cat)  # P7-E K11: every alternative out of the screen's range
            txt = (oor or {}).get(k_, "") if k_ and (k_, None) not in used else ""
            if txt:
                used.add((k_, None))
            out_n.append({**x, "impact": None, "alternative": txt})
    for k, cat, item in AUTO:
        if k not in impacts and k in (oor or {}) and (k, None) not in used:
            used.add((k, None))
            out_n.append(
                {
                    "category": cat,
                    "item": item,
                    "detail": "자동 진단(config/p7b2.yaml ranking)",
                    "impact": None,
                    "alternative": oor[k],
                }
            )
        if k in impacts and (k, None) not in used:
            out_c.append(
                {
                    "category": cat,
                    "item": item,
                    "detail": "자동 진단(config/p7b2.yaml ranking)",
                    "impact": impacts[k]["diff"],
                    "alternative": impacts[k]["alt"],
                    **({"cands": impacts[k]["cands"]} if impacts[k].get("cands") else {}),
                }
            )
    for nm, im in (impacts.get("peers") or {}).items():
        if ("peers", nm) not in used:
            out_c.append(
                {
                    "category": "피어 유사성",
                    "item": nm,
                    "detail": "자동 진단(하나 빼기)",
                    "impact": im["diff"],
                    "alternative": im["alt"],
                }
            )
    out_n += [dict(x) for x in (extra_other or [])]  # P7-U1F D-3: check items without an impact (not in the top-5 share)
    out_c.sort(key=lambda x: -abs(x["impact"]))
    # P7-B2b: estimated inputs (D&A) go to the top regardless of the impact (config/p7b2b.yaml dna.flag)
    out_c = [{**f, "impact": f.get("impact"), "alternative": f.get("alternative", "원문 확인")} for f in (forced or [])] + out_c
    for i, x in enumerate(out_c):
        x["rank"] = i + 1
        x["top5"] = i < 5
        x["impact_pct"] = x["impact"] / base_ps if base_ps and x["impact"] is not None else None
    return {"computed": out_c, "other": out_n, "share_top5": top5_share(out_c)}


def top5_share(items: list[dict], n: int = 5) -> float | None:
    """config/p7b5.yaml top5_share: |impact| of the first n items that have an impact ÷ |impact| of all such items
    (forced items without an impact are left out of both)."""
    v = [abs(float(x["impact"])) for x in items if x.get("impact") is not None and np.isfinite(float(x["impact"]))]
    tot = sum(v)
    return sum(v[:n]) / tot if tot > 0 else None
