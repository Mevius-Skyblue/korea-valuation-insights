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

import duckdb
import numpy as np
import pandas as pd

from src import yamlio
from src.collect.core import ROOT
from src.db.build import DB_PATH
from src.valuation.assumptions import load_ledger, marginal_rate, progressive_tax, rf_code
from src.valuation.dcf import Period, fade_path, roll_forward, run_dcf
from src.valuation.wacc import wacc, wacc_hp
from src.workbench.snapdata import seam

EOK = 1e8
EXPLICIT_END = 2032  # design of the three-stage structure (P3-B2), not an as-of value
FADE_END = 2040


def explicit_years(c) -> list[int]:
    """Forecast years after the base year up to the end of the explicit period."""
    return list(range(c.Y + 1, EXPLICIT_END + 1))


FADE = list(range(EXPLICIT_END + 1, FADE_END + 1))


# ---------------------------------------------------------------- pure pieces (unit-tested)


def growth_path(g_start: float, g_terminal: float, start_year: int, to_year: int, years: list[int]) -> dict[int, float]:
    """Growth falling by equal steps from g_start (start_year) to g_terminal (to_year), flat afterwards."""
    n = to_year - start_year
    return {y: g_start + (g_terminal - g_start) * min(y - start_year, n) / n for y in years}


def cagr(v0: float, v1: float, years: int) -> float:
    """Compound annual growth rate between two values."""
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
    if not (np.isfinite(q25_ps) and np.isfinite(q75_ps)):  # P7-B2: own EBITDA <= 0 -> peer range N/M
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
    segs = [
        {"name": s["name"], "margin": 100 * hist_margin if s["margin"] == "history" else s["margin"], "growth": s["growth"]}
        for s in st["segments"]
    ]
    if listed:
        if sub_mktcap is None:
            raise ValueError("listed subsidiary: subsidiary market cap needed for NCI at market value")
        nci = (1 - st["subsidiary"]["stake"]) * sub_mktcap
    else:
        nci = nci_book
    return {"listed": listed, "segments": segs, "nci_value": nci}


def notch_kd(kd_from: float, kd_to: float, steps: int, at: int) -> float:
    """Kd moved `at` of `steps` notches from one rating band to another (linear)."""
    return kd_from + (kd_to - kd_from) * at / steps


# ---------------------------------------------------------------- data


@dataclass
class Company:
    cfg: dict
    led: dict
    w: pd.DataFrame  # fs_std CFS wide, 억원, index (year, period)
    dna: pd.Series  # D&A totals, 억원, index (year, period)
    bs_lines: pd.DataFrame
    market: dict
    rates: dict
    ronic_start: str = "mixed"  # P3-C2 "mixed" (FY start NOPAT = 1H actual + 2H normal) / P3-C3 "normal"
    dna_rec: object = None  # P7-B2b: per-period D&A source of an auto draft (원문 / 보완 / 추정)
    v2: dict | None = None  # P7-B2b: mechanical_v2 inputs of an auto draft (None = v1 path)
    sotp: dict | None = None  # P7-B3: general SOTP (subsidiary rows with prices, discount, dividend adjustment)

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
    def first(self) -> str:  # label of the partial first forecast period (e.g. 2H26 after an H1 LTM)
        return f"2H{str(self.Y)[2:]}"


def beta_u0(bt: pd.DataFrame, cfg: dict, index: str | None = None, public: bool | None = None) -> tuple[float, str]:
    """βu of the model (P7-B5 config/p7b5.yaml peer_relax.beta_fallback): median of the included peers; with no peer
    βu, the target's own (Blume, Hamada) βu; without that, 1.0. Returns (βu, source).
    P7-X2a public mode (src/workbench/pubcut.py): fewer than 5 peer βu -> 1.0 (no median of few peers, no own βu)."""
    from src.workbench import pubcut

    ix = index or cfg["beta"]["index"]
    tiers = cfg["beta"]["peer_tiers"]
    v = bt[bt.tier.isin(tiers) & (bt["index"] == ix)].bu_avg.dropna() if len(bt) else pd.Series(dtype=float)
    pub = pubcut.public_scope(cfg) if public is None else public
    if pub and len(v) < pubcut.params()["peer_min_n"]:
        return pubcut.beta(float("nan"), "", len(v), True)
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
    """The market-data provider in use (PC: the DB; public mode: the user's inputs)."""
    from src.market.provider import get

    return get()


