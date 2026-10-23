"""Shared helpers of the automatic draft (split out of draft.py in P7-C4): the pre-registered rule files of P7-B / B3b / B5
and two text helpers (company-name normalisation, number text -> float).
"""

from __future__ import annotations

from src import yamlio
from src.collect.core import ROOT

P7B = ROOT / "config" / "p7b.yaml"


def load_rules() -> dict:
    return yamlio.load(P7B.read_text(encoding="utf-8"))


def load_rules_3b() -> dict:
    return yamlio.load((ROOT / "config" / "p7b3b.yaml").read_text(encoding="utf-8"))


def norm(s: str) -> str:
    from src.valuation.candidates import norm as _n

    return _n(s)


def _f(x) -> float | None:
    s = str(x).replace(",", "").strip() if x is not None else ""
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_rules_5() -> dict:
    return yamlio.load((ROOT / "config" / "p7b5.yaml").read_text(encoding="utf-8"))


def p7e_params() -> dict:
    """P7-E rule numbers (config/p7e.yaml params). Audit switch (not for normal runs): environment variable KVI_P7E_OFF =
    comma list of rules turned off for the attribution of changed results (k5, k6, k11) - scripts/audit/inv_p7e.py."""
    import os

    p = yamlio.load((ROOT / "config" / "p7e.yaml").read_text(encoding="utf-8"))["params"]
    off = {x.strip() for x in os.environ.get("KVI_P7E_OFF", "").split(",") if x.strip()}
    return {**p, "off": sorted(off)} if off else p


def p7e_off(rule: str) -> bool:
    """True when an audit run turned the P7-E rule off (KVI_P7E_OFF)."""
    return rule in (p7e_params().get("off") or [])
