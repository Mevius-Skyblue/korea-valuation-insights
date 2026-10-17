"""General company valuation (P3-C2): mechanical forecast + three-stage value-driver DCF + bridge + structure rule +
relative valuation + block premium + football field, driven only by a company config (e.g. config/valuation_jw.yaml)
and the shared discount ledger (config/valuation_rf.yaml). No RF-specific code.

Run: python -m src.valuation.company_dcf config/valuation_jw.yaml     -> data/interim/<name>_tables.md, figure

Engine pieces reused: dcf (Period, run_dcf, fade_path, value_driver, roll_forward), wacc (wacc, wacc_hp, debt_beta),
structure.decide, peer_p3.classify/bs_lines, assumptions (tax), predict (premium_range, mktcap_percentile),
p3c1 helpers (multiple_stats, block_range, football_rows, hp_unlever). Units: 억원 unless stated.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from src.collect.core import ROOT
from src.db.build import DB_PATH
from src.market.beta import relever
from src.valuation.assumptions import load_ledger, marginal_rate, progressive_tax, rf_code
from src.valuation.dcf import Period, fade_path, roll_forward, run_dcf
from src.valuation.wacc import debt_beta, wacc, wacc_hp

EOK = 1e8
EXPLICIT_END = 2032                   # design of the three-stage structure (P3-B2), not an as-of value
FADE_END = 2040


def explicit_years(c) -> list[int]:
    return list(range(c.Y + 1, EXPLICIT_END + 1))
FADE = list(range(EXPLICIT_END + 1, FADE_END + 1))


# ---------------------------------------------------------------- pure pieces (unit-tested)

def growth_path(g_start: float, g_terminal: float, start_year: int, to_year: int, years: list[int]) -> dict[int, float]:
    """Growth falling by equal steps from g_start (start_year) to g_terminal (to_year), flat afterwards."""
    n = to_year - start_year
    return {y: g_start + (g_terminal - g_start) * min(y - start_year, n) / n for y in years}


def cagr(v0: float, v1: float, years: int) -> float:
    return (v1 / v0) ** (1 / years) - 1


def bounded_ronic(r_calc: float, reinvestment: float, w: float, cap: float) -> tuple[float, str]:
    """Pre-registered bounds: reinvestment <= 0 -> WACC; else clip to [WACC, cap]."""
    if not np.isfinite(r_calc) or reinvestment <= 0:
        return w, "재투자 ≤ 0 → WACC"
    if r_calc < w:
        return w, f"계산값 {r_calc:.1%} < WACC → 하한"
    if r_calc > cap:
        return cap, f"계산값 {r_calc:.1%} > 상한(과거 ROIC {cap:.1%})"
    return r_calc, "계산값"


def convergence(dcf_ps: float, q25_ps: float, q75_ps: float) -> dict:
    """Pre-registered test: DCF per share inside the peer EV/EBITDA interquartile per-share range."""
    if not (np.isfinite(q25_ps) and np.isfinite(q75_ps)):       # P7-B2: own EBITDA <= 0 -> peer range N/M
        return {"converged": False, "gap": float("nan"), "verdict": "판정 불가(대상 지표 ≤ 0)"}
    inside = q25_ps <= dcf_ps <= q75_ps
    gap = 0.0 if inside else (dcf_ps - q75_ps if dcf_ps > q75_ps else dcf_ps - q25_ps)
    return {"converged": bool(inside), "gap": gap, "verdict": "수렴" if inside else "미수렴 → 원인 분해"}


def structure_inputs(cfg: dict, hist_margin: float, nci_book: float, sub_mktcap: float | None = None) -> dict:
    """Inputs of structure.decide from the company config (P5-A; was fixed False / one segment in P3-C2~P4).

    config `structure`:
        listed_subsidiary: bool                      a material consolidated subsidiary is listed
        subsidiary: {stock_code, stake}              needed when listed_subsidiary is true (NCI at market value)
        segments: [{name, margin, growth}]           margin "history" = the company's historical margin (%)
    NCI value = (1 − stake) x subsidiary market cap (억원, given by the caller) when listed, else the book NCI."""
    st = cfg["structure"]
    listed = st["listed_subsidiary"]
    if not isinstance(listed, bool):
        raise ValueError("structure.listed_subsidiary must be true / false")
    segs = [{"name": s["name"], "margin": 100 * hist_margin if s["margin"] == "history" else s["margin"],
             "growth": s["growth"]} for s in st["segments"]]
    if listed:
        if sub_mktcap is None:
            raise ValueError("listed subsidiary: subsidiary market cap needed for NCI at market value")
        nci = (1 - st["subsidiary"]["stake"]) * sub_mktcap
    else:
        nci = nci_book
    return {"listed": listed, "segments": segs, "nci_value": nci}


def notch_kd(kd_from: float, kd_to: float, steps: int, at: int) -> float:
    return kd_from + (kd_to - kd_from) * at / steps


# ---------------------------------------------------------------- data

@dataclass
class Company:
    cfg: dict
    led: dict
    w: pd.DataFrame            # fs_std CFS wide, 억원, index (year, period)
    dna: pd.Series             # D&A totals, 억원, index (year, period)
    bs_lines: pd.DataFrame
    market: dict
    rates: dict
    ronic_start: str = "mixed"      # P3-C2 "mixed" (FY start NOPAT = 1H actual + 2H normal) / P3-C3 "normal"
    dna_rec: object = None          # P7-B2b: per-period D&A source of an auto draft (원문 / 보완 / 추정)
    v2: dict | None = None          # P7-B2b: mechanical_v2 inputs of an auto draft (None = v1 path)
    sotp: dict | None = None        # P7-B3: general SOTP (subsidiary rows with prices, discount, dividend adjustment)

    # P3-C3: as-of dependent periods come only from config meta (ltm.year / ltm.period)
    @property
    def Y(self) -> int:
        return int(self.cfg["meta"]["ltm"]["year"])

    @property
    def P(self) -> str:
        return self.cfg["meta"]["ltm"]["period"]

    @property
    def FY(self) -> int:
        return self.Y - 1

    @property
    def first(self) -> str:             # label of the partial first forecast period (e.g. 2H26 after an H1 LTM)
        return f"2H{str(self.Y)[2:]}"


def beta_u0(bt: pd.DataFrame, cfg: dict, index: str | None = None) -> tuple[float, str]:
    """βu of the model (P7-B5 config/p7b5.yaml peer_relax.beta_fallback): median of the included peers; with no peer
    βu, the target's own (Blume, Hamada) βu; without that, 1.0. Returns (βu, source)."""
    ix = index or cfg["beta"]["index"]
    tiers = cfg["beta"]["peer_tiers"]
    v = bt[bt.tier.isin(tiers) & (bt["index"] == ix)].bu_avg.dropna() if len(bt) else pd.Series(dtype=float)
    if len(v):
        return float(v.median()), "peer"
    tg = bt[(bt.tier == "target") & (bt["index"] == ix)].bu_avg.dropna() if len(bt) else pd.Series(dtype=float)
    if len(tg):
        return float(tg.iloc[0]), "target_own"
    return 1.0, "market_1"


def fs_div(cfg: dict) -> str:
    """Statement basis of the company (config meta.fs_div; P7-B drafts may be OFS when there are no subsidiaries)."""
    return cfg["meta"].get("fs_div", "CFS")


def market_provider():
    from src.market.provider import get
    return get()


def _con():
    """A read-only DB connection, or None when the public snapshot replays the data (no DB, P7-C3)."""
    from src.workbench import snapdata as SD
    return None if SD.replaying() else duckdb.connect(str(DB_PATH), read_only=True)


def _close(con) -> None:
    if con is not None:
        con.close()


def _seam(name: str, key, canonical: bool = False):
    from src.workbench.snapdata import seam
    return seam(name, key, canonical)


# P7-C3 data seams (src/workbench/snapdata.py): the DART / ECOS reads of load_company, recorded for the public snapshot.
# Off (PC, default): the same queries as before.
@_seam("fs_rows", key=lambda con, corp, fs, fill: (corp, fs, fill), canonical=True)
def _fs_rows(con, corp: str, fs: str, fill: list) -> pd.DataFrame:
    d = con.execute("""SELECT fiscal_year y, period p, std_account a, amount FROM fs_std
                       WHERE corp_code=? AND fs_div=? AND is_default""", [corp, fs]).df()
    for y, per, other in fill:     # P7-B5 short_history.basis_fill (auto drafts)
        d = d[~((d.y == y) & (d.p == per))]
        o = con.execute("""SELECT fiscal_year y, period p, std_account a, amount FROM fs_std
                           WHERE corp_code=? AND fs_div=? AND is_default AND fiscal_year=? AND period=?""", [corp, other, y, per]).df()
        d = pd.concat([d, o], ignore_index=True)
    return d


@_seam("fs_dna_sum", key=lambda con, corp, fs: (corp, fs), canonical=True)
def _fs_dna_sum(con, corp: str, fs: str) -> pd.DataFrame:
    return con.execute("SELECT fiscal_year y, period p, sum(amount) v FROM fs_dna WHERE corp_code=? AND fs_div=? GROUP BY 1,2",
                       [corp, fs]).df()


