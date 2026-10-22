"""Account mis-tag check against the report text (P7-B3b, config/p7b3b.yaml mistag.text_rule).

The OpenDART statement API is the XBRL tagging of the filing; the printed statement in document.xml is the primary
source. Some filers tag a borrowing with a non-borrowing account (RF Materials 2026 H1 separate: the text says
'장기차입금 4,900,000,000', the API row is 'dart_LongTermTradeAndOtherNonCurrentPayables 장기매입채무 및 기타비유동채무').
Name/ID rules (config/account_map.yaml never_trust_ids) cannot see that, because both the API name and ID are wrong.

    reclass_rows(api_rows, text_rows)        pure rule: which API rows hold a borrowing the text names as such
    debt_reclass(con, corp, fs_div, periods) -> list of {year, period, rcept, text_label, api_label, api_id, amount}
    by_period(items)                         -> {(year, period): amount (원)}
Only auto drafts use it (src/pipeline/draft.py); fs_std and the RF / JW configs are unchanged.
"""

from __future__ import annotations

import re

from src.collect.core import ROOT, RawStore

BORROW = re.compile(r"(차입금|사채|차입부채|장기부채)$")
NOT_BORROW = re.compile(r"할인|조정|할증|이자|부채총계|합계")
REPRT = {"FY": "11011", "H1": "11012"}


def _periods() -> list[tuple[int, str]]:
    """FY(Y−3)~FY(Y−1) + (FY, P) + (Y, P) of the draft rules' meta (P7-X2b; FY2023~2025, 2025·2026 H1 at 2026-09-30)."""
    from src.pipeline import asof

    pe = asof.default()
    return [(y, "FY") for y in pe["avg"]] + [(pe["FY"], pe["P"]), (pe["Y"], pe["P"])]


def is_borrowing(label: str) -> bool:
    nm = re.sub(r"\s+", "", str(label or ""))
    nm = re.sub(r"\(주\d+[,\d]*\)|\(주석\d+[,\d]*\)", "", nm)
    return bool(BORROW.search(nm)) and not NOT_BORROW.search(nm)


def _same(api: float, text: float, unit: int) -> bool:
    return api == text or (unit > 1 and round(api / unit) * unit == text)


def reclass_rows(api_rows: list[dict], text_rows: list[tuple[str, float, int]]) -> list[dict]:
    """api_rows: {'account_nm', 'account_id', 'amount'} of one balance sheet (원); text_rows: (label, amount 원, unit).
    A text borrowing line whose amount appears on exactly one API row and on no API row named as a borrowing ->
    that API row is a mis-tagged borrowing."""
    out = []
    for lab, amt, unit in text_rows:
        if not amt or amt <= 0 or not is_borrowing(lab):
            continue
        same = [
            r
            for r in api_rows
            if r.get("amount") is not None and r["amount"] == r["amount"] and _same(float(r["amount"]), amt, unit)
        ]
        if not same or any(is_borrowing(r["account_nm"]) for r in same):
            continue
        if len(same) == 1:
            r = same[0]
            out.append(
                {"text_label": lab, "api_label": r["account_nm"], "api_id": r.get("account_id"), "amount": float(r["amount"])}
            )
    return out


def text_bs_rows(section_markup: str) -> list[tuple[str, float, int]]:
    """(label, first-period amount in 원, unit) of the balance-sheet table(s) of one statements section."""
    from src.clean.dna import _num, html_tables, unit_of
    from src.clean.recon import clean_label

    out = []
    for t in html_tables(section_markup) if section_markup else []:
        rows = t["rows"]
        if not rows or not any(re.search(r"부채총계", "".join(r)) for r in rows):
            continue
        unit = unit_of(t["before"]) or unit_of(" ".join(" ".join(r) for r in rows[:2]))
        if unit is None:
            continue
        head = next((r for r in rows[:3] if any(re.search(r"당기|당반기|당분기|제\d+기|과목", c) for c in r)), rows[0])
        skip = {j for j, c in enumerate(head) if re.fullmatch(r"주석|주", c)}
        for r in rows:
            if not r:
                continue
            cells = [c for j, c in enumerate(r) if j not in skip][1:]
            nums = [x for x in (_num(c) for c in cells) if x is not None]
            if nums:
                out.append((clean_label(r[0]), float(nums[0]) * unit, unit))
        break  # the first balance sheet of the section (current period)
    return out


def debt_reclass(con, corp: str, fs_div: str, periods=None) -> list[dict]:
    from src.collect.doc_text import fs_sections, main_xml

    out = []
    for y, p in periods or _periods():
        rc = con.execute(
            """SELECT DISTINCT rcept_no FROM fs_raw WHERE corp_code=? AND fs_div=? AND bsns_year=? AND reprt_code=?
                            AND sj_div='BS' ORDER BY rcept_no DESC""",
            [corp, fs_div, y, REPRT[p]],
        ).fetchone()
        if not rc:
            continue
        f = ROOT / "data" / "raw" / "dart" / "document.xml" / f"{rc[0]}.zip.gz"
        if not f.exists():
            continue
        api = (
            con.execute(
                """SELECT account_nm, account_id, thstrm_num AS amount FROM fs_raw WHERE corp_code=? AND fs_div=?
                             AND bsns_year=? AND reprt_code=? AND sj_div='BS' AND rcept_no=?""",
                [corp, fs_div, y, REPRT[p], rc[0]],
            )
            .df()
            .to_dict("records")
        )
        sec = fs_sections(main_xml(RawStore.load(f))).get(f"{fs_div}_FS", "")
        for x in reclass_rows(api, text_bs_rows(sec)):
            out.append({"year": int(y), "period": p, "rcept": rc[0], **x})
    return out


def by_period(items: list[dict] | None) -> dict[tuple[int, str], float]:
    out: dict[tuple[int, str], float] = {}
    for x in items or []:
        k = (int(x["year"]), x["period"])
        out[k] = out.get(k, 0.0) + float(x["amount"])
    return out
