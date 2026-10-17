"""Recalculate a generated workbook without Excel (Python `formulas` package, EUPL 1.1+, development-only dependency).

load(path) -> Model            parse the workbook once
Model.calc(inputs) -> dict     values of every formula cell, keyed "Sheet!A1" (sheet names as in the workbook);
                               inputs: {"Sheet!A1" or defined name: value} overrides input cells for this run
Errors (#REF!, #DIV/0! ...) come back as strings starting with "#".
If `formulas` is not installed, available() is False and callers (tests) skip.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

KEY = re.compile(r"^'?\[(?P<book>[^\]]+)\](?P<sheet>[^']+)'?!(?P<cell>[A-Z]+\d+)$")


def available() -> bool:
    try:
        import formulas  # noqa: F401
        return True
    except ImportError:
        return False


def _scalar(v):
    try:
        a = v.value if hasattr(v, "value") else v
        x = np.asarray(a, dtype=object).ravel()[0]
    except Exception:  # noqa: BLE001
        return None
    s = str(x)
    if s == "empty":
        return None
    if s.startswith("#"):
        return s
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    return s


class Model:
    def __init__(self, path: Path, names: dict[str, tuple[str, str]], sheets: list[str]):
        import formulas

        from src.excel.datatable import has_data_tables, strip_data_tables
        self.path = Path(path)
        self.names = names
        self.sheet_case = {s.upper(): s for s in sheets}
        src = self.path
        if has_data_tables(self.path):          # formulas cannot read data tables -> a copy without them (values cached)
            import tempfile
            src = Path(tempfile.mkdtemp()) / self.path.name
            strip_data_tables(self.path, src)
        self.xl = formulas.ExcelModel().loads(str(src)).finish()

    def _key(self, ref: str) -> str:
        if ref in self.names:
            sheet, cell = self.names[ref]
        else:
            sheet, cell = ref.split("!")
        return f"'[{self.path.name}]{sheet.upper()}'!{cell.replace('$', '')}"

    def calc(self, inputs: dict | None = None) -> dict:
        ins = {self._key(k): v for k, v in (inputs or {}).items()}
        sol = self.xl.calculate(inputs=ins)
        out = {}
        for k, v in sol.items():
            m = KEY.match(k)
            if not m:
                continue
            sheet = self.sheet_case.get(m.group("sheet").upper(), m.group("sheet"))
            out[f"{sheet}!{m.group('cell')}"] = _scalar(v)
        return out

    def value(self, vals: dict, ref: str):
        if ref in self.names:
            sheet, cell = self.names[ref]
        else:
            sheet, cell = ref.split("!")
        return vals.get(f"{sheet}!{cell.replace('$', '')}")


def load(path, names: dict, sheets: list[str]) -> Model:
    return Model(path, names, sheets)
