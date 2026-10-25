"""Glossary of the work screen (P7-U1, config/p7u.yaml glossary): the one source of the screen labels, the term tooltips
and the wording checks.

    label(term)        screen label: 'Korean (abbr)' for paired terms, the term itself otherwise
    short(term)        the abbreviation alone (narrow cells, formulas, sub lines) - the tooltip carries the Korean term
    tip(term)          one-line definition (tooltip)
    row_tip(text)      tooltip of a table's first-column label (dotted underline), '' when the label has none
    violations(text)   screen-wording hits: forbidden spellings ('피어', 'Q1', '하위 25%', '회전율') and internal codes
                       (BU20, G1~G8, path names v1/v2, mechanical, session ids, stage codes) -> list of {kind, term, context}
    write_doc()        docs/glossary.md from the same table (python -m app.wb.glossary)
"""

from __future__ import annotations

import re
from functools import lru_cache

from src import yamlio
from src.collect.core import ROOT

# first-column labels of the screen tables that are not glossary terms themselves (formula tooltips)
ROW_TIPS = {
    "매출": "손익계산서 매출액(영업수익)",
    "매출 성장률": "전년 대비 매출 증가율",
    "EBITDA": "영업이익 + 감가상각비 (D&A)",
    "EBIT": "영업이익",
    "(−) 법인세": "EBIT에 대한 법인세(누진 세율표)",
    "(+) 감가상각비 (D&A)": "유형자산 감가상각비 + 무형자산상각비",
    "(−) 자본적지출 (CAPEX)": "유형·무형자산 취득",
    "(−) 순운전자본 증가": "ΔNWC = (매출채권 + 재고자산 − 매입채무)의 증가 = 현금 유출",
    "(−) 재투자": "수렴 구간 성장에 필요한 투자 = NOPAT × g ÷ RONIC",
    "FCFF": "NOPAT + D&A − CAPEX − 순운전자본 증가(수렴 구간: NOPAT − 재투자)",
    "할인계수": "1 ÷ (1 + WACC)^t (기중 할인: t = 기간 중간)",
    "FCFF 현재가치 (PV)": "FCFF × 할인계수",
    "영업이익": "손익계산서 영업이익",
    "EBITDA 이익률": "EBITDA ÷ 매출",
    "ROE": "지배주주 순이익 ÷ 지배주주지분",
    "CAPEX ÷ 매출": "유형·무형자산 취득 ÷ 매출",
    "D&A ÷ 매출": "감가상각비 ÷ 매출",
    "순현금": "현금성자산 − 차입금(리스 포함)",
    "차입금 (리스 포함)": "총차입금 + 리스부채",
    "경영권 블록 주당가": "20일 VWAP × (1 + 경영권 프리미엄)",
    "블록 거래 주당가": "20일 VWAP × (1 + 경영권 프리미엄)",
    "DCF × (1 + CP) (참고)": "DCF 주당가치에 프리미엄을 곱한 참고값(대표값 아님)",
    "EV/EBITDA": "기업가치 ÷ EBITDA",
    "PER": "시가총액 ÷ 지배주주 순이익",
    "PBR": "시가총액 ÷ 지배주주지분",
    "EV/Sales": "기업가치 ÷ 매출",
    "내재 영구가치 배수": "영구가치 ÷ 마지막 해 EBITDA(Implied Terminal Multiple)",
}


@lru_cache(maxsize=1)
def table() -> dict:
    return yamlio.load((ROOT / "config" / "p7u.yaml").read_text(encoding="utf-8"))["glossary"]


@lru_cache(maxsize=1)
def _index() -> dict:
    g = table()
    out = {}
    for x in g["stats"]:
        out[x["term"]] = {"label": x["term"], "short": x["term"], "tip": x["def"]}
    for x in g["paired"]:
        lab = f"{x['term']} ({x['abbr']})"
        rec = {"label": lab, "short": x["abbr"], "tip": f"{x['term']} — {x['def']}"}
        out.setdefault(x["term"], rec)
        out.setdefault(x["abbr"], rec)
        out.setdefault(lab, rec)
    for x in g["korean_only"]:
        out[x["term"]] = {"label": x["term"], "short": x["term"], "tip": x["tip"]}
    for t in g["as_is"]:
        out.setdefault(t, {"label": t, "short": t, "tip": ROW_TIPS.get(t, "")})
    for t in g["english_only"]:
        out.setdefault(t, {"label": t, "short": t, "tip": "비슷한 업종·규모의 비교 회사"})
    return out


