"""One command from a stock code (or a config) to the report draft (P7-B):

    python -m src.pipeline.run <stock_code | config.yaml> [--pdf]   -> outputs/pipeline/<code>/summary.json + xlsx + docx

Flow (run_pipeline, importable for the P7-C web screen):
    stock code      -> src/pipeline/draft.make_draft (config/drafts/valuation_<code>.yaml) -> gate A (G1~G6)
    draft / config  -> gate B (G7 data, G8 usable peers: beta and EV/EBITDA) -> company_dcf C2 and C3 (beta / peer tables)
                    -> Excel model + verification against the engine (src/excel/verify.run)
                    -> report draft + report checks (src/report/check) -> reconciliation check (fs_recon)
    RF config (excel.forecast_type scenario_capex) keeps its own engine path: Excel + verification + report only.
Market values come from the market provider (src/market/provider.py); this module never calls KRX or ECOS.
Success criteria S1~S5 are the pre-registered ones (config/p7b.yaml success).
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np

from src import yamlio
from src.collect.core import ROOT
from src.workbench.snapdata import seam

OUT = ROOT / "outputs" / "pipeline"
REQUIRED_CATEGORIES = [
    "우선주 처리",
    "피어 유사성",
    "Kd 근거",
    "기준일 뒤 주요 공시",
    "비경상 손익",
    "시나리오 폭",
    "보고서 사람 작성 칸",
]


def call_counts() -> dict:
    """Rows per API in logs/api_calls.csv. A run's calls = counts at the end − counts at the start (the log has
    second resolution, so a time filter would double-count runs that start within the same second)."""
    from collections import Counter

    from src.collect.core import CallLog

    return dict(Counter(r["api"] for r in CallLog().rows()))


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k) if not isinstance(k, str) else k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(float(x)) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, Path):
        return x.relative_to(ROOT).as_posix() if x.is_relative_to(ROOT) else str(x)
    return x


# ---------------------------------------------------------------- checks


def excel_check(res: dict) -> dict:
    """S2: verify.run result -> pass/fail with the pre-registered tolerance (verify.TOL)."""
    from src.excel.verify import TOL, missing

    bad = [f"{r['scenario']} SRP {r['srp']:.0%}" for r in res["combos"] if not r["ok"]]
    bad += [f"Rf10 {r['scenario']} SRP {r['srp']:.0%}" for r in res.get("rf10") or [] if not r["ok"]]
    bad += [f"G {r['tenor']}y SRP {r['srp']:.4f}" for r in res.get("g") or [] if not r["ok"]]
    other_bad = []
    for lab, xl, en in res["other"]:
        if missing(xl) and missing(en):
            continue
        tol = TOL["per_share"] if ("주당" in lab or "백만원" in lab) else TOL["wacc"]
        try:
            if abs(float(xl) - float(en)) > tol:
                other_bad.append(f"{lab}: {xl} vs {en}")
        except (TypeError, ValueError):
            other_bad.append(f"{lab}: {xl} vs {en}")
    sc = res["scan"]
    max_diff = max((r["per_share_diff"] for r in res["combos"]), default=float("nan"))
    ok = (
        not bad
        and not other_bad
        and not res["errors"]
        and res["master"] == "OK"
        and not sc["hardcoded"]
        and not sc["krx_outside_inputs"]
    )
    return {
        "pass": bool(ok),
        "master": res["master"],
        "combos": len(res["combos"]),
        "bad_combos": bad,
        "other_bad": other_bad,
        "max_per_share_diff": max_diff,
        "formula_errors": len(res["errors"]),
        "hardcoded": len(sc["hardcoded"]),
        "krx_outside_inputs": len(sc["krx_outside_inputs"]),
        "verdict_live_vs_engine": list(res["verdict"]),
        "checks_warn": [lab for lab, kind, st in res["checks"] if st == "WARN"],
    }


def report_check(docx: Path, reg, xlsx: Path) -> dict:
    """S3: numbers traced to Excel cells, no forbidden wording, particles, empty human boxes, header on every page."""
    from src.report import check

    nm = check.numbers(docx, reg, xlsx)
    fb, jo, hb, hd = check.forbidden(docx), check.josa_errors(docx), check.human_boxes(docx), check.header_on_all_pages(docx)
    ok = not nm["bad_values"] and not nm["stray_tokens"] and not fb and not jo and not hb["not_empty"] and hd
    return {
        "pass": bool(ok),
        "n_excel_numbers": nm["n_excel"],
        "bad_values": nm["bad_values"][:20],
        "stray_tokens": nm["stray_tokens"][:20],
        "forbidden": fb,
        "josa_errors": jo,
        "human_boxes": hb["n"],
        "human_boxes_not_empty": hb["not_empty"],
        "header_all_pages": hd,
    }


@seam("recon_check", key=lambda corp, fs_div, years=range(2021, 2026): (corp, fs_div, list(years)))
def recon_check(corp: str, fs_div: str, years=range(2021, 2026)) -> dict:
    """S4: fs_recon of the target (report text vs API): no mismatch / sign rows and found share >= 80%."""
    from src.db.build import DB_PATH

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        d = con.execute(
            f"""SELECT fiscal_year, item, result FROM fs_recon WHERE corp_code=? AND fs_div=?
                            AND fiscal_year BETWEEN {min(years)} AND {max(years)}""",
            [corp, fs_div],
        ).df()
    finally:
        con.close()
    cnt = d.result.value_counts().to_dict() if len(d) else {}
    found = len(d) - cnt.get("not_found", 0)
    share = found / len(d) if len(d) else 0.0
    bad = d[d.result.isin(["mismatch", "sign"])]
    ok = len(d) > 0 and bad.empty and share >= 0.8
    return {
        "pass": bool(ok),
        "rows": len(d),
        "counts": cnt,
        "found_share": share,
        "bad": [f"FY{r.fiscal_year} {r.item} {r.result}" for r in bad.itertuples()],
        "years": [int(y) for y in sorted(d.fiscal_year.unique())] if len(d) else [],
    }


def human_check(cfg: dict) -> dict:
    """S5: the draft's human-review list covers the pre-registered categories."""
    hr = cfg.get("human_review") or []
    cats = {x["category"] for x in hr}
    missing = [c for c in REQUIRED_CATEGORIES if c not in cats]
    return {
        "pass": not missing and bool(hr),
        "n": len(hr),
        "missing_categories": missing,
        "by_category": {c: sum(x["category"] == c for x in hr) for c in dict.fromkeys(x["category"] for x in hr)},
    }


