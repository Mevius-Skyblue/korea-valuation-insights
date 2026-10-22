"""Screen data of the work screen (P7-C2): what each card shows, assembled from the session file (the source of the values),
the auto draft (config + summary.json) and the in-memory company of src/workbench/recalc. Nothing here changes an engine
rule: values come from the same engine functions (recalc.recalc, company_dcf helpers, p3c1.multiple_stats,
diagnose.signals / peer_range, predict.premium_range).

Modes (config/p7c2.yaml display_rules / public_mode):
    pc       values of the session versions as stored (DB market data, '한국거래소 통계정보')
    public   values recalculated on a company loaded with the user's market inputs (recalc.public_context =
             UserOverlayProvider, the same values as the public-mode export). Until the inputs are complete, cards that
             need them raise NeedInput (the card shows what to type). With no DB at all (no_db()), cards that need it
             raise PublicDataUnavailable (the card shows '이 기능은 PC 모드 또는 사용자 입력이 필요합니다').

Thread safety: recalc mutates the in-memory company, so every recalculation runs under LOCK (one browser session at a
time; a single-user tool).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src import yamlio
from src.collect.core import ROOT
from src.market.user_provider import PublicDataUnavailable
from src.workbench import judge as J
from src.workbench import pubcut, spec
from src.workbench import recalc as R
from src.workbench import session as S

LOCK = threading.RLock()
AS_OF = "2026-09-30"
APP_DATA = ROOT / "app" / "data"
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wb")
_CACHE: dict = {}  # small per-process result caches (keys include session id and version)


PREMIUM_WITHHELD = "경영권 프리미엄 집계는 이 배포에서 공개하지 않습니다(블록 1주당 가격을 계산하지 않음, PC 모드에서 계산)"


def _premium_on() -> bool:
    from src.workbench.public_deploy import premium_public

    return premium_public()


def _submit(fn, *a):
    """Background task with this run's context (P7-C3: the browser session's workspace)."""
    import contextvars

    return _POOL.submit(contextvars.copy_context().run, fn, *a)


class NeedInput(RuntimeError):
    """Public mode: the user's market inputs are needed for this card."""


def no_db() -> bool:
    """Simulation of a deployment without the DB and without a snapshot (P7-C2 test): env WB_NO_DB=1. The real public
    deployment (P7-C3) replays the public snapshot instead (snapdata replay) and needs no DB."""
    from src.workbench.snapdata import replaying

    return os.environ.get("WB_NO_DB") == "1" and not replaying()


def public_deploy() -> bool:
    """The public deployment (P7-C3): snapshot replay, public mode only."""
    from src.workbench.snapdata import replaying

    return replaying()


def need_db(what: str) -> None:
    if no_db():
        raise PublicDataUnavailable(f"{what}: DB 없음(공개 배포)")


