"""Sum-of-the-parts equity value and the consolidated cross-check (P3-B, general).

SOTP (parent's own view, separate financial statements)
    equity = Σ operating segments valued by DCF (parent business EV)
           + Σ listed subsidiaries: stake x market cap at the valuation date (shares actually listed)
           + parent net cash (separate BS: cash + short-term financial assets − debt incl. lease)
           + parent non-operating assets (separate BS) EXCLUDING the investment in subsidiaries (book) - the
             subsidiary is already counted at market value (no double count)
           − head-office costs not inside any segment (PV of unallocated corporate costs; 0 if the segment note
             has no unallocated line)
Cross-check (consolidated)
    equity = consolidated EV (DCF of all segments) − consolidated net debt + consolidated non-operating
             − NCI at market value
reconcile() splits the difference. With NCI deducted at market, the consolidated route holds 100% of the subsidiary
at its DCF value and removes (1 − stake) at market, so
    SOTP − consolidated = (subsidiary market cap − subsidiary intrinsic equity)        [100%, not x stake]
                          + other (consolidation eliminations, separate vs consolidated BS detail)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SotpResult:
    equity: float
    parts: dict = field(default_factory=dict)


def sotp_equity(segment_ev: dict[str, float], listed_stakes: dict[str, tuple[float, float]], parent_net_cash: float,
                parent_non_operating: float, investment_in_subs_book: float = 0.0,
                unallocated_hq_pv: float = 0.0) -> SotpResult:
    """listed_stakes: name -> (stake 0..1, market cap). parent_non_operating may include the subsidiary investment;
    it is removed here so the subsidiary is counted once (at market)."""
    parts = {f"EV {k}": v for k, v in segment_ev.items()}
    for k, (stake, mc) in listed_stakes.items():
        parts[f"지분 {k} ({stake:.2%} × 시가)"] = stake * mc
    parts["모회사 순현금"] = parent_net_cash
    parts["모회사 비영업자산(종속회사 투자 제외)"] = parent_non_operating - investment_in_subs_book
    parts["본사 미배분 공통비(PV, 차감)"] = -unallocated_hq_pv
    return SotpResult(sum(parts.values()), parts)


def consolidated_equity(ev_consolidated: float, net_debt: float, non_operating: float, nci: float) -> float:
    return ev_consolidated - net_debt + non_operating - nci


def reconcile(sotp: SotpResult, cons_equity: float, stake: float, sub_market_cap: float,
              sub_intrinsic_equity: float) -> dict:
    """Difference SOTP − consolidated (NCI at market), split into the subsidiary gap (market cap − intrinsic equity,
    whole company: stake x gap from the SOTP side + (1 − stake) x gap from the NCI side) and the remainder."""
    total = sotp.equity - cons_equity
    sub_gap = sub_market_cap - sub_intrinsic_equity
    return {"difference": total, "subsidiary_market_vs_intrinsic": sub_gap, "other": total - sub_gap}