def _con():
    """A read-only DB connection, or None when the public snapshot replays the data (no DB, P7-C3)."""
    from src.workbench import snapdata as SD

    return None if SD.replaying() else duckdb.connect(str(DB_PATH), read_only=True)


def _close(con) -> None:
    if con is not None:
        con.close()


# P7-C3 data seams (src/workbench/snapdata.py): the DART / ECOS reads of load_company, recorded for the public snapshot.
# Off (PC, default): the same queries as before.
@seam("fs_rows", key=lambda con, corp, fs, fill: (corp, fs, fill), canonical=True)
def _fs_rows(con, corp: str, fs: str, fill: list) -> pd.DataFrame:
    d = con.execute(
        """SELECT fiscal_year y, period p, std_account a, amount FROM fs_std
                       WHERE corp_code=? AND fs_div=? AND is_default""",
        [corp, fs],
    ).df()
    for y, per, other in fill:  # P7-B5 short_history.basis_fill (auto drafts)
        d = d[~((d.y == y) & (d.p == per))]
        o = con.execute(
            """SELECT fiscal_year y, period p, std_account a, amount FROM fs_std
                           WHERE corp_code=? AND fs_div=? AND is_default AND fiscal_year=? AND period=?""",
            [corp, other, y, per],
        ).df()
        d = pd.concat([d, o], ignore_index=True)
    return d


@seam("fs_dna_sum", key=lambda con, corp, fs: (corp, fs), canonical=True)
def _fs_dna_sum(con, corp: str, fs: str) -> pd.DataFrame:
    return con.execute(
        "SELECT fiscal_year y, period p, sum(amount) v FROM fs_dna WHERE corp_code=? AND fs_div=? GROUP BY 1,2", [corp, fs]
    ).df()


def _draft_key(cfg: dict) -> tuple:
    return (
        cfg["target"]["corp_code"],
        cfg["meta"].get("fs_div", "CFS"),
        int(cfg["meta"]["ltm"]["year"]),
        cfg["meta"]["ltm"]["period"],
        [x["corp_code"] for x in cfg.get("peers", [])],
    )


@seam("draft_dna", key=lambda con, cfg: _draft_key(cfg), canonical=True)
def draft_dna(con, cfg: dict):
    """P7-B2b filled D&A of an auto draft (src/clean/dna_fill.draft_target): (wide, record)."""
    from src.clean.dna_fill import draft_target

    return draft_target(con, cfg)


@seam("bs_lines", key=lambda con, corp, fs, y, reprt: (corp, fs, y, reprt))
def _bs_lines(con, corp: str, fs: str, y: int, reprt: str) -> pd.DataFrame:
    from src.valuation.peer_p3 import bs_lines

    return bs_lines(con, corp, fs, y, reprt)


@seam("rates", key=lambda con, as_of: as_of)
def _rates(con, as_of: str) -> dict:
    return {
        k: con.execute(
            """SELECT value FROM rates_daily WHERE rate_code=? AND freq='D' AND date<=? ORDER BY date DESC
                              LIMIT 1""",
            [k, as_of],
        ).fetchone()[0]
        / 100
        for k in ("KTB5Y", "KTB10Y", "CB3Y_AAm", "CB3Y_BBBm")
    }


@seam("debt_at", key=lambda con, corp, y, p, fs: (corp, y, p, fs))
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


