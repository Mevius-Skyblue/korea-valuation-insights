"""Public deployment pieces of the screen (P7-C3, config/p7c3.yaml public_app).

    begin()            this browser session's workspace (random folder under <temp>/kvi/ws, created once per browser session),
                       removal of workspaces unused for 6 hours, the session hook used by src/workbench/session
    diag_requested() / diag()   hidden diagnostics: only with ?diag=<token of the bundle>; numbers only (memory, workspaces, jobs)
    moved(page, title) the P6 address (/rates, /accuracy) -> notice and link to the work screen's reference page
    calculator()       the P6 simple DCF calculator page with a link back
    session_files(c)   session file download / upload (select page)
    banner()           the notice on the first screen
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st

from src.workbench import session as S

WS_ROOT = Path(os.environ.get("KVI_WS_ROOT") or Path(tempfile.gettempdir()) / "kvi" / "ws")
DIAG_LOG = WS_ROOT.parent / "_diag" / "jobs.jsonl"
KEEP_HOURS = 6.0


def _hook():
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx() is None:               # not a screen thread (worker threads use their own context)
        return None
    return st.session_state.get("kvi_ws_path")


def cleanup(hours: float = KEEP_HOURS) -> int:
    """Remove workspaces whose last use is older than `hours` (a marker file is touched on every screen run)."""
    if not WS_ROOT.exists():
        return 0
    n, cut = 0, time.time() - hours * 3600
    for d in WS_ROOT.iterdir():
        try:
            last = (d / ".last").stat().st_mtime if (d / ".last").exists() else d.stat().st_mtime
            if d.is_dir() and last < cut:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            continue
    return n


def begin() -> Path:
    S.WORKSPACE_HOOK = _hook
    if "kvi_ws_path" not in st.session_state:
        cleanup()
        from app.wb import model as M
        if len(M._CACHE) > 3000:                  # a long-running server: small result caches, never unbounded
            M._CACHE.clear()
        d = WS_ROOT / secrets.token_hex(16)
        d.mkdir(parents=True, exist_ok=True)
        st.session_state["kvi_ws_path"] = str(d)
    d = Path(st.session_state["kvi_ws_path"])
    d.mkdir(parents=True, exist_ok=True)
    (d / ".last").touch()
    S.set_workspace(d)
    return d


# ---------------------------------------------------------------- hidden diagnostics (numbers only)

def diag_requested() -> bool:
    from src.workbench.public_deploy import bundle_info
    tok = bundle_info().get("diag_page")
    return bool(tok) and st.query_params.get("diag") == tok


def rss() -> dict:
    """Current / peak resident memory of this process (MB). Linux: /proc/self/status; else psutil when present."""
    out = {"rss_mb": None, "peak_mb": None}
    try:
        txt = Path("/proc/self/status").read_text()
        for ln in txt.splitlines():
            if ln.startswith("VmRSS:"):
                out["rss_mb"] = int(ln.split()[1]) / 1024
            elif ln.startswith("VmHWM:"):
                out["peak_mb"] = int(ln.split()[1]) / 1024
        return out
    except OSError:
        pass
    if os.name == "nt":                             # this PC (Windows): working set via the process API
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = wintypes.HANDLE            # 64-bit handles
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                out["rss_mb"] = pmc.WorkingSetSize / 2**20
                out["peak_mb"] = pmc.PeakWorkingSetSize / 2**20
        except Exception:                           # noqa: BLE001
            pass
    return out


def job_log(rec: dict) -> None:
    """Called by a confirmation job at its end (src/workbench/job.py): peak memory and seconds, numbers only."""
    try:
        DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DIAG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def diag() -> None:
    m = rss()
    ws = [d for d in WS_ROOT.iterdir() if d.is_dir()] if WS_ROOT.exists() else []
    jobs = []
    if DIAG_LOG.exists():
        for ln in DIAG_LOG.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                jobs.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    rows = {"app_rss_mb": m["rss_mb"], "app_peak_mb": m["peak_mb"], "workspaces": len(ws),
            "job_count": len(jobs), "job_peak_mb_max": max((j.get("peak_mb") or 0 for j in jobs), default=None),
            "job_peak_mb_last": jobs[-1].get("peak_mb") if jobs else None, "job_seconds_last": jobs[-1].get("seconds") if jobs else None,
            "cpu_count": os.cpu_count(), "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    st.code(json.dumps({"diag": rows, "jobs": jobs[-10:]}, ensure_ascii=False, indent=1), language="json")


# ---------------------------------------------------------------- moved pages, calculator, banner

def moved(page: str, title: str) -> None:
    st.markdown(f"### '{title}' 화면을 옮겼습니다")
    st.markdown(f"이 화면은 이제 워크벤치의 참고 페이지에 있습니다: [{title} 열기](/?p={page}&m=public). "
                "회사 평가는 [워크벤치 첫 화면](/?p=select&m=public)에서 시작합니다.")
    st.caption("가정 하의 추정 내재가치(예시)이며 투자 권유가 아닙니다. 출처: DART 전자공시·한국은행 ECOS·사용자 입력 시세.")


def calculator() -> None:
    import runpy
    st.markdown("[← 워크벤치로](/?p=select&m=public) · 회사 자료 없이 가정만으로 계산하는 간이 계산기입니다(같은 계산 엔진 함수).")
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "views" / "calculator.py"), run_name="__main__")


def banner() -> None:
    from app.wb import text as tx
    st.markdown(f"<div class='wb-band-top' role='note'>{tx.PUBLIC_NOTICE}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- session files

def session_files(c) -> None:
    from app.wb import model as M
    from app.wb import nav
    from src.workbench import sessionfile as SF
    rows = M.sessions()
    st.markdown("<p class='wb-kpi-note'>공개 배포의 세션은 이 브라우저 창에만 있고 새로 고치거나 6시간 지나면 지워집니다. "
                "이어서 작업하려면 세션 파일을 내려받아 두었다가 불러오세요(가정·판단 기록·시세 입력, 서명 포함).</p>", unsafe_allow_html=True)
    if rows:
        pick = st.selectbox("내려받을 세션", [r["sid"] for r in rows], key="sf_pick",
                            format_func=lambda x: next(f"{r['name']} ({r['code']}) #{r['sid'][-3:]} · v{r['version']}" for r in rows if r["sid"] == x))
        if pick:
            st.download_button("세션 파일 내려받기(.json)", SF.dump(M.load(pick)), file_name=f"kvi_session_{pick}.json",
                               mime="application/json", key=f"sf_dl_{pick}")
    up = st.file_uploader("세션 파일 불러오기", type=["json"], key="sf_up", help="KVI 세션 파일(.json)")
    if up is not None and st.session_state.get("sf_done") != up.file_id:
        try:
            with M.LOCK:
                s, notes = SF.load(up.getvalue())
            st.session_state["sf_done"] = up.file_id
            st.success(f"불러왔습니다: 새 세션 {s['session_id']}(버전 {len(s['versions']) - 1}개 다시 계산)")
            for n in notes:
                st.info(n)
            st.button("이 세션 열기", key="sf_open", on_click=nav.go, args=("data", s["session_id"], "public"), type="primary")
        except SF.SessionFileError as e:
            st.error(f"불러오지 못했습니다: {e}")
        except ValueError as e:
            st.error(f"불러오지 못했습니다: {e}")
