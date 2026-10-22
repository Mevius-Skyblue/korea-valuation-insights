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
