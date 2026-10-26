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


def attr(x) -> str:
    """An HTML attribute value (title tooltips): escaped, line breaks as &#10;. A blank line inside st.markdown HTML ends the
    HTML block, so a raw multi-line title leaked its text and "'>" onto the screen (P7-U2F D1)."""
    return esc(x).replace("\r", "").replace("\n", "&#10;")


def badge(label: str, cls: str = "") -> str:
    return f'<span class="wb-badge {cls}">{esc(label)}</span>'


def head(title: str, sub: str | None = None, right: str = "") -> None:
    """Card title (600) with an optional grey part and a right-side note (P7-U1: one line, no paragraph)."""
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap">'
        f'<p class="wb-h2">{title}{f"<span class=wb-h2-sub>{sub}</span>" if sub else ""}</p>'
        f'<span class="wb-kpi-note">{right}</span></div>',
        unsafe_allow_html=True,
    )


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
            # P7-U2F D2: the full sentence once per run (the first card), the others say it briefly
            run = st.session_state.get("_run_no")
            msg = str(e).replace("공개 모드 시세 입력 필요: ", "")
            if st.session_state.get("_need_input_shown") != run:
                st.session_state["_need_input_shown"] = run
                st.markdown(
                    f'<p class="wb-kpi-note">시세 입력 필요({esc(msg)}) — 위 KPI <b>주가 / 시가총액</b> 칸의 <b>입력</b>에서 넣으면 계산합니다.</p>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<p class="wb-kpi-note">시세 입력 뒤 계산</p>', unsafe_allow_html=True)
        except PublicDataUnavailable as e:
            ph.empty()
            msg = str(e)
            # P7-C3: a reason that already says where it is computed is shown as it is
            st.info(msg if ("PC 모드" in msg or "공개" in msg) else f"이 기능은 PC 모드 또는 사용자 입력이 필요합니다. ({msg})")
        except Exception as e:  # noqa: BLE001 - the card fails, the page goes on
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
            band = (
                f'<div class="wb-track" aria-hidden="true"><div class="band" style="left:{b["lo"]:.1f}%;width:{max(b["hi"] - b["lo"], 1):.1f}%"></div>'
                f'<div class="mark" style="left:{b["mark"]:.1f}%"></div></div>'
            )
        unit = f"<small>{esc(it['unit'])}</small>" if it.get("unit") else ""
        bdg = it.get("badge") or ""
        cells.append(
            f'<div class="wb-card"><span class="wb-kpi-label">{it["label"]}</span>'
            f'<span class="wb-kpi-value">{esc(it["value"])}{unit} {bdg}</span>{band}'
            f'<span class="wb-kpi-note {it.get("cls", "")}">{it.get("note", "")}</span></div>'
        )
    st.markdown(f'<section class="wb-kpis">{"".join(cells)}</section>', unsafe_allow_html=True)


def table(header: list[str], rows: list[list], num_cols: tuple[int, ...] = (), caption: str = "", min_width: int = 0) -> None:
    """HTML table (horizontal scroll inside its own box on narrow screens). Cells are escaped unless they are tuples
    ('html', markup)."""

    def cell(v):
        if isinstance(v, tuple) and v and v[0] == "html":
            return v[1]
        return esc(v)

    th = "".join(f'<th class="{"num" if i in num_cols else ""}">{esc(h)}</th>' for i, h in enumerate(header))
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if i in num_cols else ""}">{cell(v)}</td>' for i, v in enumerate(r)) + "</tr>"
        for r in rows
    )
    mw = f' style="min-width:{min_width}px"' if min_width else ""
    st.markdown(
        f'<div class="wb-table-wrap"><table class="wb-table"{mw}><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'
        + (f'<p class="wb-kpi-note">{caption}</p>' if caption else ""),
        unsafe_allow_html=True,
    )


def footer(mode: str, as_of: str) -> None:
    """P7-U1: the disclaimer in one line (the full text and the sources in the tooltip)."""
    src = tx.SOURCES_PC if mode == "pc" else tx.SOURCES_PUBLIC
    line = tx.FOOT_LINE_PC if mode == "pc" else tx.FOOT_LINE_PUBLIC
    st.markdown(
        f'<div class="wb-foot"><span title="{attr(tx.DISCLAIMER + " " + src)}">{esc(line)} · 기준일 {esc(as_of)}</span>'
        f" · {tx.project_links()}</div>",  # P7-U3 U3-4a
        unsafe_allow_html=True,
    )


def pos(v: float, lo: float, hi: float) -> float:
    """Position of v on a [lo, hi] axis in % (clipped)."""
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))


# ---------------------------------------------------------------- P7-U1 building blocks (config/p7u.yaml screen)


def h2(title: str, sub: str = "", right: str = "") -> None:
    """Card title line: title (600) + grey part + right note (HTML allowed in right)."""
    head(title, sub or None, right)


def tip_span(text: str, tip: str, cls: str = "wb-term") -> str:
    return f'<span class="{cls}" title="{attr(tip)}">{esc(text)}</span>' if tip else esc(text)


def cells(items: list[dict]) -> None:
    """Grey cells (label k, value v, sub s, tooltip tip) in a 4-column grid."""
    out = []
    for x in items:
        v = x["v"] if x.get("html") else esc(x["v"])
        s = f'<span class="s">{esc(x["s"])}</span>' if x.get("s") else ""
        out.append(
            f'<div title="{attr(x.get("tip", ""))}"><span class="k">{esc(x["k"])}</span><span class="v">{v}</span>{s}</div>'
        )
    st.markdown(f'<div class="wb-cells">{"".join(out)}</div>', unsafe_allow_html=True)