def _draft_key(cfg: dict) -> tuple:
    return (cfg["target"]["corp_code"], cfg["meta"].get("fs_div", "CFS"), int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"],
            [x["corp_code"] for x in cfg.get("peers", [])])


@_seam("draft_dna", key=lambda con, cfg: _draft_key(cfg), canonical=True)
def draft_dna(con, cfg: dict):
    """P7-B2b filled D&A of an auto draft (src/clean/dna_fill.draft_target): (wide, record)."""
    from src.clean.dna_fill import draft_target
    return draft_target(con, cfg)


@_seam("bs_lines", key=lambda con, corp, fs, y, reprt: (corp, fs, y, reprt))
def _bs_lines(con, corp: str, fs: str, y: int, reprt: str) -> pd.DataFrame:
    from src.valuation.peer_p3 import bs_lines
    return bs_lines(con, corp, fs, y, reprt)


@_seam("rates", key=lambda con, as_of: as_of)
def _rates(con, as_of: str) -> dict:
    return {k: con.execute("""SELECT value FROM rates_daily WHERE rate_code=? AND freq='D' AND date<=? ORDER BY date DESC
                              LIMIT 1""", [k, as_of]).fetchone()[0] / 100 for k in ("KTB5Y", "KTB10Y", "CB3Y_AAm", "CB3Y_BBBm")}


@_seam("debt_at", key=lambda con, corp, y, p, fs: (corp, y, p, fs))
def _debt_at(con, corp: str, y: int, p: str, fs):
    from src.market.beta_table import debt_at
    return debt_at(con, corp, y, p, fs)


def _quote(mp, code: str, as_of: str, con):
    """(close, market cap, listed shares) via the provider; public mode without a user input -> (None, None, None)."""
    from src.market.user_provider import PublicDataUnavailable
    try:
        q = mp.quote(code, as_of, con=con)
    except PublicDataUnavailable:
        return (None, None, None)
    return q if q is not None else (None, None, None)


@_seam("dna_wide", key=lambda con, corp, fs: (corp, fs), canonical=True)
def dna_wide_of(con, corp: str, fs: str) -> pd.DataFrame:
    from src.valuation.peer_table import dna_wide
    return dna_wide(con, corp, fs)


def de_points_key(cfg: dict) -> tuple:
    return (cfg["target"]["corp_code"], cfg["target"]["stock_code"], cfg.get("structure", {}).get("method") == "sotp_general",
            fs_div(cfg), [list(x) for x in cfg["params"]["de_points"]], (cfg.get("bridge") or {}).get("debt_reclass") or [])


def load_company(cfg_path: str) -> Company:
    from src.workbench import snapdata as SD
    cfg = yaml.safe_load((ROOT / cfg_path).read_text(encoding="utf-8"))
    led = load_ledger(ROOT / cfg["meta"]["discount_ledger"])
    corp, code, as_of = cfg["target"]["corp_code"], cfg["target"]["stock_code"], cfg["meta"]["as_of"]
    fs = fs_div(cfg)
    mp = market_provider()
    sotp_mode = cfg.get("structure", {}).get("method") == "sotp_general"
    con = _con()
    d = _fs_rows(con, corp, fs, cfg["meta"].get("basis_fill") or [])
    from src.clean.frames import pivot
    w = pivot(d, ["y", "p"], "a", "amount") / EOK            # P7-B5: empty-safe
    dn = _fs_dna_sum(con, corp, fs)
    dna = dn.set_index(["y", "p"]).v / EOK
    dna_rec = None
    if "draft_meta" in cfg:             # P7-B2b: auto drafts read D&A filled period by period (원문 → 보완 → 추정)
        dw_f, dna_rec = draft_dna(con, cfg)
        dna = dw_f.fillna(0).sum(axis=1) / EOK
        dna.index = dna.index.set_names(["y", "p"])
    reclass = {}
    if "draft_meta" in cfg:             # P7-B3b mistag.text_rule: borrowings the API tags as another account (원)
        from src.clean.mistag import by_period
        reclass = by_period((cfg.get("bridge") or {}).get("debt_reclass"))
        for (y, p), amt in reclass.items():
            if (y, p) in w.index:
                cur = w.loc[(y, p), "total_debt"] if "total_debt" in w.columns else np.nan
                w.loc[(y, p), "total_debt"] = (0.0 if pd.isna(cur) else cur) + amt / EOK
    ly, lp = int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"]
    lines = _bs_lines(con, corp, fs, ly, {"H1": "11012", "FY": "11011", "Q1": "11013", "Q3": "11014"}[lp])
    px = lambda s: _quote(mp, s, as_of, con)  # noqa: E731     (close, market cap, listed shares) via the provider
    close, mcap_common, listed = px(code)
    sh = cfg["shares"]
    shares_note = None
    if "draft_meta" in cfg and listed and abs(listed - sh["common_issued"]) > 0.01 * sh["common_issued"]:
        # P7-B3 B3-F1: a share event between the report date and the as-of date (bonus issue, rights issue, cancellation)
        # -> issued common = KRX listed shares on the as-of date (treasury from the report, flagged for a person)
        shares_note = {"report_issued": sh["common_issued"], "asof_listed": int(listed), "report_rcept": sh.get("source", "")}
        sh["common_issued"] = int(listed)
    common_out = sh["common_issued"] - sh["common_treasury"]
    pref_out = sh["pref_issued"] - sh["pref_treasury"]
    pref_listed = [px(s) for s in sh.get("listed_pref_codes", [])]
    market_equity = None                # P7-C3 public mode before the user's price: no market equity
    if close is not None and all(p[0] is not None and p[2] is not None for p in pref_listed):
        listed_pref_shares = sum(p[2] for p in pref_listed)
        market_equity = (close * common_out + sum(p[0] * p[2] for p in pref_listed)
                         + close * max(pref_out - listed_pref_shares, 0)) / EOK
    rates = _rates(con, as_of)
    # D/E points (own average) on the common market cap of each date
    de_n = None
    if SD.replaying():                  # P7-C3 public snapshot: only the own-average D/E (aggregate; no market caps)
        agg = SD.get("de_points", de_points_key(cfg))
        de_pts, de_n = [{"date": None, "debt": None, "lease": None, "mktcap": None, "de": agg["de"]}], agg["n"]
    else:
        de_pts = []
        for y, p in cfg["params"]["de_points"]:
            dt = f"{y}-12-31" if p == "FY" else f"{y}-06-30"
            b, m = _debt_at(con, corp, int(y), p, fs if sotp_mode else None), mp.mktcap_at(code, dt, con=con)
            if b and m:
                b = {**b, "debt": b["debt"] + reclass.get((int(y), p), 0.0)}
                de_pts.append({"date": dt, "debt": b["debt"] / EOK, "lease": b["lease"] / EOK, "mktcap": m / EOK,
                               "de": (b["debt"] + b["lease"]) / m})
        if de_pts:
            SD.put("de_points", de_points_key(cfg), {"de": float(pd.DataFrame(de_pts).de.mean()), "n": len(de_pts)})
    _close(con)
    market = {"shares_note": shares_note,
              "close": None if close is None else float(close), "mktcap_common": None if mcap_common is None else mcap_common / EOK,
              "common_out": common_out, "pref_out": pref_out,
              "shares_out": common_out + pref_out, "market_equity": market_equity, "de_points": pd.DataFrame(de_pts),
              "listed_pref": pref_listed, "de_n": de_n if de_n is not None else len(de_pts)}
    comp = Company(cfg, led, w, dna, lines, market, rates)
    comp.dna_rec = dna_rec
    if sotp_mode:                         # P7-B3 general SOTP (config/p7b3.yaml sotp)
        con = _con()
        try:
            comp.sotp = sotp_inputs(con, cfg, corp, fs, as_of)
        finally:
            _close(con)
        for (y, p), amt in comp.sotp["dividends"].items():      # dividends inside operating revenue -> out of the base
            if (y, p) in comp.w.index:
                for k in ("revenue", "operating_income"):
                    if k in comp.w.columns and pd.notna(comp.w.loc[(y, p), k]):
                        comp.w.loc[(y, p), k] -= amt / EOK
        comp.__dict__.pop("_val_cache", None)
        comp.__dict__.pop("_wraw_cache", None)
    if cfg.get("forecast", {}).get("method") == "mechanical_v2":     # P7-B2b auto-draft default path
        con = _con()
        try:
            comp.v2 = v2_inputs(comp, con)
        finally:
            _close(con)
    return comp