# ---------------------------------------------------------------- gate B


def gate_b(cfg_path: str, cfg: dict) -> tuple[object, dict]:
    """G7 (statements) + G8 (usable peers) after the beta and peer tables are built (the same tables company_dcf uses)."""
    from src.db.build import DB_PATH
    from src.market.provider import get
    from src.pipeline.draft import required_fs
    from src.pipeline.draft_common import load_rules
    from src.pipeline.gate import stage_b
    from src.valuation.peer_p3 import build as build_peers

    rules = load_rules()
    name = Path(cfg_path).stem.replace("valuation_", "")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        fs_ok, miss, _ = required_fs(
            con, cfg["target"]["corp_code"], cfg["meta"].get("fs_div", "CFS"), cfg["meta"].get("basis_fill")
        )
    finally:
        con.close()
    y, p = int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"]
    bt = get().beta_table(cfg["meta"]["as_of"], cfg_path, f"beta_{name}")
    pp = build_peers(
        cfg_path,
        f"peer_{name}_c3",
        cfg["meta"]["as_of"],
        {**cfg["params"]["ebitda_rule"], "ltm_year": y, "ltm_period": p, "supplement": True, "fill": "draft_meta" in cfg},
    )
    tiers = cfg["beta"]["peer_tiers"]
    b = bt[(bt.spec == cfg["beta"]["spec"]) & (bt["index"] == cfg["beta"]["index"]) & bt.tier.isin(tiers) & bt.bu_avg.notna()]
    usable = sorted(set(b.name) & set(pp[pp.tier.isin(tiers) & pp.ev_ebitda.notna()].name))
    g = stage_b(
        {"fs_ok": fs_ok, "fs_missing": miss, "usable_peers": len(usable)}, rules["gate"]["stage_b"], relax="draft_meta" in cfg
    )  # P7-B5: auto drafts go on with < 3 peers (N/M + judgement)
    return g, {"usable_peers": usable, "fs_missing": miss}


# ---------------------------------------------------------------- run