def label(term: str) -> str:
    return _index().get(term, {}).get("label", term)


def short(term: str) -> str:
    return _index().get(term, {}).get("short", term)


def tip(term: str) -> str:
    return _index().get(term, {}).get("tip", "") or ROW_TIPS.get(term, "")


def row_tip(text: str) -> str:
    t = str(text or "")
    if t in ROW_TIPS:
        return ROW_TIPS[t]
    rec = _index().get(t)
    if rec and rec.get("tip"):
        return rec["tip"]
    m = re.search(r"\(([^()]+)\)\s*$", t)  # '세후영업이익 (NOPAT)' -> NOPAT
    if m and m.group(1) in _index():
        return _index()[m.group(1)].get("tip", "")
    return ""


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern, str]]:
    g = table()
    out = [("forbidden", re.compile(x["pattern"]), x["why"]) for x in g["forbidden_on_screen"]]
    out += [("internal", re.compile(x["pattern"]), x["why"]) for x in g["internal_codes"]]
    return out


def violations(text: str) -> list[dict]:
    """Forbidden spellings and internal codes in a rendered screen text (empty = clean)."""
    hits = []
    for kind, pat, why in _patterns():
        for m in pat.finditer(text or ""):
            hits.append({"kind": kind, "term": m.group(0), "why": why, "context": text[max(0, m.start() - 20) : m.end() + 20]})
    return hits


def write_doc() -> str:
    """docs/glossary.md (definition, paired spelling, where it is used) from config/p7u.yaml."""
    g = table()
    L = [
        "# 작업 화면 용어집",
        "",
        "P7-U1 사전 고정 `config/p7u.yaml` glossary에서 만든 문서입니다(`python -m app.wb.glossary`). 화면 라벨은 이 표기만 씁니다.",
        "",
        "## 통계",
        "",
        "| 표기 | 정의 | 쓰는 곳 |",
        "|---|---|---|",
    ]
    for x in g["stats"]:
        L.append(f"| {x['term']} | {x['def']} | 상대가치·경영권 프리미엄·실무 관행 |")
    L += [
        "",
        "`Q1`·`Q3`는 분기로 읽힐 수 있어 화면에 쓰지 않습니다(1사분위·3사분위). IQR은 처음 나오는 곳에 툴팁 '1~3사분위'.",
        "",
        "## 한영 병기",
        "",
        "항목 이름·카드 제목·KPI 라벨은 '한글 (약어)', 좁은 칸·식·보조 줄은 약어만 쓰고 툴팁에 한글을 둡니다.",
        "",
        "| 화면 표기 | 약어만 | 정의 |",
        "|---|---|---|",
    ]
    for x in g["paired"]:
        L.append(f"| {x['term']} ({x['abbr']}) | {x['abbr']} | {x['def']} |")
    L += ["", "## 약어 그대로", "", ", ".join(g["as_is"]), "", "## 한글만 (약어·식은 툴팁)", "", "| 표기 | 툴팁 |", "|---|---|"]
    for x in g["korean_only"]:
        L.append(f"| {x['term']} | {x['tip']} |")
    L += [
        "",
        "'회전율'(회)과 '회전일수'(일)를 섞지 않습니다. 화면은 회전일수만.",
        "",
        "## 영어만",
        "",
        ", ".join(g["english_only"]) + " ('피어' 표기 금지)",
        "",
        "## 화면에 쓰지 않는 표기 (묶음 검사 4·화면 시험)",
        "",
        "| 패턴 | 이유 |",
        "|---|---|",
    ]
    for x in g["forbidden_on_screen"] + g["internal_codes"]:
        L.append(f"| `{x['pattern'].replace('|', chr(92) + '|')}` | {x['why']} |")
    L += ["", "## 표 첫 열 툴팁 (식)", "", "| 라벨 | 툴팁 |", "|---|---|"]
    for k, v in ROW_TIPS.items():
        L.append(f"| {k} | {v} |")
    text = "\n".join(L) + "\n"
    (ROOT / "docs" / "glossary.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    t = write_doc()
    print(f"docs/glossary.md: {len(t.splitlines())} lines")
