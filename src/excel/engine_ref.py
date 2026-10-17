"""Reference values from the P3 engine for the Excel model (comparison targets and the 'engine value' tables).

scenario_capex_reference(led) runs src/valuation/rf_dcf2.value (P3-C3 rule: ronic_start from config excel.ronic_start)
for every scenario x SRP, plus the C2 value, the sensitivity grids, the reverse DCF, the consolidated cross-check, the
peer-multiple per-share values (p3c1 helpers) and the block band. Units: 백만원 for amounts, 원 per share.
No API calls (DB + saved filings only).
"""
from __future__ import annotations

import duckdb


from src.db.build import DB_PATH
from src.valuation.dcf import roll_forward

EOK_TO_MN = 100.0
TENORS = (5, 10)          # Rf tenor rows of the P6-A table (국고채 5년 = ledger default, 10년 = choice)


def mrp_values(led: dict) -> list[float]:
    """MRP sensitivity points: the ledger value and its options (7% / 8% / 9%)."""
    return sorted({float(led["mrp"]["value"]), *map(float, led["mrp"].get("options", []))})


def scenario_capex_reference(led: dict) -> dict:
    from src.premium.predict import mktcap_percentile, premium_range
    from src.valuation.p3c1 import block_range, broker_case, multiple_stats, parent_metrics, sotp_from_multiple, vwap20
    from src.valuation.rf_dcf import EOK, load_inputs, per_share, segments_from_filings, sotp_for, sub_value
    from src.valuation.rf_dcf2 import AFTER, solve_gu, value
    from src.valuation.sotp import consolidated_equity

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        inp = load_inputs(con, led)
        segs = segments_from_filings()
        pm = parent_metrics(con, led, inp, segs)
        peers = con.execute("SELECT * FROM peer_p3").df()
        meta = led["meta"]
        vw = vwap20(con, meta["target"]["stock_code"], meta["as_of"])
        pct = mktcap_percentile(con, meta["as_of"], meta["target"]["market"], inp["rf_mc"] * EOK)
        from src.p5.b_reference import srp_cite_pick
        srp_cite = srp_cite_pick(con)["value"]
    finally:
        con.close()
    xl = led["excel"]
    start = xl["ronic_start"]
    cases = led["parent_scenarios"]["cases"]
    srps = led["decisions"]["srp_columns"]
    price = inp["rf_close"]
    bcase, _ = broker_case(led, inp, segs)
    allc = {k: (bcase if k == "broker" else cases[k]) for k in xl["scenarios"]}
    days = 92

    grid = {}
    for k, case in allc.items():
        for s in srps:
            v = value(led, inp, case, srp=s, **AFTER, ronic_start=start)
            r = v["r"]
            ev_exit = roll_forward(r.ev_exit, v["wacc"], days)
            grid[(k, s)] = {"per_share": v["per_share"], "wacc": v["wacc"], "ronic": v["ronic"], "ronic_calc": v["ronic_calc"],
                            "ev630": v["ev630"] * EOK_TO_MN, "ev930": v["ev930"] * EOK_TO_MN, "tv_share": v["tv_share"],
                            "implied_multiple": v["implied_multiple"], "pv_explicit": v["pv_explicit"] * EOK_TO_MN,
                            "pv_tv": v["pv_tv"] * EOK_TO_MN, "equity": v["equity"] * EOK_TO_MN,
                            "per_share_exit": per_share(led, sotp_for(led, inp, ev_exit).equity),
                            "implied_g": r.implied_g, "ev930_exit": ev_exit * EOK_TO_MN, "tv_share_exit": r.tv_share_exit}
    c2_base = value(led, inp, cases["base"], **AFTER)["per_share"]          # P3-B2 / C2 rule (ronic_start mixed)

    b0 = grid[("base", 0.0)]
    w0, r0 = b0["wacc"], b0["ronic"]
    g = xl["grids"]
    wacc_g = {(dw, gg): value(led, inp, cases["base"], **AFTER, ronic_start=start, wacc_override=w0 + dw, g_override=gg,
                              ronic=r0)["per_share"] for dw in g["wacc_steps"] for gg in g["g_values"]}
    base_path = [cases["base"]["g_2027"], *cases["base"]["g_2028_2032"]]
    growth_margin = {(gx, m): value(led, inp, {**cases["base"], "margin": m}, **AFTER, ronic_start=start,
                                    growth_override=[gx] * 4 + base_path[4:])["per_share"]
                     for gx in g["growth_values"] for m in g["margin_values"]}
    reverse = {m: solve_gu(led, inp, cases["base"], m, price, **AFTER, ronic_start=start) for m in g["reverse_margins"]}
    import copy
    mrp_srp = {}
    for mv in mrp_values(led):                     # MRP sensitivity (P4-C): base scenario, same engine, MRP replaced
        led2 = copy.deepcopy(led)
        led2["mrp"]["value"] = mv
        for sv in srps:
            mrp_srp[(mv, sv)] = value(led2, inp, cases["base"], srp=sv, **AFTER, ronic_start=start)["per_share"]
    # P6-A: Rf tenor choice (ledger risk_free.tenor) - every scenario x SRP with 국고채 10년, and the G table
    # (Rf 5년 / 10년 x SRP columns + the 한공회 SRP quoted value, base scenario)
    led_t = {t: copy.deepcopy(led) for t in TENORS}
    for t in TENORS:
        led_t[t]["risk_free"]["tenor"] = t
    rf10 = {}
    for k, case in allc.items():
        for s in srps:
            v = value(led_t[10], inp, case, srp=s, **AFTER, ronic_start=start)
            rf10[(k, s)] = {"per_share": v["per_share"], "wacc": v["wacc"]}
    rf_srp = {(t, sv): value(led_t[t], inp, cases["base"], srp=sv, **AFTER, ronic_start=start)["per_share"]
              for t in TENORS for sv in [*srps, srp_cite]}

    # consolidated cross-check (base, SRP 0): parent DCF + 알에프시스템즈 simple DCF − consolidated net debt + non-op − NCI market
    stake = led["nci"]["subsidiary"]["parent_stake"]
    rs, ev_sub, smeta = sub_value(led, inp, w0, segs)
    nci_mv = (1 - stake) * inp["sub_mc"]
    cons_eq = consolidated_equity(b0["ev930"] / EOK_TO_MN + ev_sub, inp["cons"]["net_debt"], inp["cons"]["ltf"], nci_mv)
    cross = {"ev_sub930": ev_sub * EOK_TO_MN, "ev_sub630": rs.ev_gordon * EOK_TO_MN, "cons_equity": cons_eq * EOK_TO_MN,
             "per_share": per_share(led, cons_eq), "da_ratio": smeta["da_ratio"], "nwc0": smeta["nwc0"] * EOK_TO_MN}

    # relative valuation (SOTP structure, p3c1 definitions)
    tiers = led["p3c1"]["relative"]["tiers"]
    pr = peers[peers.tier.isin(tiers)]
    stake_v = stake * inp["sub_mc"]
    pnet, pnonop = inp["parent"]["net_cash"], inp["parent"]["ltf"]
    multiples = {}
    for name, col, kind, metric in (("EV/Sales", "ev_sales", "ev", pm["revenue"]), ("EV/EBITDA", "ev_ebitda", "ev", pm["ebitda"]),
                                    ("PER", "per", "equity", pm["ni"]), ("PBR", "pbr", "equity", pm["equity_ex_inv"])):
        st = multiple_stats(pr[col])
        multiples[name] = {**st, "metric": metric * EOK_TO_MN,
                           **{f"ps_{q}": per_share(led, sotp_from_multiple(kind, st[q], metric, stake_v, pnet, pnonop))
                              for q in ("q25", "median", "q75")}}
    prr = premium_range(pct["mktcap_pct"], market=meta["target"]["market"], **xl["premium"])
    block = block_range(vw["vwap"], {"q25": prr.q25, "q50": prr.q50, "q75": prr.q75})
    from src.valuation.company_dcf import convergence as _conv
    ev_m = multiples["EV/EBITDA"]
    conv = {"n10": {"n": ev_m["n"], "q25": ev_m["ps_q25"], "q75": ev_m["ps_q75"]}, "n5": None,
            "c2": {"per_share": c2_base, "verdict": _conv(c2_base, ev_m["ps_q25"], ev_m["ps_q75"])["verdict"]},
            "c3": {"per_share": b0["per_share"], "verdict": _conv(b0["per_share"], ev_m["ps_q25"], ev_m["ps_q75"])["verdict"]}}
    out = {"grid": grid, "rf10": rf10, "rf_srp": rf_srp, "srp_cite": srp_cite, "c2_base": c2_base, "wacc_g": wacc_g, "convergence": conv, "mrp_srp": mrp_srp, "growth_margin": growth_margin, "reverse": reverse,
           "cross": cross, "multiples": multiples, "parent_metrics": {k: v * EOK_TO_MN for k, v in pm.items()},
           "block": block, "premium_method": prr.method, "beta_u": float(inp["beta"]["median"]),
           "parent_net_cash": pnet * EOK_TO_MN, "price": price, "srps": list(srps)}
    # P7-B2: reliability signals only (the reverse / composition / ranking parts are company_dcf diagnostics)
    from src.pipeline.diagnose import capex_signals
    out["diagnostics"] = capex_signals(out)
    out["review_ranked"] = {"computed": [], "other": []}
    return out


