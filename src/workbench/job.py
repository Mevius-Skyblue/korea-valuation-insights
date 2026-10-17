"""Confirmation job in its own process (P7-C2 screen, config/p7c2.yaml fixes C2-F2).

    python -m src.workbench.job <session_id> <pc|public> [user_json]
    python -m src.workbench.job --standby <trigger_file> <sid> prepared confirmation (fix C2-F3): loads the modules, builds
                                                               the Excel model of the session's current state and waits;
                                                               on the screen's trigger {"sid", "mode", "user", "fp",
                                                               "clicked"} with the same fingerprint it records the
                                                               confirmation and goes on (reconciliation, report), else it
                                                               drops the prepared work and runs the asked job. Gives up
                                                               (nothing recorded) after 30 minutes

Runs confirm.confirm(background=True) and waits for its thread: the Excel model first (out-dir summary.json gets
outputs.xlsx and reconcile '대조 진행 중'), then the Excel <-> engine reconciliation and the report; the session record is
written by confirm (re-read before saving, so changes made on the screen meanwhile are kept). Public mode: afterwards the
outputs are scanned for KRX raw values (public.scan) and the result is written to that confirmation record ('scan').

Why a process: inside the Streamlit server the CPU-bound reconciliation (formulas, about 60 s) shared the interpreter
lock with the screen, and screen reruns waited behind it (confirm -> download button 83 s, reconciliation minutes).
"""
from __future__ import annotations

import json
import sys

import yaml

from src.collect.core import ROOT
from src.workbench import confirm as C
from src.workbench import session as S


def out_dir(sid: str, v: int, mode: str):
    return S.outputs_root() / sid / (f"v{v}" + ("_public" if mode == "public" else ""))


ACK = "confirm_ack.json"