def run_pipeline(
    target: str,
    pdf: bool = False,
    out_root: Path = OUT,
    regress_tag: str | None = None,
    fast: bool = False,
    on_excel=None,
    on_step=None,
) -> dict:
    """target: stock code (a draft is made) or a config path. Returns the summary (also written to summary.json).

    P7-B5 (config/p7b5.yaml exception_policy, speed): every stage is wrapped - an exception is recorded as that stage's
    failure (summary.steps / errors) and never escapes; stages that need its result are skipped with the reason.
    The first draft (engine numbers, signals, ranked judgements) is written to summary.json before the Excel model,
    the Excel <-> engine reconciliation and the report (summary.reconcile.status: 대조 대기 -> 일치 / 불일치).
    fast: stop after the first draft (engine-only robustness runs).
    on_excel(path, seconds): called as soon as the Excel model (with cached values) is written, before the reconciliation
    (P7-C1 confirm: the reconciliation and the report go on in the background).
    on_step(name, state, seconds): progress of each stage for the work screen (P7-C2), state 'start' / 'ok' / 'fail'.
    Display only - errors inside the callback are ignored."""
    t_start = datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    steps, errors, timing = {}, [], {}
    summary: dict = {
        "target": target,
        "started": t_start,
        "steps": steps,
        "errors": errors,
        "timing": timing,
        "_calls0": call_counts(),
        "fast": fast,
    }
    FAIL = object()

    def note(name, state, secs):
        if on_step:
            try:
                on_step(name, state, secs)
            except Exception:  # noqa: BLE001 - a progress display never stops the run
                pass

    def step(name, fn):
        t = time.time()
        note(name, "start", 0.0)
        try:
            out = fn()
            steps[name] = {"ok": True, "sec": round(time.time() - t, 1)}
            note(name, "ok", round(time.time() - t, 1))
            return out
        except Exception as e:  # noqa: BLE001 - recorded (P7-B5 exception policy); never re-raised
            from src.collect.core import StopCollection

            steps[name] = {"ok": False, "sec": round(time.time() - t, 1), "error": f"{type(e).__name__}: {e}"}
            errors.append(
                {
                    "step": name,
                    "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-3000:],
                    "budget_stop": isinstance(e, StopCollection),
                }
            )
            note(name, "fail", round(time.time() - t, 1))
            return FAIL
        finally:
            timing[name] = round(time.time() - t, 2)

    def failed(result: str, out_dir) -> dict:
        summary["result"] = result
        return _finish(summary, out_dir, t0, t_start)

    out = out_root / str(regress_tag or target).replace("/", "_")
    if target.endswith(".yaml"):
        cfg_path = target
        cfg = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
        mode = (
            "legacy_rf"
            if cfg.get("excel", {}).get("forecast_type") == "scenario_capex"
            else ("draft" if "draft_meta" in cfg else "handwritten")
        )
        code = (cfg["meta"]["target"] if mode == "legacy_rf" else cfg["target"])["stock_code"]
    else:
        from src.pipeline.draft import make_draft

        code, mode = target, "draft"
        dr = step(
            "draft", lambda: make_draft(code, on_part=lambda k, s: note(f"draft.{k}", "ok", s)) if on_step else make_draft(code)
        )
        if dr is FAIL:
            budget = any(e.get("budget_stop") for e in errors)
            return failed("API 예산 정지" if budget else "단계 실패", out_root / code)
        cfg_path = dr["path"].relative_to(ROOT).as_posix()
        cfg = dr["cfg"]
        timing["draft_parts"] = dr.get("timing") or {}
    out = out_root / (regress_tag or code)
    out.mkdir(parents=True, exist_ok=True)
    summary.update({"code": code, "mode": mode, "config": cfg_path, "out_dir": out})
    if mode == "legacy_rf":
        summary["gate"] = {"passed": True, "note": "RF 전용 경로(scenario_capex): 게이트·초안 없음"}
    else:
        summary["name"] = cfg["target"]["name"]
        if mode == "draft":
            ga = cfg["draft_meta"]["gate_a"]
            summary["gate"] = {
                "passed": ga["passed"],
                "stage_a": ga["reasons"],
                "notes": ga.get("notes") or [],
                "stage_a_p7b": (cfg["draft_meta"].get("gate_a_p7b") or {}).get("reasons"),
            }
            summary["facts"] = cfg["draft_meta"].get("facts")
            summary["peer_screen"] = {k: (cfg.get("peer_screen") or {}).get(k) for k in ("relax_step", "levels")}
            if not ga["passed"]:
                return failed("자동 평가 부적합", out)
            if (cfg.get("workbench") or {}).get("draft_config"):  # P7-C1 confirmed session: draft tables, filtered
                from src.workbench.snapdata import replaying

                # P7-C3 public snapshot: no DB tables (the recorded aggregates of the draft's peers are used)
                if not replaying() and step("session_tables", lambda: session_tables(cfg_path, cfg)) is FAIL:
                    return failed("단계 실패", out)
                summary["gate"].update(
                    {
                        "passed": True,
                        "stage_b": [],
                        "usable_peers": [p["name"] for p in cfg.get("peers", [])],
                        "note": "평가 세션 확정: 자동 초안의 게이트 B 통과 기록 사용(베타·피어 표 = 초안 표를 확정 피어로 거른 것)",
                    }
                )
            else:
                gb = step("gate_b", lambda: gate_b(cfg_path, cfg))
                if gb is FAIL:
                    return failed("단계 실패", out)
                gb, info = gb
                summary["gate"].update({"passed": gb.passed, "stage_b": gb.reasons, "usable_peers": info["usable_peers"]})
                summary["gate"]["notes"] = (summary["gate"].get("notes") or []) + gb.notes
                if not gb.passed:
                    return failed("자동 평가 부적합", out)
                # drafts: company_dcf.main's interim tables / figures have no consumer -> only the C2 peer table it built
                if step("valuation", lambda: _peer_c2(cfg_path, cfg)) is FAIL:
                    return failed("단계 실패", out)
        else:
            summary["gate"] = {"passed": True, "note": "수기 설정(게이트 생략)"}
            from src.valuation.company_report import main as cdcf

            for v in ("c2", "c3"):
                if step(f"valuation_{v}", lambda v=v: cdcf(cfg_path, v, fig_dir=out)) is FAIL:
                    return failed("단계 실패", out)
    from src.excel.model_data import load_model_data

    d = step("engine", lambda: load_model_data(cfg_path))
    if d is FAIL:
        return failed("단계 실패", out)
    # ---- first draft: engine numbers + signals + ranked judgements, before the Excel model
    if step("first_draft", lambda: _first_draft(summary, d, cfg, mode)) is FAIL:
        return failed("단계 실패", out)
    summary["reconcile"] = {"status": "대조 대기"}
    summary["first_draft_seconds"] = round(time.time() - t0, 1)
    _write(summary, out)
    if fast:
        return failed("초안 완료(엔진)", out)
    from src.excel.verify import run as verify_run

    xlsx = out / f"{code}_model_{(cfg['meta']['as_of'])}.xlsx"

    def built(p, secs):  # P7-C1: the model exists -> status '대조 진행 중' (summary written)
        summary["outputs"] = {"xlsx": p, "docx": None}
        summary["reconcile"] = {"status": "대조 진행 중"}
        summary["excel_ready_seconds"] = round(time.time() - t0, 1)
        _write(summary, out)
        if on_excel:
            on_excel(p, summary["excel_ready_seconds"])

    res = step("excel", lambda: verify_run(cfg_path, path=xlsx, d=d, on_built=built))
    if res is FAIL:
        summary["reconcile"] = {"status": "대조 실패(엑셀 단계 오류)"}
        return failed("단계 실패", out)
    timing.update({f"excel_{k}": v for k, v in (res.get("timing") or {}).items()})
    xlsx = res["path"]
    s2 = excel_check(res)
    summary["checks"]["S2_excel_engine"] = s2
    summary["reconcile"] = {"status": "일치" if s2["pass"] else "불일치", "max_per_share_diff": s2["max_per_share_diff"]}
    res = None  # P7-C4 C4-F6: the parsed formulas model is not needed for the report -
    import gc  # free it (it holds reference cycles) so the report reuses that memory

    gc.collect()
    from src.report.build import build_report, to_pdf

    rep = step("report", lambda: build_report(cfg_path, xlsx=xlsx, out=out / f"{code}_report_draft.docx", fig_dir=out))
    if rep is FAIL:
        return failed("단계 실패", out)
    docx, reg, _ = rep
    s3 = step("report_check", lambda: report_check(docx, reg, xlsx))
    summary["checks"]["S3_report"] = s3 if s3 is not FAIL else {"pass": False, "error": "report_check 단계 실패"}
    if pdf:
        p = step("pdf", lambda: to_pdf(docx))
        summary["pdf"] = None if p is FAIL else p
    summary["outputs"] = {"xlsx": xlsx, "docx": docx}
    summary["result"] = "완료" if not errors else "단계 실패"
    return _finish(summary, out, t0, t_start)


