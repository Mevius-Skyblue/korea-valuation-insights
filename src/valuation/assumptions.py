"""Assumption ledger loader + corporate-tax functions (P3-A).

The ledger (config/valuation_rf.yaml) holds every value that can change, each with value / source / status / basis.
load_ledger() checks that structure so a missing source or status fails loudly instead of silently.

Tax (2026~ regime, national + local income tax combined):
    progressive_tax(base)  = sum over brackets of rate x (part of the base inside the bracket)    -> used in DCF
    marginal_rate(base)    = rate of the bracket that contains the base                         -> after-tax Kd
    effective_rate(base)   = progressive_tax / base
"""

from __future__ import annotations

from pathlib import Path

from src import yamlio
from src.collect.core import ROOT

LEDGER = ROOT / "config" / "valuation_rf.yaml"
STATUS = ("✅", "🔸", "⚠️")
# ledger sections that are assumptions (need source/status/basis); other keys are lists/definitions
REQUIRED = (
    "meta",
    "risk_free",
    "mrp",
    "srp",
    "beta",
    "capital_structure",
    "cost_of_debt",
    "corporate_tax",
    "shares",
    "net_debt",
    "nci",
    "working_capital",
)


class LedgerError(ValueError):
    pass


def load_ledger(path: Path = LEDGER) -> dict:
    """Read the ledger and check each assumption has source, status (✅/🔸/⚠️) and a one-line basis."""
    cfg = yamlio.load(Path(path).read_text(encoding="utf-8"))
    for k in REQUIRED:
        if k not in cfg:
            raise LedgerError(f"ledger section missing: {k}")
        sec = cfg[k]
        if k != "meta" and not sec.get("source"):
            raise LedgerError(f"{k}: source missing")
        if sec.get("status") not in STATUS:
            raise LedgerError(f"{k}: status must be one of {STATUS}, got {sec.get('status')!r}")
        if not sec.get("basis"):
            raise LedgerError(f"{k}: basis missing")
    for row in cfg.get("non_operating", []):
        if "include" not in row or not row.get("basis"):
            raise LedgerError(f"non_operating {row.get('item')}: include/basis missing")
    check_brackets(cfg["corporate_tax"]["brackets"])
    return cfg


def rf_code(led: dict) -> str:
    """DB rate code of the selected Rf tenor (ledger risk_free.tenor: 5 = 국고채 5년 default, 10 = 10년; P6-A)."""
    rf = led["risk_free"]
    return rf.get("tenor_codes", {5: "KTB5Y"})[int(rf.get("tenor", 5))]


def check_brackets(brackets: list[dict]) -> None:
    """Brackets must start at 0, be contiguous, and only the last may be open-ended (to = null)."""
    if not brackets or brackets[0]["from"] != 0:
        raise LedgerError("tax brackets must start at 0")
    for a, b in zip(brackets, brackets[1:]):
        if a["to"] is None or a["to"] != b["from"]:
            raise LedgerError(f"tax brackets not contiguous at {a}")
    if brackets[-1]["to"] is not None:
        raise LedgerError("last tax bracket must be open-ended")


def progressive_tax(base: float, brackets: list[dict]) -> float:
    """Tax on a taxable income `base` (원) with progressive brackets. Losses -> 0 (no carry-forward here)."""
    if base <= 0:
        return 0.0
    tax = 0.0
    for b in brackets:
        hi = b["to"] if b["to"] is not None else float("inf")
        if base > b["from"]:
            tax += (min(base, hi) - b["from"]) * b["rate"]
    return tax


def marginal_rate(base: float, brackets: list[dict]) -> float:
    """Rate of the bracket that contains `base` (a loss year uses the first bracket)."""
    for b in brackets:
        if b["to"] is None or base <= b["to"]:
            return b["rate"]
    return brackets[-1]["rate"]


def effective_rate(base: float, brackets: list[dict]) -> float:
    return progressive_tax(base, brackets) / base if base > 0 else 0.0


def discount_inputs_brackets(root: Path = ROOT, regime: str = "2026~") -> list[dict]:
    """The same table in config/discount_inputs.yaml (used by the P1 beta tables), in ledger format."""
    cfg = yamlio.load((root / "config" / "discount_inputs.yaml").read_text(encoding="utf-8"))
    reg = next(r for r in cfg["corporate_tax"]["regimes"] if r["fiscal_years"] == regime)
    return [{"from": b["taxable_income_from"], "to": b["taxable_income_to"], "rate": b["rate"]} for b in reg["brackets"]]
