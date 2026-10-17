"""P2-C C3: conditional premium distribution (design pre-registered in config/premium_p2c3.yaml).

Two parts:
1. `premium_cond` table (build.py loader "p2c3"): per main-sample deal the market-cap percentile on D_unaff_doc
   among common stocks of the same market that day, the grouped predictors, premium amount, post_financing_1y.
   Prices are read only for the needed (date, market) pairs with SQL (never the whole price table).
2. `analysis()`: cause checks (premium amount, small-cap no-capital M&A), quantile regression with pairs-bootstrap
   CIs, pseudo R1, 5-fold CV, neighbour-50 comparison, decision rules. Aggregates only.

Run:  python -m src.db.build p2c3            # table
      python -m src.premium.p2c3              # tables -> data/interim/p2c3.md (+ .json for the report)
"""
from __future__ import annotations

import json
import re

import duckdb
import numpy as np
import pandas as pd
import yaml

from src.collect.core import ROOT
from src.db.build import DB_PATH

CFG = ROOT / "config" / "premium_p2c3.yaml"
SEED = int(yaml.safe_load(CFG.read_text(encoding="utf-8"))["quantile_regression"]["cross_validation"]["seed"])  # pre-registered (P2.6: was a constant)
QS = (0.25, 0.5, 0.75)
BUYER = {"corp": "strategic", "pef_spc": "financial", "union": "other", "person": "other", "other": "other"}
FIN_TITLE = re.compile(r"전환사채|신주인수권부사채|교환사채|CB|BW|EB|제3자배정")
FIN_ISSUE = re.compile(r"발행|제3자배정")
FIN_NOT = re.compile(r"만기전|조정|청구|행사|종속회사|자회사|철회|취소|정정")


