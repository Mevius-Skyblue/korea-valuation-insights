"""Fast recalculation (config/p7c1.yaml speed.recalc): engine only, the company and its tables kept in memory.

The same functions the Excel reference uses (company_dcf.forecast / dcf_value / discount_rate / kd_for, engine_ref's βu
and D/E rules) run on an in-memory copy with the session's assumptions applied, so a confirmed version reproduces the
fast value exactly (tests/test_p7c1.py). Nothing is written; no Excel, no reconciliation.

    apply_overrides(cfg, led, ov)    -> (cfg, led) with the config-native fields set and cfg['overrides'] = hook fields
    context(cfg_path)                -> cached Ctx for a draft config (load once per process)
    recalc(cfg_path, ov, ctx=None)   -> {'per_share', 'wacc', 'tv_share', 'ev', 'equity', 'scenarios', 'beta_u', 'de', 'kd', ...}
    public_context(cfg_path, user)   -> Ctx built with the user's market inputs (UserOverlayProvider, P7-C2 public-mode screen;
                                        the same values as the public-mode export). Not cached here (the screen caches it)
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

import duckdb
import numpy as np

from src import yamlio
from src.collect.core import ROOT
from src.workbench.spec import HOOK

_CTX: dict = {}


def apply_overrides(cfg: dict, led: dict, ov: dict) -> tuple[dict, dict]:
    """Copies of the config and ledger with the session's confirmed values written in."""
    cfg, led = copy.deepcopy(cfg), copy.deepcopy(led)
    if "rf_tenor" in ov:
        led["risk_free"]["tenor"] = int(ov["rf_tenor"])
    if "mrp" in ov:
        led["mrp"]["value"] = float(ov["mrp"])
    if "srp" in ov:
        s = float(ov["srp"])
        led["decisions"]["srp_columns"] = [s] + [x for x in led["decisions"]["srp_columns"] if abs(x - s) > 1e-12]
        cfg.setdefault("excel", {})["default_srp"] = s
    if "g_terminal" in ov:
        cfg["forecast"]["human"]["g_terminal"] = float(ov["g_terminal"])
    if "scenario_width" in ov:
        w = float(ov["scenario_width"])
        cfg["scenarios"]["human"] = {
            "pessimistic": {"growth_shift": -w, "margin_shift": -w},
            "base": {"growth_shift": 0.0, "margin_shift": 0.0},
            "optimistic": {"growth_shift": w, "margin_shift": w},
        }
    if "peers" in ov:
        keep = set(ov["peers"])
        cfg["peers"] = [p for p in cfg.get("peers", []) if p["name"] in keep]
    if "sotp_discount" in ov and isinstance(cfg.get("structure", {}).get("discount"), dict):
        cfg["structure"]["discount"]["base"] = float(ov["sotp_discount"])
    if "premium" in ov:
        cfg["params"]["premium"] = {**cfg["params"]["premium"], **ov["premium"]}
    hook = {k: ov[k] for k in HOOK if ov.get(k) is not None}
    if hook:
        cfg["overrides"] = hook
    return cfg, led


class Ctx:
    """One draft config in memory: the loaded company, its history, the beta and peer tables."""

    def __init__(self, cfg_path: str):
        from src.db.build import DB_PATH
        from src.valuation.company_dcf import hist_roic, history, load_company
        from src.workbench import pubcut

        self.cfg_path = cfg_path
        self.public = pubcut.public_scope()  # P7-X2a: built in the public mode (user market data) -> public n rules
        c = load_company(cfg_path)
        c.ronic_start = c.cfg["excel"]["ronic_start"]
        self.c = c
        self.base_cfg, self.base_led = copy.deepcopy(c.cfg), copy.deepcopy(c.led)
        self.base_v2 = copy.deepcopy(c.v2)
        self.base_sotp_discount = None if not c.sotp else c.sotp["discount"]
        self.h = history(c)
        self.cap = hist_roic(c, self.h)
        name = Path(cfg_path).stem.replace("valuation_", "")
        from src.workbench import pubagg
        from src.workbench import snapdata as SD

        self.beta_pub = None
        if SD.replaying():  # P7-C3 public snapshot: βu of the draft peers as an aggregate, no beta rows
            self.bt = None
            self.beta_pub = pubagg.get("ctx", cfg_path, c.cfg)
        else:
            con = duckdb.connect(str(DB_PATH), read_only=True)
            try:
                self.bt = con.execute(f"SELECT * FROM beta_{name} WHERE spec=?", [c.cfg["beta"]["spec"]]).df()
            finally:
                con.close()
            if SD.mode() == "record":
                pubagg.record("ctx", cfg_path, c.cfg, ctx_aggregates(self.bt, c.cfg))
        self.de0 = float(c.market["de_points"].de.mean())

    def peers_all(self) -> list[str]:
        return [p["name"] for p in self.base_cfg.get("peers", [])]


