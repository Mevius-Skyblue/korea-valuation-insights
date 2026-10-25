"""Wording of the work screen (config/p7c2.yaml wording): plain-Korean glossary tooltips, the disclaimer, DART links and the
forbidden-expression check used on rendered screens and export texts.

    term(key)            <abbr> with a one-line explanation (first use of a technical term)
    dart_link(rcept)     DART viewer link of a filing (link only: no filing text is copied)
    quote(text)          DART text shown as a quotation (excluded from the forbidden-expression check, not from the
                         evaluator-name check)
    check(text, names, evaluators)  -> list of hits (empty = clean)
"""

from __future__ import annotations

import html
import re

DISCLAIMER = (
    "투자 권유가 아닙니다. 공개 자료와 정한 규칙으로 계산한 가정 하의 추정 내재가치(예시)이며, 특정 종목의 가치·가격에 대한 "
    "의견이 아닙니다. 자동 생성 초안이므로 평가방법 선택 근거·주요 가정의 합리성·평가상 한계는 사람이 작성합니다."
)
FOOT_LINE_PC = "가정 하의 추정 내재가치(예시) · 투자 권유 아님 · 출처 DART · ECOS · 한국거래소 통계정보"
FOOT_LINE_PUBLIC = "가정 하의 추정 내재가치(예시) · 투자 권유 아님 · 출처 DART · ECOS · 시세는 사용자 입력"
SOURCES_PC = "출처: DART 전자공시(접수번호 링크), 한국거래소 통계정보, 한국은행 ECOS"
SOURCES_PUBLIC = "출처: DART 전자공시(접수번호 링크), 한국은행 ECOS, 시세는 사용자 입력"
MODE_LABEL = {
    "pc": ("PC 모드", "한국거래소 통계정보 포함"),
    "public": ("공개 모드", "시세 직접 입력"),
    "deploy": ("공개 배포", "시세 직접 입력 · 공개 스냅샷"),
}
PUBLIC_NOTICE = (
    "가정 하의 추정 내재가치(예시)입니다. 투자 권유가 아닙니다. 출처: DART 전자공시·한국은행 ECOS·사용자가 입력한 시세. "
    "한국거래소 시세는 이 화면에 없으며, 주가·VWAP은 직접 넣습니다(넣은 값의 정확성은 입력한 사람 책임)."
)
DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

GLOSSARY = {
    "WACC": "가중평균자본비용. 자기자본비용과 세후 타인자본비용을 시가 기준 비중으로 평균한 할인율",
    "βu": "무부채 베타. Peer의 주가 베타에서 부채 효과를 뺀 값(사업 위험만)",
    "D/E": "부채 ÷ 자기자본 시가. 무부채 베타를 대상 회사 자본구조로 다시 늘릴 때 씀",
    "Kd": "세전 타인자본비용(차입 금리)",
    "MRP": "시장위험 프리미엄. 주식시장 기대수익률 − 무위험이자율",
    "SRP": "규모위험 프리미엄. 작은 회사에 더하는 추가 할인율(근거 표가 있을 때만)",
    "Rf": "무위험이자율. 국고채 금리(기본 5년, 선택 10년)",
    "영구성장률": "예측 기간 뒤 현금흐름이 매년 자라는 비율(g)",
    "영구가치 비중": "기업가치 중 예측 기간 뒤(영구) 부분이 차지하는 비중",
    "SOTP": "부분 합산법. 모회사 사업 가치 + 상장 종속회사 지분 시가 + 비상장 지분 장부를 더함",
    "비지배지분": "연결 자회사 중 다른 주주 몫. 주주가치에서 뺌",
    "VWAP": "거래량 가중 평균 주가(20거래일)",
    "Peer": "비슷한 업종·규모의 비교 회사",
    "수렴 시험": "DCF 주당 값이 Peer 배수 범위(사분위) 안에 있는지 보는 기록용 시험",
    "판단 목록": "사람이 확인·결정해야 할 항목을 주당 영향이 큰 순서로 정렬한 목록",
    "LTM": "최근 12개월 합계(직전 사업연도 + 올해 반기 − 작년 반기)",
    "CAGR": "연평균 성장률",
    "순차입금": "총차입금(리스 포함) − 현금성 자산",
    "경영권 프리미엄": "최대주주 지분 거래 가격이 공시 전 시장가보다 높은 비율(과거 거래 집계)",
    "RONIC": "새로 투자한 자본의 수익률. 체감·영구 구간 재투자율에 씀",
    "게이트": "자동 평가를 할 수 있는 회사인지 거르는 사전 규칙(9개)",
    "대조": "엑셀 수식으로 다시 계산한 값과 계산 엔진 값이 같은지 확인",
}

