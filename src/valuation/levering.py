"""Hamada relevering (pure function, no data access). Kept apart from src/market/beta.py (market-data regressions)
so the public app bundle (P6-B) can ship the discount-rate engine without any market-data module.

    relever: βL = βu × (1 + (1 − t) × D/E)
"""

from __future__ import annotations


def relever(beta_u: float | None, t: float, de: float | None) -> float | None:
    """Levered beta βL = βu x (1 + (1-t) x D/E) (Hamada); None if an input is missing."""
    if beta_u is None or de is None:
        return None
    return beta_u * (1 + (1 - t) * de)
