"""Session file download / upload (config/p7c3.yaml public_app.session_store).

The public deployment keeps sessions in a temporary folder per browser session; a person keeps the work by downloading
the session file and continues later by uploading it.

    dump(s) -> bytes        {"format", "app_version", "snapshot_sha", "code", "session", "sig"}; sig = SHA-256 of the
                            canonical JSON of everything else (detects an edited or damaged file; not a secret key)
    load(data) -> (s, notes)  verify the signature and the format, then rebuild: a NEW session on the company's draft in
                            this workspace (paths and names in the file are not used), the user's market inputs, every
                            version's assumptions (each value range-checked again, recalculated now), the audit trail
                            (text fields only) and the judgement statuses. Another app version or snapshot -> a note
"""
from __future__ import annotations

import hashlib
import json

from src.workbench import session as S
from src.workbench import spec

FORMAT = "kvi-session/1"
AUDIT_KEYS = ("at", "v", "field", "label", "before", "after", "before_text", "after_text", "reason", "judgement", "warnings",
              "per_share_before", "per_share_after", "revert_to")


class SessionFileError(ValueError):
    pass


def _canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def app_version() -> str:
    from src.workbench.public_deploy import bundle_info, is_public
    return str(bundle_info().get("source_commit")) if is_public() else S.git_state()["commit"][:12]


def dump(s: dict) -> bytes:
    keep = {k: s.get(k) for k in ("session_id", "code", "name", "as_of", "created", "audit", "judgements", "public_inputs", "auto_headline")}
    keep["versions"] = [{"v": v["v"], "overrides": v["overrides"], "created": v["created"], "reverted_to": v.get("reverted_to")}
                        for v in s["versions"]]
    keep["confirmed_v"] = (s.get("confirmed") or {}).get("v")
    payload = {"format": FORMAT, "app_version": app_version(), "snapshot_sha": (s.get("snapshot") or {}).get("public_snapshot"),
               "code": s["code"], "session": keep}
    payload["sig"] = hashlib.sha256(_canon(payload)).hexdigest()
    return json.dumps(payload, ensure_ascii=False, indent=1, default=str).encode("utf-8")


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def load(data: bytes) -> tuple[dict, list[str]]:
    try:
        p = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SessionFileError(f"세션 파일을 읽을 수 없음({type(e).__name__})") from e
    if not isinstance(p, dict) or p.get("format") != FORMAT:
        raise SessionFileError("KVI 세션 파일 형식이 아님")
    sig = p.pop("sig", None)
    if sig != hashlib.sha256(_canon(p)).hexdigest():
        raise SessionFileError("서명이 맞지 않음 — 파일이 바뀌었거나 손상됨")
    code = str(p.get("code") or "")
    if not (len(code) == 6 and code.isalnum()):
        raise SessionFileError("회사 코드가 올바르지 않음")
    notes = []
    if p.get("app_version") != app_version():
        notes.append(f"다른 앱 버전에서 만든 파일입니다({p.get('app_version')} → 지금 {app_version()}). 가정·판단 기록은 불러오고 값은 지금 버전으로 다시 계산했습니다.")
    src = p["session"]
    s = S.create(code)
    now_sha = (s.get("snapshot") or {}).get("public_snapshot")
    if p.get("snapshot_sha") and now_sha and p["snapshot_sha"] != now_sha:
        notes.append("회사 자료(공개 스냅샷)가 바뀌었습니다. 같은 가정으로 다시 계산한 값이라 파일을 만들 때와 다를 수 있습니다.")
    u = src.get("public_inputs") or {}
    if u:
        try:
            S.set_public_inputs(s, u)
        except (ValueError, TypeError, KeyError) as e:
            notes.append(f"시세 입력을 불러오지 못함: {e}")
    from src.workbench import recalc
    x = recalc.context(s["draft_config"])
    skipped = 0
    for ver in sorted(src.get("versions") or [], key=lambda v: v.get("v", 0)):
        if not ver.get("v"):
            continue
        ov = {}
        for f, val in (ver.get("overrides") or {}).items():
            ok, _why, nv = spec.check(f, val, x.peers_all())
            if ok:
                ov[f] = nv
            else:
                skipped += 1
        r = recalc.recalc(s["draft_config"], ov, ctx=S.session_ctx(s))
        s["versions"].append({"v": len(s["versions"]), "overrides": ov, "created": str(ver.get("created") or S._now()), "result": r,
                              **({"reverted_to": ver["reverted_to"]} if isinstance(ver.get("reverted_to"), int) else {})})
    if skipped:
        notes.append(f"허용 범위를 벗어난 가정 {skipped}개는 불러오지 않았습니다(자동값 유지).")
    s["audit"] = [{k: a.get(k) for k in AUDIT_KEYS if k in a} for a in src.get("audit") or [] if isinstance(a, dict)]
    for jid, j in (src.get("judgements") or {}).items():
        mine = s["judgements"].get(jid)
        if mine and isinstance(j, dict) and str(mine.get("item")) == str(j.get("item")) and j.get("status") in ("미처리", "채택", "수정", "그대로 유지"):
            mine["status"] = j["status"]
            res = j.get("resolution")
            mine["resolution"] = {k: res.get(k) for k in ("action", "field", "value", "reason", "at", "v")} if isinstance(res, dict) else None
    s["loaded_from"] = {"session_id": str(src.get("session_id")), "app_version": p.get("app_version"), "at": S._now()}
    S.save(s)
    return s, notes
