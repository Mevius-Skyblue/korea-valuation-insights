"""Confirmation jobs of the work screen (split out of app/wb/model.py in P7-C4): start a confirmation in its own process,
follow it, and hand out the files.

    start_confirm(s, mode, user)   the prepared worker (same state, C2-F3), the warm worker (C4-F1) or a new process -
                                   or the queue when the public deployment's cap of running jobs is reached (C4-F5)
    job(sid, mode)                 live status for the screen (polled): Excel ready, reconciliation, report, queue place
    standby / prepared_state       prepared confirmation (PC)
    ensure_warm / take_warm        the warm worker: a job process that has already imported everything
    file_bytes / safe_name         downloads (only files inside this browser session's folders)
The job itself is src/workbench/job.py; this module only starts processes and reads their output folders.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from app.wb.model import no_db, public_deploy, version
from src.collect.core import ROOT
from src.workbench import session as S

_JOBS: dict = {}  # (workspace, sid, mode) -> background confirmation job
_JLOCK = threading.RLock()  # _JOBS changes (browser sessions are threads of one server process)


def _k(sid: str, kind: str) -> tuple:
    """Job key: this browser session's workspace + session id (P7-C3: ids repeat across public workspaces)."""
    return (str(S.workspace() or ""), sid, kind)


def _spawn(args: list[str], log, workspace: bool = True):
    import subprocess

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    ws = S.workspace() if workspace else None
    if ws:  # P7-C3: the job works in this browser session's workspace
        env["KVI_WORKSPACE"] = str(ws)
    else:
        env.pop("KVI_WORKSPACE", None)  # a warm worker gets its workspace with the ticket
    if public_deploy():
        env["KVI_PUBLIC"] = "1"
    with open(log, "w", encoding="utf-8") as f:
        return subprocess.Popen(
            [sys.executable, "-m", "src.workbench.job"] + args,
            cwd=str(ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


WARM_KEY = ("", "_warm", "warm")  # the warm worker in _JOBS (one per server process, any workspace)


def warm_on() -> bool:
    """Warm worker (fix C4-F1): on unless KVI_WARM=0."""
    return os.environ.get("KVI_WARM", "1") != "0"


def _warm_dir() -> Path:
    import tempfile

    return Path(os.environ.get("KVI_WARM_DIR") or Path(tempfile.gettempdir()) / "kvi_warm")


def ensure_warm() -> None:
    """Keep one warm worker waiting (fix C4-F1): a job process that has already imported everything, so the next 확정 does
    not pay for the process start and the imports. Started only when no confirmation is still building its Excel model
    (the warm-up would take CPU from it) and the concurrency cap leaves room."""
    if not warm_on():
        return
    with _JLOCK:
        w = _JOBS.get(WARM_KEY)
        if w and w["proc"].poll() is None:
            return
        _JOBS.pop(WARM_KEY, None)
        if any(
            not _excel_ready(j)
            for k, j in _JOBS.items()
            if k[2] != "standby" and k != WARM_KEY and j.get("proc") and j["proc"].poll() is None
        ):
            return
        cap = max_jobs()
        if cap is not None and running_jobs() >= cap:  # memory: no extra process while the cap is in use (C4-F5)
            return
        d = _warm_dir()
        d.mkdir(parents=True, exist_ok=True)
        base = d / f"w{int(time.time() * 1000)}"
        _JOBS[WARM_KEY] = {
            "proc": _spawn(["--warm", str(base)], base.with_suffix(".log"), workspace=False),
            "base": base,
            "log": base.with_suffix(".log"),
            "started": time.time(),
            "mode": "warm",
        }


def take_warm() -> dict | None:
    """Claim the waiting warm worker (rename .open -> .claimed, atomic) or None (none, or it is leaving)."""
    with _JLOCK:
        w = _JOBS.get(WARM_KEY)
        if not w or w["proc"].poll() is not None:
            return None
        try:
            os.replace(w["base"].with_suffix(".open"), w["base"].with_suffix(".claimed"))
        except OSError:
            # no .open yet: a worker started less than a minute ago has not written it (its interpreter is still starting)
            # and cannot be leaving (it leaves only after 30 idle minutes) -> claim it now, it reads the ticket after its
            # imports. Otherwise it is leaving: start a new process. (P7-C4: without this a confirmation started a fresh
            # job next to a booting warm worker - one process more than the cap)
            if time.time() - w["started"] > 60:
                return None
            w["base"].with_suffix(".claimed").write_text("early", encoding="utf-8")
        _JOBS.pop(WARM_KEY, None)
        return w


def _ticket(w: dict, job: dict) -> None:
    t = w["base"].with_suffix(".ticket")
    tmp = t.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, t)  # the worker never reads half a ticket


def _excel_ready(j: dict) -> bool:
    if "excel_at" in j:
        return True
    try:
        from src.workbench.job import ACK

        f = j["dir"] / "summary.json"
        return (j["dir"] / ACK).exists() and bool((json.loads(f.read_text(encoding="utf-8")).get("outputs") or {}).get("xlsx"))
    except (OSError, KeyError, ValueError):
        return False


def prepare_on() -> bool:
    """Prepared confirmation (C2-F3). PC: on unless WB_PREPARE=0. Public deployment: only with KVI_PREPARE=1 (decided from
    the server memory measurement, config/p7c3.yaml public_app.confirm)."""
    if public_deploy():
        return os.environ.get("KVI_PREPARE") == "1"
    return os.environ.get("WB_PREPARE", "1") != "0" and not no_db()


def standby(sid: str, mode: str = "pc") -> None:
    """Start the prepared-confirmation worker of this session (fix C2-F3) if none runs; workers of other sessions of this
    workspace stop (one browser session works on one session at a time). Nothing is recorded before 확정."""
    ws = str(S.workspace() or "")
    for (k_ws, k_sid, kind), j in list(_JOBS.items()):
        if kind == "standby" and k_ws == ws and k_sid != sid and j["proc"].poll() is None:
            j["proc"].terminate()
            _JOBS.pop((k_ws, k_sid, kind), None)
    j = _JOBS.get(_k(sid, "standby"))
    if j and j["proc"].poll() is None:
        return
    run = _JOBS.get(_k(sid, mode))
    if run and run["proc"].poll() is None:  # a confirmation is running for this session
        return
    d = S.jobs_dir()
    d.mkdir(parents=True, exist_ok=True)
    trig = d / f"{sid}.trigger"
    trig.unlink(missing_ok=True)
    trig.with_suffix(".status").unlink(missing_ok=True)
    _JOBS[_k(sid, "standby")] = {
        "proc": _spawn(["--standby", str(trig), sid, mode], d / f"{sid}_standby.log"),
        "trigger": trig,
        "started": time.time(),
        "mode": mode,
    }


def prepared_state(sid: str) -> dict | None:
    """State of the prepared worker of a session: starting / building / ready (None if none runs)."""
    j = _JOBS.get(_k(sid, "standby"))
    if not j or j["proc"].poll() is not None:
        return None
    f = j["trigger"].with_suffix(".status")
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"state": "starting"}
    except (OSError, json.JSONDecodeError):
        return {"state": "starting"}


