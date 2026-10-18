"""Shared state while one workbook is generated: the Book, the model data and a dictionary of cell references.

R[key] holds a formula-ready reference: a defined name (e.g. "Rf") or an absolute address ("Inputs!$B$12").
Ranges are stored the same way ("Inputs!$B$40:$B$43"). Sheets are created up front in display order so formulas may
point forward; names used before their cell exists are reserved first (Book.reg.names, sheet only).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.excel.writer import Book, Sheet

SHEETS = [
    ("Cover", "#1F4E79"),
    ("Guide", "#1F4E79"),
    ("Inputs", "#FFC000"),
    ("FS_Hist", "#FFC000"),
    ("Forecast", "#808080"),
    ("WACC", "#808080"),
    ("DCF", "#808080"),
    ("Bridge", "#808080"),
    ("Peers", "#808080"),
    ("Premium", "#808080"),
    ("Scenarios", "#2E75B6"),
    ("Scen_Calc", "#808080"),
    ("Football", "#2E75B6"),
    ("Convergence", "#2E75B6"),
    ("Checks", "#C00000"),
    ("Diagnostics", "#7030A0"),
]  # P7-B2: appended last so every earlier sheet keeps its index
CALC_SHEETS = [
    "Forecast",
    "WACC",
    "DCF",
    "Bridge",
    "Peers",
    "Premium",
    "Scenarios",
    "Scen_Calc",
    "Football",
    "Convergence",
    "Checks",
]


@dataclass
class Ctx:
    book: Book
    d: dict
    R: dict = field(default_factory=dict)
    S: dict = field(default_factory=dict)  # sheet name -> Sheet
    layout: dict = field(default_factory=dict)  # forecast columns, row maps

    def sheet(self, name: str) -> Sheet:
        return self.S[name]

    def reserve(self, name: str, sheet: str):
        """A name that formulas may use before its cell is written (for the link colour test)."""
        self.book.reg.names.setdefault(name, (sheet, None))
        self.R[name] = name

    def range_name(self, name: str, sheet: str, first: str, last: str):
        q = f"'{sheet}'" if " " in sheet else sheet
        self.book.wb.define_name(name, f"={q}!{_abs(first)}:{_abs(last)}")
        self.book.reg.names[name] = (sheet, f"{first}:{last}")
        self.R[name] = name


def _abs(cell: str) -> str:
    import re

    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", cell)
    return f"${m.group(1)}${m.group(2)}"


def sheets_for(d: dict) -> list[tuple[str, str]]:
    """Display order; a confirmed workbench session adds the Judgements sheet at the end (P7-C1)."""
    return SHEETS + ([("Judgements", "#548235")] if d.get("workbench") else [])


def make_ctx(path, d: dict, cached: dict | None = None) -> Ctx:
    bk = Book(path, cached)
    c = Ctx(bk, d)
    for nm, tab in sheets_for(d):
        c.S[nm] = bk.sheet(nm, tab)
    return c