def session_tables(cfg_path: str, cfg: dict) -> None:
    """P7-C1: the beta / peer (C3, C2) tables of a confirmed session = the auto draft's tables restricted to the session's
    peers (and the target rows). Each peer row depends only on that peer, so this equals rebuilding them (checked in
    tests/test_p7c1.py) without the 8-10 s of regressions and peer statements."""
    from src.db.build import DB_PATH

    name = Path(cfg_path).stem.replace("valuation_", "")
    base = Path(cfg["workbench"]["draft_config"]).stem.replace("valuation_", "")
    names = [p["name"] for p in cfg.get("peers", [])]
    con = duckdb.connect(str(DB_PATH))
    try:
        for t in ("beta_{}", "peer_{}_c3", "peer_{}"):
            con.execute(
                f'CREATE OR REPLACE TABLE "{t.format(name)}" AS SELECT * FROM "{t.format(base)}" '
                "WHERE tier = 'target' OR list_contains(?::VARCHAR[], name)",
                [names],
            )
    finally:
        con.close()


def _peer_c2(cfg_path: str, cfg: dict) -> None:
    """The C2 peer table (peer_<name>, D&A without the supplement) the engine reads (company_dcf.main c2 builds the same)."""
    from src.valuation.peer_p3 import build as build_peers

    name = Path(cfg_path).stem.replace("valuation_", "")
    y, p = int(cfg["meta"]["ltm"]["year"]), cfg["meta"]["ltm"]["period"]
    build_peers(
        cfg_path,
        f"peer_{name}",
        cfg["meta"]["as_of"],
        {**cfg["params"]["ebitda_rule"], "ltm_year": y, "ltm_period": p, "supplement": False, "fill": "draft_meta" in cfg},
    )


