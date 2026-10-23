"""Path text written into outputs (P7-E, config/p7e.yaml abs_paths).

The Excel model and the report name the config file each input comes from. A session confirmed in a workspace outside the
project (public deployment, KVI_WORKSPACE) used to print the workspace's absolute path (the PC's user folder or the
server's temp folder). label() is the one rule for that text; files stay where they are.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.collect.core import ROOT

WORKSPACE = "공개 배포 작업 공간"
OUTSIDE = "작업 공간 밖"


def _within(p: Path, base: Path) -> Path | None:
    for a, b in ((p, base), (p.resolve(), base.resolve())):
        if a.is_relative_to(b):
            return a.relative_to(b)
    return None


def label(p) -> str:
    """Inside the project: the path relative to it (as before). Inside the session workspace: '공개 배포 작업 공간/' + the
    path inside it. Anywhere else: '작업 공간 밖/' + the file name."""
    p = Path(p)
    p = p if p.is_absolute() else ROOT / p
    r = _within(p, ROOT)
    if r is not None:
        return r.as_posix()
    w = None
    try:
        from src.workbench.session import workspace

        w = workspace()
    except ImportError:
        w = None
    w = w or (Path(os.environ["KVI_WORKSPACE"]) if os.environ.get("KVI_WORKSPACE") else None)
    if w is not None:
        r = _within(p, Path(w))
        if r is not None:
            return f"{WORKSPACE}/{r.as_posix()}"
    return f"{OUTSIDE}/{p.name}"
