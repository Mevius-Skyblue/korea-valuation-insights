"""Public deployment without the DB (config/p7c3.yaml public_app): the snapshot replay, the user's market inputs and the
rules that differ from the PC.

    is_public()            this process serves the public deployment (env KVI_PUBLIC=1 or app/public/BUNDLE.json present)
    premium_withheld()     snapshot record / replay and decisions.premium_public is false -> no premium aggregates, no block
    public_percentile(..)  public mode market-cap percentile (P7-C3b): the as-of date's KRX percentile, fixed (snapshot: 0.1)
    premium_range(..)      predict.premium_range through a data seam (per-deal values never recorded)
    SnapshotUserProvider   the market provider of the public deployment: only the user's typed values (target close /
                           VWAP, listed subsidiaries, listed preferred); market cap = close × common shares outstanding
                           (DART), as UserOverlayProvider does on the PC. Everything else raises PublicDataUnavailable
    srp_cite_value(con)    the SRP citation used in the Rf × SRP table (P5-B aggregate) - a data seam
    p5b_excel_data(con)    the P5-B reference aggregates of the Excel model - a data seam
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import yaml

from src import yamlio
from src.collect.core import ROOT
from src.market.user_provider import PublicDataUnavailable
from src.workbench import snapdata as SD

PUBLIC_DIR = ROOT / "app" / "public"


def is_public() -> bool:
    return os.environ.get("KVI_PUBLIC") == "1" or (PUBLIC_DIR / "BUNDLE.json").exists()


@lru_cache(maxsize=1)
def premium_public() -> bool:
    """decisions.premium_public: config/p7c3b.yaml (user decision 2026-10-18: publish the aggregates) over the P7-C3 record."""
    for name in ("p7c3b.yaml", "p7c3.yaml"):
        f = ROOT / "config" / name
        try:
            return bool(yamlio.load(f.read_text(encoding="utf-8"))["decisions"]["premium_public"]["value"])
        except (OSError, KeyError, TypeError):
            continue
    return False


def premium_withheld() -> bool:
    """True in the public snapshot (record and replay) unless the premium aggregates are published."""
    return SD.mode() in ("record", "replay") and not premium_public()


def public_percentile(code: str, as_of: str, market: str, con=None) -> dict:
    """P7-C3b (config/p7c3b.yaml percentile): the public mode's market-cap percentile of the target = the as-of date's KRX
    percentile (the PC mode value), fixed - the user's typed price does not move it. PC public mode: exact; the public
    snapshot records it rounded to 0.1 point with the count of stocks (no distribution)."""
    key = f"{code}|{as_of}|{market}"
    if SD.replaying():
        return SD.get("base_pct", key)
    from src.market.provider import DbMarketProvider

    db = DbMarketProvider()
    mc = db.quote(code, as_of, con=con)[1]
    p = db.mktcap_percentile(as_of, market, mc, con=con)
    out = {"mktcap_pct": float(p["mktcap_pct"]), "n_universe": int(p["n_universe"]), "fixed": True}
    if SD.mode() == "record":
        out["mktcap_pct"] = round(out["mktcap_pct"], 1)
        SD.put("base_pct", key, out)
    return out


def premium_range(
    mktcap_pct: float,
    stake_band: str = "lt25",
    buyer_group: str = "strategic",
    market: str = "KOSDAQ",
    period: str = "2015-2026",
    public: bool | None = None,
):
    """predict.premium_range (unchanged) through a data seam: the snapshot holds the result for each premium input at the
    target's fixed percentile - quantiles, counts, method, warnings; not the neighbours' percentile range (two deals).
    P7-X2a (src/workbench/pubcut.py): in the public mode a band-table cell of fewer than 10 deals has no quantiles.
    public: None = decide from the mode / market-data provider (pubcut.public_scope)."""
    from dataclasses import asdict

    from src.premium import predict as P
    from src.workbench import pubcut

    if SD.mode() == "off":
        r = P.premium_range(mktcap_pct, stake_band=stake_band, buyer_group=buyer_group, market=market, period=period)
        if pubcut.public_scope() if public is None else public:
            return P.PremiumRange(**pubcut.premium(asdict(r), True))
        return r
    key = [float(mktcap_pct), stake_band, buyer_group, market, period]
    if SD.replaying():
        d = SD.get("premium_range", key)
    else:
        d = asdict(P.premium_range(mktcap_pct, stake_band=stake_band, buyer_group=buyer_group, market=market, period=period))
        d["neighbour"] = {k: v for k, v in d["neighbour"].items() if k != "pct_range"}
        d["inputs"] = {}
        SD.put("premium_range", key, pubcut.premium(d, True))
        d = SD.get("premium_range", key)
    return P.PremiumRange(**d)


PREMIUM_REF = "premium_ref.json"


def premium_ref_table() -> dict:
    """Reference page '경영권 프리미엄' (P7-C3b publish.on): main-sample aggregates only - overall and by market, stake
    band, buyer group, market-cap percentile band and period: n, median, q25, q75, share of negative premiums; n<10
    marked. PC: from the DB sample (predict._db_frame); public deployment: the file the snapshot build wrote."""
    if SD.replaying():
        return json.loads((snapshot_dir() / PREMIUM_REF).read_text(encoding="utf-8"))
    from src.premium.predict import _db_frame, quintile_band

    d = _db_frame()
    d = d.assign(band=d.mktcap_pct.map(quintile_band), period=d.period_early.map({1: "2010-2014", 0: "2015-2026"}))

    def agg(v):
        return {
            "n": int(len(v)),
            "median": float(v.median()),
            "q25": float(v.quantile(0.25)),
            "q75": float(v.quantile(0.75)),
            "neg": float((v < 0).mean()),
            "warn_n10": bool(len(v) < 10),
        }

    rows = []
    for layer, col, order in (
        ("시장", "market", ["KOSDAQ", "KOSPI"]),
        ("지분 구간", "stake_band", ["lt25", "25to50", "gt50"]),
        ("인수자 유형", "buyer_group", ["strategic", "financial", "other"]),
        ("시총 백분위 구간", "band", sorted(d.band.dropna().unique())),
        ("기간", "period", ["2010-2014", "2015-2026"]),
    ):
        for k in order:
            g = d[d[col] == k].prem_bu20_doc
            if len(g):
                rows.append({"layer": layer, "key": str(k), **agg(g)})
    return {"measure": "prem_bu20_doc", "all": agg(d.prem_bu20_doc), "rows": rows}


def record_premium_inputs(cfg: dict) -> int:
    """Snapshot build (record mode): every allowed premium input of a session at the fixed percentile (36 results)."""
    from src.premium.predict import BUYER_GROUPS, PERIODS, STAKE_BANDS

    t = cfg["target"]
    pct = public_percentile(t["stock_code"], cfg["meta"]["as_of"], t["market"])["mktcap_pct"]
    n = 0
    for sb in STAKE_BANDS:
        for bg in BUYER_GROUPS:
            for per in PERIODS:
                premium_range(pct, stake_band=sb, buyer_group=bg, market=t["market"], period=per)
                n += 1
    return n


@SD.seam("srp_cite", key=lambda con: "srp_cite_pick")
def srp_cite_value(con) -> float:
    from src.p5.b_reference import srp_cite_pick

    return srp_cite_pick(con)["value"]


@SD.seam("p5b_excel", key=lambda con: "excel_data")
def p5b_excel_data(con) -> dict:
    from src.p5.b_reference import excel_data

    return excel_data(con)


class SnapshotUserProvider:
    """Public deployment market provider (same methods as DbMarketProvider). Values are the user's only."""

    name = "user_snapshot"

    def __init__(self, user: dict | None, cfg: dict):
        self.u = dict(user or {})
        self.target = cfg["target"]["stock_code"]
        self.as_of = cfg["meta"]["as_of"]
        sh = cfg.get("shares") or {}
        self.common_out = (sh.get("common_issued") or 0) - (sh.get("common_treasury") or 0)

    def _mc(self) -> float:
        return float(self.u["mktcap"]) if self.u.get("mktcap") else float(self.u["close"]) * self.common_out

    def quote(self, code: str, date: str, con=None):
        if date == self.as_of:
            if code == self.target and self.u.get("close"):
                return (float(self.u["close"]), self._mc(), None)  # listed shares: DART counts (not KRX)
            if code in (self.u.get("sub_close") or {}):
                return (float(self.u["sub_close"][code]), None, None)
            if code in (self.u.get("pref") or {}):
                p = self.u["pref"][code]
                return (float(p["close"]), None, int(p["listed"]))
        raise PublicDataUnavailable(f"{code}: 사용자 입력 시세 없음")

    def mktcap_at(self, code: str, date: str, con=None):
        if code == self.target and date == self.as_of and self.u.get("close"):
            return int(self._mc())
        raise PublicDataUnavailable(f"{code} {date}: 공개 배포에는 과거 시가총액이 없음")

    def vwap20(self, code: str, as_of: str, con=None) -> dict:
        if code == self.target and self.u.get("vwap20"):
            return {
                "vwap": float(self.u["vwap20"]),
                "start": None,
                "end": as_of,
                "n": None,
                "events": [],
                "source": "사용자 입력",
            }
        raise PublicDataUnavailable(f"{code}: VWAP 사용자 입력 없음")

    def mktcap_percentile(self, as_of: str, market: str, mktcap=None, con=None) -> dict:
        """P7-C3b: the target's fixed as-of percentile from the snapshot (the typed price does not move it)."""
        return public_percentile(self.target, as_of, market)

    def beta_table(self, *a, **k):
        raise PublicDataUnavailable("베타 회귀: 공개 배포에는 없음(집계 βu만)")

    def price_days(self, *a, **k):
        raise PublicDataUnavailable("시세 일수: 공개 배포에서 쓰지 않음")

    def universe(self, *a, **k):
        raise PublicDataUnavailable("상장사 목록: 공개 배포에서 쓰지 않음")


