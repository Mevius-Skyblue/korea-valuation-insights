"""Market-data provider (P7-B): the one place valuation code reads price-derived values from.

Every closing price, market cap, 20-day VWAP, market-cap percentile and beta regression the general pipeline uses goes
through `get()`. Today there is one provider, `DbMarketProvider` (the project DuckDB, 한국거래소 통계정보). P7-C adds a
public-mode provider (values typed by the user) behind the same methods, so the engine code does not change.

    with use(MyProvider()):        # swap for one block (tests, public mode)
        ...

Methods (dates are 'YYYY-MM-DD' strings, amounts in 원):
    quote(code, date)                    (close, market cap, listed shares) on that trading day, or None
    mktcap_at(code, date)                market cap on the last trading day on or before `date` (bonus-issue corrected)
    vwap20(code, as_of)                  {'vwap', 'start', 'end', 'n', 'events'} over 20 trading days to as_of
    mktcap_percentile(as_of, market, mc) {'mktcap_pct', 'n_universe', 'n_excluded'}
    beta_table(as_of, cfg_path, table)   peer beta regressions (DataFrame, also written to DB `table` in DB mode)
    price_days(codes, as_of)             trading days with volume > 0 in the 2 years to as_of (Series by stock_code)
    universe(as_of, markets)             common stocks of the markets on as_of with market cap and corp_master fields
"""
from __future__ import annotations

from contextlib import contextmanager

import duckdb
import pandas as pd


class DbMarketProvider:
    """Reads the project DuckDB (price_daily, mktcap_fix, price_adj). Same functions the P3~P6 code called directly."""

    name = "db"

    def _con(self, con=None):
        from src.db.build import DB_PATH
        return (con, False) if con is not None else (duckdb.connect(str(DB_PATH), read_only=True), True)

    def quote(self, code: str, date: str, con=None):
        c, own = self._con(con)
        try:
            return c.execute("""SELECT d.close, coalesce(f.mktcap_fix, d.mktcap), d.list_shrs FROM price_daily d
                                LEFT JOIN mktcap_fix f ON f.stock_code=d.stock_code AND f.bas_dd=d.bas_dd
                                WHERE d.stock_code=? AND d.bas_dd=?""", [code, date]).fetchone()
        finally:
            if own:
                c.close()

    def mktcap_at(self, code: str, date: str, con=None):
        from src.market.beta_table import mktcap_at
        c, own = self._con(con)
        try:
            return mktcap_at(c, code, date)
        finally:
            if own:
                c.close()

    def vwap20(self, code: str, as_of: str, con=None) -> dict:
        from src.valuation.p3c1 import vwap20
        c, own = self._con(con)
        try:
            return vwap20(c, code, as_of)
        finally:
            if own:
                c.close()

    def mktcap_percentile(self, as_of: str, market: str, mktcap: float, con=None) -> dict:
        from src.premium.predict import mktcap_percentile
        c, own = self._con(con)
        try:
            return mktcap_percentile(c, as_of, market, mktcap)
        finally:
            if own:
                c.close()

    def beta_table(self, as_of: str, cfg_path: str, table: str) -> pd.DataFrame:
        from src.valuation.beta_p3 import build
        return build(as_of, cfg_path, table)

    def price_days(self, codes: list[str], as_of: str, con=None) -> pd.Series:
        from src.valuation.candidates import price_days
        c, own = self._con(con)
        try:
            return price_days(c, codes, as_of)
        finally:
            if own:
                c.close()

    def universe(self, as_of: str, markets: list[str], con=None) -> pd.DataFrame:
        from src.premium.p2c3 import ELIGIBLE_SQL
        c, own = self._con(con)
        try:
            return c.execute(f"""
                SELECT d.stock_code, d.isu_nm, d.mkt_nm, d.close, coalesce(mf.mktcap_fix, d.mktcap) AS mktcap, d.list_shrs,
                       cm.corp_code, cm.corp_name, cm.induty_code, cm.acc_mt, {ELIGIBLE_SQL} AS eligible
                FROM price_daily d
                LEFT JOIN (SELECT DISTINCT stock_code, corp_code, corp_name, induty_code, acc_mt, kind_stkcert, secugrp_nm
                           FROM corp_master) cm ON cm.stock_code = d.stock_code
                LEFT JOIN mktcap_fix mf ON mf.stock_code = d.stock_code AND mf.bas_dd = d.bas_dd
                WHERE d.bas_dd = ? AND d.mkt_nm IN ({','.join('?' * len(markets))})
                ORDER BY d.stock_code""", [as_of, *markets]).df()
        finally:
            if own:
                c.close()


_current = DbMarketProvider()


def get():
    """The active provider."""
    return _current


@contextmanager
def use(provider):
    """Swap the active provider inside a `with` block (restored afterwards, also on error)."""
    global _current
    prev, _current = _current, provider
    try:
        yield provider
    finally:
        _current = prev


def _set_default(provider) -> None:
    """Process-wide default provider (P7-C3 public deployment: no DB -> the user-input provider)."""
    global _current
    _current = provider
