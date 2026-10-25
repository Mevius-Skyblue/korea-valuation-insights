"""Disclosures and events of an evaluation session (P7-U1, config/p7u.yaml events).

Three sections by date: after the valuation date (follow-up events), balance-sheet date -> valuation date, before the
balance-sheet date (reference). Every row: filing date, title, kind, value-impact tags, review mark, DART link.

    kind_of(title)                 '정기' / '지분' / '주요' / '발행' / '공정' / '기타' (first title rule)
    tags_of(title, detail=None)    value-impact tags in the table order ('주식수', '순차입금', '우발', '구조', '추정');
                                   the filing type code when the row has it (list.json rows do not), else title words only
    rows(cfg, s)                   {'sections': [...], 'stats': {...}} of a session
    review(s, rcept_no, mark)      mark 'adj' (반영) / 'note' (주석) / 'na' (해당 없음) / '' (지움): session record + audit
    lookup(s, cfg, fetch=None)     PC: one OpenDART list.json call (valuation date + 1 ~ today), stored in the session
    report_rows(cfg, s)            reviewed rows for the report '기준일 뒤 사건' box (confirm)

Nothing here changes a value: '반영' means a person adjusts the assumptions or the bridge themselves.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache

from src import yamlio
from src.collect.core import ROOT

MARKS = {"adj": "반영", "note": "주석", "na": "해당 없음"}
MOVED_CATEGORY = "기준일 뒤 주요 공시"  # the judgement item this tab replaces (config/p7u.yaml events.judgement_link)
VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


@lru_cache(maxsize=1)
def rules() -> dict:
    return yamlio.load((ROOT / "config" / "p7u.yaml").read_text(encoding="utf-8"))["events"]


def _norm(title: str) -> str:
    return re.sub(r"\s+", "", str(title or ""))


def kind_of(title: str) -> str:
    t = _norm(title)
    for r in rules()["kind_rules"]:
        if not r["words"] or any(w in t for w in r["words"]):
            return r["kind"]
    return "기타"


def periodic(title: str) -> bool:
    return kind_of(title) == "정기"


def tags_of(title: str, detail: str | None = None) -> list[str]:
    """Value-impact tags of a filing title (order = the rule table); a periodic report has none (it is the statement)."""
    t = _norm(title)
    if periodic(title):
        return []
    out = []
    for r in rules()["tags"]:
        hit = any(w in t for w in r["words"]) or (detail is not None and detail in (r.get("pblntf_detail") or []))
        if hit and not any(w in t for w in r.get("not_words") or []):
            out.append(r["name"])
    return out


def tag_tab(tag: str) -> str | None:
    return next((r["tab"] for r in rules()["tags"] if r["name"] == tag), None)


def tag_tip(tag: str) -> str:
    return next((r["tip"] for r in rules()["tags"] if r["name"] == tag), "")


def _d(s: str) -> date:
    s = str(s).replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _sources(cfg: dict) -> list[tuple[str, str]]:
    """(rcept_no, title word) of the periodic reports the valuation uses, from the config's source texts."""
    texts = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("source", "structure_source") and isinstance(v, str):
                    texts.append(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk({k: cfg.get(k) for k in ("meta", "shares", "structure", "draft_meta", "kd", "bridge")})
    out = {}
    for t in texts:
        for m in re.finditer(r"(사업보고서|반기보고서|분기보고서)[^;|]{0,60}?(\d{14})", t):
            out.setdefault(m.group(2), m.group(1))
    return list(out.items())


def _row(rcept: str, dt: str, title: str, used: set, s: dict, section: str) -> dict:
    per = periodic(title)
    tg = tags_of(title)
    rv = ((s or {}).get("events_review") or {}).get(rcept) or {}
    return {
        "rcept_no": rcept,
        "date": _d(dt).isoformat(),
        "title": str(title).strip(),
        "kind": kind_of(title),
        "tags": tg,
        "tag": tg[0] if tg else ("재무 기준" if per else ""),
        "periodic": per,
        "fixed": ("반영 · 재무 탭" if rcept in used else "참고") if per else "",
        "mark": rv.get("mark") or "",
        "review": not per,
        "section": section,
        "href": VIEW + rcept,
    }


def rows(cfg: dict, s: dict | None) -> dict:
    """The event rows of a session in three sections (newest first) and the four counts above the table."""
    meta = cfg["meta"]
    bs, asof = _d(meta["bs_date"]), _d(meta["as_of"])
    used = {r for r, _ in _sources(cfg)}
    post = (cfg.get("draft_meta") or {}).get("post_bs_disclosures") or []
    mid = [_row(p["rcept_no"], p["rcept_dt"], p.get("report_nm", ""), used, s, "bs_to_asof") for p in post if p.get("rcept_no")]
    mid = [r for r in mid if bs < _d(r["date"]) <= asof]
    seen = {r["rcept_no"] for r in mid}
    before = []
    for rc, word in _sources(cfg):
        if rc in seen or _d(rc[:8]) > bs:
            continue
        before.append(_row(rc, rc[:8], _source_title(word, rc, cfg), used, s, "before_bs"))
        seen.add(rc)
    lk = (s or {}).get("events_lookup") or {}
    after = [
        _row(p["rcept_no"], p["rcept_dt"], p.get("report_nm", ""), used, s, "after_asof")
        for p in lk.get("rows") or []
        if p.get("rcept_no") and _d(p["rcept_dt"]) > asof and p["rcept_no"] not in seen
    ]
    for lst in (after, mid, before):
        lst.sort(key=lambda r: (r["date"], r["rcept_no"]), reverse=True)
    sec = rules()["sections"]
    lab = {x["id"]: x["label"].format(as_of=meta["as_of"], bs_date=meta["bs_date"]) for x in sec}
    all_rows = after + mid + before
    todo = [r for r in all_rows if r["review"] and not r["mark"]]
    return {
        "sections": [
            {"id": "after_asof", "label": lab["after_asof"], "rows": after, "lookup": lk},
            {"id": "bs_to_asof", "label": lab["bs_to_asof"], "rows": mid},
            {"id": "before_bs", "label": lab["before_bs"], "rows": before},
        ],
        "stats": {
            "bs_to_asof": len(mid),
            "tagged": sum(1 for r in all_rows if r["tags"]),
            "to_review": len(todo),
            "after": None if not lk.get("at") else len(after),
        },
    }


def _source_title(word: str, rcept: str, cfg: dict) -> str:
    y = int(rcept[:4])
    if word == "사업보고서":
        return f"사업보고서 ({y - 1}.12)"
    if word == "반기보고서":
        return f"반기보고서 ({y}.06)"
    return word


def pending(cfg: dict, s: dict) -> int:
    return rows(cfg, s)["stats"]["to_review"]


def review(s: dict, rcept_no: str, mark: str, cfg: dict | None = None, reason: str | None = None) -> dict:
    """Record a review mark (no new version: values do not change). When nothing is left to review, the moved judgement
    item '기준일 뒤 주요 공시' is kept ('그대로 유지', reason '공시·이벤트 탭 검토')."""
    from src.workbench import session as S

    if mark not in ("", *MARKS):
        return {"ok": False, "reason": f"알 수 없는 검토 '{mark}'"}
    rv = s.setdefault("events_review", {})
    old = (rv.get(rcept_no) or {}).get("mark", "")
    if old == mark:
        return {"ok": True, "noop": True}
    if mark:
        rv[rcept_no] = {"mark": mark, "at": S._now(), "v": S.current(s)["v"]}
    else:
        rv.pop(rcept_no, None)
    s["audit"].append(
        {
            "at": S._now(),
            "v": S.current(s)["v"],
            "field": None,
            "label": "공시 검토",
            "before": old,
            "after": mark,
            "before_text": MARKS.get(old, ""),
            "after_text": f"{rcept_no} {MARKS.get(mark, '지움')}",
            "reason": reason or "",
            "judgement": None,
        }
    )
    if cfg is not None and pending(cfg, s) == 0:
        for jid, j in (s.get("judgements") or {}).items():
            if j.get("category") == MOVED_CATEGORY and j.get("status") == "미처리":
                from src.workbench import judge as J

                J.resolve(s, jid, "keep", reason="공시·이벤트 탭 검토")
    S.save(s)
    return {"ok": True}


def lookup(s: dict, cfg: dict, fetch=None, today: date | None = None) -> dict:
    """Follow-up filings after the valuation date: one OpenDART list.json call (page 1, 100 rows) when the person presses
    [조회] (PC mode). fetch(corp_code, bgn, end) -> list of rows (tests pass a recorded response). Stored with its time."""
    from src.workbench import session as S

    asof = _d(cfg["meta"]["as_of"])
    bgn = date.fromordinal(asof.toordinal() + 1)
    end = today or date.today()
    rec = {"at": S._now(), "bgn": bgn.isoformat(), "end": end.isoformat()}
    if end < bgn:
        rec.update({"status": "기준일 뒤 기간 없음", "rows": []})
    else:
        try:
            if fetch is None:
                from src.collect.clients import Dart
                from src.pipeline import collect as C

                def fetch(corp, b, e):
                    return C.disclosures(Dart(), C.Calls(), corp, b, e)

            got = fetch(cfg["target"]["corp_code"], bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            rec.update(
                {
                    "status": "조회됨",
                    "rows": [{k: x.get(k) for k in ("rcept_dt", "report_nm", "rcept_no")} for x in got or []],
                }
            )
        except Exception as e:  # noqa: BLE001 - shown as '조회 실패' with the reason
            rec.update({"status": f"조회 실패: {type(e).__name__}: {str(e)[:120]}", "rows": []})
    s["events_lookup"] = rec
    s["audit"].append(
        {
            "at": rec["at"],
            "v": S.current(s)["v"],
            "field": None,
            "label": "기준일 뒤 공시 조회",
            "before": None,
            "after": rec["status"],
            "before_text": "",
            "after_text": f"{rec['bgn']}~{rec['end']} {rec['status']} {len(rec['rows'])}건",
            "reason": "",
            "judgement": None,
        }
    )
    S.save(s)
    return rec


def report_rows(cfg: dict, s: dict) -> list[dict]:
    """Reviewed non-periodic rows for the report (date, title, tags, mark) - '해당 없음' rows are counted, not listed."""
    out = []
    for sec in rows(cfg, s)["sections"]:
        for r in sec["rows"]:
            if r["review"] and r["mark"]:
                out.append(
                    {
                        "section": sec["id"],
                        "date": r["date"],
                        "title": r["title"],
                        "tags": "·".join(r["tags"]) or "-",
                        "mark": MARKS[r["mark"]],
                        "rcept_no": r["rcept_no"],
                    }
                )
    return out


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
