"""Engagement fields of the report and the Excel cover (P7-X2b config/p7x2b.yaml display.engagement).

Purpose, premise and evaluator come from the config (report.engagement, written by the workbench at confirmation) or the
pre-registered defaults - the texts used up to P7-X2a, so a config without the fields gives the same outputs. The evaluator
line is shown only when someone typed it.
"""

from __future__ import annotations

EXAMPLE_PRICE_LABEL = "예시 입력 시세(실제 종가 아님) — 결과는 가정 하의 추정 내재가치 예시"  # config/p7d.yaml example_prices


def example_label(cfg: dict) -> str | None:
    """P7-D: the label of the Excel cover and the report's first page when the public-mode prices are the screen's round
    example values (public_mode.user.example), else None."""
    return EXAMPLE_PRICE_LABEL if (((cfg or {}).get("public_mode") or {}).get("user") or {}).get("example") else None


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
