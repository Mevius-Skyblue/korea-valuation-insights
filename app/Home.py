"""Public app entry point (P6-B). Run:  streamlit run app/Home.py

Pages (app/views/): home, discount-rate assumptions in practice, opinion forecasts vs actuals, DCF calculator.
Data: app/data/ aggregates exported from DART-derived tables only (scripts/export_app_data.py).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="가치평가 툴킷 — 공개 화면(예시)", page_icon="📊", layout="wide")
V = Path(__file__).resolve().parent / "views"
nav = st.navigation([
    st.Page(str(V / "home.py"), title="홈", icon="🏠", default=True),
    st.Page(str(V / "rates.py"), title="실무 할인율 가정", icon="📐"),
    st.Page(str(V / "accuracy.py"), title="외부평가 추정 vs 실적", icon="🎯"),
    st.Page(str(V / "calculator.py"), title="DCF 계산기", icon="🧮"),
])
nav.run()
