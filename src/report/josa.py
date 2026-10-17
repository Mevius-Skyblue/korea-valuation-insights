"""Korean particles after numbers and units (받침 rule): '12,345원과', '6.8배와', '15.2%로', '3으로', '1로'.

J(text, "과") returns text + the right form of the pair it belongs to:
    과/와  은/는  이/가  을/를  으로/로(ㄹ 받침은 '로')  이다/다  이고/고(서술격)
The final sound is read from the last character: a Hangul syllable (its 받침), a digit (Korean reading: 영 일 이 삼 사
오 육 칠 팔 구), or a unit symbol (% = 퍼센트, no 받침). Latin letters use their English name (L → 엘, M → 엠, N → 엔).
"""
from __future__ import annotations

import re

PAIRS = {"과": ("과", "와"), "와": ("과", "와"), "은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"),
         "을": ("을", "를"), "를": ("을", "를"), "으로": ("으로", "로"), "로": ("으로", "로"),
         "이다": ("이다", "다"), "이고": ("이고", "고")}             # copula (서술격): 18,427원이다 / 6.80배다
# digit -> (has 받침, 받침 is ㄹ)
DIGIT = {"0": (True, False), "1": (True, True), "2": (False, False), "3": (True, False), "4": (False, False),
         "5": (False, False), "6": (True, False), "7": (True, True), "8": (True, True), "9": (False, False)}
LATIN = {"l": (True, True), "m": (True, False), "n": (True, False), "r": (False, False)}


def final_sound(text: str) -> tuple[bool, bool]:
    """(has 받침, 받침 is ㄹ) of the last pronounced character."""
    t = re.sub(r"[\s)\]』」'\"]+$", "", text)
    if not t:
        return False, False
    ch = t[-1]
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return jong != 0, jong == 8
    if ch.isdigit():
        return DIGIT[ch]
    if ch == "%":
        return False, False
    if ch.isalpha():
        return LATIN.get(ch.lower(), (False, False))
    return False, False


def J(text: str, particle: str) -> str:
    with_b, without_b = PAIRS[particle]
    has, rieul = final_sound(text)
    if with_b == "으로":
        return text + ("로" if (not has or rieul) else "으로")
    return text + (with_b if has else without_b)


# wrong combinations after a number + unit (used by the report check)
BAD = re.compile(r"\d(?:원(?:와|는|를|로(?!는)|가[다고])|배(?:과|은|을|으로|가[다고]|이[다고])|%(?:과|은|을|으로|가[다고]|이[다고]))")
