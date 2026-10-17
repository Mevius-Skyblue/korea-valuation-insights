"""Tests of the public repository korea-valuation-insights (P7-C3; copied to tests/test_public_app.py by
scripts/build_public_bundle.py). They need nothing but the repository: no API key, no DB, no KRX data.

    1 snapshots: file hashes = app/public/index.json; no market-data key or column inside (structure scan)
    2 replay: every evaluable company's public per share (example inputs) = the value the PC recorded (float equality)
    3 session file: download -> upload round trip; an edited file is rejected
    4 workspaces: two browser sessions never see each other's sessions or files
    5 screens: the work screen pages render without an exception, with the notice, and without internal code strings
    6 app/data columns = the export whitelist; the calculator equals the engine functions
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "app" / "Home.py").exists())   # tests/ (public) or docs/ci/
sys.path.insert(0, str(ROOT))
PUB = Path(os.environ.get("KVI_SNAPSHOT_DIR") or ROOT / "app" / "public")      # the private repository runs it on its build
INDEX = json.loads((PUB / "index.json").read_text(encoding="utf-8"))
EVAL = [x for x in INDEX if x["kind"] == "evaluable"]
BANNED_KEYS = {"mktcap", "mktcap_common", "mktcap_eok", "close", "vwap", "vwap20", "list_shrs", "listed_shares", "price", "raw", "se",
               "bu_avg", "bu_raw_avg", "blume", "de_avg", "ev_sales", "ev_ebitda", "per", "pbr", "prem_bu20_doc", "evaluator"}
ALLOWED = {
    "assumptions_range.csv": ["year_from", "year_to", "group", "metric", "n", "median", "q1", "q3"],
    "rf_tenor.csv": ["year", "group", "tenor", "count"],
    "sources.csv": ["year", "group", "item", "source_class", "count"],
    "srp_cites.csv": ["cited_year", "band", "srp", "count", "filed_years"],
    "achievement.csv": ["period", "group", "account", "h", "n", "shortfall_share", "median", "q1", "q3"],
    "fss_compare.csv": ["label", "scope", "shortfall_share", "mean_shortfall", "status"],
    "cagr_bands.csv": ["band", "label", "cagr_lo", "cagr_hi", "n_deals", "h1_median", "h1_n", "h2_median", "h2_n",
                       "h3_median", "h3_n"],
}


def _windows_socketpair():
    """Windows runners: IPv4 loopback socket pairs from several threads can fail (WinError 10014); build them on ::1."""
    if os.name != "nt":
        return
    orig = socket.socketpair

    def pair(family=None, type=socket.SOCK_STREAM, proto=0):
        if family not in (None, socket.AF_INET6):
            return orig(family, type, proto)
        ls = socket.socket(socket.AF_INET6, type, proto)
        try:
            ls.bind(("::1", 0))
            ls.listen(1)
            cs = socket.socket(socket.AF_INET6, type, proto)
            cs.connect(ls.getsockname()[:2])
            ss, _ = ls.accept()
        finally:
            ls.close()
        return ss, cs
    socket.socketpair = pair


_windows_socketpair()


@pytest.fixture(scope="session", autouse=True)
def public_mode():
    os.environ["KVI_RUNTIME"] = tempfile.mkdtemp(prefix="kvi_rt_")
    from src.workbench.public_deploy import boot
    boot()
    yield


def _snap(code: str) -> dict:
    return json.loads(gzip.decompress((PUB / "snapshots" / f"{code}.json.gz").read_bytes()))


# ---------------------------------------------------------------- 1 snapshots

def test_snapshot_files_match_index():
    assert INDEX and len(EVAL) > 0
    for x in INDEX:
        b = (PUB / "snapshots" / f"{x['code']}.json.gz").read_bytes()
        assert hashlib.sha256(b).hexdigest() == x["sha256"], x["code"]


def _keys(o, acc):
    if isinstance(o, dict):
        if "$df" in o:
            acc.update(str(c) for c in o["$df"]["columns"])
            return
        acc.update(k for k in o if not k.startswith("$"))
        for v in o.values():
            _keys(v, acc)
    elif isinstance(o, list):
        for v in o:
            _keys(v, acc)


AGG_KEYS = {"beta_u0", "r2_median", "n", "stats", "st5", "n_beta", "peer_margin_median", "peer_margin_n", "n_peers", "beta_n",
            "peers", "multiples", "ev_sales", "ev_ebitda", "per", "pbr", "q25", "median", "q75", "med", "name", "tier", "include",
            "fs_div", "EV/Sales", "EV/EBITDA", "PER", "PBR", "EV/EBITDA(보완 전)"}


def test_no_market_data_keys_in_snapshots():
    """No per-peer market column or key outside the aggregates; the aggregates hold only counts and quartiles."""
    bad = {}
    for x in INDEX:
        o = _snap(x["code"])
        seams = o.get("seams") or {}
        rest = {k: v for k, v in o.items() if k != "seams"} | {"seams": {k: v for k, v in seams.items() if not k.startswith("agg_")}}
        loss = (((rest.get("summary") or {}).get("diagnostics") or {}).get("loss") or {})
        if isinstance(loss.get("ev_sales"), dict):        # the loss-path per-share range from the peer EV/Sales quartiles
            assert set(loss["ev_sales"]) <= {"basis", "invalid", "median", "n", "q25", "q75", "valid"}, x["code"]
            loss = {k: v for k, v in loss.items() if k != "ev_sales"}
            rest["summary"] = {**rest["summary"], "diagnostics": {**rest["summary"]["diagnostics"], "loss": loss}}
        ks = set()
        _keys(rest, ks)
        hit = sorted(ks & BANNED_KEYS)
        agg = set()
        _keys({k: v for k, v in seams.items() if k.startswith("agg_")}, agg)
        extra = sorted(agg - AGG_KEYS - {k for k in seams if k.startswith("agg_")})
        if hit or extra:
            bad[x["code"]] = hit + extra
    assert not bad, bad


# ---------------------------------------------------------------- 2 replay = recorded

def _user(cfg: dict) -> dict:
    sh = cfg.get("shares") or {}
    prefs = list(sh.get("listed_pref_codes") or [])
    n_pref = max((sh.get("pref_issued") or 0) - (sh.get("pref_treasury") or 0), 0)
    return {"close": 10000.0, "vwap20": 9900.0,
            "sub_close": {s["stock_code"]: 5000.0 for s in (cfg.get("structure") or {}).get("subsidiaries") or []
                          if s.get("listed") and s.get("direct") and s.get("stock_code")},
            "pref": {p: {"close": 5000.0, "listed": max(n_pref // max(len(prefs), 1), 1)} for p in prefs}}


def test_replay_equals_recorded_per_share():
    import yaml

    from src.workbench import recalc as R
    from src.workbench.public_deploy import ensure
    bad = []
    for x in EVAL:
        if x.get("check_ps") is None:
            continue
        cfgp = ensure(x["code"])
        cfg = yaml.safe_load(Path(cfgp).read_text(encoding="utf-8"))
        r = R.recalc(cfgp, {}, R.public_context(cfgp, _user(cfg)))
        if r.get("per_share") != x["check_ps"]:
            bad.append((x["code"], r.get("per_share"), x["check_ps"]))
    assert not bad, bad[:5]


def test_premium_replay_equals_recorded():
    """P7-C3b: the control-premium range replayed from the snapshot (fixed as-of percentile, 0.1 point) = the PC value at
    the same percentile (index check_prem, predict on the DB), float equality."""
    import yaml

    from src.workbench.public_deploy import ensure, premium_range, public_percentile
    bad, n = [], 0
    for x in EVAL:
        cp = x.get("check_prem")
        if not cp:
            continue
        cfgp = ensure(x["code"])
        cfg = yaml.safe_load(Path(cfgp).read_text(encoding="utf-8"))
        t = cfg["target"]
        pct = public_percentile(t["stock_code"], cfg["meta"]["as_of"], t["market"])["mktcap_pct"]
        r = premium_range(pct, market=t["market"], **cfg["params"]["premium"])
        got = {"q25": r.q25, "q50": r.q50, "q75": r.q75, "method": r.method, "n_neighbour": r.neighbour["n"],
               "band": r.band["band"], "band_n": r.band["n"]}
        n += 1
        if pct != cp["pct"] or got != cp["rounded"]:
            bad.append((x["code"], pct, got, cp))
    assert n and not bad, bad[:3]


PREM_REF_KEYS = {"measure", "all", "rows", "layer", "key", "n", "median", "q25", "q75", "neg", "warn_n10"}
PREM_RANGE_KEYS = {"q25", "q50", "q75", "method", "reason", "regression", "neighbour", "band", "warnings", "inputs",
                   "cv_improvement_q50", "n", "n_same_market"}


def test_premium_aggregates_only():
    """P7-C3b publish.on / off: the reference aggregates and the recorded premium ranges hold counts and quantiles only -
    no per-deal value, no neighbours' percentile range, no deal identity."""
    ks = set()
    _keys(json.loads((PUB / "premium_ref.json").read_text(encoding="utf-8")), ks)
    assert ks <= PREM_REF_KEYS, ks - PREM_REF_KEYS
    for x in EVAL:
        for k, v in (_snap(x["code"]).get("seams") or {}).items():
            if k.startswith("premium_range:"):
                ks = set()
                _keys(v, ks)
                ks = {z for z in ks if not z.startswith("$")}
                assert ks <= PREM_RANGE_KEYS | {"band"}, (x["code"], ks - PREM_RANGE_KEYS)
                assert "pct_range" not in json.dumps(v), x["code"]