@seam("dna_wide", key=lambda con, corp, fs: (corp, fs), canonical=True)
def dna_wide_of(con, corp: str, fs: str) -> pd.DataFrame:
    """D&A of a company by period (wide table), from the peer-table reader."""
    from src.valuation.peer_table import dna_wide

    return dna_wide(con, corp, fs)


def de_points_key(cfg: dict) -> tuple:
    """Cache key of the D/E points: the inputs they depend on (company, basis, dates, reclassified debt)."""
    return (
        cfg["target"]["corp_code"],
        cfg["target"]["stock_code"],
        cfg.get("structure", {}).get("method") == "sotp_general",
        fs_div(cfg),
        [list(x) for x in cfg["params"]["de_points"]],
        (cfg.get("bridge") or {}).get("debt_reclass") or [],
    )


def load_company(cfg_path: str) -> Company:
    """Everything the engine needs for one company config: statements, D&A, balance-sheet lines, market data, rates."""
    from src.workbench import snapdata as SD

    cfg = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
    led = load_ledger(ROOT / cfg["meta"]["discount_ledger"])
    corp, code, as_of = cfg["target"]["corp_code"], cfg["target"]["stock_code"], cfg["meta"]["as_of"]
    fs = fs_div(cfg)
    mp = market_provider()
    sotp_mode = cfg.get("structure", {}).get("method") == "sotp_general"
    con = _con()
    d = _fs_rows(con, corp, fs, cfg["meta"].get("basis_fill") or [])
    from src.clean.frames import pivot

    w = pivot(d, ["y", "p"], "a", "amount") / EOK  # pivot() returns an empty table when a company has no rows
    dn = _fs_dna_sum(con, corp, fs)
    dna = dn.set_index(["y", "p"]).v / EOK
    dna_rec = None
    if "draft_meta" in cfg:  # P7-B2b: auto drafts read D&A filled period by period (원문 → 보완 → 추정)
        dw_f, dna_rec = draft_dna(con, cfg)
        dna = dw_f.fillna(0).sum(axis=1) / EOK
        dna.index = dna.index.set_names(["y", "p"])
    reclass = {}
    if "draft_meta" in cfg:  # P7-B3b mistag.text_rule: borrowings the API tags as another account (원)
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
    market_equity = None  # P7-C3 public mode before the user's price: no market equity
    if close is not None and all(p[0] is not None and p[2] is not None for p in pref_listed):
        listed_pref_shares = sum(p[2] for p in pref_listed)
        market_equity = (
            close * common_out + sum(p[0] * p[2] for p in pref_listed) + close * max(pref_out - listed_pref_shares, 0)
        ) / EOK
    rates = _rates(con, as_of)
    # D/E points (own average) on the common market cap of each date
    de_n, de_cut = None, False
    if SD.replaying():  # P7-C3 public snapshot: only the own-average D/E (aggregate; no market caps)
        agg = SD.get("de_points", de_points_key(cfg))
        de_pts, de_n = [{"date": None, "debt": None, "lease": None, "mktcap": None, "de": agg["de"]}], agg["n"]
        de_cut = bool(agg.get("public_cut"))
    else:
        de_pts = []
        for y, p in cfg["params"]["de_points"]:
            dt = f"{y}-12-31" if p == "FY" else f"{y}-06-30"
            b, m = _debt_at(con, corp, int(y), p, fs if sotp_mode else None), mp.mktcap_at(code, dt, con=con)
            if b and m:
                b = {**b, "debt": b["debt"] + reclass.get((int(y), p), 0.0)}
                de_pts.append(
                    {
                        "date": dt,
                        "debt": b["debt"] / EOK,
                        "lease": b["lease"] / EOK,
                        "mktcap": m / EOK,
                        "de": (b["debt"] + b["lease"]) / m,
                    }
                )
        from src.workbench import pubcut

        if pubcut.de_cut(len(de_pts), pubcut.public_scope(cfg)):  # P7-X2a: own D/E of fewer than 5 dates not shown
            de_n, de_cut = len(de_pts), True
            de_pts = [{"date": None, "debt": None, "lease": None, "mktcap": None, "de": pubcut.params()["de_fallback"]}]
            SD.put("de_points", de_points_key(cfg), {"de": de_pts[0]["de"], "n": de_n, "public_cut": True})
        elif de_pts:
            SD.put("de_points", de_points_key(cfg), {"de": float(pd.DataFrame(de_pts).de.mean()), "n": len(de_pts)})
    _close(con)
    market = {
        "shares_note": shares_note,
        "close": None if close is None else float(close),
        "mktcap_common": None if mcap_common is None else mcap_common / EOK,
        "common_out": common_out,
        "pref_out": pref_out,
        "shares_out": common_out + pref_out,
        "market_equity": market_equity,
        "de_points": pd.DataFrame(de_pts),
        "listed_pref": pref_listed,
        "de_n": de_n if de_n is not None else len(de_pts),
        **({"de_cut": True} if de_cut else {}),  # P7-X2a public mode: fewer than 5 dates -> D/E 0 (pubcut)
    }
    comp = Company(cfg, led, w, dna, lines, market, rates)
    comp.dna_rec = dna_rec
    if sotp_mode:  # P7-B3 general SOTP (config/p7b3.yaml sotp)
        con = _con()
        try:
            comp.sotp = sotp_inputs(con, cfg, corp, fs, as_of)
        finally:
            _close(con)
        for (y, p), amt in comp.sotp["dividends"].items():  # dividends inside operating revenue -> out of the base
            if (y, p) in comp.w.index:
                for k in ("revenue", "operating_income"):
                    if k in comp.w.columns and pd.notna(comp.w.loc[(y, p), k]):
                        comp.w.loc[(y, p), k] -= amt / EOK
        comp.__dict__.pop("_val_cache", None)
        comp.__dict__.pop("_wraw_cache", None)
    if cfg.get("forecast", {}).get("method") == "mechanical_v2":  # P7-B2b auto-draft default path
        con = _con()
        try:
            comp.v2 = v2_inputs(comp, con)
        finally:
            _close(con)
    return comp