def ctx_aggregates(bt, cfg: dict) -> dict:
    """What the public snapshot keeps of the beta table for the draft's peers (P7-C3): the model's βu (beta_u0 on the
    draft peers + target rows, as recalc), and for the data screen the R² median (2 decimals) and the number of peers with
    a regression on the model index."""
    from src.valuation.company_dcf import beta_u0
    from src.workbench.pubagg import r2_display

    names = [p["name"] for p in cfg.get("peers", [])]
    from src.workbench import pubcut

    b = bt[bt.name.isin(names) | (bt.tier == "target")] if len(bt) else bt
    sel = bt[bt.name.isin(names) & (bt["index"] == cfg["beta"]["index"])] if len(bt) else bt
    bu, src = beta_u0(b, cfg, public=True)  # recorded for the public snapshot only (P7-X2a n rule)
    r2 = pubcut.r2(r2_display(float(sel.r2.median())) if len(sel) else None, len(sel), True)
    return {"beta_u0": [bu, src], "r2_median": r2, "n": int(len(sel))}


def context(cfg_path: str) -> Ctx:
    """The in-memory company of a config (loaded once per process; recalculations reuse it)."""
    if cfg_path not in _CTX:
        from src.workbench import snapdata as SD

        if SD.replaying():  # P7-C3 public deployment: no market input yet (DCF values need none, except SOTP)
            from src.market.provider import use
            from src.workbench.public_deploy import SnapshotUserProvider

            cfg = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
            with use(SnapshotUserProvider({}, cfg)):
                _CTX[cfg_path] = Ctx(cfg_path)
        else:
            _CTX[cfg_path] = Ctx(cfg_path)
    return _CTX[cfg_path]


def drop(cfg_path: str | None = None) -> None:
    """Forget the in-memory company of one config (or all)."""
    if cfg_path is None:
        _CTX.clear()
    else:
        _CTX.pop(cfg_path, None)


def v2_for_peers(v2: dict | None, names: list[str], ov: dict) -> dict | None:
    """The v2 inputs with the peer margin / growth medians over the kept peers (same rule as company_dcf.v2_inputs)."""
    from src.valuation.company_dcf import v2_apply, v2_start_growth

    if not v2:
        return v2
    keep = set(names)
    pm_all = [x for x in v2["peers"] if x["name"] in keep]
    pms = [x["margin"] for x in pm_all if x["margin"] is not None]
    pgs = [x["growth"] for x in pm_all if x["growth"] is not None]
    pm = float(np.median(pms)) if len(pms) >= 3 else None
    pg = float(np.median(pgs)) if len(pgs) >= 3 else None
    lo, hi = v2["clip"]
    m0 = v2["m0_auto"]
    v = {
        **v2,
        "peers": pm_all,
        "peer_margin": pm,
        "peer_margin_n": len(pms),
        "peer_growth": pg,
        "peer_growth_n": len(pgs),
        "m0": m0,
        "m0_src": v2["m0_src"] if v2.get("m0") == m0 else v2.get("m0_src"),
        "conv_amt": v2["conv_share"] * (pm - m0) if pm is not None else 0.0,
        "g0": v2_start_growth(v2["own_cagr"], pg, v2["weight_own"], lo, hi),
    }
    v["g0_auto"] = v["g0"]
    return v2_apply(v, ov)


def public_context(cfg_path: str, user: dict) -> Ctx:
    """The in-memory company with the user's market inputs (public mode)."""
    from src.market.provider import use
    from src.market.user_provider import UserOverlayProvider

    cfg = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
    from src.workbench import snapdata as SD

    if SD.replaying():  # P7-C3 public deployment: the user's values only (same values, no DB)
        from src.workbench.public_deploy import SnapshotUserProvider

        prov = SnapshotUserProvider(user, cfg)
    else:
        prov = UserOverlayProvider(user, cfg)
    with use(prov):
        return Ctx(cfg_path)