@_seam("dividends", key=lambda con, corp, fs: (corp, fs))
def dividends_in_revenue(con, corp: str, fs: str) -> dict:
    """{(year, period): 원} of '배당금수익' lines above the operating-income line of the income statement (operating
    revenue of the separate statements), per report (FY = 11011, H1 = 11012, year-to-date)."""
    rows = con.execute("""SELECT bsns_year, reprt_code, ord, account_id, account_nm, thstrm_num, thstrm_add_num FROM fs_raw
                          WHERE corp_code=? AND fs_div=? AND sj_div IN ('IS','CIS') AND reprt_code IN ('11011','11012')""",
                       [corp, fs]).df()
    out = {}
    for (y, rep), g in rows.groupby(["bsns_year", "reprt_code"]):
        nm = g.account_nm.astype(str).str.replace(" ", "")
        op = g[(g.account_id == "dart_OperatingIncomeLoss") | nm.str.startswith("영업이익") | nm.str.startswith("영업손실")]
        if op.empty:
            continue
        cut = op.ord.min()
        dv = g[nm.str.contains("배당금수익") & (g.ord < cut)]
        if dv.empty:
            continue
        col = "thstrm_num" if rep == "11011" else "thstrm_add_num"
        v = pd.to_numeric(dv[col], errors="coerce").fillna(pd.to_numeric(dv.thstrm_num, errors="coerce")).sum()
        if v:
            out[(int(y), "FY" if rep == "11011" else "H1")] = float(v)
    return out


def sotp_inputs(con, cfg: dict, corp: str, fs: str, as_of: str) -> dict:
    """Subsidiary rows of the draft with the as-of close of the directly held listed ones (market provider)."""
    st = cfg["structure"]
    rows = []
    for x in st.get("subsidiaries") or []:
        close = None
        if x.get("listed") and x.get("direct") and x.get("stock_code"):
            q = _quote(market_provider(), x["stock_code"], as_of, con)
            close = float(q[0]) if q and q[0] is not None else None
        rows.append({**x, "close": close})
    return {"rows": rows, "discount": float(st.get("discount", {}).get("base", 0.0)),
            "sensitivities": list(st.get("discount", {}).get("sensitivities", [])), "dividends": dividends_in_revenue(con, corp, fs)}


def sotp_book_all(rows: list[dict]) -> float:
    """Book value (원) of the consolidated investees the parent holds (타법인 출자현황)."""
    return sum(float(x.get("book") or 0) for x in rows if x.get("direct") or (x.get("book") or 0) > 0)


def sub_line_mask(lines: pd.DataFrame, book_all: float) -> pd.Series:
    """Separate balance-sheet lines that hold the subsidiaries: names with '종속'; when there is none but the parent
    holds subsidiaries at book (P7-B3 B3-F6, e.g. 삼지전자 '관계기업및공동기업투자'), the 관계기업·공동기업·지분법 lines."""
    nm = lines.account_nm.astype(str).str.replace(" ", "")
    sec = lines.section.isin(["CA", "NCA"])
    m = nm.str.contains("종속") & sec
    if not m.any() and book_all > 0:
        m = nm.str.contains("관계기업|공동기업|지분법") & sec
    return m


def sotp_parts(lines: pd.DataFrame, rows: list[dict], discount: float) -> dict:
    """Pure SOTP bridge pieces (원): non-subsidiary lines classified as before, the '종속' lines replaced by
    listed (shares x close x (1 − discount)) + unlisted book + the associates' share of combined lines."""
    from src.valuation.peer_p3 import classify
    book_all = sotp_book_all(rows)
    mask = sub_line_mask(lines, book_all)
    cl = classify(lines[~mask].reset_index(drop=True))
    sub_lines = float(lines.amount[mask].sum())
    listed = sum((x.get("shares") or 0) * (x.get("close") or 0) for x in rows if x.get("listed") and x.get("direct"))
    missing_close = [x["name"] for x in rows if x.get("listed") and x.get("direct") and not x.get("close")]
    unlisted = sum(float(x.get("book") or 0) for x in rows if not x.get("listed"))
    remainder = max(sub_lines - book_all, 0.0)
    return {"cl": cl, "sub_lines": sub_lines, "book_all": book_all, "listed": listed, "unlisted": unlisted, "remainder": remainder,
            "discount": discount, "unit_ok": book_all <= sub_lines * 1.02 + 1, "missing_close": missing_close,
            "non_operating": cl["non_operating"] + remainder + listed * (1 - discount) + unlisted}


def v2_rules() -> dict:
    return yaml.safe_load((ROOT / "config" / "p7b2b.yaml").read_text(encoding="utf-8"))["mechanical_v2"]


@_seam("peer_metrics", key=lambda con, cfg, tiers: (int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"],
                                                  [[x["corp_code"], x["tier"]] for x in cfg.get("peers", [])], list(tiers)))
def peer_metrics(con, cfg: dict, tiers) -> list[dict]:
    """LTM operating margin and revenue growth (FY(Y−3) → FY(Y−1) 2-year CAGR, else 1-year) of the included peers."""
    from src.valuation.peer_table import basis
    y, p = int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"]
    out = []
    for x in cfg.get("peers", []):
        if x["tier"] not in tiers:
            continue
        fs = basis(con, x["corp_code"], y, p)
        d = con.execute("""SELECT fiscal_year, period, std_account, amount FROM fs_std WHERE corp_code=? AND fs_div=? AND is_default
                           AND std_account IN ('revenue','operating_income')""", [x["corp_code"], fs]).fetchall()
        v = {(int(a), b, k): float(m) for a, b, k, m in d if m is not None}
        g = lambda k, yy, pp: v.get((yy, pp, k))  # noqa: E731
        lt = {k: (g(k, y - 1, "FY") + g(k, y, p) - g(k, y - 1, p)) if None not in (g(k, y - 1, "FY"), g(k, y, p), g(k, y - 1, p))
              else None for k in ("revenue", "operating_income")}
        r1, r3, r2 = g("revenue", y - 1, "FY"), g("revenue", y - 3, "FY"), g("revenue", y - 2, "FY")
        growth = (r1 / r3) ** 0.5 - 1 if r1 and r3 and r1 > 0 and r3 > 0 else (r1 / r2 - 1 if r1 and r2 and r2 > 0 else None)
        margin = lt["operating_income"] / lt["revenue"] if lt["revenue"] and lt["revenue"] > 0 and lt["operating_income"] is not None else None
        out.append({"name": x["name"], "margin": margin, "growth": growth})
    return out


def v2_inputs(c: "Company", con) -> dict:
    """config/p7b2b.yaml mechanical_v2: start margin (5-year median), convergence amount toward the peer margin median,
    start growth (own CAGR blended with the peer growth median, clipped)."""
    r = v2_rules()
    h = history(c)
    yrs = [y for y in range(2021, 2026) if val(c, "revenue", y) > 0]
    ms = [val(c, "operating_income", y) / val(c, "revenue", y) for y in yrs]
    m0 = v2_start_margin(ms, h["margin"])
    m_src = f"FY{yrs[0]}~{yrs[-1]} 영업이익률 중앙값({len(ms)}년)" if len(ms) >= 3 else "v1 3년 평균(자료 3년 미만)"
    pm_all = peer_metrics(con, c.cfg, c.cfg["beta"]["peer_tiers"])
    pms = [x["margin"] for x in pm_all if x["margin"] is not None]
    pgs = [x["growth"] for x in pm_all if x["growth"] is not None]
    pm = float(np.median(pms)) if len(pms) >= 3 else None
    pg = float(np.median(pgs)) if len(pgs) >= 3 else None
    share = r["normal_margin"]["converge_share"]
    fc = c.cfg.get("forecast") or {}
    start = fc.get("v2_start", "median5")
    if start == "ltm":                  # P7-B3b loss path (config/p7b3b.yaml loss_path.method.b_transition_dcf)
        lr = ltm(c, "revenue")
        m0 = ltm(c, "operating_income") / lr if lr > 0 else m0
        m_src = "LTM 영업이익률(적자 경로: FY2025 + 2026 H1 − 2025 H1)"
        share = float(fc.get("converge_share", share))
    w, (lo, hi) = r["start_growth"]["weight_own"], r["start_growth"]["clip"]
    v = {"m0": m0, "m0_src": m_src, "m0_years": yrs, "start": start, "peer_margin": pm, "peer_margin_n": len(pms), "conv_share": share,
         "conv_amt": share * (pm - m0) if pm is not None else 0.0, "own_cagr": h["cagr"], "peer_growth": pg,
         "peer_growth_n": len(pgs), "weight_own": w, "clip": [lo, hi], "g0": v2_start_growth(h["cagr"], pg, w, lo, hi),
         "peers": pm_all, "m0_auto": m0}
    return v2_apply(v, overrides_of(c.cfg))


def overrides_of(cfg: dict) -> dict:
    """P7-C1 workbench: confirmed assumptions of a session config (config/p7c1.yaml assumptions); empty for drafts/RF/JW."""
    return dict(cfg.get("overrides") or {})


