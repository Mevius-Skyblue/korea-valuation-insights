"""Shared helpers of the public app: data loading (app/data aggregates only), formatting, small-n styling, footer.

Every page ends with footer() -> disclaimer + data source + as-of date (public-screen rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

APP = Path(__file__).resolve().parents[1]
DATA = APP / "data"
SMALL_N = 10
DISCLAIMER = ("투자 권유가 아닙니다. 모든 수치는 공개 공시를 집계한 예시이며 특정 종목의 가치·가격에 대한 의견이 아닙니다. "
              "금융투자업(투자자문·투자일임) 등록·신고를 하지 않은 개인 학습·포트폴리오 프로젝트입니다.")
DART = "https://dart.fss.or.kr"


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / name, encoding="utf-8")


@st.cache_data
def meta() -> dict:
    return json.loads((DATA / "meta.json").read_text(encoding="utf-8"))


def pct(v, d: int = 1) -> str:
    return "" if v is None or v != v else f"{v * 100:.{d}f}%"


def grey_small(df: pd.DataFrame, n_col: str = "n"):
    """Styler: rows with n < 10 in grey (shown, but flagged)."""
    def row(r):
        return ["color: #9e9e9e; background-color: #f2f2f2" if r[n_col] < SMALL_N else "" for _ in r]
    return df.style.apply(row, axis=1)


def small_n_note(df: pd.DataFrame, n_col: str = "n") -> None:
    k = int((df[n_col] < SMALL_N).sum())
    if k:
        st.warning(f"회색 {k}칸은 표본 n < {SMALL_N}이다. 수치를 일반화하지 말 것.", icon="⚠️")


def md(s: str) -> str:
    """Escape '~' so markdown does not render '2015~2016' as strikethrough."""
    return s.replace("~", r"\~")


def footer() -> None:
    m = meta()
    st.divider()
    st.caption(f"**면책** — {DISCLAIMER}")
    st.caption(f"**출처** — DART 전자공시({DART}): {md(m['data_scope'])}. 집계 기준일 {m['as_of']}. "
               f"정의·검증: [METHODOLOGY.md]({m['methodology_url']}) · [DATA_NOTICE.md]({m['data_notice_url']})"
               f"(내부 검증 커밋 {m['internal_commit']}). "
               "개별 거래·회사·평가기관은 표시하지 않고 집계만 보여 준다. 🔸 = 단일 출처·2차 인용, ⚠️ = 원문 미확인")