# fix C4-F5: at most this many confirmation processes at once in the public deployment (the waiting warm worker counts as
# one: it is only started while a slot is free); more confirmations wait in a queue. Rule of config/p7c4.yaml
# perf_candidates.queue: floor((server limit 2.7 GB x 70% - app process peak) / one job's peak), with the P7-C4 baseline
# server numbers in GB: floor((1.89 - 0.26) / 0.54) = 3 (reports/p7c4_perf.md).
MAX_JOBS_PUBLIC = 3
_QUEUE: list[tuple] = []  # keys (_k) of queued confirmations, oldest first


def max_jobs() -> int | None:
    """How many confirmations may run at once: the public deployment's cap (KVI_MAX_JOBS overrides), none on the PC."""
    if os.environ.get("KVI_MAX_JOBS"):
        return int(os.environ["KVI_MAX_JOBS"])
    return MAX_JOBS_PUBLIC if public_deploy() else None


def running_jobs() -> int:
    """Confirmation processes running now (not the prepared or warm workers)."""
    return sum(1 for k, j in _JOBS.items() if k[2] not in ("standby", "warm") and j.get("proc") and j["proc"].poll() is None)


def start_confirm(s: dict, mode: str = "pc", user: dict | None = None) -> dict:
    """Confirm the current version in its own process (src/workbench/job.py, fixes C2-F2·F3): the Excel model, then the
    reconciliation and the report (public mode: and the KRX scan on the PC). The screen does not wait; it polls the output
    folder (job). A prepared worker takes the click (its model is used when the session has not changed since it started);
    otherwise the warm worker (C4-F1) or a new process. When the cap of running jobs is reached (C4-F5) the confirmation
    waits in the queue and starts when a running one ends (job() moves the queue)."""
    from src.workbench.job import ACK, out_dir

    sid = s["session_id"]
    v = version(s)["v"]
    d = out_dir(sid, v, mode)
    (d / ACK).unlink(missing_ok=True)  # an earlier confirmation of this version must not be read as this one
    t0 = time.time()
    with _JLOCK:
        j = {
            "proc": None,
            "started": t0,
            "v": v,
            "dir": d,
            "mode": mode,
            "log": None,
            "s": s,
            "user": user,
            "workspace": str(S.workspace() or ""),
        }
        k = _k(sid, mode)
        _JOBS[k] = j
        cap = max_jobs()
        if cap is not None and (running_jobs() >= cap or _QUEUE):
            j["queued"] = True
            _QUEUE.append(k)
        else:
            _launch(j, s, mode, user)
    return j


