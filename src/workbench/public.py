"""Public-mode outputs (config/p7c1.yaml public_mode): aggregates instead of per-peer / per-date KRX rows, and the scan.

    transform(d)                    model data -> public model data. Per-peer beta rows, per-peer market caps / multiples and
                                    the D/E balance-sheet-date market caps are dropped; their aggregates (included-peer count,
                                    median βu, median R², quartile multiples per multiple, target D/E) become input cells.
                                    Every other calculation stays a live formula. The values equal the PC-mode engine values
                                    (same floats), so the Excel <-> engine reconciliation is unchanged.
    krx_values(pc_cfg, user)        the KRX raw values of the PC data for that (PC-mode) config (target / peers / listed subsidiaries /
                                    preferred: as-of close, market cap, 20-day VWAP, D/E-date market caps, beta regression
                                    values). Values the user typed are removed (shown because the user entered them).
    scan(paths, krx, allow)         every number of the outputs (Excel cell values, report text, summary.json) checked against
                                    them -> list of hits (empty = clean)
    scan_screen(texts, numbers, krx, allow)   the same rules on a rendered screen (P7-C2): texts like the report text,
                                    chart / table numbers like the Excel cell values

Run (the 엔에프씨 example in reports/p7c1_workbench.md):
    python -m src.workbench.public <session_id> <close> <vwap20>
"""
from __future__ import annotations

import json
import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from src.collect.core import ROOT

MULTS = [("EV/Sales", "ev", "revenue"), ("EV/EBITDA", "ev", "ebitda"), ("PER", "equity", "ni"), ("PBR", "equity", "equity")]


def _quart(vals: list) -> dict:
    """Same as Excel COUNT / QUARTILE.INC / MEDIAN over the included positive multiples (and p3c1.multiple_stats)."""
    v = pd.Series([x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x)) and x > 0], dtype=float)
    if v.empty:
        return {"n": 0, "q25": None, "med": None, "q75": None}
    return {"n": int(v.size), "q25": float(v.quantile(0.25)), "med": float(v.median()), "q75": float(v.quantile(0.75))}


def _peer_multiples(peers: list[dict]) -> dict:
    out = {}
    specs = [(nm, kind, dk, dk) for nm, kind, dk in MULTS] + [("EV/EBITDA(보완 전)", "ev", "ebitda", "ebitda_pre")]
    for nm, kind, dk, key in specs:
        vals = []
        for p in peers:
            if not p["include"]:
                continue
            ev = sum(p[k] or 0 for k in ("mktcap", "debt", "nci")) - sum(p[k] or 0 for k in ("cash_like", "non_operating"))
            num = ev if kind == "ev" else (p["mktcap"] or 0)
            den = p.get(key)
            vals.append(num / den if den is not None and den > 0 else None)
        out[nm] = _quart(vals)
    return out


def public_aggregates(beta_rows: list[dict], peers: list[dict]) -> dict:
    """The aggregates of the per-peer rows a public model shows (P7-C3: recorded in the public snapshot instead of the
    rows; the R² median rounded to 2 decimals there, config/p7c3.yaml snapshot.rounding)."""
    inc = [b for b in beta_rows if b["include"]]
    r2 = [b["r2"] for b in inc]
    from src.workbench import snapdata as SD
    from src.workbench.pubagg import r2_display
    r2m = float(np.median(r2)) if r2 else None
    return {"beta_n": len(inc), "r2_median": r2_display(r2m) if SD.mode() == "record" else r2m,
            "peers": [{k: p[k] for k in ("name", "tier", "include", "fs_div")} for p in peers],
            "multiples": _peer_multiples(peers)}


def transform(d: dict) -> dict:
    """Public model data (mechanical type). Needs the engine reference (d['engine']). In the public snapshot (no rows)
    the recorded aggregates are used (src/workbench/pubagg.py)."""
    if d["type"] != "mechanical":
        raise NotImplementedError("공개 모드는 자동 초안·mechanical 모델만")
    e = d["engine"]
    from src.workbench import snapdata as SD
    if SD.replaying():
        import yaml

        from src.workbench import pubagg
        agg = pubagg.get("public", d["cfg_path"], yaml.safe_load((ROOT / d["cfg_path"]).read_text(encoding="utf-8")))
    else:
        agg = public_aggregates(d["beta"], d["peers"])
    pub = {"beta": {"n": agg["beta_n"], "bu": float(e["beta_u"]), "src": e.get("beta_src", "peer"), "r2_median": agg["r2_median"]},
           "peers": agg["peers"], "multiples": agg["multiples"],
           "de": float(e["de_own"]), "de_n": d["de"].get("n", len(d["de"]["points"])) if d["de"]["rule"] == "points" else None}
    d = dict(d)
    d["public"] = pub
    d["beta"], d["peers"] = [], []
    d["de"] = {"rule": "fixed", "value": pub["de"], "src": "(공개 모드 집계 입력)",
               "basis": f"자체 D/E 시점 평균({pub['de_n']}개 시점, PC에서 계산한 집계값. 시점별 시가총액은 공개 모드에 표시하지 않음)"}
    return d


