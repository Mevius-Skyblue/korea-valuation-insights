"""Generate the Excel valuation model for a company config (P4-A: RF머트리얼즈, scenario_capex engine).

Run:  python -m src.excel.build config/valuation_rf.yaml      -> outputs/excel/<name>.xlsx (git-ignored)

Steps
    1 load_model_data: every input from the config, the DB and the P3 engine (no API calls)
    2 write the workbook (XlsxWriter): Cover, Guide, Inputs, FS_Hist, Forecast, WACC, DCF, Bridge, Peers, Premium,
      Scenarios, Scen_Calc, Football, Checks - inputs only on Inputs / FS_Hist, live formulas everywhere else
    3 recalculate with the `formulas` package (if installed) and write the file again with the computed values cached
      in each formula cell, so viewers that do not recalculate still show numbers (Excel recalculates on open anyway)
The SOTP blocks follow the structure decision (config decisions.structure, checked against the rule in Bridge).
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.excel import recalc
from src.excel.context import SHEETS, make_ctx
from src.excel.model_data import load_model_data, output_path


def write(path: Path, d: dict, cached: dict | None = None):
    """Write every sheet of the workbook with XlsxWriter (formulas live; `cached` = values to store with them)."""
    from src.excel import sheets_calc as sc
    from src.excel import sheets_forecast as sf
    from src.excel import sheets_input as si
    from src.excel import sheets_output as so
    from src.excel import sheets_scenarios as ss

    c = make_ctx(path, d, cached)
    c.reserve("RONIC", "DCF")
    c.reserve("PeerEvEbitdaMed", "Peers")
    for nm in ("WaccOvr", "GOvr", "GrowthOvr", "MarginOvr", "GrowthShiftOvr", "MarginShiftOvr", "MrpOvr", "SrpOvr", "RfOvr"):
        c.reserve(nm, "Scenarios")
    c.reserve("Rf", "WACC")  # P6-A: the Rf the model uses = WACC sheet (Inputs tenor choice)
    si.inputs(c)
    si.fs_hist(c)
    sf.forecast(c)
    sc.wacc_sheet(c)
    sc.dcf_sheet(c)
    sc.bridge(c)
    sc.scen_calc(c)
    so.peers(c)
    so.premium(c)
    ss.scenarios(c)
    so.football(c)
    so.convergence(c)
    so.checks(c)
    from src.excel.sheets_diag import diagnostics  # P7-B2 reliability diagnostics (new sheet, earlier sheets unchanged)

    diagnostics(c)
    if d.get("workbench"):  # P7-C1 confirmed session: people's judgements table
        from src.excel.sheets_diag import judgements

        judgements(c)
    si.guide(c)
    si.cover(c)
    c.book.wb.set_properties(
        {
            "title": f"{d['meta']['name']} valuation model (draft)",
            "subject": "P4 generated model",
            "comments": "Auto-generated draft. Not investment advice.",
        }
    )
    c.S["Cover"].ws.activate()
    c.book.close()
    if c.book.reg.datatables:  # Excel What-If tables (XML post-processing, src/excel/datatable.py)
        from src.excel.datatable import add_data_tables

        idx = [n for n, _ in SHEETS].index("Scenarios") + 1
        add_data_tables(path, idx, c.book.reg.datatables)
    return c


def writable(path: Path) -> Path:
    """If the file is open in Excel (locked), never force it closed: use <name>_v2.xlsx (then _v3 ...)."""
    p, k = path, 1
    while p.exists():
        try:
            with open(p, "r+b"):
                return p
        except PermissionError:
            k += 1
            p = path.with_name(f"{path.stem}_v{k}{path.suffix}")
    return p


def build(cfg_path: str = "config/valuation_rf.yaml", path: Path | None = None, d: dict | None = None, cache_values: bool = True):
    """Returns (path, ctx, values). values = recalculated cell values (None if `formulas` is not installed)."""
    d = d or load_model_data(cfg_path)
    path = Path(path or output_path(d))
    path.parent.mkdir(parents=True, exist_ok=True)
    path = writable(path)
    c = write(path, d)
    vals = None
    if cache_values and recalc.available():
        m = recalc.load(path, c.book.reg.names, [s for s, _ in SHEETS])
        vals = m.calc()
        c = write(path, d, cached={k: v for k, v in vals.items() if v is not None})
        c.recalc_model = m  # P7-B5: the reconciliation reuses the loaded model and these base values
    return path, c, vals


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/valuation_rf.yaml"
    p, ctx, v = build(cfg)
    mc = None
    if v is not None:
        sheet, cell = ctx.book.reg.names["MasterCheck"]
        mc = v.get(f"{sheet}!{cell}")
    print(f"written {p} (master check: {mc})")
