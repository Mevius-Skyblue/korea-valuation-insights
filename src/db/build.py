"""Rebuild data/db/valuation.duckdb from data/raw only (no API calls).

Run:  python -m src.db.build            # all tables
      python -m src.db.build price      # only some loaders (names below)

Design: raw responses are the single source of truth. Deleting the DB loses nothing;
this script recreates every table. Each loader is a separate function so it can be
tested and re-run alone.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from lxml import etree

from src import yamlio
from src.collect.core import ROOT, RawStore

DB_PATH = ROOT / "data" / "db" / "valuation.duckdb"
RAW = ROOT / "data" / "raw"
SCHEMA = Path(__file__).with_name("schema.sql")
_BUILD_CFG = yamlio.load((ROOT / "config" / "build.yaml").read_text(encoding="utf-8"))
KRX_AS_OF = _BUILD_CFG["krx_as_of"]  # KRX base-info snapshot for corp_master (config/build.yaml)
CORPCODE_KEY = _BUILD_CFG["corpcode_key"]  # DART corpCode.xml snapshot


def connect(path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def _manifest_df(api: str, op: str) -> pd.DataFrame:
    m = RawStore().manifest(api, op)
    return pd.DataFrame(m.values()) if m else pd.DataFrame(columns=["file", "key", "fetched_at", "result_code"])


def _load_json(api: str, op: str, file: str):
    return json.loads(RawStore.load(RAW / api / op / file))


def _reset(con, table: str) -> None:
    """Drop and recreate one table from schema.sql."""
    ddl = SCHEMA.read_text(encoding="utf-8")
    start = ddl.index(f"CREATE TABLE {table} ")
    stmt = ddl[start : ddl.index(");", start) + 2]
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(stmt)


# ---------------------------------------------------------------- corp_master


def corpcode_rows() -> list[dict]:
    content = RawStore.load(RAW / "dart" / "corpCode.xml" / f"{CORPCODE_KEY}.zip.gz")
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        root = etree.fromstring(z.read(z.namelist()[0]))
    return [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("list")]


def _date(s: str | None):
    s = (s or "").strip()
    return datetime.strptime(s, "%Y%m%d").date() if len(s) == 8 and s.isdigit() else None


def load_corp_master(con) -> None:
    """KRX base info (KOSPI+KOSDAQ) <-> corpCode.xml <-> company.json."""
    krx = []
    for op in ("stk_isu_base_info", "ksq_isu_base_info"):
        man = RawStore().manifest("KRX", op)[f"{KRX_AS_OF}.json.gz"]
        for r in _load_json("krx", op, f"{KRX_AS_OF}.json.gz")["OutBlock_1"]:
            krx.append({**r, "_op": op, "_fetched": man["fetched_at"]})
    cc = corpcode_rows()
    by_stock = {r["stock_code"]: r for r in cc if r["stock_code"]}
    comp_man = RawStore().manifest("DART", "company.json")

    def company(corp_code):
        rec = comp_man.get(f"{corp_code}.json.gz")
        if not rec:
            return {}, None
        return _load_json("dart", "company.json", rec["file"]), rec["fetched_at"]

    # issuer prefix (ISIN chars 3..8) of common stocks -> corp_code, for preferred shares
    # Only Korean ISINs (KR7...) carry the short code inside; foreign ISINs can collide.
    issuer = {}
    for r in krx:
        c = by_stock.get(r["ISU_SRT_CD"])
        if c and r["ISU_CD"].startswith("KR7"):
            issuer[r["ISU_CD"][3:8]] = c["corp_code"]

    rows, issues = [], []
    for r in krx:
        code = r["ISU_SRT_CD"]
        c = by_stock.get(code)
        if c:
            corp_code, method = c["corp_code"], "stock_code"
        elif r["ISU_CD"].startswith("KR7") and r["ISU_CD"][3:8] in issuer:
            corp_code, method = issuer[r["ISU_CD"][3:8]], "issuer_prefix"
        else:
            corp_code, method = None, "none"
            issues.append(
                {
                    "side": "krx_only",
                    "stock_code": code,
                    "isin": r["ISU_CD"],
                    "corp_code": None,
                    "name": r["ISU_ABBRV"],
                    "detail": f"{r['MKT_TP_NM']} {r['SECUGRP_NM']} {r['KIND_STKCERT_TP_NM']}",
                }
            )
        comp, comp_at = company(corp_code) if corp_code else ({}, None)
        rows.append(
            {
                "stock_code": code,
                "isin": r["ISU_CD"],
                "corp_code": corp_code,
                "jurir_no": comp.get("jurir_no") or None,
                "bizr_no": comp.get("bizr_no") or None,
                "link_method": method,
                "corp_name": comp.get("corp_name"),
                "krx_name": r["ISU_ABBRV"],
                "market": r["MKT_TP_NM"],
                "sect_tp_nm": r["SECT_TP_NM"],
                "secugrp_nm": r["SECUGRP_NM"],
                "kind_stkcert": r["KIND_STKCERT_TP_NM"],
                "list_dt": _date(r["LIST_DD"]),
                "parval": r["PARVAL"],
                "list_shrs": int(r["LIST_SHRS"]) if r["LIST_SHRS"] else None,
                "corp_cls": comp.get("corp_cls"),
                "induty_code": comp.get("induty_code"),
                "acc_mt": comp.get("acc_mt"),
                "est_dt": _date(comp.get("est_dt")),
                "source": f"KRX {r['_op']} + DART corpCode.xml" + (" + DART company.json" if comp else ""),
                "source_key": f"basDd={KRX_AS_OF}; corpCode={CORPCODE_KEY}; corp_code={corp_code}",
                "fetched_at": comp_at or r["_fetched"],
            }
        )
    krx_codes = {r["ISU_SRT_CD"] for r in krx}
    for c in cc:
        if c["stock_code"] and c["stock_code"] not in krx_codes:
            issues.append(
                {
                    "side": "dart_only",
                    "stock_code": c["stock_code"],
                    "isin": None,
                    "corp_code": c["corp_code"],
                    "name": c["corp_name"],
                    "detail": "stock_code in corpCode.xml but not in KRX KOSPI/KOSDAQ base info "
                    f"{KRX_AS_OF} (delisted / KONEX / other)",
                }
            )
    _reset(con, "corp_master")
    _reset(con, "corp_link_issues")
    df = pd.DataFrame(rows)  # noqa: F841 - DuckDB reads this DataFrame by its name in the SQL below
    con.execute("INSERT INTO corp_master SELECT * FROM df")
    idf = pd.DataFrame(issues)  # noqa: F841 - DuckDB reads this DataFrame by its name in the SQL below
    con.execute("INSERT INTO corp_link_issues SELECT * FROM idf")


# ---------------------------------------------------------------- KRX prices + calendar

KRX_FIELDS = [
    "BAS_DD",
    "ISU_CD",
    "ISU_NM",
    "MKT_NM",
    "SECT_TP_NM",
    "TDD_CLSPRC",
    "CMPPREVDD_PRC",
    "FLUC_RT",
    "TDD_OPNPRC",
    "TDD_HGPRC",
    "TDD_LWPRC",
    "ACC_TRDVOL",
    "ACC_TRDVAL",
    "MKTCAP",
    "LIST_SHRS",
]


def _num(col: str, typ: str = "BIGINT") -> str:
    return f"TRY_CAST(NULLIF(replace(o.{col}, ',', ''), '') AS {typ})"


def load_prices(con) -> None:
    """price_daily from all KRX bydd_trd raw files, read by DuckDB directly from .json.gz."""
    _reset(con, "price_daily")
    struct = "STRUCT(" + ", ".join(f"{f} VARCHAR" for f in KRX_FIELDS) + ")[]"
    for op in ("stk_bydd_trd", "ksq_bydd_trd"):
        d = RAW / "krx" / op
        if not d.exists():
            continue
        man = _manifest_df("KRX", op)[["file", "fetched_at"]]
        con.register("man", man)
        glob = (d / "*.json.gz").as_posix()
        con.execute(f"""
            INSERT INTO price_daily
            SELECT strptime(o.BAS_DD, '%Y%m%d')::DATE, o.ISU_CD, o.ISU_NM, o.MKT_NM, o.SECT_TP_NM,
                   {_num("TDD_CLSPRC")}, {_num("CMPPREVDD_PRC")}, {_num("FLUC_RT", "DOUBLE")},
                   {_num("TDD_OPNPRC")}, {_num("TDD_HGPRC")}, {_num("TDD_LWPRC")},
                   {_num("ACC_TRDVOL")}, {_num("ACC_TRDVAL")}, {_num("MKTCAP")}, {_num("LIST_SHRS")},
                   'KRX {op}', o.BAS_DD, TRY_CAST(man.fetched_at AS TIMESTAMP)
            FROM (SELECT unnest(OutBlock_1) AS o, parse_filename(filename) AS file
                  FROM read_json('{glob}', columns={{'OutBlock_1': '{struct}'}}, filename=true,
                                 compression='gzip', format='auto')) t
            LEFT JOIN man ON man.file = t.file
        """)
        con.unregister("man")


def load_calendar(con) -> None:
    """Weekday with rows in either market = trading day; empty in both = holiday."""
    _reset(con, "trading_calendar")
    recs = {}
    for op, col in (("stk_bydd_trd", "stk"), ("ksq_bydd_trd", "ksq")):
        for rec in RawStore().manifest("KRX", op).values():
            recs.setdefault(rec["key"], {})[col] = rec["result_code"]
    counts = con.execute("""SELECT strftime(bas_dd, '%Y%m%d') d,
                                   count(*) FILTER (WHERE mkt_nm='KOSPI') k, count(*) FILTER (WHERE mkt_nm='KOSDAQ') q
                            FROM price_daily GROUP BY 1""").fetchall()
    cnt = {d: (k, q) for d, k, q in counts}
    rows = []
    for d, codes in sorted(recs.items()):
        if "stk" not in codes or "ksq" not in codes:
            continue  # incomplete day (collection still running) -> not decided yet
        k, q = cnt.get(d, (0, 0))
        rows.append(
            {
                "date": _date(d),
                "is_trading": (k + q) > 0,
                "n_kospi": k,
                "n_kosdaq": q,
                "source": "KRX stk_bydd_trd + ksq_bydd_trd",
                "source_key": f"basDd={d}; stk={codes['stk']}; ksq={codes['ksq']}",
            }
        )
    df = pd.DataFrame(rows)
    if len(df):
        con.execute("INSERT INTO trading_calendar SELECT * FROM df")


# ---------------------------------------------------------------- ECOS


def ecos_rows() -> pd.DataFrame:
    """All StatisticSearch rows from raw ECOS files, with fetched_at and raw key."""
    man = RawStore().manifest("ECOS", "StatisticSearch")
    out = []
    for file, rec in man.items():
        d = _load_json("ecos", "StatisticSearch", file)
        for r in d.get("StatisticSearch", {}).get("row", []):
            out.append({**r, "_key": rec["key"], "_fetched": rec["fetched_at"]})
    return pd.DataFrame(out)


def _ecos_cfg() -> dict:
    return yamlio.load((ROOT / "config" / "ecos_series.yaml").read_text(encoding="utf-8"))


def load_ecos(con) -> None:
    df = ecos_rows()
    cfg = _ecos_cfg()
    df["cycle"] = df["TIME"].str.len().map({8: "D", 6: "M", 4: "A"})
    val = pd.to_numeric(df["DATA_VALUE"], errors="coerce")
    df = df.assign(value=val)
    src = "ECOS StatisticSearch"

    # index_daily
    idx = []
    for s in cfg["index"]:
        sel = df[(df.STAT_CODE == s["stat"]) & (df.ITEM_CODE1 == s["item"]) & (df.cycle == "D")]
        idx.append(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(sel.TIME, format="%Y%m%d").dt.date,
                    "index_code": s["code"],
                    "index_name": s["name"],
                    "value": sel.value,
                    "source": src,
                    "source_key": f"{s['stat']}/{s['item']}",
                    "fetched_at": pd.to_datetime(sel._fetched),
                }
            )
        )
    _reset(con, "index_daily")
    idf = pd.concat(idx)  # noqa: F841 - DuckDB reads this DataFrame by its name in the SQL below
    con.execute("INSERT INTO index_daily SELECT * FROM idf")

    # rates_daily (D and M)
    rates = []
    for freq, key in (("D", "rates_daily"), ("M", "rates_monthly")):
        for s in cfg[key]:
            sel = df[(df.STAT_CODE == s["stat"]) & (df.ITEM_CODE1 == s["item"]) & (df.cycle == freq)]
            fmt = "%Y%m%d" if freq == "D" else "%Y%m"
            rates.append(
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(sel.TIME, format=fmt).dt.date,
                        "freq": freq,
                        "rate_code": s["code"],
                        "rate_name": s["name"],
                        "value": sel.value,
                        "source": src,
                        "source_key": f"{s['stat']}/{s['item']}/{freq}",
                        "fetched_at": pd.to_datetime(sel._fetched),
                    }
                )
            )
    _reset(con, "rates_daily")
    rdf = pd.concat(rates)  # noqa: F841 - DuckDB reads this DataFrame by its name in the SQL below
    con.execute("INSERT INTO rates_daily SELECT * FROM rdf")

    # industry_bench (501Y, annual)
    sel = df[df.STAT_CODE.isin(cfg["industry"]["tables"]) & (df.cycle == "A")]
    bdf = pd.DataFrame(  # noqa: F841 - DuckDB reads this DataFrame by its name in the SQL below
        {
            "stat_code": sel.STAT_CODE,
            "stat_name": sel.STAT_NAME,
            "industry_code": sel.ITEM_CODE1,
            "industry_name": sel.ITEM_NAME1,
            "size_code": sel.ITEM_CODE2,
            "size_name": sel.ITEM_NAME2,
            "account_code": sel.ITEM_CODE3,
            "account_name": sel.ITEM_NAME3,
            "year": sel.TIME.astype(int),
            "value": sel.value,
            "unit": sel.UNIT_NAME,
            "source": src,
            "source_key": sel.STAT_CODE + "/" + sel.ITEM_CODE1 + "/" + sel.ITEM_CODE2 + "/" + sel.ITEM_CODE3,
            "fetched_at": pd.to_datetime(sel._fetched),
        }
    )
    _reset(con, "industry_bench")
    con.execute("INSERT INTO industry_bench SELECT * FROM bdf")


# ---------------------------------------------------------------- entry

LOADERS = {"corp": load_corp_master, "price": load_prices, "calendar": load_calendar, "ecos": load_ecos}


def build(names: list[str] | None = None, path: Path = DB_PATH) -> None:
    # output-only folder used by the later steps (valuation tables, Excel verification); a fresh clone has no data/
    # except the data/raw link (P4-X reproducibility finding)
    (ROOT / "data" / "interim").mkdir(parents=True, exist_ok=True)
    con = connect(path)
    try:
        for name in names or list(LOADERS) + extra_loaders():
            fn = LOADERS.get(name) or _extra(name)
            t = datetime.now()
            fn(con)
            print(f"{name}: done in {(datetime.now() - t).total_seconds():.1f}s")
    finally:
        con.close()


def extra_loaders() -> list[str]:
    """Loaders defined in other modules (financial statements, adjusted prices)."""
    return ["fs", "price_adj", "mktcap_fix", "recon", "beta", "peer", "premium", "terms", "p2b2", "p2c", "p2c3", "p5b"]


def _extra(name: str):
    if name == "fs":
        from src.clean.fs_load import load_fs

        return load_fs
    if name == "beta":
        from src.market.beta_table import build as build_beta

        return lambda con: build_beta()
    if name == "peer":
        from src.valuation.peer_table import build as build_peer

        return lambda con: build_peer()
    if name == "recon":
        from src.clean.recon import load_recon

        return load_recon
    if name == "premium":
        from src.premium.db_load import load_premium

        return load_premium
    if name == "terms":
        from src.premium.terms_load import load_terms

        return load_terms
    if name == "p2b2":
        from src.premium.p2b2_build import load_p2b2

        return load_p2b2
    if name == "p2c3":
        from src.premium.p2c3 import load_cond

        return load_cond
    if name == "p2c":
        from src.premium.p2c_calc import load_p2c

        return load_p2c
    if name == "mktcap_fix":
        from src.market.mktcap_fix import load_mktcap_fix

        return load_mktcap_fix
    if name == "p5b":
        from src.p5.b_build import load_p5b

        return load_p5b
    if name == "price_adj":
        from src.market.adjust import build_price_adj

        return build_price_adj
    raise KeyError(name)


if __name__ == "__main__":
    build(sys.argv[1:] or None)