def aggregates(d: dict) -> list[float]:
    """The aggregate input values of a public model (allowed in the scan even if one equals a peer value, e.g. an odd median)."""
    p = d.get("public") or {}
    out = [p["beta"]["bu"], p["beta"]["r2_median"], p.get("de")]
    for m in (p.get("multiples") or {}).values():
        out += [m["q25"], m["med"], m["q75"]]
    return [float(x) for x in out if x is not None]


# ---------------------------------------------------------------- scan

def krx_values(cfg_path: str, user: dict | None = None) -> list[dict]:
    """KRX raw values of the PC data (DB provider) for a PC-mode config (its beta / peer tables are in the DB), minus the
    values the user entered."""
    from src.excel.model_data import load_model_data
    from src.market.provider import DbMarketProvider, use
    with use(DbMarketProvider()):
        d = load_model_data(cfg_path, with_engine=False)
    out = [{"what": "대상 종가(원)", "v": d["market"]["close"], "unit": "won"},
           {"what": "대상 시가총액(백만원)", "v": d["market"]["rf_mc"], "unit": "mn"},
           {"what": "대상 20일 VWAP(원)", "v": d["premium"]["vwap"], "unit": "won"}]
    for p in d["de"].get("points") or []:
        out.append({"what": f"D/E 시점 시가총액 {p['date']}(백만원)", "v": p["mktcap"], "unit": "mn"})
    for p in d["peers"]:
        out.append({"what": f"피어 시가총액 {p['name']}(백만원)", "v": p["mktcap"], "unit": "mn"})
    for b in d["beta"]:
        for k in ("raw", "se", "r2"):
            out.append({"what": f"피어 베타 회귀 {k} {b['name']}", "v": b[k], "unit": "beta"})
    for p in d["shares"]["listed_pref"]:
        out.append({"what": f"우선주 종가 {p['code']}(원)", "v": p["close"], "unit": "won"})
    for r in ((d.get("sotp") or {}).get("rows") or []):
        if r.get("close"):
            out.append({"what": f"상장 종속회사 종가 {r.get('name')}(원)", "v": r["close"], "unit": "won"})
    typed = user_values(user, d)
    return [x for x in out if x["v"] is not None and not any(abs(_won(x) - t) < 0.5 for t in typed)]


def user_values(user: dict | None, d: dict) -> list[float]:
    """Values (원) the user entered or that follow from them alone: closes, VWAP, market cap (given, or close × common
    shares outstanding from DART as UserOverlayProvider uses)."""
    u = user or {}
    sh = d["shares"]
    out = [u.get("close"), u.get("mktcap"), u.get("vwap20"), *((u.get("sub_close") or {}).values()),
           *[x.get("close") for x in (u.get("pref") or {}).values()]]
    if u.get("close") and not u.get("mktcap"):
        out.append(float(u["close"]) * (sh["common_issued"] - sh["common_treasury"]))
    return [float(x) for x in out if x]


def _won(x: dict) -> float:
    return float(x["v"]) * (1e6 if x["unit"] == "mn" else 1.0) if x["unit"] != "beta" else float("nan")


def _same(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))


def _xlsx_numbers(path: Path) -> list[tuple[str, float]]:
    import openpyxl
    out = []
    for data_only in (True, False):                      # cached formula results and literal inputs
        wb = openpyxl.load_workbook(path, data_only=data_only, read_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                        out.append((f"{ws.title}!{c.coordinate}", float(c.value)))
        wb.close()
    return out


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.startswith("word/") and n.endswith(".xml"))
    return re.sub(r"<[^>]+>", "", xml)