def bundle_info() -> dict:
    f = PUBLIC_DIR / "BUNDLE.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


# ---------------------------------------------------------------- snapshot store (public deployment)


def snapshot_dir():
    """app/public (the bundle) or, on the PC for tests, data/public_snapshot (scripts/build_public_snapshots)."""
    from pathlib import Path

    env = os.environ.get("KVI_SNAPSHOT_DIR")
    for d in ([Path(env)] if env else []) + [PUBLIC_DIR, ROOT / "data" / "public_snapshot"]:
        if (d / "index.json").exists():
            return d
    raise PublicDataUnavailable("공개 스냅샷이 없음")


@lru_cache(maxsize=1)
def index() -> dict:
    return {x["code"]: x for x in json.loads((snapshot_dir() / "index.json").read_text(encoding="utf-8"))}


_SNAP: dict = {}
_LOADED: set = set()


def snapshot(code: str) -> dict | None:
    """The company's public snapshot (None when the company is not in the public range). Kept in memory once loaded."""
    import gzip

    if code not in _SNAP:
        if code not in index():
            return None
        f = snapshot_dir() / "snapshots" / f"{code}.json.gz"
        _SNAP[code] = json.loads(gzip.decompress(f.read_bytes()))
    return _SNAP[code]


def snapshot_sha(code: str) -> str | None:
    x = index().get(code)
    return None if x is None else x["sha256"]