def _load_yaml(p) -> dict:
    return yamlio.load((ROOT / p).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- companies, drafts, gate


def universe() -> list[dict]:
    """Search list: KOSPI·KOSDAQ common stocks on the as-of date (names only) + every company with an auto draft."""
    if public_deploy():  # P7-C3: the public range only (config/p7c3.yaml companies)
        from src.workbench.public_deploy import index

        return sorted(
            ({"code": x["code"], "name": x["name"], "market": x["market"]} for x in index().values()), key=lambda x: x["name"]
        )
    k = ("universe", no_db(), len(list((ROOT / "config" / "drafts").glob("valuation_*.yaml"))))
    if k in _CACHE:
        return _CACHE[k]
    out = {}
    if not no_db():
        from src.market.provider import get

        u = get().universe(AS_OF, ["KOSPI", "KOSDAQ"])
        u = u[u.eligible]
        for r in u.itertuples():
            out[r.stock_code] = {"code": r.stock_code, "name": r.isu_nm, "market": r.mkt_nm}
    for p in sorted((ROOT / "config" / "drafts").glob("valuation_*.yaml")):
        code = p.stem.replace("valuation_", "")
        if code not in out and code.isdigit():
            try:
                t = yamlio.load(p.read_text(encoding="utf-8"))["target"]
                out[code] = {"code": code, "name": t["name"], "market": t.get("market", "")}
            except Exception:  # noqa: BLE001 - a broken draft file is skipped in the search list
                continue
    _CACHE[k] = sorted(out.values(), key=lambda x: x["name"])
    return _CACHE[k]


def draft_state(code: str) -> dict:
    """{'has_draft', 'summary', 'cfg_path'} for a code (summary.json of the last pipeline run, if any)."""
    cfg_path = f"config/drafts/valuation_{code}.yaml"
    summ = S.draft_summary(code)
    if public_deploy():  # P7-C3: the snapshot holds the draft (evaluable) or the gate table only
        return {"has_draft": summ is not None, "summary": summ, "cfg_path": None, "in_public": summ is not None}
    ok = (ROOT / cfg_path).exists() and summ is not None and bool((summ.get("steps") or {}).get("first_draft", {}).get("ok"))
    return {"has_draft": ok, "summary": summ, "cfg_path": cfg_path}


GATES = [
    ("G1", "업종(금융업 아님)", ("G1_finance",)),
    ("G1b", "재무구조(금융회사형 아님)", ("G1b_finance_structure",)),
    ("G2", "최근 3년 중 영업이익 흑자 연도", ("G2_all_loss",)),
    ("G3", "3년 영업이익 합계 > 0", ("G3_negative_margin",)),
    ("G4", "FY2025 매출 100억원 이상", ("G4_tiny_revenue",)),
    ("G5", "12월 결산", ("G5_fiscal_year",)),
    ("G6", "지배구조(일반 경로·SOTP로 평가 가능)", ("G6_structure", "G6_sotp_unsupported")),
    ("G7", "필수 재무 자료(FY2022~2025·반기)", ("G7_data",)),
    ("G8", "쓸 수 있는 피어 3곳 이상", ("G8_peers",)),
]
NOTE_RULES = {
    "G6_sotp_path": ("G6", "SOTP 경로"),
    "G23_loss_path": ("G2", "적자 경로"),
    "G8_peer_relax": ("G8", "피어 부족 → 판단 1순위"),
}
OUT_WHY = {
    "G1": "금융회사는 예금·대출 같은 영업과 재무 활동이 섞여 있어 현금흐름 할인(FCFF)과 EV 배수가 맞지 않습니다. 금융업 전용 방법이 필요합니다.",
    "G1b": "재무상태표가 금융회사형(영업자산 비중 5% 미만, 부채 비중 30% 이상)이라 같은 이유로 자동 평가 범위 밖입니다.",
    "G2": "최근 3년 영업이익이 모두 적자이고 매출 기준(100억원, 시가총액의 5%)도 못 넘어 적자 경로로도 평가하지 않습니다.",
    "G3": "최근 3년 영업이익 합계가 0 이하이고 매출 기준도 못 넘어 예측 출발점을 세울 수 없습니다.",
    "G4": "매출이 너무 작아(100억원 미만) 매출을 바탕으로 한 추정을 믿기 어렵습니다(초기 바이오 등).",
    "G5": "12월 결산이 아니라 계산 엔진의 기간 계산(LTM = 사업연도 + 반기 − 전년 반기)이 맞지 않습니다.",
    "G6": "지원하지 않는 지배구조입니다(예: 상장 종속회사를 다른 종속회사를 통해서만 보유).",
    "G7": "필수 재무 자료가 없어 예측 출발점을 만들 수 없습니다(최근 상장·분할 등).",
    "G8": "비교할 피어가 3곳 미만입니다.",
}


def gate_view(summ: dict | None) -> dict:
    """Rows G1~G8 with ✓ / ✗ / → (path note) / '확인 전' and the path label. No numbers for an out-of-scope company."""
    if not summ:
        return {"rows": [], "path": "초안 없음", "passed": None, "fails": []}
    g = summ.get("gate") or {}
    fails = list(g.get("stage_a") or []) + list(g.get("stage_b") or [])
    notes = list(g.get("notes") or [])
    b_run = "stage_b" in g or g.get("passed")
    rows = []
    for gid, label, rules in GATES:
        bad = [f for f in fails if f.get("rule") in rules]
        nt = [
            n
            for n in notes
            if NOTE_RULES.get(n.get("rule"), ("",))[0] == gid or (gid == "G3" and n.get("rule") == "G23_loss_path")
        ]
        if bad:
            st_, val = "✗", "; ".join(str(f.get("value") or "") for f in bad)
        elif nt:
            st_, val = (
                "→",
                NOTE_RULES.get(nt[0]["rule"], ("", "경로"))[1] + (f" ({nt[0].get('value')})" if nt[0].get("value") else ""),
            )
        elif gid in ("G7", "G8") and not b_run:
            st_, val = "확인 전", "앞 게이트에서 멈춤"
        else:
            st_, val = "✓", ""
        rows.append({"id": gid, "label": label, "status": st_, "value": val})
    facts = summ.get("facts") or {}
    passed = bool(g.get("passed"))
    if not passed:
        path = "범위 밖"
    elif any(n.get("rule") == "G6_sotp_path" for n in notes):
        path = "SOTP(모회사 사업 가치 + 상장 종속회사 지분 시가 + 비상장 지분 장부)"
    elif any(n.get("rule") == "G23_loss_path" for n in notes):
        path = "적자 경로(피어 EV/Sales 범위 + 전환 DCF)"
    elif facts.get("nci_path"):
        path = "연결 DCF − 비지배지분(장부)"
    else:
        path = "일반(" + ("별도 DCF" if facts.get("fs_div") == "OFS" else "연결 DCF − 비지배지분") + ")"
    why = [
        {"id": r["id"], "label": r["label"], "value": r["value"], "why": OUT_WHY.get(r["id"], "")}
        for r in rows
        if r["status"] == "✗"
    ]
    return {"rows": rows, "path": path, "passed": passed, "fails": why, "result": summ.get("result")}


# ---------------------------------------------------------------- sessions


def sessions() -> list[dict]:
    """Saved sessions: company, as-of, version, status (초안/확정), pending judgements, last change."""
    out = []
    for p in sorted(S.base().glob("*/session.json")):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        v = s["versions"][-1]["v"]
        conf = (s.get("confirmed") or {}).get("v")
        out.append(
            {
                "sid": s["session_id"],
                "code": s["code"],
                "name": s["name"],
                "as_of": s["as_of"],
                "version": v,
                "status": "확정" if conf is not None and conf == v else ("확정 뒤 수정" if conf is not None else "초안"),
                "pending": S.pending(s),
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)),
                "auto": ((s.get("auto_headline") or {}).get("status") or ""),
            }
        )
    return sorted(out, key=lambda x: x["modified"], reverse=True)