# forbidden expressions (config/p7c2.yaml wording.forbidden / brands / name_flags)
FORBIDDEN = [
    r"목표\s?주가",
    r"(?<![가-힣])매수(?![가-힣])",
    r"(?<![가-힣])매도(?![가-힣])",
    r"저평가",
    r"고평가",
    r"추천",
    r"투자\s?의견",
    "영국" + "공인회계사",
]  # P7-C3: built so the literal title never appears in the public code
BRANDS = ["Bloomberg", "블룸버그", "FactSet", "팩트셋", "Capital IQ", "Refinitiv", "리피니티브", "Morningstar", "모닝스타"]
QUOTE_RE = re.compile(r'<span class="wb-quote"[^>]*>.*?</span>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def term(key: str, label: str | None = None) -> str:
    tip = GLOSSARY.get(key, "")
    return (
        f'<abbr class="wb-term" title="{html.escape(tip)}">{html.escape(label or key)}</abbr>'
        if tip
        else html.escape(label or key)
    )


def dart_link(rcept: str, label: str | None = None) -> str:
    return f'<a href="{DART_VIEW}{rcept}" target="_blank" rel="noopener">{html.escape(label or rcept)}</a>'


def quote(text: str, n: int = 160) -> str:
    t = str(text or "")
    if len(t) > n:
        t = t[:n] + "…"
    return f'<span class="wb-quote">{html.escape(t)}</span>'


def plain(markup: str, keep_quotes: bool = True) -> str:
    """Visible text of a markdown/HTML string (quotations removed unless keep_quotes)."""
    s = markup if keep_quotes else QUOTE_RE.sub(" ", markup)
    return html.unescape(TAG_RE.sub(" ", s))


def check(text: str, names: list[str] = (), evaluators: list[str] = (), quotes_removed: bool = False) -> list[dict]:
    """Forbidden expressions, brand names, '누락·위반' next to a company name, evaluator names (all of them, quotations too).
    `text` may contain HTML; quotations (span.wb-quote) are dropped for the wording checks unless already removed."""
    hits = []
    full = plain(text, keep_quotes=True)
    own = full if quotes_removed else plain(text, keep_quotes=False)
    for pat in FORBIDDEN:
        for m in re.finditer(pat, own):
            hits.append({"kind": "forbidden", "term": m.group(0), "context": own[max(0, m.start() - 25) : m.end() + 25]})
    for b in BRANDS:
        if b.lower() in own.lower():
            i = own.lower().index(b.lower())
            hits.append({"kind": "brand", "term": b, "context": own[max(0, i - 25) : i + len(b) + 25]})
    for nm in [n for n in names if n and len(n) >= 2]:
        for m in re.finditer(re.escape(nm) + r".{0,20}?(누락|위반)", own):
            hits.append({"kind": "name_flag", "term": m.group(0), "context": m.group(0)})
    for ev in [e for e in evaluators if e and len(e) >= 2]:
        if ev in full:
            i = full.index(ev)
            hits.append({"kind": "evaluator", "term": ev, "context": full[max(0, i - 25) : i + len(ev) + 25]})
    return hits


MARKET_AMOUNT = re.compile(r"(시가총액|시가|종가|시장가)(\s*(?:합계|기준)?\s*)(-?[\d,]+(?:\.\d+)?)\s*(조원|억원|억|백만원|원)")


def public_mask(s: str) -> str:
    """Public mode: amounts that come from market prices in auto-draft texts ('우선주 시가 12억', '종가 12,345원') are not
    shown (the user's inputs are shown elsewhere)."""
    return MARKET_AMOUNT.sub(lambda m: f"{m.group(1)}{m.group(2)}(공개 모드 비표시)", str(s or ""))


def mrp_source_label(s: str) -> str:
    """Practice source classes on screen: brand names of data terminals -> a generic label."""
    return {"Bloomberg": "정보 단말 과거 평균"}.get(s, s)


# ---------------------------------------------------------------- P7-C3 polish plain_words: no internal codes on screen
PLAIN = [
    (re.compile(r"\(?config/[\w/.\-]+\.yaml(?:\s+[\w.\-]+)*\)?"), "(자동 진단 규칙)"),
    (re.compile(r"기본 경로 v1\s*\(대안\)"), "3년 평균 방식(이전 기본값)"),
    (re.compile(r"기본 경로 v1"), "3년 평균 방식(이전 기본값)"),
    (re.compile(r"\bv1:\s*"), "3년 평균 방식: "),
    (re.compile(r"\bv1\b"), "3년 평균 방식"),
    (re.compile(r"mechanical_v2|\bv2\b"), "기본 방식"),
    (re.compile(r"D6\s*적용\s*규칙|D6\s*규칙|\(D6\)|\bD6\b"), "비슷한 거래 이웃 방식 규칙"),
    (re.compile(r"\bN/M\b"), "계산 불가(대상 지표 ≤ 0)"),
    (re.compile(r"피어"), "Peer"),  # P7-U1 glossary: 'Peer' only on screen
    (re.compile(r"하위 25%"), "1사분위 이하"),
    (re.compile(r"상위 25%"), "3사분위 이상"),
    (re.compile(r"\bq25\b"), "1사분위"),
    (re.compile(r"\bq75\b"), "3사분위"),
    (re.compile(r"\b[A-Z]\d?[a-z]?-F\d+\b"), "(수정 규칙)"),
    (re.compile(r"\bP\d-[A-Z]\d?[a-z]?\b"), "(개발 단계)"),
    (re.compile(r"\bG\d+[a-z]?_[a-z_]+\b"), "(게이트 규칙)"),
    (
        re.compile(r"\b(ranking|review_ranked|peer_relax|short_history|basis_fill|exception_policy|mistag\.text_rule)\b"),
        "자동 진단",
    ),
]
CODE_RE = re.compile(
    r"config/[\w/.\-]+\.yaml|\bD6\b|\bN/M\b|(?:경로|방식)\s*v[12]\b|\bv[12]\s*(?:경로|방식)|mechanical"
    r"|\b[A-Z]\d?[a-z]?-F\d+\b|\bP\d-[A-Z]\d?[a-z]?\b"
    r"|\bG\d+[a-z]?_[a-z_]+\b|\bpremium_range\b|\breview_ranked\b"
)


def plain_words(s):
    """Internal codes in auto-draft texts -> plain words (config/p7c3.yaml polish.plain_words)."""
    if not isinstance(s, str):
        return s
    for pat, rep in PLAIN:
        s = pat.sub(rep, s)
    return s


def codes_in(text: str) -> list[str]:
    """Internal code strings left in a rendered screen text (test: empty)."""
    return sorted(set(m.group(0) for m in CODE_RE.finditer(text or "")))


def plain_label(s: str) -> str:
    """A label of the P5-B aggregates without the project's stage code ('이 프로젝트(P5-B)' -> '이 프로젝트')."""
    return re.sub(r"\s*\(P\d-[A-Z]\d?[a-z]?\)", "", str(s))
