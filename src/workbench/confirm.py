"""Confirm a session version -> Excel model + report (config/p7c1.yaml confirm, public_mode).

    session_config(s, version)                -> path of the session config (draft config + confirmed assumptions)
    confirm(s, version=None, mode="pc", user=None) -> pipeline summary of the confirmed version (outputs/workbench/<id>/v<n>[_public])

The session config is written under data/workbench/sessions/<id>/v<n>/ (git-ignored):
    valuation_<code>_<id>v<n>.yaml   draft config + config-native values + `overrides` (hook values) + `workbench` record
    ledger.yaml                      the discount ledger copy when Rf tenor / MRP / SRP changed (the draft's ledger is not touched)
The normal pipeline (src/pipeline/run.run_pipeline) then builds the engine values, the Excel model (Inputs '사람 확정값',
Judgements sheet) and the report ('사람 판단 반영 내역'); the Excel <-> engine reconciliation runs after the model is written.
Public mode: the target's (and listed subsidiaries') market values come from the user (src/market/user_provider.py), the
per-peer / per-date KRX rows are replaced by their aggregates (src/workbench/public.py) and the outputs are scanned.
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from src.collect.core import ROOT
from src.workbench import session as S
from src.workbench import spec


def _changes(s: dict, v: int) -> tuple[list[dict], list[dict]]:
    """Final value per changed assumption up to version v (auto value -> confirmed value, last reason) and kept items."""
    by = {}
    for a in s["audit"]:
        if a["v"] > v or not a.get("field"):
            continue
        f = a["field"]
        first = by.get(f, {}).get("before_text", a["before_text"])
        j = (s.get("judgements") or {}).get(a.get("judgement") or "", {})
        by[f] = {"field": f, "label": a["label"], "item": j.get("item") or a["label"], "before_text": first,
                 "after_text": a["after_text"], "reason": a.get("reason") or "", "version": a["v"], "at": a["at"]}
    kept = [{"item": j["item"], "reason": (j.get("resolution") or {}).get("reason", "")} for j in (s.get("judgements") or {}).values()
            if j.get("status") == "그대로 유지"]
    return list(by.values()), kept


def session_config(s: dict, version: int | None = None, mode: str = "pc", user: dict | None = None) -> str:
    from src.workbench.recalc import apply_overrides
    ver = S.current(s) if version is None else next(x for x in s["versions"] if x["v"] == version)
    v = ver["v"]
    cfg = yaml.safe_load((ROOT / s["draft_config"]).read_text(encoding="utf-8"))
    led_path = ROOT / cfg["meta"]["discount_ledger"]
    led = yaml.safe_load(led_path.read_text(encoding="utf-8"))
    cfg2, led2 = apply_overrides(cfg, led, ver["overrides"])
    d = S.base() / s["session_id"] / (f"v{v}" + ("_public" if mode == "public" else ""))
    d.mkdir(parents=True, exist_ok=True)
    if led2 != led:
        for k in ("risk_free", "mrp", "decisions"):
            if led2.get(k) != led.get(k) and isinstance(led2.get(k), dict):
                led2[k]["basis"] = f"{led2[k].get('basis', '')} | 평가 세션 {s['session_id']} v{v} 사람 확정값"
        (d / "ledger.yaml").write_text(yaml.safe_dump(led2, allow_unicode=True, sort_keys=False), encoding="utf-8")
        cfg2["meta"]["discount_ledger"] = S.rel(d / "ledger.yaml")
    changes, kept = _changes(s, v)
    cfg2["workbench"] = {"session_id": s["session_id"], "version": v, "changes": changes, "kept": kept, "pending": S.pending(s),
                         "auto_hold_reasons": (s.get("auto_headline") or {}).get("reasons") or [],
                         "auto_status": (s.get("auto_headline") or {}).get("status"), "mode": mode,
                         "snapshot": s["snapshot"], "code_commit": s["code_commit"], "draft_config": s["draft_config"]}
    if mode == "public":
        cfg2["public_mode"] = {"user": dict(user or {})}
    sid = s["session_id"].replace("-", "")
    p = d / f"valuation_{s['code']}_{sid}v{v}{'p' if mode == 'public' else ''}.yaml"
    p.write_text(yaml.safe_dump(cfg2, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    return S.rel(p)


def confirm(s: dict, version: int | None = None, mode: str = "pc", user: dict | None = None, pdf: bool = False,
            background: bool = False, gate=None) -> dict:
    """Run the pipeline on the confirmed session config. Records the outputs and the reconciliation status in the session.
    background=True: returns as soon as the Excel model is written ({'status': '엑셀 생성', 'xlsx', 'excel_seconds',
    'thread'}); the reconciliation and the report go on in a thread that updates the session record when done
    (session.confirmations[-1].reconcile: 대조 진행 중 -> 일치 / 불일치).
    gate (P7-C2 prepared confirmation, src/workbench/job.py): called once the Excel model is written; it blocks until the
    person presses 확정 and returns True (the confirmation time is then recorded) or False (the prepared work is dropped:
    nothing is recorded in the session)."""
    import threading
    import time

    from src.pipeline.run import run_pipeline
    ver = S.current(s) if version is None else next(x for x in s["versions"] if x["v"] == version)
    t0 = time.time()
    cp = session_config(s, ver["v"], mode, user)
    out_root = S.outputs_root() / s["session_id"]
    tag = f"v{ver['v']}" + ("_public" if mode == "public" else "")
    rec = {"v": ver["v"], "mode": mode, "at": S._now(), "config": cp, "reconcile": {"status": "대조 대기"}}
    ready = threading.Event()

    def on_excel(path, secs):
        rec.update({"excel": S.rel(path), "excel_seconds": round(time.time() - t0, 2),
                    "reconcile": {"status": "대조 진행 중"}})
        ready.set()
        if gate is not None:
            t_ready = time.time()
            g = gate()                                  # {'ok': bool, 'clicked': epoch of the 확정 click}
            if not g.get("ok"):
                rec["aborted"] = True
                raise RuntimeError("미리 만든 확정 작업 버림(세션이 바뀌었거나 확정하지 않음)")
            rec.update({"at": S._now(), "prepared": True,
                        "excel_seconds": round(max(0.0, t_ready - g.get("clicked", t_ready)), 2)})

    def work() -> dict:
        def go():
            return run_pipeline(cp, pdf=pdf, out_root=out_root, regress_tag=tag, on_excel=on_excel)
        if mode == "public":
            from src.market.provider import use
            from src.market.user_provider import UserOverlayProvider
            from src.workbench.snapdata import replaying
            cfg = yaml.safe_load((ROOT / cp).read_text(encoding="utf-8"))
            if replaying():                     # P7-C3 public deployment: the user's values only, no DB
                from src.workbench.public_deploy import SnapshotUserProvider
                prov = SnapshotUserProvider(user or {}, cfg)
            else:
                prov = UserOverlayProvider(user or {}, cfg)
            with use(prov):
                summ = go()
        else:
            summ = go()
        if rec.get("aborted"):
            ready.set()
            return summ
        rec.update({"result": summ.get("result"), "per_share": (summ.get("values") or {}).get("per_share_base_srp0"),
                    "reconcile": summ.get("reconcile"), "outputs": summ.get("outputs"), "timing": summ.get("timing"),
                    "success": summ.get("success"), "seconds": round(time.time() - t0, 2)})
        s2 = S.load(s["session_id"]) if background else s       # the thread re-reads: the screen may have saved meanwhile
        s2.setdefault("confirmations", []).append(rec)
        from src.workbench.snapdata import replaying
        if mode == "pc" or replaying():     # P7-C3: in the public deployment the public export is the confirmation
            s2["confirmed"] = rec
        S.save(s2)
        ready.set()
        return summ

    if not background:
        return work()
    import contextvars
    cv = contextvars.copy_context()             # P7-C3: the thread keeps this caller's workspace
    th = threading.Thread(target=cv.run, args=(work,), name=f"confirm-{s['session_id']}-v{ver['v']}", daemon=False)
    th.start()
    ready.wait()
    return {"status": "엑셀 생성" if rec.get("excel") else "실패(엑셀 전)", "xlsx": rec.get("excel"),
            "excel_seconds": rec.get("excel_seconds"), "record": rec, "thread": th}


def change_rows(s: dict, version: int | None = None) -> list[dict]:
    """The changes table (same rows as the Judgements sheet) for the screen."""
    v = S.current(s)["v"] if version is None else version
    return _changes(s, v)[0]


def fmt_value(field: str, v) -> str:
    return spec.fmt(field, v)


def deep(x):
    return copy.deepcopy(x)