def load(sid: str) -> dict:
    return S.load(sid)


class Opened:
    """The heavy, unchanging part of an open session: draft config + summary, the in-memory company (recalc context),
    the peer table and the snapshot check (run in parallel with the company load)."""

    def __init__(self, sid: str):
        need_db("세션 열기(재무·피어·베타 표)")
        s = S.load(sid)
        if public_deploy():  # P7-C3: the company's public snapshot in this process's replay store
            from src.workbench.public_deploy import ensure

            ensure(s["code"])
        self.sid, self.code, self.name = sid, s["code"], s["name"]
        self.cfg_path = s["draft_config"]
        self.cfg = _load_yaml(self.cfg_path)
        self.summ = S.draft_summary(self.code) or {}
        self._snap = _submit(_snapshot_check, s)
        with LOCK:
            self.ctx = R.context(self.cfg_path)
        name = Path(self.cfg_path).stem.replace("valuation_", "")
        if public_deploy():  # P7-C3: multiple quartiles of the draft peers as aggregates (no rows)
            self.p3 = None
        else:
            import duckdb

            from src.db.build import DB_PATH

            con = duckdb.connect(str(DB_PATH), read_only=True)
            try:
                self.p3 = con.execute(f"SELECT * FROM peer_{name}_c3").df()
            finally:
                con.close()
            from src.workbench import snapdata as SD

            if SD.mode() == "record":
                from src.valuation.p3c1 import multiple_stats
                from src.workbench import pubagg

                tiers = self.cfg["beta"]["peer_tiers"]
                names = [p["name"] for p in self.cfg.get("peers", [])]
                pr = self.p3[self.p3.tier.isin(tiers) & self.p3.name.isin(names)]
                pubagg.record(
                    "screen",
                    self.cfg_path,
                    self.cfg,
                    {
                        "stats": {
                            c_: pubcut.peer_stats(multiple_stats(pr[c_]), True) for c_ in ("ev_sales", "ev_ebitda", "per", "pbr")
                        },  # P7-X2a: quartiles of fewer than 5 peers are not recorded
                        "n_peers": int(len(pr)),
                    },
                )
        st_ = self.cfg.get("structure") or {}
        self.subs = [x for x in st_.get("subsidiaries") or [] if x.get("listed") and x.get("direct") and x.get("stock_code")]
        # P7-X2b: listed associates at market value - their closes are user inputs too (same sub_close table)
        self.assocs = [x for x in (st_.get("associates") or {}).get("rows") or [] if x.get("shares") and x.get("stock_code")]
        self.prefs = list((self.cfg.get("shares") or {}).get("listed_pref_codes") or [])
        self.sotp = st_.get("method") == "sotp_general"
        self._warm = _submit(_warm, self, s)

    def snapshot_warnings(self, timeout: float = 10.0) -> list[str]:
        try:
            return self._snap.result(timeout=timeout)
        except Exception as e:  # noqa: BLE001 - shown as a warning, never stops the screen
            return [f"자료 확인 실패({type(e).__name__})"]


def _warm(o: Opened, s: dict) -> None:
    """Background warm-up after opening (PC values of the result page: market, premium, peer multiples), so the first
    visit of steps 3~4 does not wait for them. Errors are left for the cards to show."""
    for fn in (market, premium):  # cheap, mostly DB time (peer multiples are left for the first visit)
        try:
            fn(o, s, "pc")
        except Exception:  # noqa: BLE001 - the card shows the error when it asks again
            pass


def _snapshot_check(s: dict) -> list[str]:
    return S.snapshot_changed(s)


