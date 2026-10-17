"""Altair charts of the work screen and the reference pages (one chart library; config/p7c2.yaml app.charts).
No price series is ever drawn (display rules)."""
from __future__ import annotations

import altair as alt
import pandas as pd

from app.wb.style import FONT_WORK, T


def _cfg(ch: alt.Chart) -> alt.Chart:
    return (ch.configure(font=FONT_WORK.split(",")[0].strip("'"), background="transparent")
            .configure_axis(labelColor=T["text_sub"], titleColor=T["text_sub"], gridColor=T["line_soft"], domainColor=T["line"],
                            labelFontSize=12, titleFontSize=12)
            .configure_view(strokeWidth=0).configure_legend(labelColor=T["text_sub"], titleColor=T["text_sub"]))


def football(rows: list[dict], market: float | None = None, market_label: str = "시장가") -> alt.Chart:
    """rows: {method, lo, hi, rep (optional), kind: dcf/peer/block}. Bars = ranges, black ticks = representative values,
    dashed vertical rule = market price (only when given)."""
    df = pd.DataFrame(rows)
    colors = {"dcf": T["accent"], "peer": T["bar_dark"], "block": T["block_bar"], "other": T["band"]}
    df["color"] = df.kind.map(colors).fillna(T["band"])
    order = df.method.tolist()
    y = alt.Y("method:N", sort=order, title=None, axis=alt.Axis(labelLimit=180, labelFontSize=13, labelColor=T["text"]))
    base = alt.Chart(df)
    bars = base.mark_bar(height=18, cornerRadius=9).encode(
        y=y, x=alt.X("lo:Q", title="주당가치(원)", axis=alt.Axis(format=",.0f")), x2="hi:Q",
        color=alt.Color("color:N", scale=None),
        tooltip=[alt.Tooltip("method:N", title="방법"), alt.Tooltip("lo:Q", title="하단", format=",.0f"),
                 alt.Tooltip("rep:Q", title="대표", format=",.0f"), alt.Tooltip("hi:Q", title="상단", format=",.0f")])
    layers = [bars]
    if "rep" in df and df.rep.notna().any():
        layers.append(base.transform_filter("isValid(datum.rep)").mark_tick(color=T["text"], thickness=4, size=26).encode(
            y=y, x="rep:Q"))
    if market:
        mk = pd.DataFrame([{"x": market, "label": f"{market_label} {market:,.0f}원"}])
        layers.append(alt.Chart(mk).mark_rule(color=T["text"], strokeDash=[5, 4], strokeWidth=2).encode(
            x="x:Q", tooltip=[alt.Tooltip("label:N", title="")]))
        layers.append(alt.Chart(mk).mark_text(align="left", dx=4, dy=-6, color=T["text"], fontSize=12).encode(
            x="x:Q", y=alt.value(0), text="label:N"))
    h = 52 * len(df) + 40
    return _cfg(alt.layer(*layers).properties(height=h, width="container"))


def band(value: float, q1: float, q3: float, lo: float, hi: float, fmt: str = ".2%", label: str = "") -> alt.Chart:
    """A grey practice band (q1~q3) and the current value (orange) on one axis."""
    bd = pd.DataFrame([{"q1": q1, "q3": q3}])
    v = pd.DataFrame([{"v": value, "label": label}])
    x = alt.X("q1:Q", scale=alt.Scale(domain=[lo, hi]), axis=alt.Axis(format=fmt, title=None, tickCount=5))
    a = alt.Chart(bd).mark_bar(height=14, color=T["band"], cornerRadius=7).encode(
        x=x, x2="q3:Q", tooltip=[alt.Tooltip("q1:Q", title="실무 하위 25%", format=fmt), alt.Tooltip("q3:Q", title="실무 상위 25%", format=fmt)])
    b = alt.Chart(v).mark_tick(color=T["accent"], thickness=5, size=26).encode(
        x=alt.X("v:Q", scale=alt.Scale(domain=[lo, hi])), tooltip=[alt.Tooltip("v:Q", title=label or "이 평가", format=fmt)])
    return _cfg(alt.layer(a, b).properties(height=46, width="container"))


def year_bars(df: pd.DataFrame, x: str, y: str, n: str, fmt: str = ".2%", title: str = "", hl_from: int | None = None) -> alt.Chart:
    """Bars by year; n < 10 drawn light (shown, flagged). Bars start at zero."""
    d = df.copy()
    d["표본"] = d[n].map(lambda k: "n<10" if k < 10 else "n≥10")
    if hl_from is not None:
        d["표본"] = [("n<10" if k < 10 else ("가이던스 시기" if int(yv) >= hl_from else "n≥10")) for k, yv in zip(d[n], d[x])]
    dom = ["n≥10", "가이던스 시기", "n<10"] if hl_from is not None else ["n≥10", "n<10"]
    rng = [T["bar_dark"], T["text"], T["band"]] if hl_from is not None else [T["bar_dark"], T["band"]]
    ch = alt.Chart(d).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X(f"{x}:O", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{y}:Q", title=title, axis=alt.Axis(format=fmt), scale=alt.Scale(zero=True)),
        color=alt.Color("표본:N", scale=alt.Scale(domain=dom, range=rng), legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip(f"{x}:O", title="연도"), alt.Tooltip(f"{y}:Q", title=title, format=fmt), alt.Tooltip(f"{n}:Q", title="n")])
    return _cfg(ch.properties(height=240, width="container"))


def hbars(df: pd.DataFrame, cat: str, val: str, fmt: str = ".1%", title: str = "", lo: str | None = None, hi: str | None = None) -> alt.Chart:
    """Horizontal median bars with an optional q1~q3 range line (aggregates only)."""
    base = alt.Chart(df)
    y = alt.Y(f"{cat}:N", sort=None, title=None, axis=alt.Axis(labelLimit=200, labelColor=T["text"]))
    layers = [base.mark_bar(color=T["bar_dark"], height=16, cornerRadius=3).encode(
        y=y, x=alt.X(f"{val}:Q", title=title, axis=alt.Axis(format=fmt)),
        tooltip=[alt.Tooltip(f"{cat}:N", title=""), alt.Tooltip(f"{val}:Q", title="중앙값", format=fmt)])]
    if lo and hi:
        layers.append(base.mark_rule(color=T["accent"], strokeWidth=2).encode(y=y, x=f"{lo}:Q", x2=f"{hi}:Q"))
    return _cfg(alt.layer(*layers).properties(height=36 * len(df) + 30, width="container"))
