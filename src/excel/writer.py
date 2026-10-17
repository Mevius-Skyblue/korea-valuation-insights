"""Workbook helpers for the Excel model: one place for colours, number formats, named ranges and the cell registry.

Colour rules (FAST / ICAEW Financial Modelling Code style)
    input        blue font on light yellow fill       - the only cells a user should type into
    formula      black font                           - calculation on the same sheet
    link         green font                           - formula that reads another sheet (directly or via a name)
    engine value grey italic on grey fill             - numbers copied from the Python engine (not formulas),
                                                         used only in clearly labelled comparison tables
The registry (Book.reg) records every input, KRX single value, engine-value range and structural constant so the
tests can check styles, the KRX rule and the "no hard-coded numbers in calculation sheets" rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

INPUT_FONT, INPUT_FILL = "#0000FF", "#FFF2CC"
LINK_FONT = "#008000"
ENGINE_FONT, ENGINE_FILL = "#7F7F7F", "#F2F2F2"
HEADER_FILL = "#DDEBF7"

NUM = {
    "mn": '#,##0.0;[Red]-#,##0.0',          # 백만원
    "won": '#,##0;[Red]-#,##0',             # 원 (per share, prices)
    "int": '#,##0',
    "pct": '0.00%',
    "pct1": '0.0%',
    "pct3": '0.000%',
    "x": '0.00"x"',
    "ratio": '0.0000',
    "beta": '0.000',
    "days": '0.0',
    "year": '0',
    "date": 'yyyy-mm-dd',
    "text": '@',
    "gen": 'General',
}


@dataclass
class Registry:
    inputs: list = field(default_factory=list)        # (sheet, cell)
    krx: list = field(default_factory=list)           # (sheet, cell, label) single KRX-derived values
    engine: list = field(default_factory=list)        # (sheet, first, last) engine-value ranges
    structural: list = field(default_factory=list)    # (sheet, cell) structural constants (0/1) on calc sheets
    names: dict = field(default_factory=dict)         # name -> (sheet, cell)
    checks: list = field(default_factory=list)        # (sheet, status cell, label, kind)
    datatables: list = field(default_factory=list)    # {"sheet", "first", "ref", "r1", "r2", "engine": {cell: value}}


class Book:
    def __init__(self, path, cached: dict | None = None):
        self.wb = xlsxwriter.Workbook(str(path))
        self.wb.set_calc_mode("auto")
        self.cached = cached or {}
        self.reg = Registry()
        self._fmt = {}
        self.sheets: dict[str, "Sheet"] = {}

    def fmt(self, role: str, kind: str = "gen", **extra):
        key = (role, kind, tuple(sorted(extra.items())))
        if key in self._fmt:
            return self._fmt[key]
        p = {"num_format": NUM.get(kind, kind), "font_name": "맑은 고딕", "font_size": 10, "valign": "vcenter"}
        if role == "input":
            p.update(font_color=INPUT_FONT, bg_color=INPUT_FILL, border=1, border_color="#BFBFBF")
        elif role == "link":
            p.update(font_color=LINK_FONT)
        elif role == "engine":
            p.update(font_color=ENGINE_FONT, bg_color=ENGINE_FILL, italic=True)
        elif role == "header":
            p.update(bold=True, bg_color=HEADER_FILL, bottom=1, text_wrap=True)
        elif role == "title":
            p.update(bold=True, font_size=14)
        elif role == "subtitle":
            p.update(bold=True, font_size=11, font_color="#1F4E79")
        elif role == "note":
            p.update(italic=True, font_color="#595959", font_size=9)
        elif role == "label":
            pass
        elif role == "bold":
            p.update(bold=True)
        elif role == "wrap":
            p.update(text_wrap=True, valign="top")
        p.update(extra)
        self._fmt[key] = self.wb.add_format(p)
        return self._fmt[key]

    def sheet(self, name: str, tab: str | None = None) -> "Sheet":
        ws = self.wb.add_worksheet(name)
        if tab:
            ws.set_tab_color(tab)
        ws.hide_gridlines(2)
        s = Sheet(self, ws, name)
        self.sheets[name] = s
        return s

    def name(self, nm: str, sheet: str, cell: str):
        self.wb.define_name(nm, f"='{sheet}'!{abs_cell(cell)}" if " " in sheet else f"={sheet}!{abs_cell(cell)}")
        self.reg.names[nm] = (sheet, cell)

    def close(self):
        self.wb.close()


def abs_cell(cell: str) -> str:
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", cell)
    return f"${m.group(1)}${m.group(2)}" if m else cell


def a1(r: int, c: int, absolute: bool = False) -> str:
    return xl_rowcol_to_cell(r, c, row_abs=absolute, col_abs=absolute)


def col(c: int) -> str:
    return xl_col_to_name(c)


class Sheet:
    def __init__(self, book: Book, ws, name: str):
        self.book, self.ws, self.name = book, ws, name

    # -- addressing
    def ref(self, r: int, c: int, absolute: bool = True) -> str:
        """Reference usable from another sheet."""
        return f"{self.name}!{a1(r, c, absolute)}"

    # -- writing
    def text(self, r, c, s, role="label", **kw):
        self.ws.write_string(r, c, str(s), self.book.fmt(role, "gen", **kw))

    def inp(self, r, c, value, kind="gen", name: str | None = None, krx: str | None = None):
        f = self.book.fmt("input", kind)
        if value is None:
            self.ws.write_blank(r, c, None, f)
        elif isinstance(value, (date, datetime)):
            self.ws.write_datetime(r, c, value if isinstance(value, datetime) else datetime(value.year, value.month, value.day), f)
        elif isinstance(value, str):
            self.ws.write_string(r, c, value, f)
        else:
            self.ws.write_number(r, c, float(value), f)
        cell = a1(r, c)
        self.book.reg.inputs.append((self.name, cell))
        if krx:
            self.book.reg.krx.append((self.name, cell, krx))
        if name:
            self.book.name(name, self.name, cell)
        return self.ref(r, c)

    def fx(self, r, c, formula: str, kind="gen", name: str | None = None, bold=False):
        role = "link" if self._is_link(formula) else "calc"
        f = self.book.fmt(role, kind, **({"bold": True} if bold else {}))
        cell = a1(r, c)
        cached = self.book.cached.get(f"{self.name}!{cell}")
        if cached is None:
            self.ws.write_formula(r, c, formula, f)
        else:
            self.ws.write_formula(r, c, formula, f, cached)
        if name:
            self.book.name(name, self.name, cell)
        return self.ref(r, c)

    def const(self, r, c, value, kind="gen"):
        """Structural constant on a calculation sheet (0 / 1 opening values) - registered, black font."""
        self.ws.write_number(r, c, value, self.book.fmt("calc", kind))
        self.book.reg.structural.append((self.name, a1(r, c)))
        return self.ref(r, c)

    def eng(self, r, c, value, kind="gen"):
        f = self.book.fmt("engine", kind)
        if value is None or (isinstance(value, float) and value != value):
            self.ws.write_string(r, c, "n/a", f)
        elif isinstance(value, str):
            self.ws.write_string(r, c, value, f)
        else:
            self.ws.write_number(r, c, float(value), f)
        return a1(r, c)

    def engine_range(self, r0, c0, r1, c1):
        self.book.reg.engine.append((self.name, a1(r0, c0), a1(r1, c1)))

    def check(self, r, c, formula: str, label: str, kind: str = "check"):
        """Status cell returning "OK" / "ERR" (kind check) or "OK" / "WARN" (kind warn) or info text."""
        self.fx(r, c, formula, "gen", bold=True)
        self.book.reg.checks.append((self.name, a1(r, c), label, kind))

    def _is_link(self, formula: str) -> bool:
        if "!" in formula:
            return True
        names = self.book.reg.names
        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", formula):
            if tok in names and names[tok][0] != self.name:
                return True
        return False

    def widths(self, spec: dict[int, float]):
        for c, w in spec.items():
            self.ws.set_column(c, c, w)