def runtime_dir():
    """Shared, read-only materialisation of the public drafts (same content for every user)."""
    import tempfile
    from pathlib import Path

    d = (
        Path(os.environ.get("KVI_RUNTIME") or Path(tempfile.gettempdir()) / "kvi_public")
        / str(bundle_info().get("snapshot_set", "pc"))[:12]
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure(code: str) -> str:
    """Load an evaluable company's snapshot into the replay store and write its draft config (absolute path)."""
    sn = snapshot(code)
    if sn is None or sn["kind"] != "evaluable":
        raise ValueError(f"{code}: 공개 범위의 평가 가능 회사가 아님(공개 범위 = 개발·검증에 쓴 회사, PC 모드에서 새 초안)")
    if code not in _LOADED:
        SD.add(sn["seams"])
        _LOADED.add(code)
    p = runtime_dir() / "drafts" / f"valuation_{code}.yaml"
    cfg = dict(sn["draft_config"])
    cfg["meta"] = {**cfg["meta"], "discount_ledger": (snapshot_dir() / "ledger_public.yaml").as_posix()}
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=200)
    # P7-X2b: rewrite when the snapshot changed (the PC folder 'pc' outlives a snapshot rebuild; it held an old draft)
    if not p.exists() or p.read_text(encoding="utf-8") != text:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    return p.as_posix()


def boot() -> None:
    """Public deployment process start: replay mode (no DB), the user's market inputs only."""
    if not SD.replaying():
        SD.set_mode("replay", {})
        from src.market.provider import _set_default

        _set_default(SnapshotUserProvider({}, {"target": {"stock_code": ""}, "meta": {"as_of": ""}, "shares": {}}))