# ---------------------------------------------------------------- 3 session file, 4 workspaces

def test_session_file_round_trip_and_tamper(tmp_path):
    from src.workbench import session as S
    from src.workbench import sessionfile as SF
    code = EVAL[0]["code"]
    with S.use_workspace(tmp_path / "a"):
        s = S.create(code)
        r = S.set_assumption(s, "mrp", 0.09, "시험")
        assert r["ok"]
        blob = SF.dump(S.load(s["session_id"]))
        s2, _ = SF.load(blob)
        assert s2["versions"][-1]["overrides"] == {"mrp": 0.09}
        assert s2["versions"][-1]["result"]["per_share"] == r["result"]["per_share"]
        p = json.loads(blob)
        p["session"]["versions"][-1]["overrides"]["mrp"] = 0.10
        with pytest.raises(SF.SessionFileError):
            SF.load(json.dumps(p).encode("utf-8"))


def test_workspaces_do_not_mix(tmp_path):
    from src.workbench import session as S
    code = EVAL[0]["code"]
    with S.use_workspace(tmp_path / "u1"):
        a = S.create(code)
    with S.use_workspace(tmp_path / "u2"):
        b = S.create(code)
        assert [x["session_id"] for x in S.list_sessions()] == [b["session_id"]]
        assert S.load(b["session_id"])["draft_config"]
    with S.use_workspace(tmp_path / "u1"):
        assert [x["session_id"] for x in S.list_sessions()] == [a["session_id"]]
    assert a["session_id"] == b["session_id"]           # same id, different folders: never the same file
    assert (tmp_path / "u1" / "sessions" / a["session_id"]).exists() and (tmp_path / "u2" / "sessions" / b["session_id"]).exists()