@seam("dividends", key=lambda con, corp, fs: (corp, fs))
def dividends_in_revenue(con, corp: str, fs: str) -> dict:
    """{(year, period): 원} of '배당금수익' lines above the operating-income line of the income statement (operating
    revenue of the separate statements), per report (FY = 11011, H1 = 11012, year-to-date)."""
    rows = con.execute(
        """SELECT bsns_year, reprt_code, ord, account_id, account_nm, thstrm_num, thstrm_add_num FROM fs_raw
                          WHERE corp_code=? AND fs_div=? AND sj_div IN ('IS','CIS') AND reprt_code IN ('11011','11012')""",
        [corp, fs],
    ).df()
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
    return {
        "rows": rows,
        "discount": float(st.get("discount", {}).get("base", 0.0)),
        "sensitivities": list(st.get("discount", {}).get("sensitivities", [])),
        "dividends": dividends_in_revenue(con, corp, fs),
    }


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
    return {
        "cl": cl,
        "sub_lines": sub_lines,
        "book_all": book_all,
        "listed": listed,
        "unlisted": unlisted,
        "remainder": remainder,
        "discount": discount,
        "unit_ok": book_all <= sub_lines * 1.02 + 1,
        "missing_close": missing_close,
        "non_operating": cl["non_operating"] + remainder + listed * (1 - discount) + unlisted,
    }


def v2_rules() -> dict:
    """Pre-registered mechanical_v2 forecast rules (config/p7b2b.yaml)."""
    return yamlio.load((ROOT / "config" / "p7b2b.yaml").read_text(encoding="utf-8"))["mechanical_v2"]