def fingerprint(s: dict) -> str:
    """Everything of the session that goes into a confirmed model: version and assumptions, judgement statuses and
    reasons, the audit trail. Same fingerprint = the prepared Excel model is the one 확정 would build."""
    import hashlib
    v = S.current(s)
    js = {k: [j.get("status"), (j.get("resolution") or {}).get("reason"), (j.get("resolution") or {}).get("v")]
          for k, j in (s.get("judgements") or {}).items()}
    raw = json.dumps([s["session_id"], v["v"], v["overrides"], js, [[a.get("v"), a.get("field"), a.get("reason")] for a in s["audit"]],
                      s.get("public_inputs") or {}],                 # P7-C3: public-mode values follow the user's inputs
                     sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def ack(sid: str, v: int, mode: str, clicked: float | None, prepared: bool) -> None:
    """The screen shows the Excel download only after this file exists (the confirmation was accepted)."""
    d = out_dir(sid, v, mode)
    d.mkdir(parents=True, exist_ok=True)
    (d / ACK).write_text(json.dumps({"clicked": clicked, "prepared": prepared}), encoding="utf-8")


def _prep(s: dict) -> None:
    """P7-C3 public deployment: load the company's public snapshot into this process's replay store."""
    from src.workbench.snapdata import replaying
    if replaying():
        from src.workbench.public_deploy import ensure
        ensure(s["code"])


def run(sid: str, mode: str = "pc", user: dict | None = None, clicked: float | None = None) -> dict:
    s = S.load(sid)
    _prep(s)
    d = out_dir(sid, S.current(s)["v"], mode)
    (d / "summary.json").unlink(missing_ok=True)          # the screen must not read an earlier run of this version
    ack(sid, S.current(s)["v"], mode, clicked, False)
    cf = C.confirm(s, mode=mode, user=user, background=True)
    print(json.dumps({"event": "excel", "status": cf["status"], "xlsx": cf.get("xlsx"), "seconds": cf.get("excel_seconds")},
                     ensure_ascii=False), flush=True)
    cf["thread"].join()
    rec = cf["record"]
    from src.workbench.snapdata import replaying
    if mode == "public" and rec.get("outputs") and replaying():
        # P7-C3 public deployment: no KRX value exists here (the bundle was scanned before the push) -> nothing to compare
        s3 = S.load(sid)
        last = next(c for c in reversed(s3.get("confirmations") or []) if c.get("mode") == "public" and c.get("at") == rec["at"])
        last["scan"] = {"hits": 0, "detail": [], "krx_values": 0, "at": S._now(), "deploy": True,
                        "note": "공개 배포: 대조할 한국거래소 원값 없음(배포 전 묶음 검사에서 0건 확인)"}
        S.save(s3)
        rec["scan"] = last["scan"]
    elif mode == "public" and rec.get("outputs"):
        from src.excel.model_data import load_model_data
        from src.market.provider import use
        from src.market.user_provider import UserOverlayProvider
        from src.workbench import public as P
        krx = P.krx_values(s["draft_config"], user)
        cfg = yaml.safe_load((ROOT / rec["config"]).read_text(encoding="utf-8"))
        with use(UserOverlayProvider(user, cfg)):
            dp = load_model_data(rec["config"])
        hits = P.scan(P.outputs_of({"outputs": rec["outputs"]}), krx, P.aggregates(dp))
        s3 = S.load(sid)
        last = next(c for c in reversed(s3.get("confirmations") or []) if c.get("mode") == "public" and c.get("at") == rec["at"])
        last["scan"] = {"hits": len(hits), "detail": hits[:20], "krx_values": len(krx), "at": S._now()}
        S.save(s3)
        rec["scan"] = last["scan"]
    print(json.dumps({"event": "done", "reconcile": (rec.get("reconcile") or {}).get("status"), "result": rec.get("result"),
                      "scan": (rec.get("scan") or {}).get("hits")}, ensure_ascii=False), flush=True)
    return rec


def _trigger(f) -> dict | None:
    if not f.exists():
        return None
    try:
        job = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    f.unlink(missing_ok=True)
    return job


def standby(trigger: str, sid: str, mode: str = "pc", limit_s: float = 1800.0) -> None:
    """Prepared-confirmation worker of one session (PC mode, fix C2-F3), started when the session is opened on the screen.
    Loads the heavy modules, the premium sample and its regression fit (version-independent caches, same results), builds
    the Excel model of the session's current state and waits. When the session changes it builds again for the new state.
    On 확정 with the same fingerprint it records the confirmation (confirm gate) and goes on with the reconciliation and
    the report; with another state or mode it drops the prepared work and runs the asked job. Nothing is recorded in the
    session before the click. `<trigger>.status` tells the screen which state is prepared ({fp, v, state})."""
    import time
    from pathlib import Path

    import duckdb
    import formulas  # noqa: F401
    import openpyxl  # noqa: F401
    import xlsxwriter  # noqa: F401

    import src.excel.model_data  # noqa: F401
    import src.excel.verify  # noqa: F401
    import src.pipeline.run  # noqa: F401
    import src.report.build  # noqa: F401
    from src.workbench.snapdata import replaying
    if not replaying():                       # P7-C3 public deployment: no DB, no premium sample
        from src.db.build import DB_PATH
        from src.premium import predict
        duckdb.connect(str(DB_PATH), read_only=True).close()
        predict._db_params(), predict._db_adoption()
    f = Path(trigger)
    status = f.with_suffix(".status")
    t0 = time.time()
    while time.time() - t0 < limit_s:
        s = S.load(sid)
        _prep(s)
        fp = fingerprint(s)
        v = S.current(s)["v"]
        status.write_text(json.dumps({"fp": fp, "v": v, "state": "building"}), encoding="utf-8")
        print(json.dumps({"event": "standby", "fp": fp, "v": v}), flush=True)
        other: dict = {}
        restart = {"on": False}

        def gate(fp=fp, v=v, other=other, restart=restart) -> dict:
            status.write_text(json.dumps({"fp": fp, "v": v, "state": "ready"}), encoding="utf-8")
            while time.time() - t0 < limit_s:
                job = _trigger(f)
                if job:
                    if job.get("mode", "pc") == mode and job.get("fp") == fp and fingerprint(S.load(sid)) == fp:
                        ack(sid, v, mode, job.get("clicked"), True)
                        print(json.dumps({"event": "accepted", "clicked": job.get("clicked")}), flush=True)
                        return {"ok": True, "clicked": job.get("clicked")}
                    other.update(job)
                    return {"ok": False}
                if fingerprint(S.load(sid)) != fp:          # the session changed: prepare the new state
                    restart["on"] = True
                    return {"ok": False}
                time.sleep(0.25)
            return {"ok": False}

        cf = C.confirm(s, mode=mode, user=s.get("public_inputs") if mode == "public" else None, background=True, gate=gate)
        print(json.dumps({"event": "prepared", "status": cf["status"], "v": v}, ensure_ascii=False), flush=True)
        cf["thread"].join()
        rec = cf["record"]
        if not rec.get("aborted"):
            status.unlink(missing_ok=True)
            print(json.dumps({"event": "done", "reconcile": (rec.get("reconcile") or {}).get("status"), "result": rec.get("result")},
                             ensure_ascii=False), flush=True)
            return
        print(json.dumps({"event": "dropped", "other_job": bool(other), "restart": restart["on"]}), flush=True)
        if other:
            status.unlink(missing_ok=True)
            run(other["sid"], other.get("mode", "pc"), other.get("user"), other.get("clicked"))
            return
        if not restart["on"]:
            break
    status.unlink(missing_ok=True)


def _peak_mb() -> float | None:
    from app.wb.public_ui import rss
    return rss().get("peak_mb")


if __name__ == "__main__":
    import os
    import time as _t
    sys.stdout.reconfigure(encoding="utf-8")
    t_start = _t.time()
    if os.environ.get("KVI_PUBLIC") == "1":       # P7-C3 public deployment: snapshot replay, no DB
        from src.workbench.public_deploy import boot
        boot()
    else:
        from src.db.lockwait import install
        install()                                 # the screen process may hold the DB file for a moment
    if sys.argv[1] == "--standby":
        standby(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "pc")
    else:
        run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "pc", json.loads(sys.argv[3]) if len(sys.argv) > 3 else None)
    if os.environ.get("KVI_PUBLIC") == "1":       # numbers only, for the hidden diagnostics
        from app.wb.public_ui import job_log
        job_log({"peak_mb": _peak_mb(), "seconds": round(_t.time() - t_start, 1), "kind": sys.argv[1] if sys.argv[1] == "--standby" else "job"})