def lines(rows: list[tuple]) -> None:
    """Label / value lines of a card; (label, value, True) is a total line (600, darker rule above); a 4th item = tooltip."""
    out = []
    for r in rows:
        lab, val = r[0], r[1]
        top = len(r) > 2 and r[2]
        tipx = r[3] if len(r) > 3 else ""
        out.append(f'<div class="{"top" if top else ""}"><span>{tip_span(lab, tipx)}</span><span>{esc(val)}</span></div>')
    st.markdown(f'<div class="wb-lines">{"".join(out)}</div>', unsafe_allow_html=True)


def _neg(text) -> bool:
    s = str(text)
    return (s.startswith("(") and s.endswith(")") and any(ch.isdigit() for ch in s)) or (
        s.startswith("−") and any(ch.isdigit() for ch in s)
    )


def tbl(
    head: list[str],
    rows: list,
    groups: list[tuple] | None = None,
    shade: tuple = (),
    left: tuple = (0,),
    min_width: int = 0,
    tips: bool = True,
    compact: bool = False,
) -> None:
    """A screen table (P7-U1): header rule, numbers right-aligned, negatives in parentheses shown red, first-column terms
    with a dotted underline and a definition tooltip. rows: lists of cells or {'c': cells, 'strong', 'top', 'dim',
    'hl': {i}, 'gap': {i}}; a cell may be (text, title) for its own tooltip. groups: two-level header [(label, span, shaded)]."""
    from app.wb import glossary as G

    th = ""
    if groups:
        th += (
            "<tr>"
            + "".join(
                f'<th colspan="{n}" class="{"grp" if lab else "blank"}{" sh" if sh else ""}">{esc(lab)}</th>'
                for lab, n, sh in groups
            )
            + "</tr>"
        )
    th += (
        "<tr>"
        + "".join(
            f'<th class="{"l" if i in left else ""}{" sh" if i in shade else ""}">{esc(h)}</th>' for i, h in enumerate(head)
        )
        + "</tr>"
    )
    body = []
    for r in rows:
        meta = r if isinstance(r, dict) else {"c": r}
        cls = " ".join(k for k in ("strong", "top", "dim") if meta.get(k))
        tds = []
        for i, cv in enumerate(meta["c"]):
            title = ""
            if isinstance(cv, tuple):
                cv, title = cv[0], cv[1]
            c = ["l"] if i in left else []
            if i in shade:
                c.append("sh")
            if i not in left and _neg(cv):
                c.append("neg")
            if i in (meta.get("hl") or ()):
                c.append("hl")
            if i in (meta.get("gap") or ()):
                c.append("gap")
            txt = esc(cv)
            if i == 0 and tips and not title:
                tt = G.row_tip(str(cv))
                if tt:
                    txt = f'<span class="wb-term" title="{attr(tt)}">{esc(cv)}</span>'
            ttl = f' title="{attr(title)}"' if title else ""
            tds.append(f'<td class="{" ".join(c)}"{ttl}>{txt}</td>')
        body.append(f'<tr class="{cls}">' + "".join(tds) + "</tr>")
    mw = f' style="min-width:{min_width}px"' if min_width else ""
    st.markdown(
        f'<div class="wb-tw"><table class="wb-t{" compact" if compact else ""}"{mw}><thead>{th}</thead><tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def tsv(head: list[str], rows: list) -> str:
    """Tab-separated text of a table (copy -> Excel / PowerPoint): header line + one line per row."""
    out = ["\t".join(str(h) for h in head)]
    for r in rows:
        cs = r["c"] if isinstance(r, dict) else r
        out.append("\t".join(str(c[0] if isinstance(c, tuple) else c) for c in cs))
    return "\n".join(out)


COPY_HTML = """<html><body style="margin:0;font-family:Pretendard,'Malgun Gothic',sans-serif">
<button id="b" title="표 복사 → 엑셀·PPT에 붙여넣기" aria-label="표 복사"
 style="height:30px;padding:0 8px;border:1px solid #E4E4E0;border-radius:6px;background:#FFFFFF;color:#5A5E66;font-size:13px;cursor:pointer;white-space:nowrap">복사</button>
<script>
const t = __TEXT__;
const b = document.getElementById('b');
b.onclick = async () => {
  try { await navigator.clipboard.writeText(t); }
  catch (e) { const a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select();
    document.execCommand('copy'); a.remove(); }
  b.textContent = '복사됨'; setTimeout(() => { b.textContent = '복사'; }, 1200);
};
</script></body></html>"""


def copy_btn(text: str) -> None:
    """Copy button (clipboard = tab-separated text of a table this app drew). st.iframe with the app's own HTML
    (same origin), with the textarea fallback; '</' is escaped so a cell text cannot close the script."""
    import json as _json

    payload = _json.dumps(text, ensure_ascii=False).replace("</", "<\\/")
    st.iframe(COPY_HTML.replace("__TEXT__", payload), height=32, width=56)


def title_copy(title: str, sub: str = "", note: str = "", text: str | None = None) -> None:
    """Card title line with a copy button on the right (text = tab-separated table). P7-U3 U3-3d: the row is in a keyed
    container so the stylesheet gives only ITS last column a fixed 60 px (a narrow card's 1.4/13.4 share was under the
    button's 56 px and cut it)."""
    if text is None:
        h2(title, sub, note)
        return
    n = st.session_state["_copy_n"] = st.session_state.get("_copy_n", 0) + 1
    with st.container(key=f"copyhead_{n}"):
        a, b = st.columns([12, 1.4], vertical_alignment="center")
        with a:
            h2(title, sub, note)
        with b:
            copy_btn(text)