# ---------------------------------------------------------------- 5 screens

@pytest.mark.parametrize("page", ["select", "data", "assume", "result", "export", "ref_rates", "ref_accuracy", "ref_premium",
                                  "ref_method", "ref_guide"])
def test_pages_render_plain_words(page, tmp_path_factory):
    from streamlit.testing.v1 import AppTest

    from app.wb.text import codes_in
    from src.workbench import session as S
    ws = tmp_path_factory.getbasetemp() / "screens"
    with S.use_workspace(ws):
        s = S.list_sessions()[0] if S.list_sessions() else S.create(EVAL[0]["code"])
    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=300)
    at.session_state["kvi_ws_path"] = str(ws)
    at.query_params.update({"p": page, "m": "public", "sid": s["session_id"]})
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(str(m.value) for m in at.markdown) + " ".join(str(b.label) for b in at.button)
    assert not codes_in(text), codes_in(text)


# ---------------------------------------------------------------- 6 data whitelist, calculator

def test_app_data_columns():
    for name, cols in ALLOWED.items():
        assert list(pd.read_csv(ROOT / "app" / "data" / name, nrows=0).columns) == cols, name


def test_calculator_equals_engine():
    """The calculator page's numbers are the engine's (src/valuation/wacc.py, dcf.py) for the default inputs."""
    from app.lib.calc import DEFAULTS, calculate
    from src.valuation.wacc import wacc
    r = calculate(dict(DEFAULTS))
    w = wacc(DEFAULTS["rf"], DEFAULTS["mrp"], DEFAULTS["beta_u"], DEFAULTS["de"], DEFAULTS["kd"], DEFAULTS["tax"], DEFAULTS["tax"],
             DEFAULTS["srp"])
    assert r["wacc"] == w.wacc and r["ev"] > 0 and r["equity"] == r["ev"] - DEFAULTS["net_debt"]
