"""Screen values of the P7-U1 work tabs, computed with the engine's own functions on the session's in-memory company
(config/p7u.yaml tab_contents, delta_unit, vs_peer). Nothing here changes a value or a rule:

    kpi(o, s, mode)            the six KPI cells (base scenario, EV, equity, price, WACC / g, TV share) + Δ vs v0
    dcf_detail(o, s, mode)     the DCF tab: forecast table (FY actuals + explicit + fade), TV, bridge, WACC build-up,
                               working capital, scenarios (Gordon and exit) and the two sensitivity grids
                               (company_dcf.forecast / dcf_value / bridge, wacc.wacc - the same calls as recalc and the
                               Excel reference engine_ref)
    deltas(o, s, mode, fields) per-share change of one step of each assumption (recalc at current + step)
    vs_peer(o, s, mode)        target vs peer aggregates already computed (public mode: n >= 5 only)
    fin_table(o, s, mode)      FY 5 years + LTM valuation metrics and data checks
    football(o, s, mode)       rows of the summary Football Field (DCF Bear~Bull, peer IQR, control block, price)

Results are cached per (session, version, mode, user inputs) in model._CACHE; every recalculation runs under model.LOCK.
"""

from __future__ import annotations

import math

from app.wb import model as M
from src.workbench import recalc as R
from src.workbench import spec

TABLE_FIELDS = {
    "할인율": ["rf_tenor", "mrp", "beta_u", "de", "kd", "srp"],
    "추정": ["g_start", "normal_margin", "g_terminal", "scenario_width"],
    "Bridge": ["sotp_discount", "cash_adjust_mn", "nci_mn"],
}


