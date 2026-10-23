"""Evaluation sessions (config/p7c1.yaml session). Stored as data/workbench/sessions/<id>/session.json (git-ignored).

    create(code)                 a session on the auto draft of `code` (runs the fast first draft if there is none)
    list_sessions() / load(id) / save(s) / clone(id) / delete(id)
    set_assumption(s, field, value, reason=None, judgement=None)   -> new version (range-checked, recalculated)
    revert(s, version, reason=None)  a new version with the assumptions of an earlier version (audit kept, nothing deleted)
    set_public_inputs(s, user)   the public-mode market inputs the user typed (P7-C2 screen; not KRX data)
    result(s, version=None)      recalculate a version (same version = same numbers)
    snapshot_changed(s)          data or code signatures differ from the snapshot -> warning list

A session: {session_id, code, name, as_of, draft_config, draft_sha, snapshot, code_commit, tree_clean, versions:[{v,
overrides, created, result}], audit:[{at, v, field, before, after, reason, judgement}], judgements:{id: {...}}, confirmed}.
Market values themselves are kept only as a hash (PC mode keeps them in the DB); nothing from KRX is written here.
"""

from __future__ import annotations

import contextvars
import copy
import hashlib
import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src import yamlio
from src.collect.core import ROOT
from src.workbench import spec

BASE = ROOT / "data" / "workbench" / "sessions"  # PC default workspace (P7-C1)

# P7-C3 workspaces (config/p7c3.yaml public_app.session_store): the public deployment gives every browser session its own
# folder (<temp>/kvi/<random id>/ with sessions, outputs, jobs). The folder comes from the screen (a context variable in
# the Streamlit script thread) or, in a confirmation job process, from the environment KVI_WORKSPACE. Never from user text.
_WS: contextvars.ContextVar = contextvars.ContextVar("kvi_workspace", default=None)


WORKSPACE_HOOK = None  # the public screen sets a function returning this browser session's folder (or None)


def workspace() -> Path | None:
    """This browser session's folder (public deployment) or None (PC: the project folders)."""
    w = _WS.get()
    if not w and WORKSPACE_HOOK is not None:
        try:
            w = WORKSPACE_HOOK()
        except Exception:  # noqa: BLE001 - outside a screen run: no hook value
            w = None
    w = w or os.environ.get("KVI_WORKSPACE")
    return Path(w) if w else None


@contextmanager
def use_workspace(path):
    """Run a block in the given workspace (context variable, so threads keep their own)."""
    tok = _WS.set(str(path) if path else None)
    try:
        yield
    finally:
        _WS.reset(tok)


def set_workspace(path) -> None:
    """For the rest of this thread's context (one Streamlit script run)."""
    _WS.set(str(path) if path else None)


def base() -> Path:
    """Folder of the session files (in the workspace when there is one)."""
    w = workspace()
    return w / "sessions" if w else BASE


def outputs_root() -> Path:
    """Folder of the confirmed outputs (Excel, report)."""
    w = workspace()
    return w / "outputs" if w else ROOT / "outputs" / "workbench"


def jobs_dir() -> Path:
    """Folder of the confirmation job logs and triggers."""
    w = workspace()
    return w / "jobs" if w else ROOT / "logs" / "wb_jobs"


