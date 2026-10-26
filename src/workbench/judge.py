"""The ranked judgement list as work items (config/p7c1.yaml judgements).

Every item of the auto draft's list (review_ranked.computed in rank order, then the uncomputed ones) becomes a work item
with candidate values (alternatives the diagnostics already compute) and the assumption fields a person may type.
Status: 미처리 -> 채택 (candidate) / 수정 (direct input) / 그대로 유지 (keep the auto value). Candidates and direct inputs
go through session.set_assumption (range check, new version, audit); 'keep' is an audit entry without a new version.
"""

from __future__ import annotations

from src.workbench import spec

# category -> assumption fields a person may type for it (direct input)
DIRECT = {
    "비경상 손익": ["normal_margin"],
    "정상화(비경상 손익)": ["normal_margin"],
    "실적 전환": ["normal_margin"],
    "기본 경로": ["normal_margin", "g_start"],
    "이력 짧음": ["normal_margin", "g_start"],
    "Kd 근거": ["kd"],
    "할인율": ["srp", "rf_tenor", "mrp"],
    "영구성장률": ["g_terminal"],
    "시나리오 폭": ["scenario_width"],
    "피어 유사성": ["peers"],
    "피어 직접 지정": ["peers", "beta_u"],
    "SOTP": ["sotp_discount"],
    "SOTP 가드": ["sotp_discount"],
    "비영업·현금성 분류": ["cash_adjust_mn"],
    "비영업·현금성 분류(추가)": ["cash_adjust_mn"],
    "비지배지분": ["nci_mn"],
    "블록 프리미엄 입력": ["premium"],
    "적자 경로": ["normal_margin", "g_start"],
    "적자 경로 자금": ["normal_margin"],
    "재무 기준 혼합": [],
    "D&A 추정": [],
    "계정 오표기": [],
    "주식 수": [],
    "우선주 처리": [],
    "기준일 뒤 주요 공시": [],
    "보고서 사람 작성 칸": [],
    "구조(추가)": [],
    "상장 종속회사 확인": [],  # P7-X2a holding guard a: a person checks the structure (no single field fixes it)
    "비지배지분 확인": ["nci_mn"],  # P7-X2a holding guard b
    "SOTP 보유 수량 확인": ["sotp_discount"],  # P7-X2a X2a-F1
    "상장 관계기업 보유 수량 확인": ["assoc_discount"],  # P7-X2b
    # P7-X2b (config/p7x2b.yaml judgements): the large assumptions ranked by impact
    "목표 D/E": ["de"],
    "재투자 비율": ["dna_ratio", "capex_ratio", "nwc_days", "fade_reinvest"],
    "희석증권": [],  # P7-U1F D-3: a check item (no field changes the value)
    "이익률 수렴": ["conv_share", "conv_end"],
    "상장 관계기업": ["assoc_discount"],
    "RONIC": ["ronic"],
}


def candidates(x: dict, summ: dict, ctx) -> list[dict]:
    """Candidate values of one item from the draft's diagnostics (labels say what each is). P7-E K11 (config/p7e.yaml
    k11_candidates): only values the screen accepts (spec.check, the same ranges as a direct input)."""
    from src.pipeline.diagnose import in_range

    out = _candidates(x, summ, ctx)
    return [
        cd
        for cd in out
        if (cd["field"] == "peers" and spec.check("peers", cd["value"], ctx.peers_all())[0])
        or (cd["field"] != "peers" and in_range(cd["field"], cd["value"]))
    ]


def _candidates(x: dict, summ: dict, ctx) -> list[dict]:
    cat, item = x.get("category"), str(x.get("item") or "")
    dg = summ.get("diagnostics") or {}
    out = []
    if x.get("cands"):  # P7-X2b: the diagnostics computed this item's alternatives (value and label) with its impact
        return [{"label": cd["label"], "field": cd["field"], "value": cd["value"]} for cd in x["cands"]]
    if cat in ("비경상 손익", "정상화(비경상 손익)"):
        for cd in dg.get("margin_candidates") or []:
            if cd.get("margin") is not None:
                out.append({"label": f"정상 이익률 후보: {cd['label']}", "field": "normal_margin", "value": cd["margin"]})
    elif cat == "실적 전환" and (dg.get("turnaround") or {}).get("ltm_margin") is not None:
        out.append({"label": "LTM 영업이익률에서 출발", "field": "normal_margin", "value": dg["turnaround"]["ltm_margin"]})
    elif cat == "기본 경로":
        out.append({"label": "v1: 3년 평균 이익률", "field": "normal_margin", "value": ctx.h["margin"]})
        out.append({"label": "v1: 매출 CAGR 출발 성장률", "field": "g_start", "value": ctx.h["cagr"]})
    elif cat == "Kd 근거":
        out.append({"label": "AA- 3년 회사채 금리", "field": "kd", "value": ctx.c.rates["CB3Y_AAm"]})
        out.append({"label": "BBB- 3년 회사채 금리", "field": "kd", "value": ctx.c.rates["CB3Y_BBBm"]})
    elif cat == "할인율" and "SRP" in item:
        out += [{"label": "SRP 1%", "field": "srp", "value": 0.01}, {"label": "SRP 2%", "field": "srp", "value": 0.02}]
    elif cat == "할인율" and "Rf" in item:
        out.append({"label": "Rf 국고채 10년", "field": "rf_tenor", "value": 10})
    elif cat == "영구성장률":
        out += [{"label": "g 1%", "field": "g_terminal", "value": 0.01}, {"label": "g 3%", "field": "g_terminal", "value": 0.03}]
    elif cat == "시나리오 폭":
        out += [
            {"label": "±1%p", "field": "scenario_width", "value": 0.01},
            {"label": "±3%p", "field": "scenario_width", "value": 0.03},
        ]
    elif cat == "피어 유사성" and item in ctx.peers_all():
        out.append({"label": f"{item} 빼기", "field": "peers", "value": [p for p in ctx.peers_all() if p != item]})
    elif cat == "SOTP":
        out += [
            {"label": "상장 지분 할인 30%", "field": "sotp_discount", "value": 0.30},
            {"label": "상장 지분 할인 50%", "field": "sotp_discount", "value": 0.50},
        ]
    elif cat.startswith("비영업·현금성 분류"):
        cf = (dg.get("sensitivities") or {}).get("customer_funds") or {}
        if cf.get("operating_cash"):
            out.append(
                {"label": "고객 자금 성격 현금을 현금성에서 뺌", "field": "cash_adjust_mn", "value": float(cf["operating_cash"])}
            )
    elif cat == "비지배지분":
        n = (dg.get("sensitivities") or {}).get("nci") or {}
        eq = (dg.get("composition") or {}).get("equity")
        if n.get("book") and n.get("total_equity") and eq is not None:
            out.append(
                {
                    "label": "비례법(연결 주식가치 × 비지배 장부 비중)",
                    "field": "nci_mn",
                    "value": (eq + n["book"]) * n["book"] / n["total_equity"],
                }
            )
        if n.get("book") and n.get("peer_pbr"):
            out.append(
                {"label": f"비지배 장부 × 피어 P/B {n['peer_pbr']:.2f}배", "field": "nci_mn", "value": n["book"] * n["peer_pbr"]}
            )
    return out