def v2_apply(v: dict, ov: dict) -> dict:
    """Session overrides on the v2 inputs: normal margin (start m0; the convergence toward the peer median is recomputed)
    and start growth (replaces the clipped blend)."""
    v = dict(v)
    v["g0_auto"] = v.get("g0_auto", v["g0"])
    if ov.get("normal_margin") is not None:
        v["m0"] = float(ov["normal_margin"])
        v["m0_src"] = "사람 확정값(평가 세션)"
    if v.get("peer_margin") is not None:
        v["conv_amt"] = v["conv_share"] * (v["peer_margin"] - v["m0"])
    if ov.get("g_start") is not None:
        v["g0"] = float(ov["g_start"])
    return v


def v2_start_margin(margins: list[float], fallback: float) -> float:
    """Median of the available yearly margins when there are 3 or more, else the v1 fallback (3-year average)."""
    return float(np.median(margins)) if len(margins) >= 3 else fallback


def v2_start_growth(own: float, peer: float | None, w: float, lo: float, hi: float) -> float:
    """clip(w x own + (1 − w) x peer, lo, hi); own only when there is no peer median."""
    blend = w * own + (1 - w) * peer if peer is not None else own
    return float(min(max(blend, lo), hi))


def margin_path(m_start: float, conv: float, year: int, Y: int) -> float:
    """v2 margin of a forecast year: start + conv x min((year − Y) / (EXPLICIT_END − Y), 1)."""
    return m_start + conv * min((year - Y) / (EXPLICIT_END - Y), 1.0)


def val(c: Company, k: str, y: int, p: str = "FY") -> float:
    """Statement value (억원, 0 if missing). P7-C1 speed: memoised per statements frame (same values; the frame is not
    changed after load_company)."""
    cache = c.__dict__.setdefault("_val_cache", {})
    key = (id(c.w), k, y, p)
    if key in cache:
        return cache[key]
    try:
        v = c.w.loc[(y, p), k]
        out = 0.0 if pd.isna(v) else float(v)
    except KeyError:
        out = 0.0
    cache[key] = out
    return out


def _w_raw(c: Company, k: str):
    """c.w at (Y, P) for the bridge cache key (None if missing), memoised like val."""
    cache = c.__dict__.setdefault("_wraw_cache", {})
    key = (id(c.w), k, c.Y, c.P)
    if key not in cache:
        cache[key] = c.w.loc[(c.Y, c.P), k] if (c.Y, c.P) in c.w.index and k in c.w.columns else None
    return cache[key]


def history(c: Company) -> dict:
    yrs = c.cfg["params"]["avg_years"]
    y0, y1 = c.cfg["params"]["cagr_years"]
    rows = {}
    for y in sorted(set(yrs) | {y0, y1}):
        rev = val(c, "revenue", y)
        rows[y] = {"revenue": rev, "op": val(c, "operating_income", y), "cogs": val(c, "cogs", y),
                   "dna": float(c.dna.get((y, "FY"), np.nan)),
                   "capex": val(c, "capex_ppe", y) + val(c, "capex_intangibles", y),
                   "rec": val(c, "receivables", y), "inv": val(c, "inventories", y), "pay": val(c, "trade_payables", y),
                   "ic": (val(c, "receivables", y) + val(c, "inventories", y) - val(c, "trade_payables", y)
                          + val(c, "ppe", y) + val(c, "intangibles", y) + val(c, "rou_assets", y))}
    h = pd.DataFrame(rows).T
    a = h.loc[yrs]
    out = {"table": h, "cagr": cagr(h.loc[y0, "revenue"], h.loc[y1, "revenue"], y1 - y0),
           "margin": float((a.op / a.revenue).mean()), "dna_ratio": float((a.dna / a.revenue).mean()),
           "capex_ratio": float((a.capex / a.revenue).mean()), "cogs_ratio": float((a.cogs / a.revenue).mean()),
           "dso": _days(a.rec, a.revenue), "dio": _days(a.inv, a.cogs), "dpo": _days(a.pay, a.cogs)}
    return out


def _days(num: pd.Series, den: pd.Series) -> float:
    """P7-B3 B3-F5: turnover days, mean over years with a non-zero base (holding companies without 매출원가); no such
    year -> 0 days. The Excel days rows use the same rule (IF base = 0 -> text, COUNT = 0 -> 0)."""
    x = (num / den.where(den != 0) * 365).dropna()
    return float(x.mean()) if len(x) else 0.0


def tax_fn(c: Company):
    br = c.led["corporate_tax"]["brackets"]
    return lambda b: progressive_tax(b * EOK, br) / EOK


def eff(c: Company, ebit: float) -> float:
    return tax_fn(c)(ebit) / ebit if ebit > 0 else 0.0


def hist_roic(c: Company, h: dict) -> float:
    t = h["table"]
    vals = []
    for y in c.cfg["params"]["avg_years"]:
        ic_open = (val(c, "receivables", y - 1) + val(c, "inventories", y - 1) - val(c, "trade_payables", y - 1)
                   + val(c, "ppe", y - 1) + val(c, "intangibles", y - 1) + val(c, "rou_assets", y - 1))
        nopat = t.loc[y, "op"] * (1 - eff(c, t.loc[y, "op"]))
        if ic_open > 0:
            vals.append(nopat / ic_open)
    return float(np.mean(vals)) if vals else float("nan")       # P7-B5: no positive opening capital -> NaN (handled later)


# ---------------------------------------------------------------- forecast and value

def forecast(c: Company, h: dict, growth_shift: float = 0.0, margin_shift: float = 0.0,
             g_start_override: float | None = None) -> pd.DataFrame:
    gT = c.cfg["forecast"]["human"]["g_terminal"]
    v2 = c.v2
    base_g = v2["g0"] if v2 else h["cagr"]
    g0 = (base_g + growth_shift) if g_start_override is None else g_start_override
    Y, years = c.Y, explicit_years(c)
    gp = growth_path(g0, gT, Y, c.cfg["params"]["fade_to_terminal_by"], [Y] + years)
    m = (v2["m0"] if v2 else h["margin"]) + margin_shift
    conv = v2["conv_amt"] if v2 else 0.0            # P7-B2b v2: margin converges toward the peer median by 2032
    rev_fy = {Y: val(c, "revenue", c.FY) * (1 + gp[Y])}
    for y in years:
        rev_fy[y] = rev_fy[y - 1] * (1 + gp[y])
    h1_rev, h1_op = val(c, "revenue", Y, c.P), val(c, "operating_income", Y, c.P)
    nwc0 = val(c, "receivables", Y, c.P) + val(c, "inventories", Y, c.P) - val(c, "trade_payables", Y, c.P)

    def nwc(y):
        r = rev_fy[y]
        cg = r * h["cogs_ratio"]
        return r * h["dso"] / 365 + cg * h["dio"] / 365 - cg * h["dpo"] / 365
    rows, prev = [], nwc0
    first_start = date.fromordinal(date.fromisoformat(c.cfg["meta"]["bs_date"]).toordinal() + 1)
    for lab, y, start in [(c.first, Y, first_start)] + [(str(y), y, date(y, 1, 1)) for y in years]:
        rev = rev_fy[Y] - h1_rev if lab == c.first else rev_fy[y]
        ebit = rev * (margin_path(m, conv, y, Y) if v2 else m)
        cur = nwc(y)
        rows.append({"label": lab, "year": y, "start": start, "end": date(y, 12, 31), "revenue": rev, "growth": gp[y],
                     "ebit": ebit, "fy_ebit": h1_op + ebit if lab == c.first else ebit, "dna": rev * h["dna_ratio"],
                     "capex": rev * h["capex_ratio"], "nwc": cur, "dnwc": cur - prev})
        prev = cur
    t = pd.DataFrame(rows)
    t.attrs.update({"g_start": g0, "margin": m, "margin_end": m + conv, "rev_fy": rev_fy, "gT": gT})
    return t


def discount_rate(c: Company, srp: float, beta_u: float, de: float, kd: float, mode: str = "hamada") -> float:
    r, mrp = c.rates[rf_code(c.led)], c.led["mrp"]["value"]
    ltm_pretax = ltm(c, "pretax_income")
    t_kd = marginal_rate(ltm_pretax * EOK, c.led["corporate_tax"]["brackets"])
    if mode == "harris_pringle":
        return wacc_hp(r, mrp, beta_u, de, kd, t_kd, srp).wacc
    return wacc(r, mrp, beta_u, de, kd, c.cfg["beta"]["tax"], t_kd, srp).wacc