def load_cfg() -> dict:
    return yaml.safe_load(CFG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 1. table

ELIGIBLE_SQL = """
-- common stocks of the market on that day (pre-registered universe rule)
CASE WHEN right(d.stock_code, 1) <> '0' THEN false                                   -- preferred
     WHEN d.isu_nm LIKE '%스팩%' OR d.isu_nm LIKE '%기업인수목적%'
          OR coalesce(d.sect_tp_nm, '') LIKE 'SPAC%' THEN false                       -- SPAC
     WHEN d.isu_nm LIKE '%리츠%' AND d.isu_nm NOT LIKE '%메리츠%' THEN false             -- REIT
     WHEN cm.stock_code IS NOT NULL
          AND NOT (cm.kind_stkcert = '보통주' AND cm.secugrp_nm IN ('주권', '외국주권')) THEN false
     ELSE coalesce(d.mktcap, 0) > 0 END"""


def mktcap_percentiles(con, deals: pd.DataFrame) -> pd.DataFrame:
    """deals: bundle_id, stock_code, d_unaff_doc, market. Returns pct, universe size and excluded count per deal.
    Market caps inside a bonus-issue window (ex-date .. new-share listing) use the corrected value (P3-B, mktcap_fix)."""
    from src.market.mktcap_fix import MKTCAP_JOIN, MKTCAP_SQL
    con.register("pairs", deals[["bundle_id", "stock_code", "d_unaff_doc", "market"]])
    try:
        out = con.execute(f"""
            WITH days AS (SELECT DISTINCT d_unaff_doc AS bas_dd, market AS mkt_nm FROM pairs),
            u AS (
                SELECT d.bas_dd, d.mkt_nm, d.stock_code, {MKTCAP_SQL} AS mktcap, {ELIGIBLE_SQL} AS eligible
                FROM days JOIN price_daily d ON d.bas_dd = days.bas_dd AND d.mkt_nm = days.mkt_nm
                {MKTCAP_JOIN}
                LEFT JOIN (SELECT DISTINCT stock_code, kind_stkcert, secugrp_nm FROM corp_master) cm
                       ON cm.stock_code = d.stock_code),
            stats AS (SELECT bas_dd, mkt_nm, count(*) FILTER (WHERE eligible) AS n_univ,
                             count(*) FILTER (WHERE NOT eligible) AS n_excl FROM u GROUP BY ALL)
            SELECT p.bundle_id, coalesce(tf.mktcap_fix, t.mktcap) AS mktcap,
                   100.0 * ((SELECT count(*) FROM u WHERE u.bas_dd = p.d_unaff_doc AND u.mkt_nm = p.market
                                AND u.eligible AND u.mktcap < coalesce(tf.mktcap_fix, t.mktcap))
                          + 0.5 * (SELECT count(*) FROM u WHERE u.bas_dd = p.d_unaff_doc AND u.mkt_nm = p.market
                                AND u.eligible AND u.mktcap = coalesce(tf.mktcap_fix, t.mktcap))) / s.n_univ AS mktcap_pct,
                   s.n_univ, s.n_excl
            FROM pairs p
            JOIN price_daily t ON t.stock_code = p.stock_code AND t.bas_dd = p.d_unaff_doc
            LEFT JOIN mktcap_fix tf ON tf.stock_code = t.stock_code AND tf.bas_dd = t.bas_dd
            JOIN stats s ON s.bas_dd = p.d_unaff_doc AND s.mkt_nm = p.market""").fetchdf()
    finally:
        con.unregister("pairs")
    return out.drop_duplicates("bundle_id")


def post_financing(con, deals: pd.DataFrame) -> pd.Series:
    """1 if the company filed a CB/BW/EB or 제3자배정 issue (decision/result) within 365 days after closing."""
    dl = con.execute("""SELECT corp_code, rcept_dt, body FROM disclosure_list WHERE NOT is_amend
                        AND regexp_matches(body, '전환사채|신주인수권부사채|교환사채|CB|BW|EB|제3자배정')""").fetchdf()
    dl["body"] = dl.body.fillna("").str.replace(r"\s+", "", regex=True)
    dl = dl[dl.body.map(lambda b: bool(FIN_TITLE.search(b) and FIN_ISSUE.search(b) and not FIN_NOT.search(b)))]
    dl["rcept_dt"] = pd.to_datetime(dl.rcept_dt)
    by = {k: g.rcept_dt for k, g in dl.groupby("corp_code")}
    out = []
    for r in deals.itertuples():
        start = pd.Timestamp(r.d_close_final if pd.notna(r.d_close_final) else r.d_ann)
        s = by.get(r.corp_code)
        out.append(bool(s is not None and ((s > start) & (s <= start + pd.Timedelta(days=365))).any()))
    return pd.Series(out, index=deals.index)


def build_cond(con) -> pd.DataFrame:
    d = con.execute("""
        SELECT c.bundle_id, c.stock_code, c.d_ann, c.year, c.d_unaff_doc, c.market_at_ann AS market, c.price,
               c.bu20_doc, c.prem_bu20_doc, c.pct_band AS stake_band, c.acquirer_group, c.nocap_suspect,
               coalesce(x.shares_p2c, f.effective_shares) AS effective_shares, t.corp_code, f.d_close_final
        FROM premium_calc c JOIN deal_fix x USING (bundle_id) JOIN deal_terms t USING (bundle_id)
        JOIN deal_final f USING (bundle_id)
        WHERE c.in_main AND c.prem_bu20_doc IS NOT NULL""").fetchdf()
    pct = mktcap_percentiles(con, d)
    d = d.merge(pct, on="bundle_id", how="left")
    d["buyer_group"] = d.acquirer_group.map(BUYER).fillna("other")
    d["kospi"] = (d.market == "KOSPI").astype(int)
    d["period_early"] = (d.year <= 2014).astype(int)
    d["shares"] = d.effective_shares
    d["premium_amt"] = (d.price - d.bu20_doc) * d.shares / 1e8          # 억원
    d["stake_value"] = d.bu20_doc * d.shares / 1e8
    d["post_financing_1y"] = post_financing(con, d)
    return d


COND_COLS = ["bundle_id", "mktcap", "mktcap_pct", "n_univ", "n_excl", "stake_band", "buyer_group", "kospi",
             "period_early", "premium_amt", "stake_value", "post_financing_1y"]


def load_cond(con) -> None:
    from src.db.build import _reset
    d = build_cond(con)
    _reset(con, "premium_cond")
    df = d[COND_COLS].copy()
    con.register("tmp_df", df)
    try:
        con.execute("INSERT INTO premium_cond BY NAME SELECT * FROM tmp_df")
    finally:
        con.unregister("tmp_df")
    print(f"premium_cond={len(df):,} pct missing={int(df.mktcap_pct.isna().sum())}")


# ---------------------------------------------------------------- 2. analysis helpers (pure, unit-tested)

def pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    """Mean pinball (check) loss."""
    e = np.asarray(y, float) - np.asarray(pred, float)
    return float(np.mean(np.maximum(q * e, (q - 1) * e)))


def design(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-registered design matrix: const, mktcap_pct, stake dummies (ref lt25), buyer dummies (ref strategic),
    kospi, period_early."""
    X = pd.DataFrame({"const": 1.0, "mktcap_pct": df.mktcap_pct.astype(float)}, index=df.index)
    X["stake_25to50"] = (df.stake_band == "25to50").astype(float)
    X["stake_gt50"] = (df.stake_band == "gt50").astype(float)
    X["buyer_financial"] = (df.buyer_group == "financial").astype(float)
    X["buyer_other"] = (df.buyer_group == "other").astype(float)
    X["kospi"] = df.kospi.astype(float)
    X["period_early"] = df.period_early.astype(float)
    return X


def fit_qr(df: pd.DataFrame, q: float) -> pd.Series:
    from statsmodels.regression.quantile_regression import QuantReg
    X = design(df)
    return QuantReg(df.prem_bu20_doc.astype(float), X).fit(q=q, max_iter=5000).params


def predict_qr(params: pd.Series, df: pd.DataFrame) -> np.ndarray:
    return design(df)[params.index].to_numpy() @ params.to_numpy()


def pseudo_r1(df: pd.DataFrame, q: float) -> float:
    """Koenker-Machado R1 = 1 - V(model) / V(intercept only)."""
    y = df.prem_bu20_doc.to_numpy(float)
    v1 = pinball(y, predict_qr(fit_qr(df, q), df), q)
    v0 = pinball(y, np.full(len(y), np.quantile(y, q)), q)
    return 1 - v1 / v0


def bootstrap_params(df: pd.DataFrame, q: float, n: int = 1000, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        s = df.iloc[rng.integers(0, len(df), len(df))]
        try:
            out.append(fit_qr(s, q))
        except Exception:   # noqa: BLE001  (a degenerate resample: skip)
            continue
    return pd.DataFrame(out)


def cross_validate(df: pd.DataFrame, k: int = 5, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    folds = np.array_split(rng.permutation(len(df)), k)
    loss = {q: {"model": [], "uncond": []} for q in QS}
    covered, crossings, n_test = 0, 0, 0
    for i in range(k):
        te = df.iloc[folds[i]]
        tr = df.iloc[np.concatenate([folds[j] for j in range(k) if j != i])]
        preds = {}
        for q in QS:
            preds[q] = predict_qr(fit_qr(tr, q), te)
            y = te.prem_bu20_doc.to_numpy(float)
            loss[q]["model"].append(pinball(y, preds[q], q) * len(te))
            loss[q]["uncond"].append(pinball(y, np.full(len(te), tr.prem_bu20_doc.quantile(q)), q) * len(te))
        y = te.prem_bu20_doc.to_numpy(float)
        covered += int(((y >= preds[0.25]) & (y <= preds[0.75])).sum())
        crossings += int(((preds[0.25] > preds[0.5]) | (preds[0.5] > preds[0.75])).sum())
        n_test += len(te)
    res = {}
    for q in QS:
        m, u = sum(loss[q]["model"]) / n_test, sum(loss[q]["uncond"]) / n_test
        res[f"q{int(q * 100)}"] = {"model": m, "uncond": u, "improvement": 1 - m / u}
    res["coverage_25_75"] = covered / n_test
    res["crossings"] = crossings
    res["n_test"] = n_test
    return res


def cv_repeats(df: pd.DataFrame, n: int = 20, base_seed: int = SEED) -> dict:
    """P2.6 reference only (logic review L16): the same 5-fold CV with n different fold splits (seeds base_seed ..
    base_seed + n - 1). The pre-registered decision still uses the single registered seed; this shows how much the
    q50 improvement moves with the split alone."""
    imp = np.array([cross_validate(df, seed=base_seed + i)["q50"]["improvement"] for i in range(n)])
    return {"n_seeds": n, "seeds": f"{base_seed}..{base_seed + n - 1}", "min": float(imp.min()),
            "q25": float(np.quantile(imp, 0.25)), "median": float(np.median(imp)), "q75": float(np.quantile(imp, 0.75)),
            "max": float(imp.max()), "share_ge_5pct": float((imp >= 0.05).mean()), "values": [float(x) for x in imp]}


def neighbours(df: pd.DataFrame, pct: float, market: str, k: int = 50) -> pd.DataFrame:
    """The k deals nearest in mktcap_pct, same market first, filled from the other market if needed."""
    d = df.assign(_dist=(df.mktcap_pct - pct).abs())
    same = d[d.market == market].sort_values("_dist")
    if len(same) >= k:
        return same.head(k)
    other = d[d.market != market].sort_values("_dist")
    return pd.concat([same, other.head(k - len(same))])


def quintile_band(p: float) -> str:
    """mktcap_pct band of 20 points (the fallback table): P0-20 ... P80-100."""
    lo = min(int(p // 20) * 20, 80)
    return f"P{lo}-{lo + 20}"


def mode_profile(df: pd.DataFrame) -> dict:
    return {"stake_band": df.stake_band.mode()[0], "buyer_group": df.buyer_group.mode()[0],
            "period_early": int(df.period_early.mode()[0])}


# ---------------------------------------------------------------- 3. analysis

def load_frame(con) -> pd.DataFrame:
    df = con.execute("""SELECT c.bundle_id, c.prem_bu20_doc, c.market_at_ann AS market, c.year, c.nocap_suspect,
                               p.* EXCLUDE (bundle_id)
                        FROM premium_cond p JOIN premium_calc c USING (bundle_id)""").fetchdf()
    df["nocap_suspect"] = df.nocap_suspect.fillna(False).astype(bool)
    df["post_financing_1y"] = df.post_financing_1y.fillna(False).astype(bool)
    return df.dropna(subset=["mktcap_pct", "prem_bu20_doc"]).reset_index(drop=True)


def amount_checks(df: pd.DataFrame) -> dict:
    from statsmodels.regression.quantile_regression import QuantReg
    from src.premium.p2c_stats import median_diff_ci  # noqa: F401  (used by callers for symmetry)
    d = df.dropna(subset=["premium_amt", "stake_value"]).copy()
    d["band"] = d.mktcap_pct.map(quintile_band)
    tab = d.groupby("band").agg(n=("premium_amt", "size"), amt_med=("premium_amt", "median"),
                                amt_q1=("premium_amt", lambda s: s.quantile(0.25)),
                                amt_q3=("premium_amt", lambda s: s.quantile(0.75)),
                                stake_med=("stake_value", "median"), pct_med=("prem_bu20_doc", "median"),
                                mktcap_med=("mktcap", lambda s: s.median() / 1e8)).reset_index()
    pos = d[(d.premium_amt > 0) & (d.stake_value > 0)]
    x, y = np.log(pos.stake_value.to_numpy()), np.log(pos.premium_amt.to_numpy())
    A = np.column_stack([np.ones(len(x)), x])
    beta = float(np.linalg.lstsq(A, y, rcond=None)[0][1])
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(1000):
        i = rng.integers(0, len(x), len(x))
        bs.append(np.linalg.lstsq(A[i], y[i], rcond=None)[0][1])
    lo, hi = np.quantile(bs, [0.025, 0.975])
    qr = QuantReg(d.premium_amt.astype(float), pd.DataFrame({"const": 1.0, "stake_value": d.stake_value})).fit(q=0.5)
    return {"table": tab, "ols": {"n": len(pos), "beta": beta, "ci_lo": float(lo), "ci_hi": float(hi),
                                  "fixed_component": bool(hi < 1)},
            "median_reg": {"n": len(d), "const": float(qr.params["const"]), "slope": float(qr.params["stake_value"])}}


def small_cap_checks(df: pd.DataFrame) -> pd.DataFrame:
    from src.premium.p2c_stats import median_diff_ci
    s = df[df.mktcap_pct <= 100 / 3]
    rows = []
    for name, col in (("무자본 의심", "nocap_suspect"), ("종결 후 1년 안 CB·BW·EB·제3자배정(post_financing_1y)", "post_financing_1y")):
        a, b = s.loc[s[col], "prem_bu20_doc"], s.loc[~s[col], "prem_bu20_doc"]
        d, lo, hi = median_diff_ci(a, b)
        rows.append({"비교(소형 1/3 안)": name, "예 n": len(a), "예 중앙값": a.median(), "아니오 n": len(b),
                     "아니오 중앙값": b.median(), "차이": d, "95% CI 하한": lo, "95% CI 상한": hi})
    # same comparison in the rest of the sample, for context
    r = df[df.mktcap_pct > 100 / 3]
    for name, col in (("(참고) 소형 밖: 무자본 의심", "nocap_suspect"), ("(참고) 소형 밖: post_financing_1y", "post_financing_1y")):
        a, b = r.loc[r[col], "prem_bu20_doc"], r.loc[~r[col], "prem_bu20_doc"]
        d, lo, hi = median_diff_ci(a, b)
        rows.append({"비교(소형 1/3 안)": name, "예 n": len(a), "예 중앙값": a.median(), "아니오 n": len(b),
                     "아니오 중앙값": b.median(), "차이": d, "95% CI 하한": lo, "95% CI 상한": hi})
    return pd.DataFrame(rows)


def regression(df: pd.DataFrame, n_boot: int = 1000) -> dict:
    coefs = []
    for q in QS:
        p = fit_qr(df, q)
        bs = bootstrap_params(df, q, n_boot)
        for name in p.index:
            coefs.append({"q": q, "term": name, "coef": float(p[name]),
                          "ci_lo": float(bs[name].quantile(0.025)), "ci_hi": float(bs[name].quantile(0.975)),
                          "n_boot": len(bs)})
    r1 = {f"q{int(q * 100)}": pseudo_r1(df, q) for q in QS}
    return {"coefs": pd.DataFrame(coefs), "pseudo_r1": r1, "cv": cross_validate(df)}


def comparison_table(df: pd.DataFrame) -> pd.DataFrame:
    prof = mode_profile(df)
    params = {q: fit_qr(df, q) for q in QS}
    rows = []
    for market in ("KOSDAQ", "KOSPI"):
        for p in (10, 30, 50, 70, 90):
            pt = pd.DataFrame([{"mktcap_pct": p, "stake_band": prof["stake_band"], "buyer_group": prof["buyer_group"],
                                "kospi": int(market == "KOSPI"), "period_early": prof["period_early"]}])
            reg = {q: float(predict_qr(params[q], pt)[0]) for q in QS}
            nb = neighbours(df, p, market)
            n_same = int((nb.market == market).sum())
            nq = nb.prem_bu20_doc.quantile(list(QS)).to_list()
            rows.append({"시장": market, "시총 백분위": p, "회귀 25%": reg[0.25], "회귀 50%": reg[0.5], "회귀 75%": reg[0.75],
                         "이웃 25%": nq[0], "이웃 50%": nq[1], "이웃 75%": nq[2], "이웃 n(같은 시장)": n_same,
                         "이웃 백분위 범위": f"{nb.mktcap_pct.min():.0f}~{nb.mktcap_pct.max():.0f}",
                         "경고(|차이|>10%p)": abs(reg[0.5] - nq[1]) > 0.10})
    return pd.DataFrame(rows)


def analysis(con) -> dict:
    df = load_frame(con)
    cfg = load_cfg()
    out = {"n": len(df), "profile": mode_profile(df)}
    u = con.execute("SELECT avg(n_univ), avg(n_excl), min(n_univ), max(n_univ) FROM premium_cond").fetchone()
    out["universe"] = {"avg_n_univ": u[0], "avg_n_excl": u[1], "min": u[2], "max": u[3]}
    out["pct_range"] = df.groupby("market").mktcap_pct.agg(["min", "max", "median", "size"]).reset_index()
    out["amount"] = amount_checks(df)
    out["small_cap"] = small_cap_checks(df)
    out["regression"] = regression(df)
    imp = out["regression"]["cv"]["q50"]["improvement"]
    out["decision"] = {"cv_improvement_q50": imp, "threshold": 0.05,
                       "adopt_regression": bool(imp >= 0.05), "rule": cfg["decision_rules"]["adopt_regression"]}
    out["cv_repeats"] = cv_repeats(df)
    out["comparison"] = comparison_table(df)
    d = df.copy()
    d["band"] = d.mktcap_pct.map(quintile_band)
    out["band_table"] = d.groupby(["band"]).prem_bu20_doc.agg(
        n="size", q25=lambda s: s.quantile(0.25), q50="median", q75=lambda s: s.quantile(0.75)).reset_index()
    out["band_market_table"] = d.groupby(["market", "band"]).prem_bu20_doc.agg(
        n="size", q25=lambda s: s.quantile(0.25), q50="median", q75=lambda s: s.quantile(0.75)).reset_index()
    return out


def main() -> None:
    from src.premium.p2b1_summary import md as to_md
    con = duckdb.connect(str(DB_PATH), read_only=True)
    a = analysis(con)
    parts = [f"n = {a['n']}, mode profile = {a['profile']}", f"universe = {a['universe']}",
             f"decision = {a['decision']}", f"pseudo R1 = {a['regression']['pseudo_r1']}",
             f"cv = {json.dumps(a['regression']['cv'], ensure_ascii=False)}",
             f"amount ols = {a['amount']['ols']}", f"median reg = {a['amount']['median_reg']}",
             f"cv repeats (reference, not the decision) = {json.dumps(a['cv_repeats'], ensure_ascii=False)}"]
    for k in ("pct_range", "band_table", "band_market_table", "comparison", "small_cap"):
        parts.append(f"## {k}\n\n{to_md(a[k].round(4))}")
    parts.append(f"## amount table\n\n{to_md(a['amount']['table'].round(3))}")
    parts.append(f"## coefs\n\n{to_md(a['regression']['coefs'].round(4))}")
    text = "\n\n".join(parts)
    (ROOT / "data" / "interim" / "p2c3.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
