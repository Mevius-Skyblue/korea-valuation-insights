"""One shared read-only DuckDB connection for a block of read-only work (P7-C1 speed).

Opening the project DB costs about 0.33 s per connection (539 tables in the catalog); the model data + engine reference
of one company opens it about 10 times. Inside `shared_readonly()` every `duckdb.connect(DB_PATH, read_only=True)`
returns a cursor of one shared connection (a cursor has its own result state; closing it leaves the shared connection
open). Data and results are the same as with separate connections. A read-write connection asked for inside the block
closes the shared one first (DuckDB does not allow both configurations in one process).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path


@contextmanager
def shared_readonly():
    import duckdb

    from src.db.build import DB_PATH

    if getattr(duckdb.connect, "_shared_ro", False):  # nested: the outer block already shares
        yield
        return
    real = duckdb.connect
    target = Path(DB_PATH).resolve()
    state = {"base": None}

    def _is_db(database) -> bool:
        try:
            return Path(str(database)).resolve() == target
        except (OSError, ValueError):
            return False

    def connect(database=":memory:", read_only=False, *args, **kwargs):
        if _is_db(database) and read_only and not args and not kwargs:
            if state["base"] is None:
                state["base"] = real(str(DB_PATH), read_only=True)
            return state["base"].cursor()
        if _is_db(database) and state["base"] is not None:  # a writer: release the shared read-only connection
            state["base"].close()
            state["base"] = None
        return real(database, read_only, *args, **kwargs)

    connect._shared_ro = True
    duckdb.connect = connect
    try:
        yield
    finally:
        duckdb.connect = real
        if state["base"] is not None:
            state["base"].close()
