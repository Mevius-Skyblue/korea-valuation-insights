"""Assumptions a person may change in a session (config/p7c1.yaml assumptions) and their range checks.

Two kinds:
    config-native   values the draft config / discount ledger already holds (the Excel model already has input cells):
                    rf_tenor, mrp, srp, g_terminal, scenario_width, peers, sotp_discount, premium
    hook            values the engine and the Excel model take from `cfg['overrides']` (Inputs '사람 확정값' cells):
                    normal_margin, g_start, beta_u, de, kd, cash_adjust_mn, nci_mn
"""

from __future__ import annotations

import math

from src import yamlio
from src.collect.core import ROOT

NATIVE = ("rf_tenor", "mrp", "srp", "g_terminal", "scenario_width", "peers", "sotp_discount", "premium")
HOOK = ("normal_margin", "g_start", "beta_u", "de", "kd", "cash_adjust_mn", "nci_mn")
LABEL = {
    "rf_tenor": "Rf 만기(년)",
    "mrp": "MRP",
    "srp": "SRP",
    "g_terminal": "영구성장률",
    "scenario_width": "시나리오 폭(±)",
    "peers": "피어 목록",
    "sotp_discount": "상장 지분 할인",
    "premium": "블록 프리미엄 입력",
    "normal_margin": "정상 영업이익률(출발)",
    "g_start": "출발 성장률",
    "beta_u": "βu",
    "de": "목표 D/E",
    "kd": "세전 Kd",
    "cash_adjust_mn": "영업용 현금(현금성에서 뺌, 백만원)",
    "nci_mn": "비지배지분(백만원)",
}
KIND = {
    "rf_tenor": "int",
    "mrp": "pct",
    "srp": "pct",
    "g_terminal": "pct",
    "scenario_width": "pct",
    "sotp_discount": "pct",
    "normal_margin": "pct",
    "g_start": "pct",
    "beta_u": "beta",
    "de": "ratio",
    "kd": "pct",
    "cash_adjust_mn": "mn",
    "nci_mn": "mn",
}


def rules() -> dict:
    return yamlio.load((ROOT / "config" / "p7c1.yaml").read_text(encoding="utf-8"))["assumptions"]


def fmt(field: str, v) -> str:
    """Display text of a value (Judgements sheet, report table, screen)."""
    if v is None:
        return ""
    if field == "peers":
        return ", ".join(v) if v else "(없음)"
    if field == "premium":
        return ", ".join(f"{k}={x}" for k, x in v.items())
    k = KIND.get(field, "gen")
    if k == "pct":
        return f"{float(v) * 100:.2f}%"
    if k == "beta":
        return f"{float(v):.3f}"
    if k == "ratio":
        return f"{float(v):.3f}배"
    if k == "mn":
        return f"{float(v):,.0f}백만원"
    if k == "int":
        return f"{int(v)}"
    return str(v)


def check(field: str, value, allowed_peers: list[str] | None = None) -> tuple[bool, str, object]:
    """(ok, reason, normalized value). Out-of-range or malformed values are rejected with the reason."""
    r = rules()
    if field not in NATIVE + HOOK:
        return False, f"알 수 없는 가정 '{field}'", None
    if field == "peers":
        if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) for x in value):
            return False, "피어 목록은 이름 목록이어야 한다", None
        bad = [x for x in value if allowed_peers is not None and x not in allowed_peers]
        if bad:
            return False, f"자동 초안 피어가 아님(새 피어 추가는 재수집 필요): {', '.join(bad)}", None
        return True, "", list(dict.fromkeys(value))
    if field == "premium":
        # P7-C2 fix C2-F1 (config/p7c2.yaml fixes): the allowed values are those predict.premium_range accepts
        # (p7c1 listed buyer_group 'all', which premium_range rejects -> the block card failed)
        from src.premium.predict import BUYER_GROUPS, PERIODS, STAKE_BANDS

        if not isinstance(value, dict):
            return False, "블록 프리미엄 입력은 {stake_band, buyer_group, period} 형식", None
        out = {}
        for k, v in value.items():
            if k == "stake_band" and v not in STAKE_BANDS:
                return False, f"지분 구간은 {list(STAKE_BANDS)} 중 하나", None
            if k == "buyer_group" and v not in BUYER_GROUPS:
                return False, f"인수자 유형은 {list(BUYER_GROUPS)} 중 하나", None
            if k == "period" and v not in PERIODS:
                return False, f"표본 기간은 {list(PERIODS)} 중 하나", None
            if k not in ("stake_band", "buyer_group", "period"):
                return False, f"알 수 없는 프리미엄 칸 '{k}'", None
            out[k] = v
        return True, "", out
    if field == "rf_tenor":
        try:
            v = int(value)
        except (TypeError, ValueError):
            return False, "Rf 만기는 정수(년)", None
        if v not in r["rf_tenor"]["allowed"]:
            return False, f"Rf 만기는 {r['rf_tenor']['allowed']} 중 하나", None
        return True, "", v
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"{LABEL[field]}: 숫자가 아님", None
    if not math.isfinite(v):
        return False, f"{LABEL[field]}: 유한한 숫자가 아님", None
    if field in ("cash_adjust_mn", "nci_mn"):
        if v < 0:
            return False, f"{LABEL[field]}: 0 이상이어야 한다", None
        return True, "", v
    s = r[field]
    if v < s["min"] or v > s["max"]:
        return False, f"{LABEL[field]}: 허용 범위 {s['min']}~{s['max']} 밖({v})", None
    return True, "", v
