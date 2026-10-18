"""Public deployment entry (P7-C3, config/p7c3.yaml public_app). Run:  streamlit run app/Home.py

The KVI work screen in public mode only, on the public snapshots (DART · ECOS data and peer aggregates; no DB, no KRX
values): the user types the market prices. Same app and functions as the PC (app/Workbench.py), body app/wb/main.py.
Pages (address):
    /                 the work screen (?p=select|data|assume|result|export|ref_*)
    /rates, /accuracy the P6 public pages moved into the work screen's reference pages -> a notice with the new address
    /calculator       the simple DCF calculator of P6 (kept: a what-if tool without company data, same engine functions)
Community Cloud runs this file (branch main, app/Home.py); the file name is kept so its settings need no change.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="KVI 밸류에이션 워크벤치 — 공개(예시)", page_icon="📐", layout="wide", initial_sidebar_state="auto")

from src.workbench.public_deploy import boot  # noqa: E402

boot()  # snapshot replay: no DB in this process

from app.wb import main, public_ui  # noqa: E402


def workbench():
    main.run(public=True)


def rates():
    public_ui.moved("ref_rates", "실무 할인율 관행")


def accuracy():
    public_ui.moved("ref_accuracy", "추정 vs 실적")


def calculator():
    public_ui.calculator()


st.navigation(
    [
        st.Page(workbench, title="워크벤치", default=True),
        st.Page(rates, title="실무 할인율 가정(옮김)", url_path="rates"),
        st.Page(accuracy, title="추정 vs 실적(옮김)", url_path="accuracy"),
        st.Page(calculator, title="간이 DCF 계산기", url_path="calculator"),
    ],
    position="hidden",
).run()
