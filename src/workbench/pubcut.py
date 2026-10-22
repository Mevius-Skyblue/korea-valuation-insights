"""Public-scope n rules (P7-X2a, config/p7x2a.yaml public_scope): aggregates of few peers or few deals are not shown.

A quartile of 2~3 peers' multiples gives back each peer's multiple (linear interpolation), and a multiple times the
peer's DART figures gives back its KRX market cap. So in the public mode:

    peer multiple quartiles (per multiple)   n >= 5 included peers, else no value ('피어 부족(공개 모드)')
    βu median and R² median                  n >= 5 peers with a regression, else βu = 1.0 (P7-B5 last fallback, market
                                             average) and no R²; the target's own regression βu is not used
    own D/E average over balance-sheet dates n >= 5 dates, else D/E = 0 (judgement: type the D/E)
    premium band-table cell                  n >= 10 deals, else the count and '표본 부족' only

'Public mode' = the public deployment (replay), the snapshot build (record) and the PC public mode (the market data come
from the user: UserInputProvider / UserOverlayProvider, or a config with public_mode). The PC mode is unchanged.
Every consumer calls these functions, so the PC public mode, the snapshot and the deployment show the same values.
"""

from __future__ import annotations

import math

from src import yamlio
from src.collect.core import ROOT

FEW_PEERS = "피어 부족(공개 모드)"
FEW_DEALS = "표본 부족(공개 모드)"
BETA_SRC = "public_few_peers"
_P: dict = {}


def params() -> dict:
    if not _P:
        _P.update(yamlio.load((ROOT / "config" / "p7x2a.yaml").read_text(encoding="utf-8"))["params"]["public_scope"])
    return _P


def public_scope(cfg: dict | None = None) -> bool:
    """True in the public deployment, the snapshot build and the PC public mode."""
    from src.workbench import snapdata as SD

    if SD.mode() != "off":
        return True
    if cfg is not None and cfg.get("public_mode"):
        return True
    from src.market.provider import get
    from src.market.user_provider import UserInputProvider, UserOverlayProvider

    return isinstance(get(), (UserInputProvider, UserOverlayProvider))


def few_peers(n) -> bool:
    return 0 < int(n or 0) < params()["peer_min_n"]


def peer_stats(st: dict, public: bool, med: str = "median", empty=math.nan) -> dict:
    """Quartile stats of one multiple; in the public mode with 1~4 peers the quartiles are emptied (n kept)."""
    if not public or not few_peers(st.get("n")):
        return st
    return {**st, "q25": empty, med: empty, "q75": empty, "public_cut": True}


def beta(bu: float, src: str, n: int, public: bool) -> tuple[float, str]:
    """βu of the model: in the public mode with fewer than 5 peer regressions, the market average 1.0."""
    if public and int(n or 0) < params()["peer_min_n"]:
        return float(params()["beta_fallback"]), BETA_SRC
    return bu, src


def r2(v, n: int, public: bool):
    return None if public and int(n or 0) < params()["peer_min_n"] else v


def de_cut(n: int, public: bool) -> bool:
    return public and 0 < int(n or 0) < params()["peer_min_n"]


def premium(d: dict, public: bool) -> dict:
    """premium_range as a dict: the band-table cell's quantiles emptied when n < 10 (and the headline quantiles when the
    band table is the method)."""
    if not public:
        return d
    b = d.get("band") or {}
    if int(b.get("n") or 0) >= params()["premium_min_n"]:
        return d
    out = {**d, "band": {**b, "q25": math.nan, "q50": math.nan, "q75": math.nan}}
    if d.get("method") == "band_table":
        out.update({"q25": math.nan, "q50": math.nan, "q75": math.nan})
        out["warnings"] = list(d.get("warnings") or []) + [f"{FEW_DEALS}: 구간 표 n={b.get('n')} < {params()['premium_min_n']}"]
    return out


def shown(v):
    """An Excel input value: the number, or the 'few peers' text for an emptied aggregate."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return FEW_PEERS
    return v
