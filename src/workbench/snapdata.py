"""Data seams of the public snapshot (config/p7c3.yaml decisions.snapshot_mechanism).

A *seam* wraps an engine function that reads the DB and returns only DART / ECOS data (statements, D&A, balance-sheet
lines, rates, ...) or an aggregate of KRX-derived peer data (median βu, multiple quartiles, target D/E). Three modes:

    off      (PC, default)  the function runs as before -> every PC / RF / JW value is unchanged
    record   (PC snapshot build, scripts/build_public_snapshots)  the function runs and its return value is stored
    replay   (public deployment, no DB)  the stored value is returned; a call that was not recorded raises Missing
             ('PC 모드에서만'), e.g. a peer subset the public snapshot has no aggregate for

    @seam("fs_frame", key=lambda corp, fs, fill: (corp, fs, fill))
    def fs_frame(corp, fs, fill): ...

The mode is process-wide (the Streamlit server and the confirmation job each run one mode). Values are stored as JSON with
type tags (DataFrame, Series, tuple, non-string dict keys, NaN) so a replayed value equals the recorded one exactly
(floats round-trip through repr). Nothing here decides a value.
"""
from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime
from functools import wraps

import numpy as np
import pandas as pd

from src.market.user_provider import PublicDataUnavailable


class Missing(PublicDataUnavailable):
    """The public snapshot has no value for this call (PC mode only). args = (message on screen, seam name for logs)."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


_LOCK = threading.RLock()
_STATE = {"mode": "off", "store": {}}


def mode() -> str:
    return _STATE["mode"]


def replaying() -> bool:
    return _STATE["mode"] == "replay"


def set_mode(m: str, store: dict | None = None) -> None:
    if m not in ("off", "record", "replay"):
        raise ValueError(m)
    with _LOCK:
        _STATE["mode"] = m
        _STATE["store"] = {} if store is None else store


def store() -> dict:
    return _STATE["store"]


def add(entries: dict) -> None:
    """Replay: merge one company's recorded entries (keys are unique per data identity, shared peers are equal)."""
    with _LOCK:
        _STATE["store"].update(entries)


class recording:
    """with recording() as st: ... -> st = the entries recorded inside the block (mode restored afterwards)."""

    def __enter__(self):
        self._prev = (_STATE["mode"], _STATE["store"])
        set_mode("record", {})
        return _STATE["store"]

    def __exit__(self, *exc):
        set_mode(*self._prev)
        return False