def rel(p) -> str:
    """Path text kept in records: relative to the project when inside it, else absolute (public workspaces)."""
    p = Path(p)
    p = p if p.is_absolute() else ROOT / p
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def git_state() -> dict:
    """Code commit and whether the working tree is clean (recorded in every session)."""
    from src.workbench.public_deploy import bundle_info, is_public

    if is_public():  # P7-C3: the bundle's source commit (no git on the server)
        b = bundle_info()
        return {"commit": b.get("source_commit", "public"), "tree_clean": True}
    # P7-X2b: git prints non-ASCII paths in UTF-8 (a modified docs/기획안.md broke the cp949 decode -> stdout None)
    kw = {"cwd": ROOT, "capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}
    head = (subprocess.run(["git", "rev-parse", "HEAD"], **kw).stdout or "").strip()
    st = (subprocess.run(["git", "status", "--porcelain"], **kw).stdout or "").strip()
    return {"commit": head, "tree_clean": st == ""}


def snapshot(cfg: dict) -> dict:
    """Signatures of the data the draft reads: statements of target + peers (raw files, report texts, loader code) and the
    market values (provider name + hash of the closes / market caps / VWAP of target, peers, listed subsidiaries).
    Public deployment (P7-C3): the public snapshot's SHA-256 (it holds every value the session reads)."""
    from src.workbench.snapdata import replaying

    if replaying():
        from src.workbench.public_deploy import snapshot_sha

        sha = snapshot_sha(cfg["target"]["stock_code"])
        return {
            "statements": {"public_snapshot": sha},
            "loader_code": "public_snapshot",
            "market_provider": "user",
            "market_hash": "user_input",
            "taken_at": _now(),
            "public_snapshot": sha,
        }
    import duckdb

    from src.db.build import DB_PATH
    from src.market.provider import get
    from src.pipeline.fsload import code_sig, raw_sigs

    corps = [cfg["target"]["corp_code"]] + [p["corp_code"] for p in cfg.get("peers", [])]
    as_of = cfg["meta"]["as_of"]
    mp = get()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        sigs = raw_sigs(corps, con)
        codes = [cfg["target"]["stock_code"]] + [p["stock_code"] for p in cfg.get("peers", [])]
        codes += [x["stock_code"] for x in (cfg.get("structure") or {}).get("subsidiaries") or [] if x.get("stock_code")]
        vals = [(k, mp.quote(k, as_of, con=con)) for k in sorted(set(codes))]
        vw = mp.vwap20(cfg["target"]["stock_code"], as_of, con=con).get("vwap")
    finally:
        con.close()
    mh = hashlib.sha256(json.dumps([vals, vw], default=str).encode()).hexdigest()[:16]
    return {
        "statements": sigs,
        "loader_code": code_sig(),
        "market_provider": getattr(mp, "name", "?"),
        "market_hash": mh,
        "taken_at": _now(),
    }


def _path(sid: str) -> Path:
    if not sid or "/" in sid or "\\" in sid or ".." in sid:
        raise FileNotFoundError(sid)
    return base() / sid / "session.json"


def save(s: dict) -> dict:
    """Write the session file (the source of every value the screen shows)."""
    p = _path(s["session_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return s


def load(sid: str) -> dict:
    """Read a session file."""
    return json.loads(_path(sid).read_text(encoding="utf-8"))


def list_sessions() -> list[dict]:
    """Sessions of this workspace with version, confirmed version and pending judgements."""
    out = []
    for p in sorted(base().glob("*/session.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        out.append(
            {k: s.get(k) for k in ("session_id", "code", "name", "as_of", "created")}
            | {"version": s["versions"][-1]["v"], "confirmed": (s.get("confirmed") or {}).get("v"), "pending": pending(s)}
        )
    return out


def _new_id(code: str, as_of: str) -> str:
    b = base()
    n = len(list(b.glob(f"{code}_{as_of.replace('-', '')}_*"))) + 1
    while (b / f"{code}_{as_of.replace('-', '')}_{n:03d}").exists():
        n += 1
    return f"{code}_{as_of.replace('-', '')}_{n:03d}"


def draft_summary(code: str) -> dict | None:
    """The auto draft's summary.json (public deployment: the sanitized copy in the snapshot)."""
    from src.workbench.snapdata import replaying

    if replaying():  # P7-C3: the sanitized summary in the public snapshot
        from src.workbench.public_deploy import snapshot

        sn = snapshot(code)
        return None if sn is None else sn["summary"]
    f = ROOT / "outputs" / "pipeline" / code / "summary.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def create(code: str, on_step=None) -> dict:
    """A new session on the auto draft (config/drafts/valuation_<code>.yaml). The first draft is made if missing.
    on_step(name, state, seconds): progress of the first-draft stages (P7-C2 screen)."""
    from src.workbench import judge, recalc
    from src.workbench.snapdata import replaying

    if replaying():  # P7-C3 public deployment: the draft comes from the public snapshot
        from src.workbench.public_deploy import ensure

        cfg_path = ensure(code)  # raises when the company is not in the public range
    else:
        cfg_path = f"config/drafts/valuation_{code}.yaml"
    summ = draft_summary(code)
    if replaying() and not (summ and (summ.get("steps") or {}).get("first_draft", {}).get("ok")):
        raise ValueError(f"{code}: 공개 범위의 평가 가능 회사가 아님")
    if not (ROOT / cfg_path).exists() or summ is None or not (summ.get("steps") or {}).get("first_draft", {}).get("ok"):
        from src.pipeline.run import run_pipeline

        summ = run_pipeline(code, fast=True, on_step=on_step)
        if not (summ.get("steps") or {}).get("first_draft", {}).get("ok"):
            raise ValueError(
                f"{code}: 초안을 만들 수 없음 — {summ.get('result')}: "
                + "; ".join(
                    f"{r['rule']} {r.get('value', '')}"
                    for r in ((summ.get("gate") or {}).get("stage_a") or []) + ((summ.get("gate") or {}).get("stage_b") or [])
                )
            )
    cfg = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
    sid = _new_id(code, cfg["meta"]["as_of"])
    g = git_state()
    r0 = recalc.recalc(cfg_path, {})
    s = {
        "session_id": sid,
        "code": code,
        "name": cfg["target"]["name"],
        "as_of": cfg["meta"]["as_of"],
        "created": _now(),
        "draft_config": cfg_path,
        "draft_sha": _sha(ROOT / cfg_path),
        "snapshot": snapshot(cfg),
        "code_commit": g["commit"],
        "tree_clean": g["tree_clean"],
        "versions": [{"v": 0, "overrides": {}, "created": _now(), "result": r0}],
        "audit": [],
        "auto_headline": summ.get("headline"),
        "judgements": judge.items(summ, cfg_path),
        "confirmed": None,
    }
    return save(s)


def clone(sid: str) -> dict:
    """A new session with the same versions and audit (not confirmed)."""
    s = load(sid)
    s2 = copy.deepcopy(s)
    s2["session_id"] = _new_id(s["code"], s["as_of"])
    s2["created"] = _now()
    s2["cloned_from"] = sid
    s2["confirmed"] = None
    return save(s2)


def delete(sid: str) -> None:
    """Remove a session folder (only inside the sessions folder)."""
    b = base()
    d = b / sid
    if d.exists() and d.parent == b:
        shutil.rmtree(d)


def current(s: dict) -> dict:
    """The latest version of a session."""
    return s["versions"][-1]


def pending(s: dict) -> int:
    """Number of judgements still to process."""
    return sum(1 for j in (s.get("judgements") or {}).values() if j.get("status") == "미처리")


def _explicit_end(c) -> int:
    from src.valuation.company_dcf import explicit_end

    return explicit_end(c)


def _auto_value(field: str, cfg: dict, led: dict, r0: dict, x) -> object:
    """The auto-draft value of an assumption (for the audit and the Judgements table)."""
    m = {
        "rf_tenor": led["risk_free"].get("tenor", 5),
        "mrp": led["mrp"]["value"],
        "srp": led["decisions"]["srp_columns"][0],
        "g_terminal": cfg["forecast"]["human"]["g_terminal"],
        "scenario_width": abs(cfg["scenarios"]["human"]["optimistic"]["margin_shift"]),
        "peers": [p["name"] for p in cfg.get("peers", [])],
        "premium": dict(cfg["params"]["premium"]),
        "sotp_discount": ((cfg.get("structure") or {}).get("discount") or {}).get("base"),
        "normal_margin": r0.get("m0"),
        "g_start": r0.get("g0"),
        "beta_u": r0.get("beta_u"),
        "de": r0.get("de"),
        "kd": r0.get("kd"),
        "cash_adjust_mn": 0.0,
        "nci_mn": None,
        # P7-X2b
        "assoc_discount": (((cfg.get("structure") or {}).get("associates") or {}).get("discount") or {}).get("base"),
        "dna_ratio": x.h.get("dna_ratio") if x is not None else None,
        "capex_ratio": x.h.get("capex_ratio") if x is not None else None,
        "nwc_days": {k: x.h.get(k) for k in ("dso", "dio", "dpo")} if x is not None else None,
        "conv_share": (x.base_v2 or {}).get("conv_share") if x is not None else None,
        "conv_end": ((x.base_v2 or {}).get("conv_end") or _explicit_end(x.c)) if x is not None and x.base_v2 else None,
        "ronic": r0.get("ronic"),
    }
    return m.get(field)


def set_assumption(s: dict, field: str, value, reason: str | None = None, judgement: str | None = None) -> dict:
    """Range-check, apply on top of the current version, recalculate -> a new version + an audit entry.
    Returns {'ok', 'reason', 'session', 'result'}; a rejected value leaves the session unchanged."""
    from src.market.user_provider import PublicDataUnavailable
    from src.workbench import recalc

    x = recalc.context(s["draft_config"])
    ok, why, v = spec.check(field, value, x.peers_all())
    if not ok:
        return {"ok": False, "reason": why, "session": s, "result": None}
    cur = current(s)
    if field in cur["overrides"] and cur["overrides"][field] == v:
        # P7-C3 fix C3-F4: the same value again is not a change (no new version). A slow server re-sent the value of a
        # re-keyed input after each new version and the versions ran away (v16)
        return {"ok": True, "reason": "", "session": s, "result": cur["result"], "noop": True}
    ov = {**cur["overrides"], field: v}
    try:
        r = recalc.recalc(s["draft_config"], ov, ctx=session_ctx(s))
    except PublicDataUnavailable as e:  # P7-C3 public deployment: e.g. a peer change (PC only)
        return {"ok": False, "reason": str(e), "session": s, "result": None}
    if r.get("per_share") is None:
        return {"ok": False, "reason": r.get("error", "계산 불가"), "session": s, "result": r}
    before = cur["overrides"].get(field, _auto_value(field, x.base_cfg, x.base_led, s["versions"][0]["result"], x))
    nv = cur["v"] + 1
    s["versions"].append({"v": nv, "overrides": ov, "created": _now(), "result": r})
    from src.valuation.assumptions import rf_code

    warn = []
    if field == "kd" and v < x.c.rates[rf_code(x.base_led)]:
        warn.append("세전 Kd가 Rf보다 낮다(정책 금리 등 근거 확인)")
    s["audit"].append(
        {
            "at": _now(),
            "v": nv,
            "field": field,
            "label": spec.LABEL[field],
            "before": before,
            "after": v,
            "before_text": spec.fmt(field, before),
            "after_text": spec.fmt(field, v),
            "reason": reason or "",
            "judgement": judgement,
            "warnings": warn,
            "per_share_before": cur["result"].get("per_share"),
            "per_share_after": r.get("per_share"),
        }
    )
    save(s)
    return {"ok": True, "reason": "; ".join(warn), "session": s, "result": r}


def revert(s: dict, version: int, reason: str | None = None) -> dict:
    """A new version whose assumptions equal those of `version` (P7-C2 '이 버전으로 되돌리기'). One audit entry per field
    that changes (before -> after, label '되돌리기 vN'); earlier versions and the audit stay. Judgement statuses are kept
    (the audit shows the revert). Returns {'ok', 'reason', 'session', 'result'}."""
    from src.workbench import recalc

    try:
        target = next(x for x in s["versions"] if x["v"] == int(version))
    except (StopIteration, TypeError, ValueError):
        return {"ok": False, "reason": f"버전 {version}이 없다", "session": s, "result": None}
    cur = current(s)
    ov = copy.deepcopy(target["overrides"])
    if ov == cur["overrides"]:
        return {"ok": False, "reason": f"지금 가정이 이미 v{target['v']}와 같다", "session": s, "result": cur["result"]}
    from src.market.user_provider import PublicDataUnavailable

    x = recalc.context(s["draft_config"])
    try:
        r = recalc.recalc(s["draft_config"], ov, ctx=session_ctx(s))
    except PublicDataUnavailable as e:
        return {"ok": False, "reason": str(e), "session": s, "result": None}
    if r.get("per_share") is None:
        return {"ok": False, "reason": r.get("error", "계산 불가"), "session": s, "result": r}
    nv = cur["v"] + 1
    s["versions"].append({"v": nv, "overrides": ov, "created": _now(), "result": r, "reverted_to": target["v"]})
    for f in [k for k in spec.NATIVE + spec.HOOK if cur["overrides"].get(k) != ov.get(k)]:
        auto = _auto_value(f, x.base_cfg, x.base_led, s["versions"][0]["result"], x)
        b, a = cur["overrides"].get(f, auto), ov.get(f, auto)
        s["audit"].append(
            {
                "at": _now(),
                "v": nv,
                "field": f,
                "label": spec.LABEL[f],
                "before": b,
                "after": a,
                "before_text": spec.fmt(f, b),
                "after_text": spec.fmt(f, a),
                "reason": reason or f"v{target['v']}로 되돌리기",
                "judgement": None,
                "warnings": [],
                "revert_to": target["v"],
                "per_share_before": cur["result"].get("per_share"),
                "per_share_after": r.get("per_share"),
            }
        )
    save(s)
    return {"ok": True, "reason": "", "session": s, "result": r}


def set_engagement(s: dict, fields: dict, reason: str | None = None) -> dict:
    """P7-X2b (config/p7x2b.yaml display.engagement): purpose, premise and evaluator of the report and the Excel cover.
    Empty text = the default wording. One audit entry (before -> after); no new version (values of the model unchanged)."""
    keys = ("purpose", "premise", "evaluator")
    new = {k: str(fields.get(k) or "").strip()[:200] for k in keys}
    old = {k: str((s.get("engagement") or {}).get(k) or "") for k in keys}
    if new == old:
        return {"ok": True, "reason": "", "session": s, "noop": True}
    s["engagement"] = {k: v for k, v in new.items() if v}
    s["audit"].append(
        {
            "at": _now(),
            "v": current(s)["v"],
            "field": None,
            "label": "평가 목적·전제·평가자",
            "before": old,
            "after": new,
            "before_text": " / ".join(f"{k}={v}" for k, v in old.items() if v),
            "after_text": " / ".join(f"{k}={v}" for k, v in new.items() if v),
            "reason": reason or "",
            "judgement": None,
        }
    )
    save(s)
    return {"ok": True, "reason": "", "session": s}


def set_public_inputs(s: dict, user: dict) -> dict:
    """Store the public-mode market inputs (close, vwap20, sub_close, pref) the user typed. Values must be positive."""
    out = {}
    for k in ("close", "vwap20", "mktcap"):
        if user.get(k) not in (None, ""):
            v = float(user[k])
            if not v > 0:
                raise ValueError(f"{k}: 0보다 커야 한다")
            out[k] = v
    for k in ("sub_close",):
        d = {c: float(v) for c, v in (user.get(k) or {}).items() if v not in (None, "")}
        if any(not v > 0 for v in d.values()):
            raise ValueError("상장 종속회사 종가: 0보다 커야 한다")
        if d:
            out[k] = d
    pref = {
        c: {"close": float(v["close"]), "listed": int(v["listed"])}
        for c, v in (user.get("pref") or {}).items()
        if v and v.get("close") not in (None, "") and v.get("listed") not in (None, "")
    }
    if pref:
        out["pref"] = pref
    if user.get("example") is True:  # P7-D: the screen's round example values (shown as '예시 입력', not a real close)
        out["example"] = True
    s["public_inputs"] = out
    save(s)
    return s


def result(s: dict, version: int | None = None) -> dict:
    """Recalculate a stored version from its overrides (reproducibility: equals the stored result)."""
    from src.workbench import recalc

    v = s["versions"][-1] if version is None else next(x for x in s["versions"] if x["v"] == version)
    return recalc.recalc(s["draft_config"], v["overrides"], ctx=session_ctx(s))


def session_ctx(s: dict):
    """The in-memory company a session's stored results use. PC: the cached PC context (DB market values). Public
    deployment (P7-C3): the user's market inputs when complete (the same values the screen shows), else the context without
    market values (DCF values need none; a SOTP needs the listed subsidiaries' closes)."""
    from src.workbench import recalc
    from src.workbench.snapdata import replaying

    if not replaying():
        return None
    u = s.get("public_inputs") or {}
    if u.get("close") and u.get("vwap20"):
        return recalc.public_context_cached(s["draft_config"], u)
    return None


def snapshot_changed(s: dict) -> list[str]:
    """Warnings when the draft, statements or loader code changed since the session was made."""
    cfg = yamlio.load((ROOT / s["draft_config"]).read_text(encoding="utf-8"))
    now = snapshot(cfg)
    out = []
    if _sha(ROOT / s["draft_config"]) != s["draft_sha"]:
        out.append("자동 초안 설정 파일이 바뀜")
    if now["statements"] != s["snapshot"]["statements"] or now["loader_code"] != s["snapshot"]["loader_code"]:
        out.append("재무 원본 또는 적재 코드가 바뀜")
    if now["market_hash"] != s["snapshot"]["market_hash"]:
        out.append("시세 값이 바뀜")
    return out