def _first_draft(summary: dict, d: dict, cfg: dict, mode: str) -> None:
    """Fill the summary from the engine reference values (no Excel needed)."""
    e = d["engine"]
    summary["values"] = key_values(d)
    corp = (cfg["meta"]["target"] if mode == "legacy_rf" else cfg["target"])["corp_code"]
    fsd = "OFS" if mode == "legacy_rf" else cfg["meta"].get("fs_div", "CFS")
    summary["checks"] = {
        "S4_recon": recon_check(corp, fsd, range(2021, 2026) if mode != "legacy_rf" else range(2019, 2026)),
        "S5_human_list": human_check(cfg) if mode == "draft" else {"pass": None, "note": "수기 설정: 해당 없음"},
    }
    summary["human_review"] = cfg.get("human_review") or []
    dg = e.get("diagnostics") or {}  # P7-B2: same content and order as Excel Diagnostics / report
    summary["diagnostics"] = {
        k: dg.get(k)
        for k in ("signals", "reverse", "composition", "composition_share", "anomalies", "margin_candidates", "sensitivities")
    }
    summary["review_ranked"] = e.get("review_ranked")
    summary["review_share"] = (e.get("review_ranked") or {}).get("share_top5")
    gd = dg.get("guard") or {"hold": False, "status": "표시", "reasons": []}
    top = ((e.get("review_ranked") or {}).get("computed") or [None])[0]
    summary["headline"] = (
        {
            "status": gd["status"],
            "per_share": None,
            "reasons": [x["text"] for x in gd["reasons"]],
            "top_judgement": None if top is None else {k: top.get(k) for k in ("category", "item", "alternative", "impact")},
        }
        if gd["hold"]
        else {"status": "표시", "per_share": summary["values"]["per_share_base_srp0"], "reasons": []}
    )
    for k in ("v1", "v2", "guard", "dna", "sotp", "turnaround", "loss", "ltm_margin"):
        summary["diagnostics"][k] = dg.get(k)
    summary["debt_reclass"] = (cfg.get("bridge") or {}).get("debt_reclass") or []
    summary["beta_src"] = e.get("beta_src")
    lo = dg.get("loss")
    if lo:  # P7-B3b loss path: (a) EV/Sales range + (b) transition DCF together
        ev = lo["ev_sales"]
        dcf_ok = not gd["hold"]
        summary["headline"] = {
            "status": "적자 경로" if (ev["valid"] or dcf_ok) else "자동 결과 보류",
            "fixed_text": lo["fixed_text"],
            "range": [ev["q25"], ev["q75"]] if ev["valid"] else None,
            "range_invalid": ev["invalid"],
            "per_share": summary["values"]["per_share_base_srp0"] if dcf_ok else None,
            "dcf_hold_reasons": [x["text"] for x in gd["reasons"]] if not dcf_ok else [],
            "funding_need": lo["funding"]["need"],
            "top_judgement": None if top is None else {k: top.get(k) for k in ("category", "item", "alternative", "impact")},
        }
    wb = cfg.get("workbench")
    if wb:  # P7-C1 confirmed session: the confirmed value is the headline (auto hold kept as record)
        summary["workbench"] = {
            k: wb.get(k) for k in ("session_id", "version", "mode", "pending", "auto_status", "auto_hold_reasons")
        }
        summary["headline"] = {
            "status": "확정",
            "per_share": summary["values"]["per_share_base_srp0"],
            "auto_status": wb.get("auto_status"),
            "auto_hold_reasons": wb.get("auto_hold_reasons") or [],
            "guard_now": [x["text"] for x in gd["reasons"]],
            "changes": len(wb.get("changes") or []),
        }
    if "convergence" in e:
        summary["convergence"] = {
            "verdict": e["convergence"]["c3"]["verdict"],
            "dcf": e["convergence"]["c3"]["per_share"],
            "q25": e["convergence"]["n10"]["q25"],
            "q75": e["convergence"]["n10"]["q75"],
        }