def key_of(name: str, key) -> str:
    return name + ":" + json.dumps(encode(key), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canon(o):
    """Canonical row order of a recorded value (record mode, seams with canon=True): DB results without ORDER BY come back in
    a different order from run to run; the engine does not depend on the order (pivots, sums, look-ups by period), the
    snapshot file must (same input -> same bytes). DataFrame with a RangeIndex -> rows sorted by every column; other
    DataFrame / Series -> sorted by index; tuples and dict values recursively."""
    if isinstance(o, pd.DataFrame):
        positional = isinstance(o.index, pd.RangeIndex) or (o.index.nlevels == 1 and list(o.index) == list(range(len(o))))
        if positional:                    # a plain row number (a decoded frame has an Index 0..n-1, not a RangeIndex)
            try:
                return o.sort_values(list(o.columns), kind="mergesort", na_position="last").reset_index(drop=True)
            except TypeError:
                key = o.astype(str).agg("|".join, axis=1)
                return o.loc[key.sort_values(kind="mergesort").index].reset_index(drop=True)
        return o.sort_index(kind="mergesort")
    if isinstance(o, pd.Series):
        return o.sort_index(kind="mergesort")
    if isinstance(o, tuple):
        return tuple(canon(x) for x in o)
    if isinstance(o, dict):
        return {k: canon(v) for k, v in o.items()}
    return o


def seam(name: str, key, canonical: bool = False):
    """Decorator. key(*args, **kw) -> JSON-able identity of the data (never a connection or a path of this machine).
    canonical: record the value in canonical row order (canon)."""
    def deco(fn):
        @wraps(fn)
        def w(*a, **kw):
            m = _STATE["mode"]
            if m == "off":
                return fn(*a, **kw)
            k = key_of(name, key(*a, **kw))
            if m == "replay":
                st = _STATE["store"]
                if k not in st:
                    raise Missing("공개 배포에 없는 계산입니다(PC 모드에서만)", name)
                return decode(st[k])
            out = fn(*a, **kw)
            _STATE["store"][k] = encode(canon(out) if canonical else out)
            return decode(_STATE["store"][k])          # the PC run continues with exactly what the cloud will get
        w.__wrapped_seam__ = name
        return w
    return deco


def put(name: str, key, value) -> None:
    """Record a value computed outside a seam function (record mode only; ignored otherwise)."""
    if _STATE["mode"] == "record":
        _STATE["store"][key_of(name, key)] = encode(value)


def get(name: str, key):
    """Replay a value recorded with put (raises Missing)."""
    k = key_of(name, key)
    if k not in _STATE["store"]:
        raise Missing("공개 배포에 없는 값입니다(PC 모드에서만)", name)
    return decode(_STATE["store"][k])


# ---------------------------------------------------------------- JSON with type tags

def _f(x: float):
    if math.isnan(x):
        return {"$f": "nan"}
    if math.isinf(x):
        return {"$f": "inf" if x > 0 else "-inf"}
    return x


def encode(o):
    if o is None or isinstance(o, (bool, str)):
        return o
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return _f(float(o))
    if isinstance(o, (pd.Timestamp, datetime)):
        return {"$dt": o.isoformat()}
    if isinstance(o, date):
        return {"$date": o.isoformat()}
    if isinstance(o, tuple):
        return {"$t": [encode(x) for x in o]}
    if isinstance(o, list):
        return [encode(x) for x in o]
    if isinstance(o, dict):
        if all(isinstance(k, str) and not k.startswith("$") for k in o):
            return {k: encode(v) for k, v in o.items()}
        return {"$m": [[encode(k), encode(v)] for k, v in o.items()]}
    if isinstance(o, pd.DataFrame):
        ix = o.index
        return {"$df": {"columns": [encode(c) for c in o.columns], "dtypes": [str(t) for t in o.dtypes],
                        "index": [encode(x) for x in ix.tolist()], "index_names": [encode(n) for n in ix.names],
                        "index_dtype": str(ix.dtype) if ix.nlevels == 1 else None, "nlevels": ix.nlevels,
                        "data": [[encode(v) for v in row] for row in o.itertuples(index=False, name=None)]}}
    if isinstance(o, pd.Series):
        ix = o.index
        return {"$s": {"name": encode(o.name), "dtype": str(o.dtype), "index": [encode(x) for x in ix.tolist()],
                       "index_names": [encode(n) for n in ix.names], "index_dtype": str(ix.dtype) if ix.nlevels == 1 else None,
                       "nlevels": ix.nlevels, "values": [encode(v) for v in o.tolist()]}}
    if isinstance(o, np.ndarray):
        return [encode(x) for x in o.tolist()]
    if o is pd.NA or o is pd.NaT:
        return {"$f": "nan"}
    raise TypeError(f"snapdata.encode: {type(o).__name__}")


def _index(vals, names, nlevels, dtype):
    if nlevels > 1:
        return pd.MultiIndex.from_tuples([tuple(v) for v in vals], names=names)
    try:
        return pd.Index(vals, name=names[0], dtype=dtype if dtype not in (None, "object") else None)
    except (TypeError, ValueError):
        return pd.Index(vals, name=names[0])


def _col(vals, dt):
    try:
        return pd.array(vals, dtype=dt) if dt != "object" else pd.array(vals, dtype=object)
    except (TypeError, ValueError):
        return pd.array(vals, dtype=object)


def decode(o):
    if isinstance(o, list):
        return [decode(x) for x in o]
    if not isinstance(o, dict):
        return o
    if "$f" in o:
        return float(o["$f"])
    if "$dt" in o:
        return pd.Timestamp(o["$dt"])
    if "$date" in o:
        return date.fromisoformat(o["$date"])
    if "$t" in o:
        return tuple(decode(x) for x in o["$t"])
    if "$m" in o:
        return {_hashable(decode(k)): decode(v) for k, v in o["$m"]}
    if "$df" in o:
        d = o["$df"]
        cols = [decode(c) for c in d["columns"]]
        rows = [[decode(v) for v in r] for r in d["data"]]
        ix = _index([decode(x) for x in d["index"]], [decode(n) for n in d["index_names"]], d["nlevels"], d.get("index_dtype"))
        data = {i: _col([r[i] for r in rows], dt) for i, dt in enumerate(d["dtypes"])}
        df = pd.DataFrame(data, index=ix)
        df.columns = pd.Index(cols) if cols else pd.Index([])
        if not cols:
            df = pd.DataFrame(index=ix)
        return df
    if "$s" in o:
        d = o["$s"]
        ix = _index([decode(x) for x in d["index"]], [decode(n) for n in d["index_names"]], d["nlevels"], d.get("index_dtype"))
        return pd.Series(_col([decode(v) for v in d["values"]], d["dtype"]), index=ix, name=decode(d["name"]))
    return {k: decode(v) for k, v in o.items()}


def _hashable(k):
    return tuple(_hashable(x) for x in k) if isinstance(k, list) else k