@seam(
    "peer_metrics",
    key=lambda con, cfg, tiers: (
        int(cfg["meta"]["ltm"]["year"]),
        cfg["meta"]["ltm"]["period"],
        [[x["corp_code"], x["tier"]] for x in cfg.get("peers", [])],
        list(tiers),
    ),
)
def peer_metrics(con, cfg: dict, tiers) -> list[dict]:
    """LTM operating margin and revenue growth (FY(Y−3) → FY(Y−1) 2-year CAGR, else 1-year) of the included peers."""
    from src.valuation.peer_table import basis

    y, p = int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"]
    out = []
    for x in cfg.get("peers", []):
        if x["tier"] not in tiers:
            continue
        fs = basis(con, x["corp_code"], y, p)
        d = con.execute(
            """SELECT fiscal_year, period, std_account, amount FROM fs_std WHERE corp_code=? AND fs_div=? AND is_default
                           AND std_account IN ('revenue','operating_income')""",
            [x["corp_code"], fs],
        ).fetchall()
        v = {(int(a), b, k): float(m) for a, b, k, m in d if m is not None}
        g = lambda k, yy, pp: v.get((yy, pp, k))  # noqa: E731, B023
        lt = {
            k: (g(k, y - 1, "FY") + g(k, y, p) - g(k, y - 1, p))
            if None not in (g(k, y - 1, "FY"), g(k, y, p), g(k, y - 1, p))
            else None
            for k in ("revenue", "operating_income")
        }
        r1, r3, r2 = g("revenue", y - 1, "FY"), g("revenue", y - 3, "FY"), g("revenue", y - 2, "FY")
        growth = (r1 / r3) ** 0.5 - 1 if r1 and r3 and r1 > 0 and r3 > 0 else (r1 / r2 - 1 if r1 and r2 and r2 > 0 else None)
        margin = (
            lt["operating_income"] / lt["revenue"]
            if lt["revenue"] and lt["revenue"] > 0 and lt["operating_income"] is not None
            else None
        )
        out.append({"name": x["name"], "margin": margin, "growth": growth})
    return out


def v2_inputs(c: Company, con) -> dict:
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
    if start == "ltm":  # P7-B3b loss path (config/p7b3b.yaml loss_path.method.b_transition_dcf)
        lr = ltm(c, "revenue")
        m0 = ltm(c, "operating_income") / lr if lr > 0 else m0
        m_src = "LTM 영업이익률(적자 경로: FY2025 + 2026 H1 − 2025 H1)"
        share = float(fc.get("converge_share", share))
    w, (lo, hi) = r["start_growth"]["weight_own"], r["start_growth"]["clip"]
    v = {
        "m0": m0,
        "m0_src": m_src,
        "m0_years": yrs,
        "start": start,
        "peer_margin": pm,
        "peer_margin_n": len(pms),
        "conv_share": share,
        "conv_amt": share * (pm - m0) if pm is not None else 0.0,
        "own_cagr": h["cagr"],
        "peer_growth": pg,
        "peer_growth_n": len(pgs),
        "weight_own": w,
        "clip": [lo, hi],
        "g0": v2_start_growth(h["cagr"], pg, w, lo, hi),
        "peers": pm_all,
        "m0_auto": m0,
    }
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
    """Historical revenue, margins, D&A and working-capital days for the averages and the growth (CAGR)."""
    yrs = c.cfg["params"]["avg_years"]
    y0, y1 = c.cfg["params"]["cagr_years"]
    rows = {}
    for y in sorted(set(yrs) | {y0, y1}):
        rev = val(c, "revenue", y)
        rows[y] = {
            "revenue": rev,
            "op": val(c, "operating_income", y),
            "cogs": val(c, "cogs", y),
            "dna": float(c.dna.get((y, "FY"), np.nan)),
            "capex": val(c, "capex_ppe", y) + val(c, "capex_intangibles", y),
            "rec": val(c, "receivables", y),
            "inv": val(c, "inventories", y),
            "pay": val(c, "trade_payables", y),
            "ic": (
                val(c, "receivables", y)
                + val(c, "inventories", y)
                - val(c, "trade_payables", y)
                + val(c, "ppe", y)
                + val(c, "intangibles", y)
                + val(c, "rou_assets", y)
            ),
        }
    h = pd.DataFrame(rows).T
    a = h.loc[yrs]
    out = {
        "table": h,
        "cagr": cagr(h.loc[y0, "revenue"], h.loc[y1, "revenue"], y1 - y0),
        "margin": float((a.op / a.revenue).mean()),
        "dna_ratio": float((a.dna / a.revenue).mean()),
        "capex_ratio": float((a.capex / a.revenue).mean()),
        "cogs_ratio": float((a.cogs / a.revenue).mean()),
        "dso": _days(a.rec, a.revenue),
        "dio": _days(a.inv, a.cogs),
        "dpo": _days(a.pay, a.cogs),
    }
    return out


