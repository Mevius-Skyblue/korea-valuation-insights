"""How assumption values look in the work screen's input boxes (split out of app/wb/model.py in P7-C4): which fields
form a group, which are percentages, value <-> text, and the allowed range text from the range rules (src/workbench/spec).
"""

from __future__ import annotations

from src.workbench import spec

GROUPS = [
    ("할인율", ["rf_tenor", "mrp", "beta_u", "de", "kd", "srp"]),
    ("예측", ["g_start", "normal_margin", "g_terminal", "scenario_width"]),
    ("피어", ["peers"]),
    ("경로별", ["sotp_discount", "cash_adjust_mn", "nci_mn", "premium"]),
]
PCT_FIELDS = {"mrp", "srp", "kd", "g_start", "normal_margin", "g_terminal", "scenario_width", "sotp_discount"}


def to_text(field: str, v) -> str:
    """Value -> text in the input box (% fields in percent)."""
    if v is None:
        return ""
    if field in PCT_FIELDS:
        return f"{float(v) * 100:.2f}"
    if field in ("beta_u", "de"):
        return f"{float(v):.3f}"
    if field in ("cash_adjust_mn", "nci_mn"):
        return f"{float(v):,.0f}"
    if field == "rf_tenor":
        return str(int(v))
    return str(v)


def parse(field: str, text: str):
    """Text typed by the user -> value for set_assumption. A text that is not a number is passed through unchanged so the
    range check gives its own message (spec.check: '숫자가 아님')."""
    t = str(text).strip().replace(",", "").replace("%", "").replace("배", "")
    try:
        v = float(t)
    except ValueError:
        return text
    if field in PCT_FIELDS:
        return v / 100
    if field == "rf_tenor":
        return int(v) if v.is_integer() else v
    return v


def rng_text(field: str) -> str:
    r = spec.rules().get(field) or {}
    if field == "rf_tenor":
        return "5년 또는 10년"
    if "min" in r:
        if field in PCT_FIELDS:
            return f"{r['min'] * 100:g}% ~ {r['max'] * 100:g}%"
        return f"{r['min']:g} ~ {r['max']:g}"
    if field in ("cash_adjust_mn", "nci_mn"):
        return "0 이상(백만원)"
    return ""