def mechanical_reference(cfg_path: str) -> dict:
    """company_dcf (P3-C3 rules: Kd common rule, RONIC start normal) for every scenario x SRP, the grids, the reverse
    DCF, peer multiples, block band, convergence (C2 first pre-registered verdict and C3) and an Exit value at the peer
    EV/EBITDA median (display only - the engine itself has no exit value). Units: 백만원, 원 per share."""
    import duckdb as _duck
    import numpy as np
    import pandas as pd

    from src.premium.predict import premium_range
    from src.valuation.company_dcf import (EOK, bisect, bridge, convergence, dcf_value, discount_rate, forecast,
                                           hist_roic, history, kd_for, load_company, ltm, ltm_dna, solve_g_start, val)
    from src.valuation.p3c1 import block_range, multiple_stats
    from pathlib import Path

    c = load_company(cfg_path)
    cfg, xl = c.cfg, c.cfg["excel"]
    c.ronic_start = xl["ronic_start"]
    h = history(c)
    cap = hist_roic(c, h)
    base_name = Path(cfg_path).stem.replace("valuation_", "")
    from src.market.provider import get as market_provider
    from src.workbench import pubagg
    from src.workbench import snapdata as SD
    from src.workbench.public_deploy import premium_range as premium_range_pub
    from src.workbench.public_deploy import premium_withheld, srp_cite_value
    replay = SD.replaying()                                # P7-C3 public snapshot: aggregates instead of the peer tables
    tiers = cfg["beta"]["peer_tiers"]
    if replay:
        agg = pubagg.get("engine", cfg_path, cfg)
        bt = p3 = p2 = None
        vw = market_provider().vwap20(cfg["target"]["stock_code"], cfg["meta"]["as_of"])
        pct = None if premium_withheld() else market_provider().mktcap_percentile(cfg["meta"]["as_of"], cfg["target"]["market"])
        srp_cite = srp_cite_value(None)
    else:
        con = _duck.connect(str(DB_PATH), read_only=True)
        try:
            bt = con.execute(f"SELECT * FROM beta_{base_name} WHERE spec=?", [cfg["beta"]["spec"]]).df()
            p3 = con.execute(f"SELECT * FROM peer_{base_name}_c3").df()
            p2 = con.execute(f"SELECT * FROM peer_{base_name}").df()
            vw = market_provider().vwap20(cfg["target"]["stock_code"], cfg["meta"]["as_of"], con=con)
            pct = None if premium_withheld() else market_provider().mktcap_percentile(
                cfg["meta"]["as_of"], cfg["target"]["market"], c.market["mktcap_common"] * EOK, con=con)
            srp_cite = srp_cite_value(con)
        finally:
            con.close()
    from src.valuation.company_dcf import beta_u0
    if replay:
        sel = pd.DataFrame({"name": pd.Series(dtype=object), "bu_avg": pd.Series(dtype=float)})
        bu0, beta_src = agg["beta_u0"]
    else:
        sel = bt[bt.tier.isin(tiers) & (bt["index"] == cfg["beta"]["index"])]
        bu0, beta_src = beta_u0(bt, cfg)                   # P7-B5: peers' median, else the target's own, else 1.0
    de_own = float(c.market["de_points"].de.mean())
    kd, kd_lab, _ = kd_for(c, xl["kd_version"])
    from src.valuation.company_dcf import overrides_of      # P7-C1 workbench: confirmed βu / D/E / Kd
    ov = overrides_of(cfg)
    if ov.get("beta_u") is not None:
        bu0, beta_src = float(ov["beta_u"]), "override"
    if ov.get("de") is not None:
        de_own = float(ov["de"])
    if ov.get("kd") is not None:
        kd, kd_lab = float(ov["kd"]), "사람 확정값"
    srps = c.led["decisions"]["srp_columns"]
    w_base = {s: discount_rate(c, s, bu0, de_own, kd) for s in srps}
    br = bridge(c)
    shares = c.market["shares_out"]
    # relative valuation (consolidated) and the exit multiple used for display
    eb, eb_why = ltm_dna(c)
    m_rev = ltm(c, "revenue")
    m_ebitda = ltm(c, "operating_income") + eb / EOK if eb else None
    m_ni = ltm(c, "net_income_parent") or ltm(c, "net_income")
    m_eq = val(c, "equity_parent", c.Y, c.P) or (val(c, "total_equity", c.Y, c.P) - val(c, "nci", c.Y, c.P))
    pr = None if replay else p3[p3.tier.isin(tiers)]
    multiples = {}
    for nm, col, kind, metric in (("EV/Sales", "ev_sales", "ev", m_rev), ("EV/EBITDA", "ev_ebitda", "ev", m_ebitda),
                                  ("PER", "per", "eq", m_ni), ("PBR", "pbr", "eq", m_eq)):
        st = dict(agg["stats"][col]) if replay else multiple_stats(pr[col])

        def ps(mu, kind=kind, metric=metric):
            if metric is None or not np.isfinite(mu) or metric <= 0:      # P7-B2 B2-F2: negative own metric -> N/M
                return float("nan")
            eq = (mu * metric - br["net_debt"] + br["non_operating"] - br["nci"]) if kind == "ev" else mu * metric
            return eq * EOK / shares
        multiples[nm] = {**st, "metric": (metric or float("nan")) * EOK_TO_MN, "ps_q25": ps(st["q25"]),
                         "ps_median": ps(st["median"]), "ps_q75": ps(st["q75"])}
    exit_mult = multiples["EV/EBITDA"]["median"]
    days = 92
    grid = {}
    labels = xl["scenarios"]
    for k in labels:
        shf = cfg["scenarios"]["human"][k]
        t = forecast(c, h, shf["growth_shift"], shf["margin_shift"])
        for s in srps:
            v = dcf_value(c, h, t, w_base[s], cap)
            r = v["r"]
            pv_exit = exit_mult * r.inputs["ebitda_final"] * (1 + v["wacc"]) ** -r.inputs["t_n"]
            ev_exit = roll_forward(r.pv_explicit + pv_exit, v["wacc"], days)
            eq_exit = ev_exit - br["net_debt"] + br["non_operating"] - br["nci"]
            from src.valuation.dcf import implied_g
            g_imp = implied_g(exit_mult * r.inputs["ebitda_final"], r.inputs["fcf_norm"], v["wacc"], r.inputs["mid_year"])
            grid[(k, s)] = {"per_share": v["per_share"], "wacc": v["wacc"], "ronic": v["ronic"], "ronic_calc": v["ronic_calc"],
                            "ev930": v["ev"] * EOK_TO_MN, "tv_share": v["tv_share"], "implied_multiple": v["implied_multiple"],
                            "equity": v["equity"] * EOK_TO_MN, "per_share_exit": eq_exit * EOK / shares,
                            "ronic_why": v["ronic_why"], "implied_g": g_imp, "tv_share_exit": pv_exit / (r.pv_explicit + pv_exit)}
    tb = forecast(c, h)
    w0 = w_base[srps[0]]
    g = xl["grids"]
    def _ps(fn):                         # P7-B5 B5-F1: a sensitivity cell with WACC <= g is N/M (Gordon undefined), not an error
        try:
            return fn()["per_share"]
        except ValueError as ex:
            if "WACC must exceed g" in str(ex):
                return float("nan")
            raise
    wacc_g = {(dw, gg): _ps(lambda dw=dw, gg=gg: dcf_value(c, h, tb, w0 + dw, cap, g=gg))
              for dw in g["wacc_steps"] for gg in g["g_values"]}
    growth_margin = {(gs, ms): dcf_value(c, h, forecast(c, h, gs, ms), w0, cap)["per_share"]
                     for gs in g["growth_shifts"] for ms in g["margin_shifts"]}
    mrp_srp = {}
    mrp0 = c.led["mrp"]["value"]
    for mv in mrp_values(c.led):
        c.led["mrp"]["value"] = mv
        for sv in srps:
            mrp_srp[(mv, sv)] = _ps(lambda sv=sv: dcf_value(c, h, tb, discount_rate(c, sv, bu0, de_own, kd), cap))
    c.led["mrp"]["value"] = mrp0
    # P6-A: Rf tenor choice - the Kd floor (max(rule Kd, Rf)) follows the chosen Rf, as in the Excel WACC sheet
    tenor0 = c.led["risk_free"].get("tenor", 5)
    rf10, rf_srp = {}, {}
    for t in TENORS:
        c.led["risk_free"]["tenor"] = t
        kd_t, _, _ = kd_for(c, xl["kd_version"])
        if ov.get("kd") is not None:                     # P7-C1: a confirmed Kd does not follow the Rf floor
            kd_t = float(ov["kd"])
        for sv in [*srps, srp_cite]:
            rf_srp[(t, sv)] = _ps(lambda sv=sv, kd_t=kd_t: dcf_value(c, h, tb, discount_rate(c, sv, bu0, de_own, kd_t), cap))
        if t == 10:
            for k in labels:
                shf = cfg["scenarios"]["human"][k]
                tk = forecast(c, h, shf["growth_shift"], shf["margin_shift"])
                for s in srps:
                    w = discount_rate(c, s, bu0, de_own, kd_t)
                    rf10[(k, s)] = {"per_share": dcf_value(c, h, tk, w, cap)["per_share"], "wacc": w}
    c.led["risk_free"]["tenor"] = tenor0
    price = c.market["close"]
    reverse = {"g_start": solve_g_start(c, h, w0, cap, price),
               "wacc": bisect(lambda x: dcf_value(c, h, tb, x, cap)["per_share"] - price, 0.03, 0.30)}
    m_imp = bisect(lambda ms: dcf_value(c, h, forecast(c, h, 0.0, ms), w0, cap)["per_share"] - price, -0.12, 0.10)
    reverse["margin"] = None if m_imp is None else h["margin"] + m_imp
    # convergence: C2 first pre-registered verdict (actual Kd, mixed RONIC start) and C3, peer table after / before
    to_ps = lambda mu: (float("nan") if not m_ebitda or m_ebitda <= 0 else  # noqa: E731   (P7-B2 B2-F2)
                        (mu * m_ebitda - br["net_debt"] + br["non_operating"] - br["nci"]) * EOK / shares)
    if replay:
        st10, st5 = dict(agg["stats"]["ev_ebitda"]), dict(agg["st5"])
    else:
        st10, st5 = multiple_stats(pr.ev_ebitda), multiple_stats(p2[p2.tier.isin(tiers)].ev_ebitda)
    c.ronic_start = "mixed"
    kd2, _, _ = kd_for(c, "c2")
    v_c2 = dcf_value(c, h, tb, discount_rate(c, srps[0], bu0, de_own, kd2), cap)["per_share"]
    c.ronic_start = xl["ronic_start"]
    v_c3 = grid[("base", srps[0])]["per_share"]
    conv = {"n10": {"n": st10["n"], "q25": to_ps(st10["q25"]), "q75": to_ps(st10["q75"])},
            "n5": {"n": st5["n"], "q25": to_ps(st5["q25"]), "q75": to_ps(st5["q75"])},
            "c2": {"per_share": v_c2, "verdict": convergence(v_c2, to_ps(st5["q25"]), to_ps(st5["q75"]))["verdict"]},
            "c3": {"per_share": v_c3, "verdict": convergence(v_c3, to_ps(st10["q25"]), to_ps(st10["q75"]))["verdict"]}}
    if premium_withheld():                               # P7-C3 decisions.premium_public = false (public deployment)
        prr, block = None, {"q25": None, "q50": None, "q75": None}
    else:
        prr = premium_range_pub(pct["mktcap_pct"], market=cfg["target"]["market"], **cfg["params"]["premium"])
        block = block_range(vw["vwap"], {"q25": prr.q25, "q50": prr.q50, "q75": prr.q75})
    # P7-B2 diagnostics (values unchanged: candidates and sensitivities only) and the ranked human-review list
    from src.pipeline.diagnose import mechanical as diagnose, peer_inputs, rank_review
    if SD.mode() == "record":                            # P7-C3: the aggregates the public snapshot replays
        pubagg.record("engine", cfg_path, cfg, {"beta_u0": [bu0, beta_src], "st5": st5,
                                                 "stats": {col: multiple_stats(pr[col]) for col in ("ev_sales", "ev_ebitda", "per", "pbr")},
                                                 **peer_inputs(sel, p3, tiers)})
    pin = {k: agg[k] for k in ("n_beta", "peer_margin_median", "peer_margin_n")} if replay else None
    diag = diagnose(c, h, cap, srps, w_base, bu0, de_own, kd, br, multiples, sel, p3, grid, rf_srp, tiers, public=pin)
    used = {(y, "FY") for y in cfg["params"]["avg_years"]} | {(2025, "FY"), (2025, "H1"), (2026, "H1")}   # B2b-F3 / P7-B5
    forced = [{"category": "D&A 추정", "item": f"{x['period']}{x['year']} D&A 추정", "detail": x["source"]}
              for x in diag["dna"] if x["estimated"] and (x["year"], x["period"]) in used]
    forced = diag.get("forced", []) + forced            # P7-B3b: funding / turnaround / SOTP guard / stake discount first, then D&A
    ranked = rank_review(cfg.get("human_review"), diag["impacts"], diag["base_per_share"], forced)
    return {"diagnostics": diag, "review_ranked": ranked,
            "grid": grid, "rf10": rf10, "rf_srp": rf_srp, "srp_cite": srp_cite, "wacc_g": wacc_g, "growth_margin": growth_margin,
            "reverse": reverse, "multiples": multiples,
            "block": block, "premium_method": None if prr is None else prr.method, "beta_u": bu0, "beta_src": beta_src, "price": price, "srps": list(srps),
            "convergence": conv, "mrp_srp": mrp_srp, "kd": kd, "kd_label": kd_lab, "de_own": de_own, "ronic_cap": cap, "exit_multiple": exit_mult,
            "hist": {k: h[k] for k in ("cagr", "margin", "dna_ratio", "capex_ratio", "cogs_ratio", "dso", "dio", "dpo")},
            "ebitda_dna": (eb or float("nan")) / 1e6, "ebitda_dna_rule": eb_why, "net_debt": br["net_debt"] * EOK_TO_MN,
            "non_operating": br["non_operating"] * EOK_TO_MN, "cross": None, "c2_base": v_c2}