def _ok(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _ctx(o, s, mode):
    return o.ctx if mode == "pc" else M.public_ctx(o, s)


def _key(name, o, s, mode, *extra):
    ver = M.version(s)
    return (name, str(M.S.workspace() or ""), s["session_id"], ver["v"], mode, M.ukey(s) if mode == "public" else "", *extra)


# ---------------------------------------------------------------- DCF tab


def dcf_detail(o, s, mode: str) -> dict:
    k = _key("dcfd", o, s, mode)
    if k in M._CACHE:
        return M._CACHE[k]
    from src.valuation.assumptions import marginal_rate, rf_code
    from src.valuation.company_dcf import (
        EOK,
        bridge,
        dcf_value,
        eff,
        explicit_end,
        fade_years,
        forecast,
        hist_overrides,
        kd_for,
        ltm,
        overrides_of,
        val,
    )
    from src.valuation.dcf import fade_path, roll_forward
    from src.valuation.wacc import wacc as wacc_fn

    ver = M.version(s)
    ctx = _ctx(o, s, mode)
    rel = None
    try:
        rel = M.relative(o, s, mode)
    except Exception:  # noqa: BLE001 - the exit-multiple reference is left out
        rel = None
    with M.LOCK:
        r = R.recalc(o.cfg_path, ver["overrides"], ctx=ctx)
        if r.get("per_share") is None:
            M._CACHE[k] = {"error": r.get("error") or "계산 불가"}
            return M._CACHE[k]
        c, x = ctx.c, ctx
        cfg = c.cfg
        hh = hist_overrides(x.h, overrides_of(cfg))
        w = r["wacc"]
        t = forecast(c, hh, 0.0, 0.0)
        v = dcf_value(c, hh, t, w, x.cap)
        rr = v["r"]
        tab = rr.table
        n_exp = len(t)
        gT = t.attrs["gT"]
        end = explicit_end(c)
        # explicit periods (engine table) with revenue and growth of the forecast
        exp = []
        for i in range(n_exp):
            tr, fr = t.iloc[i], tab.iloc[i]
            rev = float(tr.revenue)
            exp.append(
                {
                    "label": f"{tr.label}E" if not str(tr.label).endswith("E") else str(tr.label),
                    "revenue": rev,
                    "growth": float(tr.growth),
                    "ebitda": float(fr.ebit + fr.dna),
                    "ebit": float(fr.ebit),
                    "margin": float(fr.ebit) / rev if rev else float("nan"),
                    "tax": -float(fr.tax),
                    "nopat": float(fr.nopat),
                    "dna": float(fr.dna),
                    "capex": -float(fr.capex),
                    "dnwc": -float(fr.dnwc),
                    "reinvest": None,
                    "fcff": float(fr.fcff),
                    "df": float(fr.discount_factor),
                    "pv": float(fr.pv),
                }
            )
        # fade periods: revenue chain with the same growth path the engine uses (checked against the engine EBIT)
        fy = fade_years(c)
        g_end = float(t.set_index("label")["growth"].get(str(end), gT))
        prev = float(t.set_index("label")["revenue"].get(str(end)))
        fade = []
        for j, (yy, gy) in enumerate(zip(fy, fade_path(g_end, gT, len(fy)))):
            fr = tab.iloc[n_exp + j]
            rev = prev * (1 + gy)
            fade.append(
                {
                    "label": str(yy),
                    "revenue": rev,
                    "growth": gy,
                    "ebit": float(fr.ebit),
                    "margin": float(fr.ebit) / rev if rev else float("nan"),
                    "tax": -float(fr.tax),
                    "nopat": float(fr.nopat),
                    "reinvest": -float(fr.capex),
                    "fcff": float(fr.fcff),
                    "df": float(fr.discount_factor),
                    "pv": float(fr.pv),
                }
            )
            prev = rev
        # FY actuals (statements; the engine's operating tax rule)
        hist = []
        for y in (c.FY - 1, c.FY):
            rev, op = val(c, "revenue", y), val(c, "operating_income", y)
            dna = float(c.dna.get((y, "FY"), float("nan")))
            capex = val(c, "capex_ppe", y) + val(c, "capex_intangibles", y)

            def nwc(yy):
                return val(c, "receivables", yy) + val(c, "inventories", yy) - val(c, "trade_payables", yy)

            tax = op * eff(c, op)
            prev_rev = val(c, "revenue", y - 1)
            hist.append(
                {
                    "label": f"FY{y}A",
                    "revenue": rev,
                    "growth": rev / prev_rev - 1 if prev_rev else float("nan"),
                    "ebitda": op + dna if _ok(dna) else float("nan"),
                    "ebit": op,
                    "margin": op / rev if rev else float("nan"),
                    "tax": -tax,
                    "nopat": op - tax,
                    "dna": dna,
                    "capex": -capex,
                    "dnwc": -(nwc(y) - nwc(y - 1)),
                    "reinvest": None,
                    "fcff": op - tax + (dna if _ok(dna) else 0.0) - capex - (nwc(y) - nwc(y - 1)),
                    "df": None,
                    "pv": None,
                }
            )
        # terminal value
        inp = rr.inputs
        R_ = v["ronic"]
        fcf_next = inp["fcf_norm"] * (1 + gT)
        dfn = (1 + w) ** -inp["t_n"]
        tv = {
            "year": fy[-1] + 1 if fy else end + 1,
            "fcf_next": fcf_next,
            "g": gT,
            "ronic": R_,
            "ronic_why": v.get("ronic_why"),
            "tv_plain": fcf_next / (w - gT),
            "mid_year": bool(inp["mid_year"]),
            "tv": rr.tv_gordon,
            "t_n": inp["t_n"],
            "dfn": dfn,
            "pv_tv": rr.pv_tv_gordon,
            "ebitda_final": inp["ebitda_final"],
            "implied_multiple": rr.implied_multiple,
        }
        br = bridge(c)
        days = (_date(cfg["meta"]["as_of"]) - _date(cfg["meta"]["bs_date"])).days
        shares = c.market["shares_out"]
        exit_mult = None
        if rel is not None:
            em = (rel["multiples"].get("EV/EBITDA") or {}).get("median")
            exit_mult = float(em) if _ok(em) and float(em) > 0 else None

        def per_share_exit(rres, ww):
            if exit_mult is None:
                return None
            pv_exit = exit_mult * rres.inputs["ebitda_final"] * (1 + ww) ** -rres.inputs["t_n"]
            ev_e = roll_forward(rres.pv_explicit + pv_exit, ww, days)
            return (ev_e - br["net_debt"] + br["non_operating"] - br["nci"]) * EOK / shares

        if exit_mult is not None:
            tv["exit_mult"] = exit_mult
            tv["tv_exit"] = exit_mult * inp["ebitda_final"]
            tv["ps_exit"] = per_share_exit(rr, w)
        # WACC build-up (same inputs as company_dcf.discount_rate)
        rf = c.rates[rf_code(c.led)]
        mrp = c.led["mrp"]["value"]
        t_kd = marginal_rate(ltm(c, "pretax_income") * EOK, c.led["corporate_tax"]["brackets"])
        wr = wacc_fn(rf, mrp, r["beta_u"], r["de"], r["kd"], cfg["beta"]["tax"], t_kd, r["srp"])
        kd_lab = "사람 확정값" if overrides_of(cfg).get("kd") is not None else kd_for(c, cfg["excel"]["kd_version"])[1]
        wacc_b = {
            "rf": rf,
            "tenor": int(c.led["risk_free"].get("tenor", 5)),
            "beta_u": wr.beta_u,
            "de": wr.de,
            "beta_l": wr.beta_l,
            "mrp": mrp,
            "srp": r["srp"],
            "ke": wr.ke,
            "kd": r["kd"],
            "kd_label": kd_lab,
            "t_kd": t_kd,
            "kd_after": wr.kd_after_tax,
            "wd": wr.wd,
            "wacc": wr.wacc,
            "matches_engine": abs(wr.wacc - w) < 1e-12,
        }
        nwc0 = {
            "rec": val(c, "receivables", c.Y, c.P),
            "inv": val(c, "inventories", c.Y, c.P),
            "pay": val(c, "trade_payables", c.Y, c.P),
            "dso": hh["dso"],
            "dio": hh["dio"],
            "dpo": hh["dpo"],
        }
        nwc0["nwc"] = nwc0["rec"] + nwc0["inv"] - nwc0["pay"]
        # scenarios (Gordon and exit), same shifts as recalc
        scen = {}
        for name in cfg["excel"]["scenarios"]:
            shf = cfg["scenarios"]["human"][name]
            tk = forecast(c, hh, shf["growth_shift"], shf["margin_shift"])
            vk = dcf_value(c, hh, tk, w, x.cap)
            scen[name] = {
                "g_start": tk.attrs["g_start"],
                "margin": tk.attrs["margin"],
                "ev": vk["ev"],
                "tv_share": vk["tv_share"],
                "implied_multiple": vk["implied_multiple"],
                "per_share": vk["per_share"],
                "per_share_exit": per_share_exit(vk["r"], w),
            }
        # sensitivity grids (Excel grids of the config)
        gd = cfg["excel"]["grids"]

        def ps(fn):
            try:
                return fn()["per_share"]
            except ValueError as ex:
                if "WACC must exceed g" in str(ex):
                    return float("nan")
                raise

        wacc_g = [
            [ps(lambda dw=dw, gg=gg: dcf_value(c, hh, t, w + dw, x.cap, g=gg)) for dw in gd["wacc_steps"]]
            for gg in gd["g_values"]
        ]
        gm = [
            [dcf_value(c, hh, forecast(c, hh, gs, ms), w, x.cap)["per_share"] for ms in gd["margin_shifts"]]
            for gs in gd["growth_shifts"]
        ]
        drivers = {
            "g0": t.attrs["g_start"],
            "gT": gT,
            "g_to": cfg["params"]["fade_to_terminal_by"],
            "m0": t.attrs["margin"],
            "m_end": t.attrs.get("margin_end", t.attrs["margin"]),
            "m_end_year": int((c.v2 or {}).get("conv_end") or end),
            "conv_share": (c.v2 or {}).get("conv_share"),
            "peer_margin": (c.v2 or {}).get("peer_margin"),
            "tax_marginal": marginal_rate(max(exp[-1]["ebit"], 0.0) * EOK, c.led["corporate_tax"]["brackets"]),
            "dna_ratio": hh["dna_ratio"],
            "capex_ratio": hh["capex_ratio"],
            "dso": hh["dso"],
            "dio": hh["dio"],
            "dpo": hh["dpo"],
            "ronic": R_,
            "ronic_why": v.get("ronic_why"),
            "auto_ratios": {k_: hh.get(f"{k_}_auto") for k_ in ("dna_ratio", "capex_ratio")},
        }
        meta = {
            "as_of": cfg["meta"]["as_of"],
            "bs_date": cfg["meta"]["bs_date"],
            "mid_year": bool(cfg["forecast"]["mid_year"]),
            "explicit": (exp[0]["label"], f"{end}E"),
            "fade": (fy[0], fy[-1]) if fy else None,
            "days": days,
            "units": "억원",
        }
        from src.valuation.company_dcf import fade_jump

        out = {
            "meta": meta,
            "drivers": drivers,
            # P7-U1F D-2: FCFF of the first fade year ÷ the last explicit year (engine table) and the fade rule in use
            "fade_jump": fade_jump(tab, n_exp),
            "fade_rule": overrides_of(cfg).get("fade_reinvest") or "rule",
            # P7-U1F D-3: dilutive securities from the draft's diagnostics (summary.json; None = an older draft)
            "dilution": (o.summ.get("diagnostics") or {}).get("dilution"),
            "hist": hist,
            "explicit": exp,
            "fade": fade,
            "pv_explicit": float(sum(e["pv"] for e in exp)),
            "pv_fade": float(sum(f["pv"] for f in fade)),
            "tv": tv,
            "ev_bs": rr.ev_gordon,
            "ev": v["ev"],
            "equity": v["equity"],
            "per_share": v["per_share"],
            "tv_share": v["tv_share"],
            "bridge": dict(br),
            "shares": {
                "out": shares,
                "common_out": c.market["common_out"],
                "pref_out": c.market["pref_out"],
                "common_issued": (cfg.get("shares") or {}).get("common_issued"),
                "common_treasury": (cfg.get("shares") or {}).get("common_treasury"),
                "source": (cfg.get("shares") or {}).get("source", ""),
                "note": c.market.get("shares_note"),
            },
            "wacc": wacc_b,
            "nwc": nwc0,
            "scenarios": scen,
            "grids": {
                "wacc_steps": list(gd["wacc_steps"]),
                "g_values": list(gd["g_values"]),
                "growth_shifts": list(gd["growth_shifts"]),
                "margin_shifts": list(gd["margin_shifts"]),
                "wacc_g": wacc_g,
                "growth_margin": gm,
                "wacc0": w,
            },
            "engine_per_share": r["per_share"],
            "sotp": bool(c.sotp),
        }
    M._CACHE[k] = out
    return out


def _date(sv):
    from datetime import date

    return date.fromisoformat(str(sv))


# ---------------------------------------------------------------- KPI band


def kpi(o, s, mode: str, scen: str = "base") -> dict:
    """Six KPI values of the current version and the v0 values for the Δ in the tooltips. P7-U2: scen = 'pessimistic' /
    'optimistic' shows that scenario's engine values (per share, EV, equity, TV share: dcf_detail scenario block, the same
    dcf_value calls as the Scenarios table); v0's EV / equity of that scenario are not computed (Δ '—')."""
    from src.valuation.company_dcf import EOK

    r = M.result(o, s, mode)
    try:
        r0 = M.result(o, s, mode, 0)
    except M.NeedInput:
        r0 = {}
    out = {"r": r, "r0": r0, "mk": M.market(o, s, mode)}
    try:
        d = dcf_detail(o, s, mode)
        out["bridge"] = d.get("bridge")
        out["implied_multiple"] = (d.get("tv") or {}).get("implied_multiple")
        sc = (d.get("scenarios") or {}).get(scen) if scen != "base" else None
        if sc and r.get("per_share") is not None:
            out["r"] = {
                **r,
                "per_share": sc["per_share"],
                "ev": sc["ev"],
                "equity": sc["per_share"] * d["shares"]["out"] / EOK,
                "tv_share": sc["tv_share"],
                "implied_multiple": sc["implied_multiple"],
            }
            out["r0"] = {"per_share": (r0.get("scenarios") or {}).get(scen)} if r0 else {}
    except (M.NeedInput, M.PublicDataUnavailable):
        out["bridge"] = None
    try:
        rel = M.relative(o, s, mode)
        eb = (rel["multiples"].get("EV/EBITDA") or {}).get("metric")
        out["ltm_ebitda"] = eb / 100 if _ok(eb) else None
    except Exception:  # noqa: BLE001 - the sub line shows '—'
        out["ltm_ebitda"] = None
    return out


# ---------------------------------------------------------------- assumption table Δ per unit


def step_of(field: str, cur):
    """The value one step away (config/p7u.yaml delta_unit) or None when the field has no step / value."""
    du = M._load_yaml("config/p7u.yaml")["delta_unit"].get(field)
    if du is None or cur is None:
        return None
    if field == "rf_tenor":
        return 10 if int(cur) != 10 else 5
    return float(cur) + float(du["step"])


_WARMED: set = set()


def warm_deltas(o, s, mode: str) -> None:
    """P7-U2 speed: compute the assumption tables' one-step Δ (the same deltas() and cache) in a thread while another tab
    is open, so the first visit of the 가정·판단 tab does not wait for them. Once per session version and mode."""
    import threading

    k = (s["session_id"], M.version(s)["v"], mode, M.ukey(s) if mode == "public" else "")
    if k in _WARMED:
        return
    _WARMED.add(k)

    def run():
        for g in TABLE_FIELDS:
            try:
                deltas(o, s, mode, [f for f in TABLE_FIELDS[g] if M.applicable(o, f)])
            except Exception:  # noqa: BLE001 - the tab computes them itself
                return

    threading.Thread(target=run, daemon=True).start()


def deltas(o, s, mode: str, fields: list[str]) -> dict:
    """{field: {'step_label', 'after', 'delta', 'error'}}: recalc at current + one step (base per-share)."""
    du_all = M._load_yaml("config/p7u.yaml")["delta_unit"]
    base = M.result(o, s, mode).get("per_share")
    ver = M.version(s)
    out = {}
    for f in fields:
        du = du_all.get(f)
        if not du:
            continue
        k = _key("delta", o, s, mode, f)
        if k not in M._CACHE:
            cur = M.current_value(o, s, f)
            if f in ("cash_adjust_mn", "nci_mn") and cur is None:
                cur = 0.0 if f == "cash_adjust_mn" else None
            if f == "nci_mn" and cur is None:
                bi = dcf_detail(o, s, mode).get("bridge") or {}
                cur = (bi.get("nci") or 0.0) * 100  # 억원 -> 백만원 (the field's unit)
            nv = step_of(f, cur)
            rec = {"step_label": du["label"], "note": du.get("note", "")}
            if nv is None:
                rec["error"] = "자동값 없음"
            else:
                ok, why, val = spec.check(f, nv, o.ctx.peers_all())
                if not ok:
                    rec["error"] = "범위 밖"
                else:
                    try:
                        ctx = _ctx(o, s, mode)
                        with M.LOCK:
                            rr = R.recalc(o.cfg_path, {**ver["overrides"], f: val}, ctx=ctx)
                        rec["after"] = rr.get("per_share")
                        rec["delta"] = (rr["per_share"] - base) if _ok(rr.get("per_share")) and _ok(base) else None
                        if rr.get("error"):
                            rec["error"] = rr["error"]
                    except M.NeedInput:
                        rec["error"] = "시세 입력 뒤"
                    except Exception as e:  # noqa: BLE001 - shown in the cell
                        rec["error"] = type(e).__name__
            M._CACHE[k] = rec
        out[f] = M._CACHE[k]
    return out


# ---------------------------------------------------------------- relative valuation: target vs peers


def vs_peer(o, s, mode: str) -> dict:
    """Target vs the peers' aggregates already computed (no per-peer value): LTM operating margin, revenue growth, D/E."""
    from src.valuation.company_dcf import ltm
    from src.workbench import pubcut

    k = _key("vspeer", o, s, mode)
    if k in M._CACHE:
        return M._CACHE[k]
    ver = M.version(s)
    ctx = _ctx(o, s, mode)
    pub = mode == "public"
    with M.LOCK:
        r = R.recalc(o.cfg_path, ver["overrides"], ctx=ctx)
        c = ctx.c
        v2 = c.v2 or {}
        rev = ltm(c, "revenue")
        margin = ltm(c, "operating_income") / rev if rev else None
        names = [p["name"] for p in c.cfg.get("peers", [])]
    pm, pmn = v2.get("peer_margin"), int(v2.get("peer_margin_n") or 0)
    pg, pgn = v2.get("peer_growth"), int(v2.get("peer_growth_n") or 0)
    de_m, de_n = None, 0
    bt = o.ctx.bt
    if bt is not None and len(bt):
        sel = bt[bt.name.isin(names) & (bt["index"] == o.cfg["beta"]["index"])]
        if "de_avg" in sel.columns:
            dd = sel.de_avg.dropna()
            de_m, de_n = (float(dd.median()) if len(dd) else None), int(len(dd))
    elif set(names) == set(o.ctx.peers_all()):
        from src.workbench import pubagg

        try:
            agg = pubagg.get("engine", o.cfg_path, o.cfg)
            de_m, de_n = agg.get("peer_de_median"), int(agg.get("peer_de_n") or 0)
        except Exception:  # noqa: BLE001 - not recorded for this company
            de_m, de_n = None, 0

    def cut(vv, n):
        if vv is None:
            return None
        return None if pub and pubcut.few_peers(n) else vv

    ps = o.summ.get("peer_screen") or o.cfg.get("peer_screen") or {}
    lv = (ps.get("levels") or [{}])[-1] if ps.get("levels") else {}
    out = {
        "margin": (margin, cut(pm, pmn), pmn),
        "growth": (v2.get("own_cagr"), cut(pg, pgn), pgn),
        "de": (r.get("de"), cut(de_m, de_n), de_n),
        "ksic": lv.get("ksic") or o.cfg["target"].get("induty_code", ""),
        "relax": ps.get("relax_step"),
        "n": len(names),
    }
    M._CACHE[k] = out
    return out


# ---------------------------------------------------------------- financial tab


def fin_table(o, s, mode: str) -> dict:
    """FY 5 years + LTM metrics used by the valuation (statements; same keys as company_dcf.history)."""
    from src.valuation.company_dcf import EOK, ltm, val  # noqa: F401

    k = ("fin", o.cfg_path, mode, M.ukey(s) if mode == "public" else "")
    if k in M._CACHE:
        return M._CACHE[k]
    ctx = _ctx(o, s, mode)
    with M.LOCK:
        c = ctx.c
        yrs = [y for y in range(c.FY - 4, c.FY + 1)]
        cols = {}
        for y in yrs:
            rev, op = val(c, "revenue", y), val(c, "operating_income", y)
            dna = float(c.dna.get((y, "FY"), float("nan")))
            cogs = val(c, "cogs", y)
            eqp = val(c, "equity_parent", y)
            ni = val(c, "net_income_parent", y) or val(c, "net_income", y)
            cols[y] = {
                "revenue": rev,
                "growth": rev / val(c, "revenue", y - 1) - 1 if val(c, "revenue", y - 1) else float("nan"),
                "op": op,
                "margin": op / rev if rev else float("nan"),
                "ebitda_margin": (op + dna) / rev if rev and _ok(dna) else float("nan"),
                "roe": ni / eqp if eqp else float("nan"),
                "capex_ratio": (val(c, "capex_ppe", y) + val(c, "capex_intangibles", y)) / rev if rev else float("nan"),
                "dna_ratio": dna / rev if rev and _ok(dna) else float("nan"),
                "dio": val(c, "inventories", y) / cogs * 365 if cogs else float("nan"),
                "dso": val(c, "receivables", y) / rev * 365 if rev else float("nan"),
                "dpo": val(c, "trade_payables", y) / cogs * 365 if cogs else float("nan"),
                "rec": val(c, "receivables", y),
                "pay": val(c, "trade_payables", y),
                "debt": val(c, "total_debt", y) + val(c, "lease_liabilities", y),
            }
        lrev, lop = ltm(c, "revenue"), ltm(c, "operating_income")
        from src.valuation.company_dcf import bridge

        br = bridge(c)
        ltm_col = {
            "revenue": lrev,
            "op": lop,
            "margin": lop / lrev if lrev else float("nan"),
            "net_cash": br["cash_like"] - br["total_debt"],
            "debt": br["total_debt"],
        }
        fs = "연결" if c.cfg["meta"]["fs_div"] == "CFS" else "별도"
    zero_rec = all(cols[y]["rec"] == 0 for y in yrs)
    zero_pay = all(cols[y]["pay"] == 0 for y in yrs)
    out = {
        "years": yrs,
        "cols": cols,
        "ltm": ltm_col,
        "fs": fs,
        "bs_date": o.cfg["meta"]["bs_date"],
        "zero_rec": zero_rec,
        "zero_pay": zero_pay,
    }
    M._CACHE[k] = out
    return out


# ---------------------------------------------------------------- summary: football field


FF_ORDER = ["EV/EBITDA", "PER", "EV/Sales", "PBR"]


def scen_result(o, s, mode: str, scen: str = "base") -> dict:
    """The version's result with the per share of the chosen scenario (P7-U2 screen switch; base = unchanged)."""
    r = M.result(o, s, mode)
    sc = (r.get("scenarios") or {}).get(scen) if scen != "base" else None
    return {**r, "per_share": sc} if _ok(sc) else r


def football(o, s, mode: str, scen: str = "base") -> dict:
    """DCF Bear~Bull (marker = the chosen scenario, default base), peer IQR + median per multiple, the control block
    (VWAP x (1 + premium IQR)) and the target price (PC close / public input)."""
    r = scen_result(o, s, mode, scen)
    sc = r.get("scenarios") or {}
    rows = []
    vals = [v for v in sc.values() if _ok(v)]
    if vals:
        rows.append(
            {"label": "DCF", "sub": "Bear ~ Bull", "lo": min(vals), "hi": max(vals), "rep": r.get("per_share"), "kind": "dcf"}
        )
    rel = M.relative(o, s, mode)
    for nm in FF_ORDER:
        m = rel["multiples"].get(nm) or {}
        if m.get("n") and _ok(m.get("ps_q25")) and _ok(m.get("ps_q75")):
            rows.append(
                {
                    "label": nm,
                    "sub": "Peer IQR",
                    "lo": m["ps_q25"],
                    "hi": m["ps_q75"],
                    "rep": m["ps_median"],
                    "kind": "peer",
                    "n": m["n"],
                }
            )
        else:
            rows.append(
                {
                    "label": nm,
                    "sub": "Peer IQR",
                    "lo": None,
                    "hi": None,
                    "rep": None,
                    "kind": "peer",
                    "n": m.get("n"),
                    "cut": bool(m.get("public_cut")),
                }
            )
    block = None
    try:
        pm = M.premium(o, s, mode)
        if pm.get("block"):
            block = pm["block"]
    except (M.NeedInput, M.PublicDataUnavailable):
        block = None
    if block:
        rows.append(
            {
                "label": "경영권 거래",
                "sub": "블록 · 중앙값",
                "lo": block["q25"],
                "hi": block["q75"],
                "rep": block["q50"],
                "kind": "block",
            }
        )
    else:
        rows.append({"label": "경영권 거래", "sub": "VWAP 입력 시", "lo": None, "hi": None, "rep": None, "kind": "block"})
    mk = M.market(o, s, mode)
    return {
        "rows": rows,
        "price": mk.get("close"),
        "example": bool((s.get("public_inputs") or {}).get("example")) and mode == "public",
        "source": mk.get("source"),
    }
