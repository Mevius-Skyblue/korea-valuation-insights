"""Valuation structure rule (P3-B, general): sum-of-the-parts (SOTP) or consolidated DCF − NCI.

Inputs (one company)
    nci_value          NCI to deduct (market value if the subsidiary is listed, else book)
    equity_value       the company's equity value (market cap at the valuation date)
    listed_subsidiary  True if a material consolidated subsidiary is listed (has a market price)
    segments           list of {name, margin (%), growth (%)} for the reportable segments
Rule (thresholds in config/valuation_rules.yaml, project assumptions)
    SOTP on if  NCI / equity >= nci_share_min
            or  listed subsidiary and (segment margin gap >= listed_sub_margin_gap_pp
                                       or segment growth gap >= listed_sub_growth_gap_pp)
    otherwise consolidated DCF − NCI.
decide() returns the decision and the reasons (each test with its value and threshold).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src import yamlio
from src.collect.core import ROOT

RULES = ROOT / "config" / "valuation_rules.yaml"


@dataclass
class StructureDecision:
    method: str  # sotp / consolidated
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)


def load_rules(path: Path = RULES) -> dict:
    return yamlio.load(Path(path).read_text(encoding="utf-8"))["structure"]


def decide(
    nci_value: float, equity_value: float, listed_subsidiary: bool, segments: list[dict], rules: dict | None = None
) -> StructureDecision:
    r = rules or load_rules()
    share = nci_value / equity_value if equity_value else 0.0
    margins = [s["margin"] for s in segments if s.get("margin") is not None]
    growths = [s["growth"] for s in segments if s.get("growth") is not None]
    mgap = max(margins) - min(margins) if len(margins) > 1 else 0.0
    ggap = max(growths) - min(growths) if len(growths) > 1 else 0.0
    checks = {
        "nci_share": (share, r["nci_share_min"], share >= r["nci_share_min"]),
        "listed_subsidiary": (listed_subsidiary, True, bool(listed_subsidiary)),
        "margin_gap_pp": (mgap, r["listed_sub_margin_gap_pp"], mgap >= r["listed_sub_margin_gap_pp"]),
        "growth_gap_pp": (ggap, r["listed_sub_growth_gap_pp"], ggap >= r["listed_sub_growth_gap_pp"]),
    }
    reasons = []
    if checks["nci_share"][2]:
        reasons.append(f"비지배지분/주식가치 {share:.1%} ≥ {r['nci_share_min']:.0%}")
    if listed_subsidiary and checks["margin_gap_pp"][2]:
        reasons.append(f"상장 종속회사 + 부문 영업이익률 차이 {mgap:.1f}%p ≥ {r['listed_sub_margin_gap_pp']}%p")
    if listed_subsidiary and checks["growth_gap_pp"][2]:
        reasons.append(f"상장 종속회사 + 부문 매출 성장률 차이 {ggap:.1f}%p ≥ {r['listed_sub_growth_gap_pp']}%p")
    if reasons:
        return StructureDecision("sotp", reasons, checks)
    return StructureDecision(
        "consolidated", [f"비지배지분/주식가치 {share:.1%} < {r['nci_share_min']:.0%}, 상장 종속회사 조건 해당 없음"], checks
    )