_PCTX: dict = {}


def public_context_cached(cfg_path: str, user: dict) -> Ctx:
    """public_context, kept per (config, inputs) in this process (P7-C3 public deployment; at most 32 entries)."""
    import json

    k = (cfg_path, json.dumps(user, sort_keys=True, default=str))
    if k not in _PCTX:
        if len(_PCTX) >= 32:
            _PCTX.pop(next(iter(_PCTX)))
        _PCTX[k] = public_context(cfg_path, user)
    return _PCTX[k]


def recalc(cfg_path: str, ov: dict, ctx: Ctx | None = None) -> dict:
    """Engine-only values of the draft with the session assumptions `ov` (deterministic). ctx: another in-memory company
    (the public-mode context); default the cached PC context of cfg_path."""
    from src.valuation.company_dcf import beta_u0, dcf_value, discount_rate, forecast, kd_for, overrides_of

    t0 = time.time()
    x = ctx or context(cfg_path)
    c = x.c
    cfg, led = apply_overrides(x.base_cfg, x.base_led, ov)
    c.cfg, c.led = cfg, led
    c.__dict__["_bridge_cache"] = {}
    if c.sotp:
        c.sotp["discount"] = float(cfg["structure"]["discount"]["base"]) if "sotp_discount" in ov else x.base_sotp_discount
    names = [p["name"] for p in cfg.get("peers", [])]
    if c.sotp and x.bt is None:  # P7-C3 public deployment: a listed subsidiary without the user's close
        miss = [r.get("name") for r in c.sotp["rows"] if r.get("listed") and r.get("direct") and not r.get("close")]
        if miss:
            return {
                "per_share": None,
                "error": "상장 종속회사 종가 입력 필요: " + ", ".join(map(str, miss)),
                "scenarios": {},
                "seconds": round(time.time() - t0, 3),
            }
    c.v2 = v2_for_peers(x.base_v2, names, overrides_of(cfg))
    hk = overrides_of(cfg)
    if hk.get("beta_u") is not None:
        bu0, src = float(hk["beta_u"]), "override"
    elif x.bt is None:  # P7-C3 public snapshot: the recorded βu holds for the draft's peer set only
        if set(names) != set(x.peers_all()):
            from src.workbench.snapdata import Missing

            raise Missing("피어 구성을 바꾼 βu는 피어별 시세가 있어야 계산합니다(PC 모드). βu를 직접 입력하면 계산합니다")
        bu0, src = float(x.beta_pub["beta_u0"][0]), x.beta_pub["beta_u0"][1]
    else:
        bt = x.bt[x.bt.name.isin(names) | (x.bt.tier == "target")] if len(x.bt) else x.bt
        bu0, src = beta_u0(bt, cfg, public=x.public)
    de = float(hk["de"]) if hk.get("de") is not None else x.de0
    kd = float(hk["kd"]) if hk.get("kd") is not None else kd_for(c, cfg["excel"]["kd_version"])[0]
    srps = led["decisions"]["srp_columns"]
    w = discount_rate(c, srps[0], bu0, de, kd)
    out = {"wacc": w, "beta_u": bu0, "beta_src": src, "de": de, "kd": kd, "srp": srps[0], "scenarios": {}}
    if w <= cfg["forecast"]["human"]["g_terminal"]:
        out.update({"error": f"WACC {w:.2%} ≤ 영구성장률 {cfg['forecast']['human']['g_terminal']:.2%}", "per_share": None})
        out["seconds"] = round(time.time() - t0, 3)
        return out
    for k in cfg["excel"]["scenarios"]:
        shf = cfg["scenarios"]["human"][k]
        v = dcf_value(c, x.h, forecast(c, x.h, shf["growth_shift"], shf["margin_shift"]), w, x.cap)
        out["scenarios"][k] = v["per_share"]
        if k == "base":
            out.update(
                {
                    "per_share": v["per_share"],
                    "tv_share": v["tv_share"],
                    "ev": v["ev"],
                    "equity": v["equity"],
                    "ronic": v["ronic"],
                    "implied_multiple": v["implied_multiple"],
                }
            )
    out["m0"] = (c.v2 or {}).get("m0")
    out["g0"] = (c.v2 or {}).get("g0")
    out["seconds"] = round(time.time() - t0, 3)
    return out
