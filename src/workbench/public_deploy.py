"""Public deployment without the DB (config/p7c3.yaml public_app): the snapshot replay, the user's market inputs and the
rules that differ from the PC.

    is_public()            this process serves the public deployment (env KVI_PUBLIC=1 or app/public/BUNDLE.json present)
    premium_withheld()     snapshot record / replay and decisions.premium_public is false -> no premium aggregates, no block
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

from src.collect.core import ROOT
from src.market.user_provider import PublicDataUnavailable
from src.workbench import snapdata as SD

PUBLIC_DIR = ROOT / "app" / "public"


def is_public() -> bool:
    return os.environ.get("KVI_PUBLIC") == "1" or (PUBLIC_DIR / "BUNDLE.json").exists()


@lru_cache(maxsize=1)
def premium_public() -> bool:
    f = ROOT / "config" / "p7c3.yaml"
    try:
        return bool(yaml.safe_load(f.read_text(encoding="utf-8"))["decisions"]["premium_public"]["value"])
    except (OSError, KeyError, TypeError):
        return False


def premium_withheld() -> bool:
    """True in the public snapshot (record and replay) unless the premium aggregates are published."""
    return SD.mode() in ("record", "replay") and not premium_public()


def _seam(name, key):
    return SD.seam(name, key)


@_seam("srp_cite", key=lambda con: "srp_cite_pick")
def srp_cite_value(con) -> float:
    from src.p5.b_reference import srp_cite_pick
    return srp_cite_pick(con)["value"]


@_seam("p5b_excel", key=lambda con: "excel_data")
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
                return (float(self.u["close"]), self._mc(), None)      # listed shares: DART counts (not KRX)
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
            return {"vwap": float(self.u["vwap20"]), "start": None, "end": as_of, "n": None, "events": [], "source": "사용자 입력"}
        raise PublicDataUnavailable(f"{code}: VWAP 사용자 입력 없음")

    def mktcap_percentile(self, *a, **k):
        raise PublicDataUnavailable("시총 백분위: 공개 배포에서 계산하지 않음(경영권 프리미엄 집계 비공개)")

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
    d = Path(os.environ.get("KVI_RUNTIME") or Path(tempfile.gettempdir()) / "kvi_public") / str(bundle_info().get("snapshot_set", "pc"))[:12]
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
    if not p.exists():
        cfg = dict(sn["draft_config"])
        cfg["meta"] = {**cfg["meta"], "discount_ledger": (snapshot_dir() / "ledger_public.yaml").as_posix()}
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
        os.replace(tmp, p)
    return p.as_posix()


def boot() -> None:
    """Public deployment process start: replay mode (no DB), the user's market inputs only."""
    if not SD.replaying():
        SD.set_mode("replay", {})
        from src.market.provider import _set_default
        _set_default(SnapshotUserProvider({}, {"target": {"stock_code": ""}, "meta": {"as_of": ""}, "shares": {}}))