def open_key(s: dict) -> str:
    snap = s.get("snapshot") or {}
    raw = json.dumps(
        [s["session_id"], s.get("draft_sha"), snap.get("market_hash"), snap.get("statements"), snap.get("loader_code")],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- results per mode


def ukey(s: dict) -> str:
    return json.dumps(s.get("public_inputs") or {}, sort_keys=True)


def public_missing(o: Opened, s: dict) -> list[str]:
    u = s.get("public_inputs") or {}
    miss = []
    if not u.get("close"):
        miss.append("대상 종가")
    if not u.get("vwap20"):
        miss.append("대상 20일 VWAP")
    for x in o.subs:
        if x["stock_code"] not in (u.get("sub_close") or {}):
            miss.append(f"상장 종속회사 종가: {x.get('name', x['stock_code'])}({x['stock_code']})")
    for x in getattr(o, "assocs", []):
        if x["stock_code"] not in (u.get("sub_close") or {}):
            miss.append(f"상장 관계기업 종가: {x.get('name', x['stock_code'])}({x['stock_code']})")
    for p in o.prefs:
        if p not in (u.get("pref") or {}):
            miss.append(f"상장 우선주 종가·상장주식수: {p}")
    return miss


def public_ctx(o: Opened, s: dict):
    miss = public_missing(o, s)
    if miss:
        raise NeedInput("공개 모드 시세 입력 필요: " + ", ".join(miss))
    k = ("pctx", o.cfg_path, ukey(s))
    if k not in _CACHE:
        with LOCK:
            _CACHE[k] = R.public_context(o.cfg_path, s["public_inputs"])
    return _CACHE[k]


def version(s: dict, v: int | None = None) -> dict:
    return S.current(s) if v is None else next(x for x in s["versions"] if x["v"] == v)


def result(o: Opened, s: dict, mode: str, v: int | None = None) -> dict:
    """Engine values of a version for the screen. PC: the stored result. Public: recalculated on the public context."""
    ver = version(s, v)
    if mode == "pc":
        return ver["result"]
    ctx = public_ctx(o, s)
    k = ("res", s["session_id"], ver["v"], json.dumps(ver["overrides"], sort_keys=True, default=str), ukey(s))
    if k not in _CACHE:
        with LOCK:
            _CACHE[k] = R.recalc(o.cfg_path, ver["overrides"], ctx=ctx)
    return _CACHE[k]


def srp_columns(o: Opened, s: dict, mode: str) -> list[dict]:
    """Per-share value of the current assumptions at SRP 0·1·2% (and the chosen SRP when different)."""
    ver = version(s)
    cur = ver["overrides"].get("srp", o.ctx.base_led["decisions"]["srp_columns"][0])
    srps = sorted({0.0, 0.01, 0.02, round(float(cur), 6)})
    ctx = o.ctx if mode == "pc" else public_ctx(o, s)
    out = []
    for x in srps:
        k = ("srp", s["session_id"], ver["v"], mode, ukey(s) if mode == "public" else "", x)
        if k not in _CACHE:
            with LOCK:
                r = R.recalc(o.cfg_path, {**ver["overrides"], "srp": x}, ctx=ctx)
            _CACHE[k] = r.get("per_share")
        out.append({"srp": x, "per_share": _CACHE[k], "chosen": abs(x - float(cur)) < 1e-9})
    return out


def relative(o: Opened, s: dict, mode: str) -> dict:
    """Peer multiples of the current version: per multiple n, quartiles and per-share quartiles (same formula as
    excel.engine_ref.mechanical_reference) and the signal range (diagnose.peer_range)."""
    import numpy as np

    from src.pipeline.diagnose import load_rules, peer_range
    from src.valuation.company_dcf import EOK, bridge, ltm, ltm_dna, val
    from src.valuation.p3c1 import multiple_stats

    ver = version(s)
    k = ("rel", s["session_id"], ver["v"], mode, ukey(s) if mode == "public" else "")
    if k in _CACHE:
        return _CACHE[k]
    ctx = o.ctx if mode == "pc" else public_ctx(o, s)
    with LOCK:
        R.recalc(o.cfg_path, ver["overrides"], ctx=ctx)  # puts the company in this version's state
        c = ctx.c
        tiers = c.cfg["beta"]["peer_tiers"]
        names = [p["name"] for p in c.cfg.get("peers", [])]
        if o.p3 is None:  # P7-C3 public deployment: the draft peers' aggregates only
            from src.workbench import pubagg

            agg = pubagg.get("screen", o.cfg_path, o.cfg, names)
            pr = None
        else:
            pr = o.p3[o.p3.tier.isin(tiers) & o.p3.name.isin(names)]
        br = bridge(c)
        shares = c.market["shares_out"]
        eb, _ = ltm_dna(c)
        m_rev = ltm(c, "revenue")
        m_ebitda = ltm(c, "operating_income") + eb / EOK if eb else None
        m_ni = ltm(c, "net_income_parent") or ltm(c, "net_income")
        m_eq = val(c, "equity_parent", c.Y, c.P) or (val(c, "total_equity", c.Y, c.P) - val(c, "nci", c.Y, c.P))
    mult = {}
    for nm, col, kind, metric in (
        ("EV/Sales", "ev_sales", "ev", m_rev),
        ("EV/EBITDA", "ev_ebitda", "ev", m_ebitda),
        ("PER", "per", "eq", m_ni),
        ("PBR", "pbr", "eq", m_eq),
    ):
        st_ = dict(agg["stats"][col]) if pr is None else pubcut.peer_stats(multiple_stats(pr[col]), mode == "public")

        def ps(mu, kind=kind, metric=metric):
            if metric is None or not np.isfinite(mu) or metric <= 0:
                return float("nan")
            eq = (mu * metric - br["net_debt"] + br["non_operating"] - br["nci"]) if kind == "ev" else mu * metric
            return eq * EOK / shares

        mult[nm] = {
            **st_,
            "metric": (metric or float("nan")) * 100,
            "ps_q25": ps(st_["q25"]),
            "ps_median": ps(st_["median"]),
            "ps_q75": ps(st_["q75"]),
        }
    out = {
        "multiples": mult,
        "range": peer_range(mult, load_rules()["diagnostics"]),
        "n_peers": agg["n_peers"] if pr is None else len(pr),
        "bridge": dict(br),
        "shares": shares,
    }
    _CACHE[k] = out
    return out


def market(o: Opened, s: dict, mode: str) -> dict:
    """Target close / VWAP / market cap: PC = DB (한국거래소 통계정보), public = the user's inputs (None until typed)."""
    if mode == "public":
        u = s.get("public_inputs") or {}
        mc = u.get("mktcap") or (u["close"] * o.ctx.c.market["common_out"] if u.get("close") else None)
        return {"close": u.get("close"), "vwap": u.get("vwap20"), "mktcap_won": mc, "source": "사용자 입력"}
    k = ("mkt", o.code)
    if k not in _CACHE:
        from src.market.provider import get

        vw = get().vwap20(o.code, AS_OF)
        _CACHE[k] = {
            "close": o.ctx.c.market["close"],
            "vwap": vw["vwap"],
            "mktcap_won": o.ctx.c.market["mktcap_common"] * 1e8,
            "vwap_n": vw.get("n"),
            "source": "한국거래소 통계정보",
        }
    return _CACHE[k]


def signals(o: Opened, s: dict, mode: str) -> dict:
    from src.pipeline.diagnose import load_rules
    from src.pipeline.diagnose import signals as sig

    r = result(o, s, mode)
    rel = relative(o, s, mode)
    price = market(o, s, mode)["close"]
    if r.get("per_share") is None:
        return {}
    out = sig(r["per_share"], rel["range"], price or float("nan"), load_rules()["diagnostics"])
    if not price:
        out.update({"light_market": "입력 전", "ratio_market": None, "price": None})
    return out


def premium(o: Opened, s: dict, mode: str) -> dict:
    """Conditional premium range (predict.premium_range, D6 rule) for the session's premium inputs and the target's
    market-cap percentile; block per-share prices only when a market price exists (PC or user input).
    P7-C3b (config/p7c3b.yaml): public mode uses the as-of percentile, fixed (the typed price does not move it); the public
    deployment replays it (0.1 point) and the 36 premium-input results from the snapshot."""
    from src.market.provider import get
    from src.workbench.public_deploy import premium_range, premium_withheld, public_percentile

    if premium_withheld() or (public_deploy() and not _premium_on()):
        raise PublicDataUnavailable(PREMIUM_WITHHELD)
    if not public_deploy():
        need_db("경영권 프리미엄 표본")
    ver = version(s)
    pm = {**o.cfg["params"]["premium"], **(ver["overrides"].get("premium") or {})}
    mk = market(o, s, mode)
    mkt = o.cfg["target"]["market"]
    if mode == "public":
        k = ("prem", o.code, json.dumps(pm, sort_keys=True), "fixed")
    else:
        k = ("prem", o.code, json.dumps(pm, sort_keys=True), round(float(mk["mktcap_won"])))
    if k not in _CACHE:
        pct = public_percentile(o.code, AS_OF, mkt) if mode == "public" else get().mktcap_percentile(AS_OF, mkt, mk["mktcap_won"])
        prr = premium_range(pct["mktcap_pct"], market=mkt, public=mode == "public", **pm)  # P7-X2a n rule
        _CACHE[k] = {
            "pct": pct["mktcap_pct"],
            "pct_fixed": mode == "public",
            "method": prr.method,
            "reason": prr.reason,
            "q25": prr.q25,
            "q50": prr.q50,
            "q75": prr.q75,
            "n_neighbour": prr.neighbour.get("n"),
            "neighbour": dict(prr.neighbour),
            "band": dict(prr.band),
            "regression": dict(prr.regression),
            "cv_improvement": prr.cv_improvement_q50,
            "warnings": list(prr.warnings),
            **pm,
        }
    out = dict(_CACHE[k])
    base = mk.get("vwap")
    out["block"] = {q: base * (1 + out[q]) for q in ("q25", "q50", "q75")} if base else None
    out["vwap"] = base
    return out


def plan_check(o: Opened, s: dict, mode: str) -> dict:
    """Forecast revenue CAGR FY2026 → FY2030 of the current version (base scenario) and its band in the P5-B table
    (app/data/cagr_bands.csv; display only, same definition as the Excel 'PlanFcCAGR5')."""
    from src.valuation.company_dcf import forecast

    ver = version(s)
    ctx = o.ctx if mode == "pc" else public_ctx(o, s)
    with LOCK:
        R.recalc(o.cfg_path, ver["overrides"], ctx=ctx)
        f = forecast(ctx.c, ctx.h, 0.0, 0.0)
        w = ctx.c.w
        h1 = w.loc[(2026, "H1"), "revenue"] if (2026, "H1") in w.index and "revenue" in w.columns else float("nan")
    rev = f.set_index("label")["revenue"]
    r26 = float(h1) + float(rev.get("2H26", float("nan")))
    r30 = float(rev.get("2030", float("nan")))
    cagr = (r30 / r26) ** (1 / 4) - 1 if r26 > 0 and r30 > 0 else None
    bands = pd.read_csv(APP_DATA / "cagr_bands.csv")
    row = None
    if cagr is not None:
        lo = bands.cagr_lo.tolist()
        b = 4 if cagr >= lo[3] else 3 if cagr >= lo[2] else 2 if cagr >= lo[1] else 1
        row = bands[bands.band == b].iloc[0].to_dict()
        row["inside"] = bands.cagr_lo.min() <= cagr <= bands.cagr_hi.max()
    return {"cagr": cagr, "g0": result(o, s, mode).get("g0"), "band": row}


# ---------------------------------------------------------------- practice references (app/data aggregates, P5-B)


def practice() -> dict:
    """Quartiles of the external valuation opinions (all years, all deals) and 2023~ medians."""
    k = ("practice",)
    if k not in _CACHE:
        ar = pd.read_csv(APP_DATA / "assumptions_range.csv")
        y0, y1 = int(ar.year_from.min()), int(ar.year_to.max())
        full = ar[(ar.year_from == y0) & (ar.year_to == y1) & (ar.group == "전체")].set_index("metric")
        late = ar[(ar.year_from == 2023) & (ar.year_to == y1) & (ar.group == "전체")].set_index("metric")
        rt = pd.read_csv(APP_DATA / "rf_tenor.csv")
        rt = rt[rt.group == "전체"].groupby("tenor")["count"].sum()
        _CACHE[k] = {
            "years": (y0, y1),
            "full": {m: full.loc[m].to_dict() for m in full.index},
            "late": {m: late.loc[m].to_dict() for m in late.index},
            "rf10": int(rt.get("10년", 0)),
            "rf_marked": int(rt.get("10년", 0) + rt.get("5년", 0) + rt.get("기타", 0)),
        }
    return _CACHE[k]


def differs_from_practice(s: dict, r: dict, o: Opened) -> list[dict]:
    """Assumptions that differ from practice (not wrong - items whose reason goes into the report)."""
    p = practice()
    ov = version(s)["overrides"]
    led = o.ctx.base_led
    out = []
    tenor = int(ov.get("rf_tenor", led["risk_free"].get("tenor", 5)))
    if tenor != 10:
        out.append({"item": "Rf 만기", "ours": f"{tenor}년", "practice": f"10년({p['rf10']}/{p['rf_marked']}건)"})
    mrp = float(ov.get("mrp", led["mrp"]["value"]))
    if abs(mrp - p["late"]["mrp"]["median"]) > 0.0005:
        out.append({"item": "MRP", "ours": f"{mrp:.2%}", "practice": f"2023~ 중앙값 {p['late']['mrp']['median']:.2%}"})
    srp = float(ov.get("srp", led["decisions"]["srp_columns"][0]))
    if srp < p["full"]["srp"]["q1"]:
        out.append(
            {
                "item": "SRP",
                "ours": f"{srp:.2%}",
                "practice": f"중앙값 {p['full']['srp']['median']:.2%}(n={int(p['full']['srp']['n'])})",
            }
        )
    g = float(ov.get("g_terminal", o.ctx.base_cfg["forecast"]["human"]["g_terminal"]))
    if abs(g - p["full"]["g"]["median"]) > 0.0005:
        out.append({"item": "영구성장률", "ours": f"{g:.2%}", "practice": f"중앙값 {p['full']['g']['median']:.2%}"})
    w = r.get("wacc")
    if w is not None and not (p["full"]["wacc"]["q1"] <= w <= p["full"]["wacc"]["q3"]):
        out.append(
            {
                "item": "WACC",
                "ours": f"{w:.2%}",
                "practice": f"사분위 {p['full']['wacc']['q1']:.2%}~{p['full']['wacc']['q3']:.2%}",
            }
        )
    tv = r.get("tv_share")
    if tv is not None and not (p["full"]["tv_share"]["q1"] <= tv <= p["full"]["tv_share"]["q3"]):
        out.append(
            {
                "item": "영구가치 비중",
                "ours": f"{tv:.1%}",
                "practice": f"사분위 {p['full']['tv_share']['q1']:.1%}~{p['full']['tv_share']['q3']:.1%}",
            }
        )
    return out


# ---------------------------------------------------------------- assumptions (inputs)


def auto_value(o: Opened, s: dict, field: str):
    x = o.ctx
    return S._auto_value(field, x.base_cfg, x.base_led, s["versions"][0]["result"], x)


def current_value(o: Opened, s: dict, field: str):
    ov = version(s)["overrides"]
    return ov[field] if field in ov else auto_value(o, s, field)


def applicable(o: Opened, field: str) -> bool:
    """Path-specific fields shown only where they act."""
    if field == "sotp_discount":
        return o.sotp
    if field == "nci_mn":
        return not o.sotp
    return True


def set_value(s: dict, field: str, value, reason: str | None = None, judgement: str | None = None) -> dict:
    with LOCK:
        r = S.set_assumption(s, field, value, reason or None, judgement=judgement)
    return r


def resolve(s: dict, item: str, action: str, **kw) -> dict:
    with LOCK:
        return J.resolve(s, item, action, **kw)


def revert(s: dict, v: int, reason: str | None = None) -> dict:
    with LOCK:
        return S.revert(s, v, reason)


# ---------------------------------------------------------------- judgements, versions, audit


def judgement_rows(s: dict) -> list[dict]:
    out = []
    for jid, j in (s.get("judgements") or {}).items():
        aud = [a for a in s["audit"] if a.get("judgement") == jid and a.get("field")]
        out.append(
            {
                **j,
                "id": jid,
                "before": aud[0].get("per_share_before") if aud else None,
                "after": aud[-1].get("per_share_after") if aud else None,
                "changed_v": aud[-1]["v"] if aud else None,
            }
        )
    return out


def versions_table(o: Opened, s: dict, mode: str) -> list[dict]:
    rows = []
    for ver in s["versions"]:
        ch = [a for a in s["audit"] if a.get("v") == ver["v"] and a.get("field")]
        try:
            ps = result(o, s, mode, ver["v"]).get("per_share")
        except NeedInput:
            ps = None
        rows.append(
            {
                "v": ver["v"],
                "created": ver["created"].replace("T", " "),
                "per_share": ps,
                "change": ", ".join(f"{a['label']} {a['before_text']} → {a['after_text']}" for a in ch)
                or ("자동 초안" if ver["v"] == 0 else ""),
                "reverted_to": ver.get("reverted_to"),
            }
        )
    return rows


def compare(s: dict, a: int, b: int) -> list[dict]:
    va, vb = version(s, a)["overrides"], version(s, b)["overrides"]
    out = []
    for f in spec.NATIVE + spec.HOOK:
        if va.get(f) != vb.get(f):
            out.append(
                {
                    "field": spec.LABEL[f],
                    "a": spec.fmt(f, va[f]) if f in va else "자동값",
                    "b": spec.fmt(f, vb[f]) if f in vb else "자동값",
                }
            )
    return out


# ---------------------------------------------------------------- data screen


def rcepts(text: str) -> list[str]:
    return re.findall(r"(?<!\d)(\d{14})(?!\d)", str(text or ""))


def data_facts(o: Opened) -> dict:
    """KPI facts of the data screen (DART-derived; market values come from market())."""
    from src.valuation.company_dcf import ltm

    c = o.ctx.c
    facts = o.summ.get("facts") or (o.cfg.get("draft_meta") or {}).get("facts") or {}
    with LOCK:
        ltm_rev = ltm(c, "revenue")
    sh = o.cfg["shares"]
    rec = (o.summ.get("checks") or {}).get("S4_recon") or {}
    return {
        "fs_div": o.cfg["meta"]["fs_div"],
        "revenue_2025_eok": (facts.get("revenue_2025") or float("nan")) / 1e8,
        "ltm_rev_eok": ltm_rev,
        "ltm": o.cfg["meta"]["ltm"],
        "shares": sh,
        "common_out": c.market["common_out"],
        "pref_out": c.market["pref_out"],
        "shares_out": c.market["shares_out"],
        "shares_note": c.market.get("shares_note"),
        "kd": o.cfg.get("kd") or {},
        "recon": rec,
        "structure_source": facts.get("structure_source", ""),
        "bs_date": o.cfg["meta"]["bs_date"],
        "basis": o.cfg["meta"].get("basis", ""),
    }


def peer_rows(o: Opened, s: dict, mode: str) -> list[dict]:
    """Every draft peer with its inclusion; PC adds market cap, multiples and the beta regression values."""
    names = set(current_value(o, s, "peers") or [])
    bt = o.ctx.bt
    idx = o.cfg["beta"]["index"]
    out = []
    for p in o.ctx.base_cfg.get("peers", []):
        row = {
            "name": p["name"],
            "code": p["stock_code"],
            "tier": p["tier"],
            "include": p["name"] in names,
            "reason": p.get("reason", ""),
            "overview": p.get("overview", ""),
        }
        if mode == "pc" and o.p3 is not None:
            q = o.p3[o.p3.name == p["name"]]
            b = bt[(bt.name == p["name"]) & (bt["index"] == idx)] if len(bt) else bt
            if len(q):
                q = q.iloc[0]
                row.update(
                    {
                        "mktcap_eok": q.mktcap / 1e8 if pd.notna(q.mktcap) else None,
                        "ev_ebitda": q.ev_ebitda,
                        "ev_sales": q.ev_sales,
                        "per": q.per,
                        "pbr": q.pbr,
                    }
                )
            if len(b):
                row.update({"beta_raw": float(b.iloc[0].raw), "r2": float(b.iloc[0].r2)})
        out.append(row)
    return out


def beta_info(o: Opened, s: dict, mode: str) -> dict:
    r = result(o, s, mode)
    names = set(current_value(o, s, "peers") or [])
    bt = o.ctx.bt
    if bt is None:  # P7-C3 public deployment: R² median (2 decimals) of the draft peers
        same = names == set(o.ctx.peers_all())
        r2 = o.ctx.beta_pub["r2_median"] if same else None
        n = o.ctx.beta_pub["n"] if same else None
    else:
        sel = bt[bt.name.isin(names) & (bt["index"] == o.cfg["beta"]["index"])] if len(bt) else bt
        r2 = float(sel.r2.median()) if len(sel) else None
        n = int(len(sel))
        r2 = pubcut.r2(r2, n, mode == "public")  # P7-X2a: R² median of fewer than 5 peers not shown
    de_cut = False
    if mode == "public":  # P7-X2a: own D/E of fewer than 5 dates -> 0 in the public mode
        try:
            de_cut = bool(public_ctx(o, s).c.market.get("de_cut"))
        except (NeedInput, PublicDataUnavailable):
            de_cut = bool(o.ctx.c.market.get("de_cut"))
    return {
        "beta_u": r.get("beta_u"),
        "src": r.get("beta_src"),
        "de_cut": de_cut,
        "r2_median": r2,
        "n": n,
        "index": o.cfg["beta"]["index"],
        "warn": r2 is not None and r2 < 0.10,
        "de": r.get("de"),
        "kd": r.get("kd"),
    }


def bridge_info(o: Opened) -> dict:
    d = o.summ.get("diagnostics") or {}
    comp = d.get("composition") or {}
    sens = d.get("sensitivities") or {}
    items = [
        j for j in (o.summ.get("review_ranked") or {}).get("computed") or [] if str(j.get("category", "")).startswith("비영업")
    ]
    return {
        "composition": comp,
        "customer_funds": sens.get("customer_funds"),
        "nci": sens.get("nci"),
        "affiliate_loans": (o.cfg.get("excel") or {}).get("affiliate_loans"),
        "items": items,
    }


def history_info(o: Opened) -> dict:
    h = o.ctx.h
    v2 = o.ctx.base_v2 or {}
    return {
        "cagr": h["cagr"],
        "margin": h["margin"],
        "cogs_ratio": h["cogs_ratio"],
        "dso": h["dso"],
        "dio": h["dio"],
        "dpo": h["dpo"],
        "dna_ratio": h["dna_ratio"],
        "capex_ratio": h["capex_ratio"],
        "m0": v2.get("m0"),
        "m0_src": v2.get("m0_src"),
        "g0": v2.get("g0"),
        "own_cagr": v2.get("own_cagr"),
        "peer_margin": v2.get("peer_margin"),
        "peer_growth": v2.get("peer_growth"),
        "years": o.cfg["params"].get("avg_years"),
        "cagr_years": o.cfg["params"].get("cagr_years"),
    }


def corrections(o: Opened) -> dict:
    d = o.summ.get("diagnostics") or {}
    return {
        "debt_reclass": o.summ.get("debt_reclass") or [],
        "dna": d.get("dna") or [],
        "basis_fill": o.cfg["meta"].get("basis_fill") or [],
        "shares_note": o.ctx.c.market.get("shares_note"),
    }


# ---------------------------------------------------------------- status


def status(o: Opened, s: dict) -> dict:
    """Badge: 확정 (confirmed at the current version) / 보류 (auto hold) / 초안."""
    cur = version(s)["v"]
    conf = s.get("confirmed") or {}
    hl = o.summ.get("headline") or s.get("auto_headline") or {}
    hold = hl.get("status") == "자동 결과 보류"
    if conf.get("v") == cur:
        return {"label": "확정", "cls": "ok", "hold": hold, "headline": hl, "confirmed": conf}
    if hold:
        return {"label": "보류", "cls": "warn", "hold": True, "headline": hl, "confirmed": conf or None}
    return {"label": "초안", "cls": "", "hold": False, "headline": hl, "confirmed": conf or None}


# ---------------------------------------------------------------- P7-C3 polish: candidate previews


def candidate_preview(o: Opened, s: dict, mode: str, field: str, value) -> dict:
    """Per share now -> after this candidate (current version's assumptions + the candidate value), in the mode's context
    (public: the user's inputs). The same recalc the adoption runs, so the preview equals the value after adoption.
    Returns {'before', 'after'} or {'error'} (input needed / PC only / out of range)."""
    ver = version(s)
    ok, why, v = spec.check(field, value, o.ctx.peers_all())
    if not ok:
        return {"error": why}
    k = (
        "cand",
        str(S.workspace() or ""),
        s["session_id"],
        ver["v"],
        mode,
        ukey(s) if mode == "public" else "",
        field,
        json.dumps(v, sort_keys=True, default=str),
    )
    if k not in _CACHE:
        try:
            ctx = public_ctx(o, s) if mode == "public" else o.ctx
            with LOCK:
                r = R.recalc(o.cfg_path, {**ver["overrides"], field: v}, ctx=ctx)
            _CACHE[k] = {"before": result(o, s, mode).get("per_share"), "after": r.get("per_share"), "error": r.get("error")}
        except NeedInput:
            _CACHE[k] = {"error": "시세 입력 뒤 계산"}
        except PublicDataUnavailable as e:
            _CACHE[k] = {"error": str(e)}
    return _CACHE[k]


def keep_many(s: dict, ids: list[str], reason: str) -> int:
    """'그대로 유지' for several pending items at once; the audit gets one entry per item (P7-C3 polish long_list)."""
    n = 0
    with LOCK:
        for jid in ids:
            if (s.get("judgements") or {}).get(jid, {}).get("status") == "미처리":
                if J.resolve(s, jid, "keep", reason=reason)["ok"]:
                    n += 1
    return n
