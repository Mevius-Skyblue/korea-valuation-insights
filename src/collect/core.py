"""Public stand-in for the private repository's collector core (P7-C3 public bundle).

The public app reads no API and no raw file: only the path of the project, the call log (empty) and the error types the
engine code names. The private repository's core (collectors, raw store, call budget) is not part of the public bundle.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class StopCollection(RuntimeError):
    """Collector budget stop (never raised in the public app)."""


class CallLog:
    """API call log: empty in the public app (no API is called)."""

    def __init__(self, root: Path = ROOT):
        self.path = None

    def rows(self) -> list[dict]:
        return []

    def append(self, row: dict) -> None:
        raise RuntimeError("공개 앱은 API를 호출하지 않음")


class RawStore:
    """Raw filings: not in the public app (the public snapshot replays the values read from them)."""

    def __init__(self, *a, **k):
        from src.market.user_provider import PublicDataUnavailable
        raise PublicDataUnavailable("공시 원문 파일: 공개 배포에 없음(PC 모드에서만)")