def dcf_value(c: Company, h: dict, t: pd.DataFrame, w: float, roic_cap: float, g: float | None = None,
              ronic_override: float | None = None) -> dict:
    tx = tax_fn(c)
    gT = t.attrs["gT"] if g is None else g
    yrs = [str(y) for y in explicit_years(c)]
    # P7-C1 speed: plain lists instead of repeated DataFrame lookups (same floats, same arithmetic order)
    col = {k: t[k].tolist() for k in ("label", "start", "end", "ebit", "dna", "capex", "dnwc", "fy_ebit", "revenue", "growth")}
    ix = {lab: i for i, lab in enumerate(col["label"])}
    fy26 = col["fy_ebit"][ix[c.first]]
    if c.ronic_start == "normal":       # P3-C3 common rule: start NOPAT = FY revenue x normal margin (no mixing)
        from src.valuation.common_rules import start_nopat
        n26 = start_nopat(t.attrs["rev_fy"][c.Y], t.attrs["margin"], tax_fn(c))
    else:
        n26 = fy26 * (1 - eff(c, fy26))
    e32 = col["ebit"][ix["2032"]]
    n32 = e32 * (1 - eff(c, e32))
    reinv = float(np.array([col["capex"][ix[y]] - col["dna"][ix[y]] + col["dnwc"][ix[y]] for y in yrs]).sum())
    r_calc = (n32 - n26) / reinv if reinv else float("nan")
    R, why = bounded_ronic(r_calc, reinv, w, roic_cap) if ronic_override is None else (ronic_override, "지정")
    periods = [Period(col["label"][i], col["start"][i], col["end"][i], col["ebit"][i], col["dna"][i], col["capex"][i],
                      col["dnwc"][i], tax_base=col["fy_ebit"][i]) for i in range(len(col["label"]))]
    m = t.attrs.get("margin_end", t.attrs["margin"])     # fade and terminal margin (v1: the normal margin, v2: path end)
    prev = col["revenue"][ix["2032"]]
    g32 = col["growth"][ix["2032"]]
    for y, gy in zip(FADE, fade_path(g32, gT, len(FADE))):
        rev = prev * (1 + gy)
        ebit = rev * m
        nopat = ebit * (1 - eff(c, ebit))
        periods.append(Period(str(y), date(y, 1, 1), date(y, 12, 31), ebit, 0.0, nopat * gy / R, 0.0, tax_base=ebit))
        prev = rev
    rev_next = prev * (1 + gT)
    ebit_next = rev_next * m
    nopat_next = ebit_next * (1 - eff(c, ebit_next))
    fcf_norm = nopat_next * (1 - gT / R) / (1 + gT)
    r = run_dcf(periods, tx, w, date.fromisoformat(c.cfg["meta"]["bs_date"]), g=gT, mid_year=c.cfg["forecast"]["mid_year"],
                fcf_norm=fcf_norm, ebitda_final=prev * m + prev * h["dna_ratio"])
    days = (date.fromisoformat(c.cfg["meta"]["as_of"]) - date.fromisoformat(c.cfg["meta"]["bs_date"])).days
    ev = roll_forward(r.ev_gordon, w, days)
    br = bridge(c)
    eq = ev - br["net_debt"] + br["non_operating"] - br["nci"]
    return {"wacc": w, "ronic": R, "ronic_calc": r_calc, "ronic_why": why, "ev": ev, "equity": eq,
            "per_share": eq * EOK / c.market["shares_out"], "tv_share": r.tv_share_gordon,
            "implied_multiple": r.implied_multiple, "r": r}


def bridge(c: Company) -> dict:
    """EV -> equity items (억원). P7-B5 cache: the result depends only on the balance-sheet lines, the statements
    frame and the SOTP rows/discount, so it is kept on the company per that key (same values, ~500 calls per model)."""
    ov = overrides_of(c.cfg)
    key = (id(c.bs_lines), id(c.w), None if not c.sotp else (id(c.sotp["rows"]), c.sotp["discount"]),
           ov.get("cash_adjust_mn"), ov.get("nci_mn"),
           tuple(_w_raw(c, k) for k in ("total_debt", "lease_liabilities", "nci")))
    cache = c.__dict__.setdefault("_bridge_cache", {})
    if key not in cache:
        cache[key] = _bridge(c)
    return dict(cache[key])


def _bridge(c: Company) -> dict:
    """P7-C1: session overrides cash_adjust_mn (operating cash taken out of cash-like, 백만원) and nci_mn (NCI, 백만원)."""
    b = _bridge_raw(c)
    ov = overrides_of(c.cfg)
    if ov.get("cash_adjust_mn") is not None:
        adj = float(ov["cash_adjust_mn"]) / 100.0
        b = {**b, "cash_like": b["cash_like"] - adj, "net_debt": b["net_debt"] + adj}
    if ov.get("nci_mn") is not None:
        b = {**b, "nci": float(ov["nci_mn"]) / 100.0}
    return b


def _bridge_raw(c: Company) -> dict:
    from src.valuation.peer_p3 import classify
    if c.sotp:                            # P7-B3: subsidiaries replace the '종속' investment lines
        sp = sotp_parts(c.bs_lines, c.sotp["rows"], c.sotp["discount"])
        debt = val(c, "total_debt", c.Y, c.P) + val(c, "lease_liabilities", c.Y, c.P)
        cash = sp["cl"]["cash_like"] / EOK
        return {"total_debt": debt, "cash_like": cash, "net_debt": debt - cash, "non_operating": sp["non_operating"] / EOK,
                "nci": val(c, "nci", c.Y, c.P), "cash_detail": sp["cl"]["cash_like_detail"], "nonop_detail": sp["cl"]["non_op_detail"],
                "sotp": {k: (v / EOK if isinstance(v, float) and k not in ("discount",) else v) for k, v in sp.items() if k != "cl"}}
    cl = classify(c.bs_lines)
    debt = val(c, "total_debt", c.Y, c.P) + val(c, "lease_liabilities", c.Y, c.P)
    cash = cl["cash_like"] / EOK
    return {"total_debt": debt, "cash_like": cash, "net_debt": debt - cash, "non_operating": cl["non_operating"] / EOK,
            "nci": val(c, "nci", c.Y, c.P), "cash_detail": cl["cash_like_detail"], "nonop_detail": cl["non_op_detail"]}


def ltm(c: Company, k: str) -> float:
    return val(c, k, c.FY) + val(c, k, c.Y, c.P) - val(c, k, c.FY, c.P)


def ltm_dna(c: Company) -> tuple[float | None, str]:
    from src.valuation.peer_table import dna_ltm_checked
    con = _con()
    try:
        if "draft_meta" in c.cfg:           # P7-B2b: filled D&A for auto drafts
            dw = draft_dna(con, c.cfg)[0]
        else:
            dw = dna_wide_of(con, c.cfg["target"]["corp_code"], fs_div(c.cfg))
    finally:
        _close(con)
    return dna_ltm_checked(dw, val(c, "revenue", c.FY) * EOK, c.cfg["params"]["ebitda_rule"], c.Y, c.P)


def solve_g_start(c: Company, h: dict, w: float, cap: float, target_ps: float, margin_shift: float = 0.0) -> float | None:
    def f(g0):
        return dcf_value(c, h, forecast(c, h, margin_shift=margin_shift, g_start_override=g0), w, cap)["per_share"] - target_ps
    lo, hi = -0.30, 0.60
    try:
        if f(lo) > 0 or f(hi) < 0:
            return None
    except ValueError:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def bisect(f, lo: float, hi: float, n: int = 60) -> float | None:
    """Root of a monotone f on [lo, hi] (None if f has the same sign at both ends)."""
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(n):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def md(df: pd.DataFrame, fmt: str = "{:,.1f}") -> str:
    from src.valuation.rf_dcf import md as _md
    return _md(df, fmt)


def actual_rate(cfg: dict) -> float | None:
    """Weighted rate of config kd.actual (None when no amount, e.g. a draft without borrowings)."""
    rows = cfg["kd"].get("actual") or []
    tot = sum(x["amount"] for x in rows)
    return sum(x["rate"] * x["amount"] for x in rows) / tot if tot > 0 else None


def kd_for(c: Company, version: str) -> tuple[float, str, dict]:
    """C2: actual weighted rate (370efdb rule). C3: common rating-band rule with the Rf floor.
    P7-B drafts without a rating: kd.method 'implied' = interest expense ÷ average debt (kd.actual), floored at Rf."""
    act = actual_rate(c.cfg)
    rf = c.rates[rf_code(c.led)]
    if version == "c2":
        if act is None:
            return c.rates["CB3Y_BBBm"], "실제 차입 없음 → BBB- 3년", {}
        return act, f"실제 가중 약정이자율 {act:.3%}", {}
    if c.cfg["kd"].get("method") == "implied" and act is not None:
        kd = max(act, rf)
        lab = f"이자비용 ÷ 평균 차입금 {act:.3%}" + (f" → Rf 하한 {rf:.3%}" if kd > act else "")
        return kd, lab, {"BBB- 3년": c.rates["CB3Y_BBBm"]}
    from src.valuation.common_rules import kd_choice
    k = kd_choice(c.cfg["kd"].get("rating"), act, c.rates, rf)
    return k["kd"], k["label"], k["sensitivity"]


