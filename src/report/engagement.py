"""Engagement fields of the report and the Excel cover (P7-X2b config/p7x2b.yaml display.engagement).

Purpose, premise and evaluator come from the config (report.engagement, written by the workbench at confirmation) or the
pre-registered defaults - the texts used up to P7-X2a, so a config without the fields gives the same outputs. The evaluator
line is shown only when someone typed it.
"""

from __future__ import annotations


def engagement(cfg: dict) -> dict:
    from src.valuation.associates import params

    dft = params()["engagement_defaults"]
    e = ((cfg or {}).get("report") or {}).get("engagement") or {}
    purpose = str(e.get("purpose") or "").strip()
    return {
        "report_purpose": purpose or dft["report_purpose"],
        "excel_purpose": purpose or dft["excel_purpose"],
        "premise": str(e.get("premise") or "").strip() or dft["premise"],
        "evaluator": str(e.get("evaluator") or "").strip() or None,
        "typed": bool(purpose or e.get("premise") or e.get("evaluator")),
    }