def _launch(j: dict, s: dict, mode: str, user: dict | None) -> None:
    """Start the job of one confirmation: the prepared worker (same state), the warm worker, or a new process."""
    from src.workbench.job import fingerprint

    sid = s["session_id"]
    log_dir = S.jobs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    sb = _JOBS.get(_k(sid, "standby"))
    ps = prepared_state(sid)
    # the worker takes the job when it prepares this state, or is still loading its modules (it reads the session after
    # that, so it builds this state; a change in between makes it run a fresh job itself)
    use_sb = bool(
        ps and sb and sb.get("mode", "pc") == mode and (ps.get("state") == "starting" or ps.get("fp") == fingerprint(s))
    )
    _JOBS.pop(_k(sid, "standby"), None)
    if sb and not use_sb and sb["proc"].poll() is None:
        sb["proc"].terminate()  # prepared for another state (or still starting): a fresh job is sooner
    if use_sb:
        sb["trigger"].write_text(
            json.dumps(
                {"sid": sid, "mode": mode, "user": user, "fp": fingerprint(s), "clicked": j["started"]}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        proc, log = sb["proc"], log_dir / f"{sid}_standby.log"
    else:
        w = take_warm()  # fix C4-F1: a worker that has already imported everything
        if w:
            _ticket(
                w,
                {
                    "sid": sid,
                    "mode": mode,
                    "user": user if mode == "public" else None,
                    "clicked": j["started"],
                    "workspace": j["workspace"],
                },
            )
            proc, log = w["proc"], w["log"]
        else:
            log = log_dir / f"{sid}_v{j['v']}_{mode}.log"
            proc = _spawn([sid, mode] + ([json.dumps(user, ensure_ascii=False)] if mode == "public" else []), log)
    j.update({"proc": proc, "log": log, "queued": False})


def _pump() -> None:
    """Start queued confirmations while the cap leaves room (called from job(), i.e. by every waiting screen's poll)."""
    with _JLOCK:
        cap = max_jobs()
        while _QUEUE and (cap is None or running_jobs() < cap):
            k = _QUEUE.pop(0)
            j = _JOBS.get(k)
            if not j or not j.get("queued"):
                continue
            with S.use_workspace(j["workspace"] or None):  # the queued job keeps its own browser workspace
                _launch(j, j["s"], j["mode"], j["user"])


def job(sid: str, mode: str) -> dict | None:
    """The job's live status: alive, Excel path once written, reconciliation status, report, seconds since start."""
    if _QUEUE:
        _pump()
    j = _JOBS.get(_k(sid, mode))
    if not j:
        return None
    if j.get("queued"):  # fix C4-F5: waiting for a free slot
        ahead = _QUEUE.index(_k(sid, mode)) if _k(sid, mode) in _QUEUE else 0
        return {
            **j,
            "alive": True,
            "queued": True,
            "ahead": ahead,
            "returncode": None,
            "xlsx": None,
            "docx": None,
            "reconcile": "대조 대기",
            "result": None,
            "excel_seconds": None,
            "elapsed": round(time.time() - j["started"], 1),
        }
    from src.workbench.job import ACK

    summ = {}
    f = j["dir"] / "summary.json"
    if (j["dir"] / ACK).exists() and f.exists():  # accepted by the worker: its folder is this confirmation's
        try:
            summ = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # being written: next poll
            summ = {}
    outs = summ.get("outputs") or {}

    def rel(p):
        return S.rel(p) if p else None

    alive = j["proc"].poll() is None
    if not alive and "excel_at" not in j and outs.get("xlsx"):
        j["excel_at"] = time.time()
    if alive and outs.get("xlsx") and "excel_at" not in j:
        j["excel_at"] = time.time()
        ensure_warm()  # the Excel model is out: prepare the next worker now (fix C4-F1)
    return {
        **j,
        "alive": alive,
        "returncode": j["proc"].poll(),
        "xlsx": rel(outs.get("xlsx")),
        "docx": rel(outs.get("docx")),
        "reconcile": (summ.get("reconcile") or {}).get("status", "대조 대기"),
        "result": summ.get("result"),
        "excel_seconds": round(j["excel_at"] - j["started"], 1) if "excel_at" in j else None,
        "elapsed": round(time.time() - j["started"], 1),
    }


def confirmations(s: dict) -> list[dict]:
    """All confirmation records of a session."""
    return list(s.get("confirmations") or [])


def safe_name(p: str | None) -> str:
    """File name only (no folders) for a download."""
    return Path(p).name if p else ""


def file_bytes(rel: str | None) -> bytes | None:
    """Bytes of an output file of this workspace (or the project on the PC); any other path -> None (P7-C3 isolation)."""
    if not rel:
        return None
    p = (ROOT / rel).resolve()
    ws = S.workspace()
    allowed = [ws.resolve()] if ws else [ROOT.resolve()]
    if not any(p.is_relative_to(a) for a in allowed):
        return None
    return p.read_bytes() if p.exists() else None