def main(cfg_path: str, version: str = "c2", fig_dir: Path | None = None) -> str:
    """fig_dir: where the football figure goes (default reports/figures, as in P3-C2/C3; the P7-B pipeline uses its
    outputs folder)."""
    from src.premium.predict import premium_range
    from src.valuation.p3c1 import block_range, football_rows, hp_unlever, multiple_stats
    from src.valuation.peer_p3 import build as build_peers
    from src.valuation.structure import decide
    c = load_company(cfg_path)
    c.ronic_start = "normal" if version == "c3" else "mixed"
    base_name = Path(cfg_path).stem.replace("valuation_", "")
    name = base_name if version == "c2" else f"{base_name}_{version}"
    cfg, mk, out = c.cfg, c.market, []
    price = mk["close"]
    # peers (tables beta_<name>, peer_<name>)
    bt = market_provider().beta_table(cfg["meta"]["as_of"], cfg_path, f"beta_{base_name}")
    rule = {**cfg["params"]["ebitda_rule"], "ltm_year": c.Y, "ltm_period": c.P, "supplement": version == "c3",
            "fill": "draft_meta" in cfg}     # P7-B2b: drafts fill peer D&A period by period (원문 → 보완, no estimate)
    pp = build_peers(cfg_path, f"peer_{name}", cfg["meta"]["as_of"], rule)
    tiers = cfg["beta"]["peer_tiers"]
    sel = bt[bt.tier.isin(tiers) & (bt.spec == cfg["beta"]["spec"])]
    beta_tab = (sel.pivot_table(index="name", columns="index", values=["blume", "bu_avg", "r2", "de_avg"]) if len(sel)
                else pd.DataFrame())                       # P7-B5: no peer betas
    bsel = bt[bt.spec == cfg["beta"]["spec"]] if len(bt) else bt
    bu = {ix: beta_u0(bsel, cfg, ix)[0] for ix in ("KOSPI", "KOSDAQ")}
    de_peer = float(sel[sel["index"] == cfg["beta"]["index"]].de_avg.median()) if len(sel) else float("nan")
    de_own = float(mk["de_points"].de.mean())
    kd_base, kd_label, _ = kd_for(c, version)
    kd_act = actual_rate(cfg)
    kd_act = kd_base if kd_act is None else kd_act
    kn = cfg["params"]["kd_notch"]
    kd_notch = notch_kd(c.rates[kn["from"]], c.rates[kn["to"]], kn["steps"], kn["at"])
    h = history(c)
    cap = hist_roic(c, h)
    srps = c.led["decisions"]["srp_columns"]
    bu0 = bu[cfg["beta"]["index"]]
    w_base = {s: discount_rate(c, s, bu0, de_own, kd_base) for s in srps}

    if version != "c2":                 # P3-C3: beta reliability table and warning (display only)
        from src.valuation.common_rules import beta_reliability
        idx = cfg["beta"]["index"]
        s_ = sel[sel["index"] == idx]
        rel_b = beta_reliability(s_.r2)
        out.append(f"## 베타 신뢰성 ({idx}, 주간 2년)\n\n" + md(s_.set_index("name")[[
            "raw", "se", "r2", "blume", "de_avg", "bu_avg", "bu_raw_avg"]].astype(float), "{:.3f}"))
        out.append(f"\n피어 R² 중앙값 {rel_b['r2_median']:.3f} → {rel_b['text'] or '경고 없음'}. "
                   f"βu 중앙값: Blume {bu0:.3f}, 원 회귀 {float(s_.bu_raw_avg.median()):.3f}\n")
        out.append(f"Kd(공통 규칙): {kd_label}\n")

    # ---- structure
    sub = c.cfg["structure"].get("subsidiary")
    sub_mc = None
    if c.cfg["structure"]["listed_subsidiary"]:
        sub_mc = market_provider().mktcap_at(sub["stock_code"], cfg["meta"]["as_of"]) / EOK
    si = structure_inputs(c.cfg, h["margin"], val(c, "nci", c.Y, c.P), sub_mc)
    dec = decide(si["nci_value"], mk["market_equity"], si["listed"], si["segments"])
    out.append(f"## 구조 판단\n\n- 판정 **{dec.method}** — " + "; ".join(dec.reasons) + "\n")

    # ---- inputs
    br = bridge(c)
    out.append("## 입력\n")
    out.append(md(pd.DataFrame({"값": [h["cagr"] * 100, h["margin"] * 100, h["dna_ratio"] * 100, h["capex_ratio"] * 100,
                                      h["cogs_ratio"] * 100, h["dso"], h["dio"], h["dpo"], cap * 100, bu0, bu["KOSDAQ"],
                                      de_own, de_peer, kd_act * 100, kd_notch * 100, c.rates["CB3Y_AAm"] * 100,
                                      c.rates["CB3Y_BBBm"] * 100, w_base[0.0] * 100]},
                              index=["매출 5년 CAGR(%)", "영업이익률 3년(%)", "D&A/매출 3년(%)", "CAPEX/매출 3년(%)", "매출원가율 3년(%)",
                                     "DSO", "DIO", "DPO", "과거 3년 ROIC(%) = RONIC 상한", "βu 피어 중앙값(KOSPI)",
                                     "βu 피어 중앙값(KOSDAQ)", "D/E 자체 평균", "D/E 피어 중앙값", "Kd 실제(%)", "Kd 등급 보간 A-(%)",
                                     "Kd AA-(%)", "Kd BBB-(%)", "WACC 기본 SRP 0(%)"]).rename_axis("항목"), "{:,.3f}"))
    out.append("\n" + md(h["table"].astype(float).rename_axis("연도(억원)")))
    out.append("\nD/E 시점\n\n" + md(mk["de_points"].set_index("date"), "{:,.3f}"))
    out.append(f"\n브리지({cfg['meta']['bs_date']}): 총차입금(리스 포함) {br['total_debt']:.1f}, 현금성 {br['cash_like']:.1f}({br['cash_detail']}), "
               f"순차입금 {br['net_debt']:.1f}, 비영업 {br['non_operating']:.1f}({br['nonop_detail']}), 비지배 {br['nci']:.2f}억; "
               f"시장 주식가치 {mk['market_equity']:,.1f}억(보통주 시총 {mk['mktcap_common']:,.1f}), 유통주식 {mk['shares_out']:,}주\n")

    # ---- DCF table
    res = []
    for sc, sh in cfg["scenarios"]["human"].items():
        t = forecast(c, h, sh["growth_shift"], sh["margin_shift"])
        for s in srps:
            v = dcf_value(c, h, t, w_base[s], cap)
            res.append({"scenario": sc, "srp": s, **{k: v[k] for k in ("wacc", "ronic", "ronic_why", "ev", "equity",
                                                                        "per_share", "tv_share", "implied_multiple")},
                        "g_start": t.attrs["g_start"], "margin": t.attrs["margin"]})
    R = pd.DataFrame(res)
    order = ["pessimistic", "base", "optimistic"]
    for col, lab, f in (("per_share", "주당 가치(원)", "{:,.0f}"), ("wacc", "WACC", "{:.2%}"), ("ronic", "RONIC", "{:.1%}"),
                        ("ev", "EV(9/30, 억원)", "{:,.1f}"), ("tv_share", "영구가치 비중", "{:.1%}"),
                        ("implied_multiple", "Gordon 함의 EV/EBITDA(2040)", "{:.1f}")):
        pv = R.pivot(index="scenario", columns="srp", values=col).loc[order]
        pv.columns = [f"SRP {x:.0%}" for x in pv.columns]
        pv.index.name = lab
        out.append("\n" + md(pv, f))
    vs = R.pivot(index="scenario", columns="srp", values="per_share").loc[order] / price - 1
    vs.columns = [f"SRP {x:.0%}" for x in vs.columns]
    vs.index.name = f"종가 {price:,.0f}원 대비"
    out.append("\n" + md(vs, "{:+.1%}"))
    out.append("\nRONIC 판정: " + "; ".join(f"{r.scenario} {r.ronic_why}" for r in R[R.srp == 0].itertuples()))
    tb = forecast(c, h)
    vb = dcf_value(c, h, tb, w_base[0.0], cap)
    ft = tb.set_index("label")[["revenue", "growth", "ebit", "dna", "capex", "dnwc"]].T
    out.append("\n기본 경로(억원)\n\n" + md(ft.astype(float), "{:,.3f}"))

    # ---- sensitivities
    sens = {}
    for dw in (-0.02, -0.01, 0, 0.01, 0.02):
        for g in (0.01, 0.015, 0.02, 0.025, 0.03):
            sens[(f"{w_base[0.0] + dw:.2%}", f"g {g:.1%}")] = dcf_value(c, h, tb, w_base[0.0] + dw, cap, g=g)["per_share"]
    s1 = pd.Series(sens).unstack()
    s1 = s1.loc[sorted(s1.index, key=lambda x: float(x.strip('%')))]
    s1.index.name = "WACC \\ g"
    out.append("\n## 민감도\n\n" + md(s1, "{:,.0f}"))
    sens2 = {}
    for gs in (-0.04, -0.02, 0, 0.02, 0.04):
        for ms in (-0.04, -0.02, 0, 0.02, 0.04):
            sens2[(f"성장 {gs:+.0%}p", f"이익률 {ms:+.0%}p")] = dcf_value(c, h, forecast(c, h, gs, ms), w_base[0.0], cap)["per_share"]
    s2 = pd.Series(sens2).unstack()
    s2.index.name = "출발 성장률 이동 \\ 이익률 이동"
    out.append("\n" + md(s2, "{:,.0f}"))
    peer_hp = {}
    for lab, kd in (("BBB-", c.rates["CB3Y_BBBm"]), ("AA-", c.rates["CB3Y_AAm"]), ("실제", kd_act)):
        bd = debt_beta(kd, c.rates[rf_code(c.led)], c.led["mrp"]["value"])
        s_ = sel[sel["index"] == cfg["beta"]["index"]]
        peer_hp[lab] = float(np.median([hp_unlever(b, bd, d) for b, d in zip(s_.blume, s_.de_avg)]))
    alt = []
    base_lab = "기본: 자체 D/E, Kd 실제, Hamada" if version == "c2" else f"기본: 자체 D/E, Kd {kd_base:.3%}(공통 규칙), Hamada"
    for lab, de, kd, mode, b in ((base_lab, de_own, kd_base, "hamada", bu0),
                                 ("D/E 피어 중앙값", de_peer, kd_base, "hamada", bu0), ("D/E 0", 0.0, kd_base, "hamada", bu0),
                                 ("Kd AA-", de_own, c.rates["CB3Y_AAm"], "hamada", bu0),
                                 ("Kd BBB-", de_own, c.rates["CB3Y_BBBm"], "hamada", bu0),
                                 ("Kd 등급 보간(A-)", de_own, kd_notch, "hamada", bu0),
                                 ("Harris–Pringle(HP βu), Kd 실제", de_own, kd_act, "harris_pringle", peer_hp["실제"]),
                                 ("Harris–Pringle(HP βu), Kd BBB-", de_own, c.rates["CB3Y_BBBm"], "harris_pringle", peer_hp["BBB-"]),
                                 ("βu KOSDAQ 지수", de_own, kd_base, "hamada", bu["KOSDAQ"])):
        w_ = discount_rate(c, 0.0, b, de, kd, mode)
        alt.append({"경우": lab, "βu": b, "WACC": w_ * 100, "주당(원)": dcf_value(c, h, tb, w_, cap)["per_share"]})
    if version != "c2":                 # P3-C3 beta sensitivities: raw regression beta, monthly 5y Blume
        idx = cfg["beta"]["index"]
        b_raw = float(sel[sel["index"] == idx].bu_raw_avg.median())
        m5 = bt[bt.tier.isin(tiers) & (bt.spec == "monthly_5y") & (bt["index"] == idx)]
        b_m5 = float(m5.bu_avg.median()) if len(m5) else float("nan")
        for lab, b in ((f"β 원 회귀(C2에서도 기본은 Blume였음), {idx}", b_raw), (f"β 월간 5년 Blume, {idx}", b_m5)):
            w_ = discount_rate(c, 0.0, b, de_own, kd_base)
            alt.append({"경우": lab, "βu": b, "WACC": w_ * 100, "주당(원)": dcf_value(c, h, tb, w_, cap)["per_share"]})
    out.append("\n" + md(pd.DataFrame(alt).set_index("경우"), "{:,.3f}"))
    for lab, ro in (("RONIC = WACC", w_base[0.0]), ("RONIC = 1.5 × WACC", 1.5 * w_base[0.0])):
        out.append(f"- {lab}: {dcf_value(c, h, tb, w_base[0.0], cap, ronic_override=ro)['per_share']:,.0f}원")

    # ---- reverse DCF
    gr = solve_g_start(c, h, w_base[0.0], cap, price)
    w_imp = bisect(lambda x: dcf_value(c, h, tb, x, cap)["per_share"] - price, 0.03, 0.30)
    m_imp = bisect(lambda ms: dcf_value(c, h, forecast(c, h, 0.0, ms), w_base[0.0], cap)["per_share"] - price, -0.12, 0.10)
    g_txt = "없음(범위 밖)" if gr is None else f"{gr:.2%}"
    w_txt = "없음" if w_imp is None else f"{w_imp:.2%}"
    m_txt = "없음" if m_imp is None else f"{h['margin'] + m_imp:.2%} (이동 {m_imp:+.2%}p)"
    out.append(f"\n## 역DCF\n\n- 종가 {price:,.0f}원을 맞추는 출발 성장률 g_2026(2030년까지 g로 체감, 탐색 −30%~+60%): "
               f"{g_txt} (기본 = 5년 CAGR {h['cagr']:.2%})")
    out.append(f"- 보조: 같은 경로·이익률에서 종가를 맞추는 WACC {w_txt}; 기본 성장·WACC에서 필요한 정상 이익률 {m_txt}\n")

    # ---- relative
    pr = pp[pp.tier.isin(tiers)]
    eb, eb_why = ltm_dna(c)
    m_rev, m_ebitda = ltm(c, "revenue"), (ltm(c, "operating_income") + eb / EOK if eb else None)
    m_ni = ltm(c, "net_income_parent") or ltm(c, "net_income")
    m_eq = val(c, "equity_parent", c.Y, c.P) or (val(c, "total_equity", c.Y, c.P) - val(c, "nci", c.Y, c.P))
    rel = []
    for nm, col, kind, metric in (("EV/Sales", "ev_sales", "ev", m_rev), ("EV/EBITDA", "ev_ebitda", "ev", m_ebitda),
                                  ("PER", "per", "eq", m_ni), ("PBR", "pbr", "eq", m_eq)):
        st = multiple_stats(pr[col])
        def ps(mu):
            if metric is None or not np.isfinite(mu) or metric <= 0:      # P7-B2 B2-F2: negative own metric -> N/M
                return np.nan
            eq = (mu * metric - br["net_debt"] + br["non_operating"] - br["nci"]) if kind == "ev" else mu * metric
            return eq * EOK / mk["shares_out"]
        rel.append({"배수": nm, "n": st["n"], "q25": st["q25"], "중앙값": st["median"], "q75": st["q75"], "지표(억원)": metric,
                    "주당 q25": ps(st["q25"]), "주당 중앙값": ps(st["median"]), "주당 q75": ps(st["q75"]),
                    "경고": f"n<{cfg['relative']['n_warn']}" if st["n"] < cfg["relative"]["n_warn"] else ""})
    rel = pd.DataFrame(rel).set_index("배수")
    out.append("## 상대가치\n\n" + md(rel, "{:,.2f}"))
    out.append(f"\n대상 LTM: 매출 {m_rev:,.1f}, 영업이익 {ltm(c, 'operating_income'):,.1f}, D&A {eb / EOK if eb else float('nan'):,.1f}({eb_why}), "
               f"EBITDA {m_ebitda if m_ebitda else float('nan'):,.1f}, 지배순이익 {m_ni:,.1f}, 지배지분 {m_eq:,.1f}억\n")
    ptab = pp.set_index("name")[["tier", "fs_div", "revenue", "ebitda", "ni_parent", "mktcap", "net_debt", "ev", "ev_sales",
                                 "ev_ebitda", "per", "pbr", "dna_missing"]].copy()
    for k in ("revenue", "ebitda", "ni_parent", "mktcap", "net_debt", "ev"):
        ptab[k] = ptab[k] / EOK
    out.append("\n" + md(ptab.rename_axis("피어"), "{:,.1f}"))
    out.append("\n" + md(beta_tab.round(3).astype(float), "{:.3f}"))
    q25, q75 = rel.loc["EV/EBITDA", "주당 q25"], rel.loc["EV/EBITDA", "주당 q75"]
    conv = convergence(vb["per_share"], q25, q75)
    conv_n5, n5_lines = None, []
    if version != "c2":                 # P3-C3: the same test on the previous peer table (EBITDA n before supplement)
        con = duckdb.connect(str(DB_PATH), read_only=True)
        p5 = con.execute(f"SELECT * FROM peer_{base_name}").df()
        con.close()
        st5 = multiple_stats(p5[p5.tier.isin(tiers)].ev_ebitda)
        to_ps = lambda mu: (float("nan") if not m_ebitda or m_ebitda <= 0 else  # noqa: E731   (P7-B2 B2-F3: no own EBITDA)
                            (mu * m_ebitda - br["net_debt"] + br["non_operating"] - br["nci"]) * EOK / mk["shares_out"])
        conv_n5 = {**convergence(vb["per_share"], to_ps(st5["q25"]), to_ps(st5["q75"])), "n": st5["n"],
                   "q25": to_ps(st5["q25"]), "q75": to_ps(st5["q75"])}
        n5_lines.append(f"- 같은 기준, 보완 전 피어 표(EV/EBITDA n={st5['n']}): 사분위 {conv_n5['q25']:,.0f}~{conv_n5['q75']:,.0f}원 → "
                   f"**{conv_n5['verdict']}**")
        st_now = multiple_stats(pr.ev_ebitda)
        n5_lines.append(f"- 시험 강도(표시만): EV/EBITDA 사분위 폭 ÷ 중앙값 = {(st_now['q75'] - st_now['q25']) / st_now['median']:.2f}"
                   f"(보완 후 n={st_now['n']}), 보완 전 {(st5['q75'] - st5['q25']) / st5['median']:.2f}(n={st5['n']})")
    out.append(f"\n## 수렴 시험(사전 고정)\n\n- 기본 DCF(SRP 0%) {vb['per_share']:,.0f}원 vs 피어 EV/EBITDA 사분위 {q25:,.0f}~{q75:,.0f}원 → **{conv['verdict']}**"
               f" (범위 밖 거리 {conv['gap']:,.0f}원). 종가 {price:,.0f}원 대비 DCF {vb['per_share'] / price - 1:+.1%}(표시만)\n")
    out.extend(n5_lines)
    if not conv["converged"]:                       # pre-registered: decompose the cause when outside the range
        dec_rows = [("DCF EV ÷ 대상 LTM EBITDA(배)", vb["ev"] / m_ebitda if m_ebitda else np.nan,
                     f"피어 EV/EBITDA 중앙값 {rel.loc['EV/EBITDA', '중앙값']:.2f}배"),
                    ("DCF 영구가치 함의 EV/EBITDA(2040, 배)", vb["implied_multiple"], "")]
        for lab_, tgt in (("q75", q75), ("중앙값", rel.loc["EV/EBITDA", "주당 중앙값"])):
            wv = bisect(lambda x: dcf_value(c, h, tb, x, cap)["per_share"] - tgt, 0.03, 0.30)
            dec_rows.append((f"피어 EV/EBITDA {lab_} 주당가를 맞추는 WACC", wv, f"기본 WACC {w_base[0.0]:.2%}"))
        for lab_, b_, s_ in (("기본", bu0, 0.0), ("βu를 KOSDAQ 지수 값으로", bu["KOSDAQ"], 0.0),
                             ("+ SRP 1%", bu["KOSDAQ"], 0.01), ("+ SRP 2%", bu["KOSDAQ"], 0.02)):
            w_ = discount_rate(c, s_, b_, de_own, kd_base)
            v_ = dcf_value(c, h, tb, w_, cap)["per_share"]
            dec_rows.append((f"순차: {lab_}", v_, f"WACC {w_:.2%}, 사분위 안: {q25 <= v_ <= q75}"))
        dec_rows.append(("피어 회귀 R² 중앙값(KOSPI)", float(sel[sel["index"] == cfg["beta"]["index"]].r2.median()),
                         "설명력 낮음 → βu 불확실"))
        out.append("원인 분해\n\n" + md(pd.DataFrame(dec_rows, columns=["항목", "값", "비고"]).set_index("항목"), "{:,.4f}"))

    # ---- block
    pct = market_provider().mktcap_percentile(cfg["meta"]["as_of"], cfg["target"]["market"], mk["mktcap_common"] * EOK)
    vw = market_provider().vwap20(cfg["target"]["stock_code"], cfg["meta"]["as_of"])
    pm = cfg["params"]["premium"]
    prr = premium_range(pct["mktcap_pct"], stake_band=pm["stake_band"], buyer_group=pm["buyer_group"],
                        market=cfg["target"]["market"], period=pm["period"])
    q = {"q25": prr.q25, "q50": prr.q50, "q75": prr.q75}          # D6 application rule (P4-A): method + reason
    blk = block_range(vw["vwap"], q)
    out.append(f"## 블록 프리미엄\n\n- 시총 백분위 {pct['mktcap_pct']:.1f}({cfg['target']['market']} 보통주 {pct['n_universe']}종목), method {prr.method}"
               f"(이유 {prr.reason}, 규칙 D6): {q['q25']:.1%}/{q['q50']:.1%}/{q['q75']:.1%}; "
               f"회귀(참고) {prr.regression['q25']:.1%}/{prr.regression['q50']:.1%}/{prr.regression['q75']:.1%}; "
               f"이웃 {prr.neighbour['q25']:.1%}/{prr.neighbour['q50']:.1%}/{prr.neighbour['q75']:.1%}(n 같은 시장 {prr.neighbour['n_same_market']}); "
               f"구간 {prr.band['band']} n={prr.band['n']}; 경고: {'; '.join(prr.warnings) or '없음'}\n"
               f"- 20일 VWAP {vw['vwap']:,.0f}원({vw['start']}~{vw['end']}) → 블록 1주당 {blk['q25']:,.0f} / {blk['q50']:,.0f} / {blk['q75']:,.0f}원\n"
               f"- 상증법 할증 20%: {vw['vwap'] * 1.2:,.0f}원 / 할증 제외: {vw['vwap']:,.0f}원(원문 미확인 ⚠️)\n")

    # ---- football
    items = []
    for sc in order:
        v = R[R.scenario == sc]
        items.append({"group": "DCF(연결, 기계적 경로)", "label": f"DCF {sc}", "low": v.per_share.min(), "high": v.per_share.max(),
                      "mid": float(v[v.srp == 0].per_share.iloc[0]), "definition": "SRP 2%~0%, 대표 = SRP 0%"})
    for nm in ("EV/EBITDA", "PER", "EV/Sales", "PBR"):
        r_ = rel.loc[nm]
        if np.isfinite(r_["주당 q25"]):
            items.append({"group": "상대가치(피어 LTM)", "label": f"{nm} (n={int(r_.n)})", "low": r_["주당 q25"], "high": r_["주당 q75"],
                          "mid": r_["주당 중앙값"], "definition": f"피어 사분위 {r_.q25:.1f}~{r_.q75:.1f}배"})
    items.append({"group": "블록 거래 가격(참고)", "label": "지배 블록 1주당", "low": blk["q25"], "high": blk["q75"], "mid": blk["q50"],
                  "definition": f"20일 VWAP × (1 + 프리미엄 {q['q25']:.1%}~{q['q75']:.1%})"})
    ff = football_rows(items)
    out.append("## 풋볼필드\n\n" + md(ff.set_index("label")[["group", "low", "mid", "high", "definition"]], "{:,.0f}"))
    _football(ff, price, cfg["target"]["name"], name, cfg["meta"]["as_of"],
              None if version == "c2" else f"p3c3_{base_name}_football.png", fig_dir)
    extra = {} if version == "c2" else {"version": version, "kd": kd_base, "beta_u": bu0,
                                         "conv_n5": None if conv_n5 is None else conv_n5["verdict"]}
    summary = {**extra, "w_implied": w_imp, "margin_needed": None if m_imp is None else h["margin"] + m_imp, "dcf_base": vb["per_share"], "tv_share": vb["tv_share"], "implied_multiple": vb["implied_multiple"],
               "ev_ebitda_median_ps": rel.loc["EV/EBITDA", "주당 중앙값"], "per_median_ps": rel.loc["PER", "주당 중앙값"],
               "price": price, "g_reverse": gr, "g_base": h["cagr"], "converged": conv["converged"], "wacc": w_base[0.0],
               "ronic": vb["ronic"]}
    out.append("\n## 요약값\n\n" + "\n".join(f"- {k}: {v}" for k, v in summary.items()))
    text = "\n".join(out)
    (ROOT / "data" / "interim" / f"{name}_tables.md").write_text(text, encoding="utf-8")
    R.to_csv(ROOT / "data" / "interim" / f"{name}_dcf.csv", index=False)
    return text


