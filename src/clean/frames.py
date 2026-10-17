"""Empty-table guards (P7-B5). A query or a list of rows can be empty; pandas then builds a DataFrame without the
expected columns and the next `df.col` access fails (P7-B4 crash: a peer without balance-sheet lines -> classify).

    frame(rows, cols)                      DataFrame with these columns even when there are no rows
    ensure(df, cols)                       add missing columns (empty) to a DataFrame from a query
    pivot(df, index, columns, values)      pivot_table that returns an empty frame with the index names when df is empty
"""
from __future__ import annotations

import pandas as pd


def frame(rows, cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=cols)


def ensure(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if df is None:
        return frame([], cols)
    for c in cols:
        if c not in df.columns:
            df[c] = pd.Series(dtype=object)
    return df


def pivot(df: pd.DataFrame, index: list[str], columns: str, values: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(index=pd.MultiIndex.from_tuples([], names=index))
    return df.pivot_table(index=index, columns=columns, values=values, aggfunc="first")