def _forms(x: dict) -> list[str]:
    """Text forms a KRX value would take in the report (원 / 백만원 / 억원 with thousands separators, β to 3 decimals)."""
    v = float(x["v"])
    if x["unit"] == "beta":
        return [f"{v:.3f}"] if abs(v) >= 0.0005 else []
    won = v if x["unit"] == "won" else v * 1e6
    forms = [f"{won:,.0f}", f"{won / 1e6:,.0f}", f"{won / 1e8:,.0f}", f"{won / 1e8:,.1f}"]
    return [f for f in dict.fromkeys(forms) if len(f.replace(",", "").replace(".", "").lstrip("-0")) >= 4]


def scan(paths: list, krx: list[dict], allow: list[float] = ()) -> list[dict]:
    """Hits of KRX raw values in the outputs. Excel / JSON: exact number (any of 원·백만원·억원 scale); report: text forms."""
    hits = []
    allow = [float(a) for a in allow]
    for p in map(Path, paths):
        if not p.exists():
            continue
        if p.suffix == ".xlsx":
            nums = _xlsx_numbers(p)
        elif p.suffix == ".json":
            nums = []

            def walk(o, k=""):
                if isinstance(o, dict):
                    for kk, vv in o.items():
                        walk(vv, f"{k}.{kk}")
                elif isinstance(o, list):
                    for i, vv in enumerate(o):
                        walk(vv, f"{k}[{i}]")
                elif isinstance(o, (int, float)) and not isinstance(o, bool):
                    nums.append((k, float(o)))
            walk(json.loads(p.read_text(encoding="utf-8")))
        elif p.suffix == ".docx":
            txt = _docx_text(p)
            allowed_forms = {f for a in allow for f in (f"{a:.3f}", f"{a:.2f}")}
            for x in krx:
                for f in _forms(x):
                    if f in allowed_forms:          # an aggregate shown in the report (e.g. an odd-count median R²)
                        continue
                    if re.search(rf"(?<![\d,.]){re.escape(f)}(?![\d])", txt):
                        hits.append({"file": p.name, "where": "text", "what": x["what"], "value": x["v"], "form": f})
            continue
        else:
            continue
        for x in krx:
            v = float(x["v"])
            scales = [1.0] if x["unit"] == "beta" else ([1.0, 1e-6, 1e-8] if x["unit"] == "won" else [1.0, 1e6, 100.0 / 1e4, 1e-2])
            for where, n in nums:
                if any(_same(n, v * s) for s in scales) and not any(_same(n, a) for a in allow):
                    hits.append({"file": p.name, "where": where, "what": x["what"], "value": x["v"], "found": n})
    return hits


def scan_screen(texts: list[str], numbers: list[tuple[str, float]], krx: list[dict], allow: list[float] = ()) -> list[dict]:
    """Hits of KRX raw values on a rendered screen: `texts` (visible text, tags stripped) by text form, `numbers`
    ((where, value) of chart data / table cells) by exact value on the 원·백만원·억원 scales."""
    allow = [float(a) for a in allow]
    allowed_forms = {f for a in allow for f in (f"{a:.3f}", f"{a:.2f}")}
    txt = "\n".join(texts)
    hits = []
    for x in krx:
        for f in _forms(x):
            if f in allowed_forms:
                continue
            for m in re.finditer(rf"(?<![\d,.]){re.escape(f)}(?![\d])", txt):
                hits.append({"where": "text", "what": x["what"], "value": x["v"], "form": f,
                             "context": txt[max(0, m.start() - 30):m.end() + 30]})
                break
        v = float(x["v"])
        scales = [1.0] if x["unit"] == "beta" else ([1.0, 1e-6, 1e-8] if x["unit"] == "won" else [1.0, 1e6, 100.0 / 1e4, 1e-2])
        for where, n in numbers:
            if any(_same(n, v * s) for s in scales) and not any(_same(n, a) for a in allow):
                hits.append({"where": where, "what": x["what"], "value": x["v"], "found": n})
    return hits


def outputs_of(summ: dict) -> list[Path]:
    o = summ.get("outputs") or {}
    out = [ROOT / o[k] for k in ("xlsx", "docx") if o.get(k)]
    if out:
        out.append(out[0].parent / "summary.json")
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    from src.workbench import confirm as C, session as S
    sid, close, vw = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    s = S.load(sid)
    user = {"close": close, "vwap20": vw}
    summ = C.confirm(s, mode="public", user=user)
    print(json.dumps({k: summ.get(k) for k in ("result", "success", "outputs", "timing")}, ensure_ascii=False, indent=1, default=str))