def key_values(d: dict) -> dict:
    """The headline numbers of a model data dict for summary.json (per share, WACC, grid, multiples)."""
    if "ctx" in d:  # backwards compatible: a verify.run result
        d = d["ctx"].d
    e = d["engine"]
    labels = d["excel"]["scenarios"]
    srps = d["rates"]["srp_list"]
    grid = {f"{k}|SRP{s:.0%}": e["grid"][(k, s)]["per_share"] for k in labels for s in srps}
    base = e["grid"][("base", srps[0])]
    out = {
        "per_share_base_srp0": base["per_share"],
        "wacc_base_srp0": base["wacc"],
        "ronic": base["ronic"],
        "tv_share": base["tv_share"],
        "ev930_mn": base["ev930"],
        "close": e.get("price"),
        "grid": grid,
        "beta_u": e.get("beta_u"),
        "kd": e.get("kd"),
        "de_own": e.get("de_own"),
        "block": e.get("block"),
        "premium_method": e.get("premium_method"),
    }
    if "multiples" in e:
        out["relative_median_ps"] = {k: v["ps_median"] for k, v in e["multiples"].items()}
        out["relative_n"] = {k: v["n"] for k, v in e["multiples"].items()}
    return out


def _write(summary: dict, out: Path) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    s = {k: v for k, v in summary.items() if k != "_calls0"}
    (out / "summary.json").write_text(json.dumps(_jsonable(s), ensure_ascii=False, indent=1), encoding="utf-8")


def _finish(summary: dict, out: Path, t0: float, t_start: str) -> dict:
    summary["seconds"] = round(time.time() - t0, 1)
    c0, c1 = summary.pop("_calls0", {}), call_counts()
    summary["api_calls"] = {k: c1.get(k, 0) - c0.get(k, 0) for k in ("DART", "KRX", "ECOS")}
    ch = summary.get("checks") or {}
    if summary.get("result") == "완료" or (ch and not summary.get("fast")):
        s1 = summary.get("result") == "완료" and not summary["errors"]
        ch["S1_end_to_end"] = {"pass": s1}
        summary["checks"] = ch
        need = ["S1_end_to_end", "S2_excel_engine", "S3_report", "S4_recon"] + (
            ["S5_human_list"] if summary.get("mode") == "draft" else []
        )
        summary["success"] = all((ch.get(k) or {}).get("pass") for k in need)
    _write(summary, out)
    return summary


if __name__ == "__main__":
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else None  # e.g. --tag jw_regression
    s = run_pipeline(sys.argv[1], pdf="--pdf" in sys.argv, regress_tag=tag, fast="--fast" in sys.argv)
    ch = s.get("checks") or {}
    print(
        s.get("code"),
        s.get("result"),
        "gate:",
        (s.get("gate") or {}).get("passed"),
        {k: v.get("pass") for k, v in ch.items()},
        "success:",
        s.get("success"),
        f"{s['seconds']}s",
        s["api_calls"],
    )
    for e in s["errors"]:
        print("ERROR", e["step"], e["error"])