def _days(num: pd.Series, den: pd.Series) -> float:
    """P7-B3 B3-F5: turnover days, mean over years with a non-zero base (holding companies without 매출원가); no such
    year -> 0 days. The Excel days rows use the same rule (IF base = 0 -> text, COUNT = 0 -> 0)."""
    x = (num / den.where(den != 0) * 365).dropna()
    return float(x.mean()) if len(x) else 0.0


def tax_fn(c: Company):
    """Progressive corporate tax of the ledger as a function of the base (억원)."""
    br = c.led["corporate_tax"]["brackets"]
    return lambda b: progressive_tax(b * EOK, br) / EOK


def eff(c: Company, ebit: float) -> float:
    """Effective tax rate on an EBIT (0 for a loss)."""
    return tax_fn(c)(ebit) / ebit if ebit > 0 else 0.0


def hist_roic(c: Company, h: dict) -> float:
    """Average historical ROIC = NOPAT / opening invested capital (cap for the RONIC rule)."""
    t = h["table"]
    vals = []
    for y in c.cfg["params"]["avg_years"]:
        ic_open = (
            val(c, "receivables", y - 1)
            + val(c, "inventories", y - 1)
            - val(c, "trade_payables", y - 1)
            + val(c, "ppe", y - 1)
            + val(c, "intangibles", y - 1)
            + val(c, "rou_assets", y - 1)
        )
        nopat = t.loc[y, "op"] * (1 - eff(c, t.loc[y, "op"]))
        if ic_open > 0:
            vals.append(nopat / ic_open)
    return float(np.mean(vals)) if vals else float("nan")  # P7-B5: no positive opening capital -> NaN (handled later)


# ---------------------------------------------------------------- forecast and value


def forecast(
    c: Company, h: dict, growth_shift: float = 0.0, margin_shift: float = 0.0, g_start_override: float | None = None
) -> pd.DataFrame:
    """Explicit forecast: revenue growth fading to g, margins, D&A, CAPEX and ΔNWC by year."""
    gT = c.cfg["forecast"]["human"]["g_terminal"]
    v2 = c.v2
    base_g = v2["g0"] if v2 else h["cagr"]
    g0 = (base_g + growth_shift) if g_start_override is None else g_start_override
    Y, years = c.Y, explicit_years(c)
    gp = growth_path(g0, gT, Y, c.cfg["params"]["fade_to_terminal_by"], [Y] + years)
    m = (v2["m0"] if v2 else h["margin"]) + margin_shift
    conv = v2["conv_amt"] if v2 else 0.0  # P7-B2b v2: margin converges toward the peer median by 2032
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
        rows.append(
            {
                "label": lab,
                "year": y,
                "start": start,
                "end": date(y, 12, 31),
                "revenue": rev,
                "growth": gp[y],
                "ebit": ebit,
                "fy_ebit": h1_op + ebit if lab == c.first else ebit,
                "dna": rev * h["dna_ratio"],
                "capex": rev * h["capex_ratio"],
                "nwc": cur,
                "dnwc": cur - prev,
            }
        )
        prev = cur
    t = pd.DataFrame(rows)
    t.attrs.update({"g_start": g0, "margin": m, "margin_end": m + conv, "rev_fy": rev_fy, "gT": gT})
    return t


