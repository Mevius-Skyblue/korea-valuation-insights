"""Excel What-If data tables ({=TABLE(row input, column input)}) added to an XlsxWriter file by XML post-processing.

XlsxWriter cannot write data tables. Excel stores a 2-D data table as ONE element in the first result cell
(checked against a table made by Excel itself, P4-B):
    <c r="C5"><f t="dataTable" ref="C5:E6" dt2D="1" dtr="1" r1="A1" r2="A2"/><v>15</v></c>
    r1 = row input cell (receives the values of the header row above the table)
    r2 = column input cell (receives the values of the header column left of the table)
All other result cells keep plain cached values. Excel recalculates the table on open (fullCalcOnLoad) and on F9.
The `formulas` package cannot read such files -> strip_data_tables() gives it a copy without the table formulas.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path


def _rewrite(src: Path, dst: Path, fn) -> None:
    # P7-X4 E-F3: the temporary folder is removed when done (also on an error); it used to stay behind empty in %TEMP%
    with tempfile.TemporaryDirectory(prefix="kvi_dt_") as d:
        tmp = Path(d) / "x.xlsx"
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.startswith("xl/worksheets/sheet") and item.filename.endswith(".xml"):
                    data = fn(item.filename, data.decode("utf-8")).encode("utf-8")
                zout.writestr(item, data)
        shutil.move(str(tmp), str(dst))


def add_data_tables(path: Path, sheet_index: int, tables: list[dict]) -> None:
    """tables: {"first": "D50", "ref": "D50:H54", "r1": "C46", "r2": "D46"} on the sheet with 1-based index."""
    target = f"xl/worksheets/sheet{sheet_index}.xml"

    def fn(name, xml):
        if name != target:
            return xml
        for t in tables:
            pat = re.compile(rf'(<c r="{t["first"]}"[^>]*?)(/>|>)')
            m = pat.search(xml)
            if not m:
                raise ValueError(f"data table anchor cell {t['first']} not found")
            f = f'<f t="dataTable" ref="{t["ref"]}" dt2D="1" dtr="1" r1="{t["r1"]}" r2="{t["r2"]}"/>'
            if m.group(2) == "/>":  # empty cell: <c r=".." s=".."/>
                xml = xml[: m.start()] + m.group(1) + ">" + f + "</c>" + xml[m.end() :]
            else:
                xml = xml[: m.end()] + f + xml[m.end() :]
        return xml

    _rewrite(path, path, fn)


def strip_data_tables(src: Path, dst: Path) -> bool:
    """Copy without the data-table formulas (cached values stay). Returns True if anything was removed."""
    found = []

    def fn(name, xml):
        new = re.sub(r'<f t="dataTable"[^>]*/>', "", xml)
        if new != xml:
            found.append(name)
        return new

    _rewrite(Path(src), Path(dst), fn)
    return bool(found)


def has_data_tables(path: Path) -> bool:
    with zipfile.ZipFile(path) as z:
        return any(b't="dataTable"' in z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/sheet"))


def zero_cached(src: Path, dst: Path, sheet_index: int, ranges: list[str]) -> int:
    """Copy with the cached values of the data-table result cells set to 0 (verification: proves Excel recalculates
    the tables instead of showing stored values). Returns the number of cells changed."""
    from openpyxl.utils.cell import range_boundaries

    cells = set()
    for rg in ranges:
        c0, r0, c1, r1 = range_boundaries(rg.split("!")[-1].replace("$", ""))
        from openpyxl.utils import get_column_letter

        cells |= {f"{get_column_letter(cc)}{rr}" for rr in range(r0, r1 + 1) for cc in range(c0, c1 + 1)}
    n = [0]
    target = f"xl/worksheets/sheet{sheet_index}.xml"

    def fn(name, xml):
        if name != target:
            return xml

        def rep(m):
            if m.group(2) in cells:
                n[0] += 1
                return m.group(1) + "<v>0</v>"
            return m.group(0)

        return re.sub(r'(<c r="([A-Z]+\d+)"[^>]*>(?:<f[^>]*/>)?)<v>[^<]*</v>', rep, xml)

    _rewrite(Path(src), Path(dst), fn)
    return n[0]