def items(summ: dict, cfg_path: str) -> dict:
    """{item_id: work item} from the draft summary, in the ranked order (computed items first)."""
    from src.workbench import recalc

    ctx = recalc.context(cfg_path)
    rk = summ.get("review_ranked") or {}
    out = {}
    for i, x in enumerate((rk.get("computed") or []) + (rk.get("other") or []), start=1):
        out[f"j{i:02d}"] = {
            "id": f"j{i:02d}",
            "rank": x.get("rank"),
            "category": x.get("category"),
            "item": x.get("item"),
            "detail": x.get("detail"),
            "alternative": x.get("alternative"),
            "impact": x.get("impact"),
            "candidates": candidates(x, summ, ctx),
            "direct_fields": DIRECT.get(x.get("category"), []),
            "status": "미처리",
            "resolution": None,
        }
    return out


def resolve(
    s: dict,
    item_id: str,
    action: str,
    candidate: int | None = None,
    field: str | None = None,
    value=None,
    reason: str | None = None,
) -> dict:
    """action 'candidate' (index), 'direct' (field, value), 'keep' or 'note' (P7-U1F: an audit note, the item stays open).
    Returns {'ok', 'reason', 'session', 'result'}."""
    from src.workbench import session as S

    j = s["judgements"][item_id]
    if action == "note":  # P7-U1F D-3 '원문 확인 후 판단': the note is recorded, the status does not change
        j["note"] = {"reason": reason or "", "at": S._now(), "v": S.current(s)["v"]}
        s["audit"].append(
            {
                "at": S._now(),
                "v": S.current(s)["v"],
                "field": None,
                "label": "판단 메모(원문 확인 후 판단)",
                "before": None,
                "after": None,
                "before_text": "",
                "after_text": "",
                "reason": reason or "",
                "judgement": item_id,
            }
        )
        S.save(s)
        return {"ok": True, "reason": "", "session": s, "result": S.current(s)["result"]}
    if action == "keep":
        j.update(
            {
                "status": "그대로 유지",
                "resolution": {"action": "keep", "reason": reason or "", "at": S._now(), "v": S.current(s)["v"]},
            }
        )
        s["audit"].append(
            {
                "at": S._now(),
                "v": S.current(s)["v"],
                "field": None,
                "label": "판단(그대로 유지)",
                "before": None,
                "after": None,
                "before_text": "",
                "after_text": "",
                "reason": reason or "",
                "judgement": item_id,
            }
        )
        S.save(s)
        return {"ok": True, "reason": "", "session": s, "result": S.current(s)["result"]}
    if action == "candidate":
        try:
            cd = j["candidates"][int(candidate)]
        except (TypeError, ValueError, IndexError):
            return {"ok": False, "reason": "후보 번호가 없다", "session": s, "result": None}
        f, v, status = cd["field"], cd["value"], "채택"
        why = reason or cd["label"]
    elif action == "direct":
        if field not in j["direct_fields"] and field not in spec.NATIVE + spec.HOOK:
            return {"ok": False, "reason": f"이 항목에서 고칠 수 있는 가정이 아님: {field}", "session": s, "result": None}
        f, v, status, why = field, value, "수정", reason
    else:
        return {"ok": False, "reason": f"알 수 없는 처리 '{action}'", "session": s, "result": None}
    r = S.set_assumption(s, f, v, why, judgement=item_id)
    if r["ok"]:
        j.update(
            {
                "status": status,
                "resolution": {
                    "action": action,
                    "field": f,
                    "value": v,
                    "reason": why or "",
                    "at": S._now(),
                    "v": S.current(s)["v"],
                },
            }
        )
        S.save(s)
    return r
