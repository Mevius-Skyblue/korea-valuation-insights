"""Public-mode market providers (config/p7c1.yaml public_mode). Same methods as DbMarketProvider (src/market/provider.py).

    UserInputProvider(user)            only what the user typed: close, market cap, 20-day VWAP of the target and the closes of
                                       listed subsidiaries / preferred shares. Every other KRX function raises
                                       PublicDataUnavailable (a public deployment has no KRX data at all).
    UserOverlayProvider(user, cfg)     the PC-side export of a confirmed session in public mode: the target's (and listed
                                       subsidiaries' / preferred shares') values on the as-of date come from the user, so every
                                       number shown that is a KRX raw value is the user's; aggregates the model needs (peer betas,
                                       peer market caps, the target's past market caps for D/E) are read from the DB and appear in
                                       the public outputs only as aggregates (median βu, quartile multiples, target D/E).

user = {"close": 원, "mktcap": 원 (default close × common shares outstanding), "vwap20": 원,
        "sub_close": {stock_code: 원}, "pref": {stock_code: {"close": 원, "listed": 주}}}
"""
from __future__ import annotations


class PublicDataUnavailable(RuntimeError):
    """A KRX-derived value was asked for in public mode without a user input."""


class UserInputProvider:
    name = "user"

    def __init__(self, user: dict, target: str, as_of: str):
        self.u, self.target, self.as_of = dict(user or {}), target, as_of

    def quote(self, code: str, date: str, con=None):
        if date != self.as_of:
            raise PublicDataUnavailable(f"{code} {date}: 공개 모드는 기준일 사용자 입력만")
        if code == self.target and self.u.get("close"):
            return (float(self.u["close"]), float(self.u["mktcap"]) if self.u.get("mktcap") else None, None)
        if code in (self.u.get("sub_close") or {}):
            return (float(self.u["sub_close"][code]), None, None)
        if code in (self.u.get("pref") or {}):
            p = self.u["pref"][code]
            return (float(p["close"]), None, int(p["listed"]) if p.get("listed") else None)
        raise PublicDataUnavailable(f"{code}: 사용자 입력 시세 없음")

    def mktcap_at(self, code: str, date: str, con=None):
        if code == self.target and date == self.as_of and self.u.get("mktcap"):
            return int(self.u["mktcap"])
        raise PublicDataUnavailable(f"{code} {date}: 시가총액 사용자 입력 없음")

    def vwap20(self, code: str, as_of: str, con=None) -> dict:
        if code == self.target and self.u.get("vwap20"):
            return {"vwap": float(self.u["vwap20"]), "start": None, "end": as_of, "n": None, "events": [], "source": "사용자 입력"}
        raise PublicDataUnavailable(f"{code}: VWAP 사용자 입력 없음")

    def mktcap_percentile(self, *a, **k):
        raise PublicDataUnavailable("시총 백분위: 공개 모드에서 계산하지 않음")

    def beta_table(self, *a, **k):
        raise PublicDataUnavailable("베타 회귀: 공개 모드에서 계산하지 않음(βu는 입력)")

    def price_days(self, *a, **k):
        raise PublicDataUnavailable("시세 일수: 공개 모드에서 쓰지 않음")

    def universe(self, *a, **k):
        raise PublicDataUnavailable("상장사 목록: 공개 모드에서 쓰지 않음")


class UserOverlayProvider:
    """DB provider with the target / listed subsidiaries / preferred shares replaced by user values on the as-of date."""
    name = "user_overlay"

    def __init__(self, user: dict, cfg: dict):
        from src.market.provider import DbMarketProvider
        self.base = DbMarketProvider()
        self.u = dict(user or {})
        self.target = cfg["target"]["stock_code"]
        self.as_of = cfg["meta"]["as_of"]
        sh = cfg.get("shares") or {}
        self.common_out = (sh.get("common_issued") or 0) - (sh.get("common_treasury") or 0)
        self.subs = {x["stock_code"] for x in (cfg.get("structure") or {}).get("subsidiaries") or []
                     if x.get("listed") and x.get("direct") and x.get("stock_code")}
        self.prefs = set(sh.get("listed_pref_codes") or [])
        if not self.u.get("close"):
            raise PublicDataUnavailable("공개 모드 내보내기: 대상 종가(사용자 입력)가 필요하다")
        if not self.u.get("vwap20"):         # block per-share prices are shown only from a user price input
            raise PublicDataUnavailable("공개 모드 내보내기: 대상 20일 VWAP(사용자 입력)가 필요하다(블록 1주당 가격)")
        miss = sorted(self.subs - set(self.u.get("sub_close") or {}))
        if miss:
            raise PublicDataUnavailable(f"공개 모드 내보내기: 상장 종속회사 종가 입력 필요 {miss}")
        missp = sorted(self.prefs - set(self.u.get("pref") or {}))
        if missp:
            raise PublicDataUnavailable(f"공개 모드 내보내기: 상장 우선주 종가·상장주식수 입력 필요 {missp}")

    def _mc(self) -> float:
        return float(self.u["mktcap"]) if self.u.get("mktcap") else float(self.u["close"]) * self.common_out

    def quote(self, code: str, date: str, con=None):
        if date == self.as_of:
            if code == self.target:
                return (float(self.u["close"]), self._mc(), None)        # listed shares: DART counts are used (not KRX)
            if code in self.subs:
                return (float(self.u["sub_close"][code]), None, None)
            if code in self.prefs:
                p = self.u["pref"][code]
                return (float(p["close"]), None, int(p["listed"]))
        return self.base.quote(code, date, con=con)

    def mktcap_at(self, code: str, date: str, con=None):
        if code == self.target and date == self.as_of:
            return int(self._mc())
        return self.base.mktcap_at(code, date, con=con)

    def vwap20(self, code: str, as_of: str, con=None) -> dict:
        if code == self.target:
            return {"vwap": float(self.u["vwap20"]), "start": None, "end": as_of, "n": None, "events": [], "source": "사용자 입력"}
        return self.base.vwap20(code, as_of, con=con)

    def mktcap_percentile(self, as_of: str, market: str, mktcap: float, con=None) -> dict:
        """P7-C3b (config/p7c3b.yaml percentile): public mode uses the target's as-of KRX percentile, fixed - the typed
        price does not move it (same as the public deployment, which holds it rounded to 0.1)."""
        from src.workbench.public_deploy import public_percentile
        return public_percentile(self.target, as_of, market, con=con)

    def beta_table(self, as_of: str, cfg_path: str, table: str):
        return self.base.beta_table(as_of, cfg_path, table)

    def price_days(self, codes, as_of: str, con=None):
        return self.base.price_days(codes, as_of, con=con)

    def universe(self, as_of: str, markets, con=None):
        return self.base.universe(as_of, markets, con=con)