def discount_rate(c: Company, srp: float, beta_u: float, de: float, kd: float, mode: str = "hamada") -> float:
    """WACC of one case (Hamada, or Harris-Pringle as a sensitivity) from the ledger's Rf and MRP."""
    r, mrp = c.rates[rf_code(c.led)], c.led["mrp"]["value"]
    ltm_pretax = ltm(c, "pretax_income")
    t_kd = marginal_rate(ltm_pretax * EOK, c.led["corporate_tax"]["brackets"])
    if mode == "harris_pringle":
        return wacc_hp(r, mrp, beta_u, de, kd, t_kd, srp).wacc
    return wacc(r, mrp, beta_u, de, kd, c.cfg["beta"]["tax"], t_kd, srp).wacc


def dcf_value(
    c: Company, h: dict, t: pd.DataFrame, w: float, roic_cap: float, g: float | None = None, ronic_override: float | None = None
) -> dict:
    """Three-stage value-driver DCF of a forecast at a WACC -> EV, bridge, per share and TV share."""
    tx = tax_fn(c)
    gT = t.attrs["gT"] if g is None else g
    yrs = [str(y) for y in explicit_years(c)]
    # P7-C1 speed: plain lists instead of repeated DataFrame lookups (same floats, same arithmetic order)
    col = {k: t[k].tolist() for k in ("label", "start", "end", "ebit", "dna", "capex", "dnwc", "fy_ebit", "revenue", "growth")}
    ix = {lab: i for i, lab in enumerate(col["label"])}
    fy26 = col["fy_ebit"][ix[c.first]]
    if c.ronic_start == "normal":  # P3-C3 common rule: start NOPAT = FY revenue x normal margin (no mixing)
        from src.valuation.common_rules import start_nopat

        n26 = start_nopat(t.attrs["rev_fy"][c.Y], t.attrs["margin"], tax_fn(c))
    else:
        n26 = fy26 * (1 - eff(c, fy26))
    e32 = col["ebit"][ix["2032"]]
    n32 = e32 * (1 - eff(c, e32))
    reinv = float(np.array([col["capex"][ix[y]] - col["dna"][ix[y]] + col["dnwc"][ix[y]] for y in yrs]).sum())
    r_calc = (n32 - n26) / reinv if reinv else float("nan")
    R, why = bounded_ronic(r_calc, reinv, w, roic_cap) if ronic_override is None else (ronic_override, "지정")
    periods = [
        Period(
            col["label"][i],
            col["start"][i],
            col["end"][i],
            col["ebit"][i],
            col["dna"][i],
            col["capex"][i],
            col["dnwc"][i],
            tax_base=col["fy_ebit"][i],
        )
        for i in range(len(col["label"]))
    ]
    m = t.attrs.get("margin_end", t.attrs["margin"])  # fade and terminal margin (v1: the normal margin, v2: path end)
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
    r = run_dcf(
        periods,
        tx,
        w,
        date.fromisoformat(c.cfg["meta"]["bs_date"]),
        g=gT,
        mid_year=c.cfg["forecast"]["mid_year"],
        fcf_norm=fcf_norm,
        ebitda_final=prev * m + prev * h["dna_ratio"],
    )
    days = (date.fromisoformat(c.cfg["meta"]["as_of"]) - date.fromisoformat(c.cfg["meta"]["bs_date"])).days
    ev = roll_forward(r.ev_gordon, w, days)
    br = bridge(c)
    eq = ev - br["net_debt"] + br["non_operating"] - br["nci"]
    return {
        "wacc": w,
        "ronic": R,
        "ronic_calc": r_calc,
        "ronic_why": why,
        "ev": ev,
        "equity": eq,
        "per_share": eq * EOK / c.market["shares_out"],
        "tv_share": r.tv_share_gordon,
        "implied_multiple": r.implied_multiple,
        "r": r,
    }