def _football(ff: pd.DataFrame, price: float, title: str, name: str, as_of: str = "", fname: str | None = None,
              fig_dir: Path | None = None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    colors = {"DCF(연결, 기계적 경로)": "#2a6f97", "상대가치(피어 LTM)": "#61a5c2", "블록 거래 가격(참고)": "#e09f3e"}
    fig, ax = plt.subplots(figsize=(9, 4.8))
    y = np.arange(len(ff))[::-1]
    for yi, r in zip(y, ff.itertuples()):
        ax.barh(yi, r.high - r.low, left=r.low, color=colors.get(r.group, "#888"), height=0.6)
        ax.plot([r.mid], [yi], marker="|", color="black", ms=14)
        ax.text(r.high + max(ff.high) * 0.01, yi, f"{r.low:,.0f}~{r.high:,.0f}", va="center", fontsize=7)
    ax.axvline(price, color="#c1121f", ls="--", lw=1)
    ax.text(price, -0.9, f" 기준일 종가 {price:,.0f}원", color="#c1121f", fontsize=8)
    ax.set_xlim(0, max(ff.high.max(), price) * 1.15)
    ax.set_ylim(-1.3, len(ff) - 0.4)
    ax.set_yticks(y, ff.label)
    ax.set_xlabel("주당 원 (가정 하 추정·참고 범위)")
    ax.set_title(f"{title} 풋볼필드 (초안, 기준일 {as_of})")
    ax.legend(handles=[Patch(color=c_, label=g) for g, c_ in colors.items()], fontsize=7, loc="upper right")
    fig.text(0.01, 0.01, "가정 기반 계산·참고 범위(투자 권유 아님). 종가·VWAP·시가총액은 한국거래소 통계정보", fontsize=6.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    folder = Path(fig_dir) if fig_dir else ROOT / "reports" / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / (fname or f"p3c2_{name}_football.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "config/valuation_jw.yaml", sys.argv[2] if len(sys.argv) > 2 else "c2"))
