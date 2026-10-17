"""Aggregates of KRX-derived peer data for the public snapshot (config/p7c3.yaml snapshot.include / exclude).

The PC code reads the per-peer beta and multiple tables (beta_<name>, peer_<name>_c3, peer_<name>: market caps, regression
betas). The public snapshot keeps only their aggregates. Each consumer records the aggregates it needs, computed from the
same frames with the same functions, and replays them in the public deployment:

    engine(...)   excel.engine_ref.mechanical_reference: βu of the model (beta_u0), multiple quartiles per multiple (peer
                  table after the D&A supplement), EV/EBITDA quartiles before it (convergence n5), number of peer betas,
                  the peers' LTM operating-margin median (diagnose normal-margin candidate)
    ctx(...)      workbench.recalc.Ctx: βu of the draft peers, R² median (display, 2 decimals), number of peers with a beta
    screen(...)   app/wb/model.relative: multiple quartiles of the session's peers
    public(...)   excel.model_data (public mode): the aggregates public.transform puts in the model instead of the rows

Keys = (draft table name, beta spec / index, tiers, peer names). The public snapshot records the draft's full peer set only;
another peer set is not in it (Missing -> 'PC 모드에서만', config/p7c3.yaml decisions.peer_change_public).
Off mode (PC): record / get are not used and the callers keep their own code.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from src.workbench import snapdata as SD


def draft_base(cfg_path: str, cfg: dict) -> str:
    """Table name of the draft (a confirmed session config names its draft in workbench.draft_config)."""
    p = (cfg.get("workbench") or {}).get("draft_config") or cfg_path
    return Path(p).stem.replace("valuation_", "")


def _key(cfg_path: str, cfg: dict, names=None) -> tuple:
    names = sorted(names if names is not None else [p["name"] for p in cfg.get("peers", [])])
    return (draft_base(cfg_path, cfg), cfg["beta"]["spec"], cfg["beta"]["index"], list(cfg["beta"]["peer_tiers"]), names)


def record(kind: str, cfg_path: str, cfg: dict, value: dict, names=None) -> None:
    SD.put(f"agg_{kind}", _key(cfg_path, cfg, names), value)


def get(kind: str, cfg_path: str, cfg: dict, names=None) -> dict:
    return SD.get(f"agg_{kind}", _key(cfg_path, cfg, names))


def r2_display(v) -> float | None:
    """R² median as shown in public (2 decimals, config/p7c3.yaml snapshot.rounding.display_aggregates)."""
    return None if v is None or not np.isfinite(v) else round(float(v), 2)
