"""Small building blocks of the work screen: cards with an error boundary, KPI rows, badges, HTML tables, the footer.

card(key, title, ...) is the screen version of 'no crash' (quality standard v2): an exception inside a card shows
'실패 + 사유 + 다시 시도' in that card only; the rest of the page renders. A test can inject a failure into one card
(st.session_state['wb_inject'] = <card key>). Streamlit's own rerun / stop signals pass through.
"""
from __future__ import annotations

import html
import traceback
from contextlib import contextmanager
from datetime import datetime

import streamlit as st
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException

from app.wb import text as tx
from app.wb.model import NeedInput, PublicDataUnavailable
from src.collect.core import ROOT

LOG = ROOT / "logs" / "wb_errors.log"


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def badge(label: str, cls: str = "") -> str:
    return f'<span class="wb-badge {cls}">{esc(label)}</span>'


def head(title: str, sub: str | None = None, right: str = "") -> None:
    st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">'
                f'<div><p class="wb-h2">{title}</p>{f"<p class=wb-sub>{sub}</p>" if sub else ""}</div>{right}</div>',
                unsafe_allow_html=True)


def page_title(eyebrow: str, title: str) -> None:
    st.markdown(f'<p class="wb-eyebrow">{eyebrow}</p><h1 class="wb-title">{esc(title)}</h1>', unsafe_allow_html=True)


def _log(key: str, e: BaseException) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat(timespec='seconds')} card={key}\n{traceback.format_exc()}\n")
    except OSError:
        pass


@contextmanager
def card(key: str, title: str | None = None, sub: str | None = None, right: str = "", plain: bool = False):
    """A white card (bordered container) with an error boundary: the body is drawn in a placeholder; if it raises, the
    partial output is cleared and the card shows the failure, its reason and '다시 시도'."""
    box = st.container(key=f"card_{key}") if not plain else st.container(key=f"plain_{key}")
    with box:
        if title:
            head(title, sub, right)
        ph = st.empty()
        try:
            with ph.container():
                yield box
            if st.session_state.get("wb_inject") == key:
                raise RuntimeError("시험용 예외 주입")
        except (RerunException, StopException):
            raise
        except NeedInput as e:
            ph.empty()
            st.markdown(f'<p class="wb-kpi-note">공개 모드: {esc(e)}. 5단계 또는 2단계 위의 <b>시세 직접 입력</b>에서 넣으면 계산합니다.</p>',
                        unsafe_allow_html=True)
        except PublicDataUnavailable as e:
            ph.empty()
            msg = str(e)
            # P7-C3: a reason that already says where it is computed is shown as it is
            st.info(msg if ("PC 모드" in msg or "공개" in msg) else f"이 기능은 PC 모드 또는 사용자 입력이 필요합니다. ({msg})")
        except Exception as e:                    # noqa: BLE001 - the card fails, the page goes on
            ph.empty()
            _log(key, e)
            st.error(f"이 카드를 표시하지 못했습니다(실패). 사유: {type(e).__name__}: {e}")
            st.button("다시 시도", key=f"retry_{key}", help="이 카드를 다시 계산합니다")


def kpis(items: list[dict]) -> None:
    """items: {label, value, unit, note, cls, band: {lo, hi, mark} in 0~100 %, badge}"""
    cells = []
    for it in items:
        band = ""
        if it.get("band"):
            b = it["band"]
            band = (f'<div class="wb-track" aria-hidden="true"><div class="band" style="left:{b["lo"]:.1f}%;width:{max(b["hi"] - b["lo"], 1):.1f}%"></div>'
                    f'<div class="mark" style="left:{b["mark"]:.1f}%"></div></div>')
        unit = f"<small>{esc(it['unit'])}</small>" if it.get("unit") else ""
        bdg = it.get("badge") or ""
        cells.append(f'<div class="wb-card"><span class="wb-kpi-label">{it["label"]}</span>'
                     f'<span class="wb-kpi-value">{esc(it["value"])}{unit} {bdg}</span>{band}'
                     f'<span class="wb-kpi-note {it.get("cls", "")}">{it.get("note", "")}</span></div>')
    st.markdown(f'<section class="wb-kpis">{"".join(cells)}</section>', unsafe_allow_html=True)


def table(header: list[str], rows: list[list], num_cols: tuple[int, ...] = (), caption: str = "", min_width: int = 0) -> None:
    """HTML table (horizontal scroll inside its own box on narrow screens). Cells are escaped unless they are tuples
    ('html', markup)."""
    def cell(v):
        if isinstance(v, tuple) and v and v[0] == "html":
            return v[1]
        return esc(v)
    th = "".join(f'<th class="{"num" if i in num_cols else ""}">{esc(h)}</th>' for i, h in enumerate(header))
    body = "".join("<tr>" + "".join(f'<td class="{"num" if i in num_cols else ""}">{cell(v)}</td>' for i, v in enumerate(r)) + "</tr>"
                   for r in rows)
    mw = f' style="min-width:{min_width}px"' if min_width else ""
    st.markdown(f'<div class="wb-table-wrap"><table class="wb-table"{mw}><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'
                + (f'<p class="wb-kpi-note">{caption}</p>' if caption else ""), unsafe_allow_html=True)


def footer(mode: str, as_of: str) -> None:
    src = tx.SOURCES_PC if mode == "pc" else tx.SOURCES_PUBLIC
    st.markdown(f'<div class="wb-foot">{esc(tx.DISCLAIMER)} {esc(src)} · 기준일 {esc(as_of)}</div>', unsafe_allow_html=True)


def pos(v: float, lo: float, hi: float) -> float:
    """Position of v on a [lo, hi] axis in % (clipped)."""
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