def bridge(c: Company) -> dict:
    """EV -> equity items (억원). P7-B5 cache: the result depends only on the balance-sheet lines, the statements
    frame and the SOTP rows/discount, so it is kept on the company per that key (same values, ~500 calls per model)."""
    ov = overrides_of(c.cfg)
    key = (
        id(c.bs_lines),
        id(c.w),
        None if not c.sotp else (id(c.sotp["rows"]), c.sotp["discount"]),
        ov.get("cash_adjust_mn"),
        ov.get("nci_mn"),
        tuple(_w_raw(c, k) for k in ("total_debt", "lease_liabilities", "nci")),
    )
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

    if c.sotp:  # P7-B3: subsidiaries replace the '종속' investment lines
        sp = sotp_parts(c.bs_lines, c.sotp["rows"], c.sotp["discount"])
        debt = val(c, "total_debt", c.Y, c.P) + val(c, "lease_liabilities", c.Y, c.P)
        cash = sp["cl"]["cash_like"] / EOK
        return {
            "total_debt": debt,
            "cash_like": cash,
            "net_debt": debt - cash,
            "non_operating": sp["non_operating"] / EOK,
            "nci": val(c, "nci", c.Y, c.P),
            "cash_detail": sp["cl"]["cash_like_detail"],
            "nonop_detail": sp["cl"]["non_op_detail"],
            "sotp": {k: (v / EOK if isinstance(v, float) and k not in ("discount",) else v) for k, v in sp.items() if k != "cl"},
        }
    cl = classify(c.bs_lines)
    debt = val(c, "total_debt", c.Y, c.P) + val(c, "lease_liabilities", c.Y, c.P)
    cash = cl["cash_like"] / EOK
    return {
        "total_debt": debt,
        "cash_like": cash,
        "net_debt": debt - cash,
        "non_operating": cl["non_operating"] / EOK,
        "nci": val(c, "nci", c.Y, c.P),
        "cash_detail": cl["cash_like_detail"],
        "nonop_detail": cl["non_op_detail"],
    }


def ltm(c: Company, k: str) -> float:
    """Last-twelve-months value: FY + current interim - prior-year interim."""
    return val(c, k, c.FY) + val(c, k, c.Y, c.P) - val(c, k, c.FY, c.P)


def ltm_dna(c: Company) -> tuple[float | None, str]:
    """LTM D&A with its source (filed notes, supplement or the draft's filled values)."""
    from src.valuation.peer_table import dna_ltm_checked

    con = _con()
    try:
        if "draft_meta" in c.cfg:  # P7-B2b: filled D&A for auto drafts
            dw = draft_dna(con, c.cfg)[0]
        else:
            dw = dna_wide_of(con, c.cfg["target"]["corp_code"], fs_div(c.cfg))
    finally:
        _close(con)
    return dna_ltm_checked(dw, val(c, "revenue", c.FY) * EOK, c.cfg["params"]["ebitda_rule"], c.Y, c.P)


def solve_g_start(c: Company, h: dict, w: float, cap: float, target_ps: float, margin_shift: float = 0.0) -> float | None:
    """Reverse DCF: the starting growth that gives a target per-share value (None if out of range)."""

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


if __name__ == "__main__":  # the report run lives in src/valuation/company_report.py (P7-C4 split)
    from src.valuation.company_report import main

    print(main(sys.argv[1] if len(sys.argv) > 1 else "config/valuation_jw.yaml", sys.argv[2] if len(sys.argv) > 2 else "c2"))
