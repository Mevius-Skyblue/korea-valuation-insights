"""Valuation report draft (Word) for one company, filled only from the generated Excel model (cached values).

Run:  python -m src.report.build config/valuation_rf.yaml     -> outputs/report/<name>_report_draft.docx (git-ignored)
      (run python -m src.excel.build <config> first; the report reads that .xlsx)

One template (this module, sections 1~9) + company data (the .xlsx and the company config):
    1 평가 개요  2 대상 회사 개요(공시 기반 사실)  3 평가방법과 선택 근거(선택 근거 = 사람 작성 칸)  4 주요 가정과 출처
    5 결과  6 민감도  7 주요 가정의 합리성(사람 작성 칸)  8 평가상 한계(자동 + 사람 보완 칸)  9 부록
Every number goes through Reg.num(value, fmt, excel address) or Reg.lit(text) so a test can check that each number
in the document is an Excel cell value (formatted the same way) or a registered literal (dates, codes, headings).
Header on every page; no investment-judgement wording (FORBIDDEN, tested).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from src import yamlio
from src.collect.core import ROOT
from src.report.josa import J
from src.report.xlsx import Model

HEADER = "자동 생성 초안 — 주식가치 산정 결과(기계적 가치산정), 전문가 판단 전, 투자 권유 아님"
HUMAN = "[사람 작성 칸]"
FORBIDDEN = ["매수", "매도", "목표주가", "저평가", "고평가", "상승 여력", "상승여력", "투자의견", "추천", "목표 주가"]
TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")
PREREG = ["1386d1d", "19b03c4", "370efdb", "bf5211c", "7e14f06"]


def fmtv(v, fmt: str) -> str:
    """The one formatting function (report and test)."""
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    if isinstance(v, str):
        return v
    return {
        "won": f"{v:,.0f}원",
        "num0": f"{v:,.0f}",
        "mn": f"{v:,.0f}",
        "pct1": f"{v * 100:.1f}%",
        "pct2": f"{v * 100:.2f}%",
        "pct3": f"{v * 100:.3f}%",
        "x": f"{v:.2f}배",
        "x2": f"{v:.2f}",
        "beta": f"{v:.3f}",
        "int": f"{v:,.0f}",
        "days": f"{v:.1f}",
    }[fmt]


class Reg:
    """Registry of every number written into the document."""

    def __init__(self):
        self.entries: list[dict] = []
        self.literals: set[str] = set()

    def num(self, v, fmt: str, ref: str | None, kind: str = "excel") -> str:
        t = fmtv(v, fmt)
        self.entries.append({"text": t, "value": v, "fmt": fmt, "ref": ref, "kind": kind})
        return t

    def lit(self, text) -> str:
        text = str(text)
        self.literals |= set(TOKEN.findall(text))
        return text

    def tokens(self) -> set[str]:
        out = set(self.literals)
        for e in self.entries:
            out |= set(TOKEN.findall(e["text"]))
        return out


PPR_AFTER_AUTOSPACE = (
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
)


def no_autospace(doc) -> int:
    """P6-A: turn off Word's automatic spacing between Korean and Latin text / numbers (paragraph properties
    w:autoSpaceDE / w:autoSpaceDN = 0, Word option "한글과 영어 사이 간격 자동 조절") in the document defaults and in
    every paragraph / table style, so 'RF머트리얼즈' is not shown as 'RF 머트리얼즈'. Elements are inserted in schema
    order (before w:bidi ... ). Returns the number of pPr elements set."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def put(ppr):
        for tag, after in (("autoSpaceDE", ("autoSpaceDN", *PPR_AFTER_AUTOSPACE)), ("autoSpaceDN", PPR_AFTER_AUTOSPACE)):
            el = ppr.find(qn(f"w:{tag}"))
            if el is None:
                el = OxmlElement(f"w:{tag}")
                succ = next((ch for ch in ppr if ch.tag in {qn(f"w:{a}") for a in after}), None)
                if succ is None:
                    ppr.append(el)
                else:
                    succ.addprevious(el)
            el.set(qn("w:val"), "0")

    st = doc.styles.element
    dd = st.find(qn("w:docDefaults"))
    if dd is None:
        dd = OxmlElement("w:docDefaults")
        st.insert(0, dd)
    pd_ = dd.find(qn("w:pPrDefault"))
    if pd_ is None:
        pd_ = OxmlElement("w:pPrDefault")
        rd = dd.find(qn("w:rPrDefault"))
        if rd is not None:
            rd.addnext(pd_)
        else:
            dd.append(pd_)
    ppr = pd_.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        pd_.append(ppr)
    put(ppr)
    n = 1
    for s in st.findall(qn("w:style")):
        if s.get(qn("w:type")) in ("paragraph", "table"):
            put(s.get_or_add_pPr())
            n += 1
    return n


class Doc:
    def __init__(self):
        from docx import Document
        from docx.shared import Pt

        self.d = Document()
        st = self.d.styles["Normal"]
        st.font.name = "맑은 고딕"
        st.font.size = Pt(10)
        st.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "맑은 고딕")
        for sec in self.d.sections:
            p = sec.header.paragraphs[0]
            p.text = HEADER
            p.runs[0].font.size = Pt(8)
        no_autospace(self.d)

    def h(self, text, level=1):
        self.d.add_heading(text, level=level)

    def p(self, text, italic=False, size=None):
        from docx.shared import Pt

        para = self.d.add_paragraph()
        run = para.add_run(text)
        run.italic = italic
        if size:
            run.font.size = Pt(size)
        return para

    def b(self, text):
        self.d.add_paragraph(text, style="List Bullet")

    def table(self, headers, rows, widths=None):
        from docx.shared import Pt

        t = self.d.add_table(rows=1, cols=len(headers))
        t.style = "Light Grid Accent 1"
        for j, h in enumerate(headers):
            t.rows[0].cells[j].text = h
        for r in rows:
            cells = t.add_row().cells
            for j, v in enumerate(r):
                cells[j].text = v
        for row in t.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(8.5)
        self.d.add_paragraph()
        return t

    def human(self, title, guidance):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        t = self.d.add_table(rows=1, cols=1)
        t.style = "Table Grid"
        cell = t.rows[0].cells[0]
        cell.text = f"{HUMAN} {title}\n작성 안내: {guidance}\n\n"
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "FFF2CC")
        cell._tc.get_or_add_tcPr().append(shd)
        self.d.add_paragraph()


def git_record(h: str) -> str:
    r = subprocess.run(["git", "log", "-1", "--format=%h %cI %s", h], capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
    return r.stdout.strip()  # full first line of the commit message (no cut inside a word)


def football_png(m: Model, out: Path, title: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    # P7-C3: the public server (Linux) has no Malgun Gothic -> a Korean font it has (packages.txt fonts-nanum)
    plt.rcParams["font.family"] = next(
        (f for f in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "AppleGothic") if f in have), "Malgun Gothic"
    )
    plt.rcParams["axes.unicode_minus"] = False
    rows = [[v for v, _ in r] for r in m.rng("FootballTable")]
    rows = [r for r in rows if "목표" not in str(r[1])]  # broker target bar not shown in the report
    close = m.val("Close")
    pal = {}
    colors = ["#2A6F97", "#61A5C2", "#E09F3E", "#9E9E9E"]
    fig, ax = plt.subplots(figsize=(8.5, 0.5 * len(rows) + 1.6))
    for i, r in enumerate(rows):
        y = len(rows) - 1 - i
        col = pal.setdefault(r[0], colors[len(pal) % len(colors)])
        if not all(isinstance(v, (int, float)) for v in (r[2], r[3], r[4])):  # P7-B2: N/M rows (own metric <= 0) not drawn
            continue
        ax.barh(y, r[3] - r[2], left=r[2], color=col, height=0.55)
        ax.plot([r[4]], [y], marker="D", color="black", ms=4)
    ax.axvline(close, color="#C00000", ls="--", lw=1)
    ax.set_xlim(0, max(max((r[3] for r in rows if isinstance(r[3], (int, float))), default=0), close) * 1.08)
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_yticks(range(len(rows))[::-1], [str(r[1]) for r in rows], fontsize=8)
    ax.set_xlabel("주당 원 (가정 하 추정·참고 범위)")
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


P7B_PREREG = "ed17691"  # P7-B pre-registration (auto drafts)
WITHHELD = "공개 배포: 경영권 프리미엄 집계는 한국거래소 서면 확인 뒤 공개(블록 1주당 가격은 PC 모드에서 계산)"


def build_report(
    cfg_path: str, xlsx: Path | None = None, out: Path | None = None, fig_dir: Path | None = None
) -> tuple[Path, Reg, Path]:
    """fig_dir: folder of the football figure (default outputs/report/figures). P7-B auto drafts (config with a `report`
    section) take their company facts and warning lines from the draft instead of the JW texts."""
    cfg = yamlio.load((ROOT / cfg_path).read_text(encoding="utf-8"))
    auto = isinstance(cfg.get("report"), dict)
    basis_ko = "별도" if cfg.get("meta", {}).get("fs_div") == "OFS" else "연결"
    meta_name = Path(cfg_path).stem.replace("valuation_", "")
    if xlsx is None:
        base = ROOT / cfg["excel"]["output"].format(as_of=cfg["meta"]["as_of"])
        cands = sorted(base.parent.glob(base.stem + "*.xlsx"), key=lambda p: p.stat().st_mtime)
        xlsx = cands[-1]
    m = Model(xlsx)
    R = Reg()
    D = Doc()
    cap = cfg["excel"]["forecast_type"] == "scenario_capex"
    name = cfg["meta"]["target"]["name"] if cap else cfg["target"]["name"]
    code = cfg["meta"]["target"]["stock_code"] if cap else cfg["target"]["stock_code"]
    market = cfg["meta"]["target"]["market"] if cap else cfg["target"]["market"]
    asof = cfg["meta"]["as_of"]
    inp = m.inputs_rows()
    n = lambda key, fmt: R.num(m.val(key), fmt, m.addr(key))  # noqa: E731
    c_ = lambda cell, fmt: R.num(cell[0], fmt, cell[1])  # noqa: E731     (value, address) pair
    L = R.lit
    sotp = m.val("StructureChoice") == "sotp"
    names = [v for v, _ in m.rng("ScenNames")[0]]
    bi = names.index(cfg["excel"]["scenario_labels"]["base"])
    srp = [v for v, _ in (r[0] for r in m.rng("SRP_List"))]
    grid = m.rng("ScenGridPS")
    ps = {r[0][0]: r for r in m.rng("PeerSummary")}
    cv = m.rng("ConvEngine")
    dtm = m.rng("DT_M")
    mrps = [r[0] for r in m.rng("DT_M_Left")]
    sub_name = cfg["nci"]["subsidiary"]["name"] if cap else ""

    D.d.add_heading(L(f"{name} 주식가치 산정 결과 보고서 (자동 생성 초안)"), 0)
    D.p(L(f"평가기준일 {asof} · 자동 생성 {Path(xlsx).name} 기준 · 금액 단위 백만원(주당 값은 원)"), italic=True, size=9)
    D.p(
        "이 문서는 기계적 가치산정 결과다. 전문가 판단을 거친 가치평가(평가보고서)가 아니며, 판단 칸은 사람이 채운다.",
        italic=True,
        size=9,
    )

    # ---------------------------------------------------------------- summary (numbers only)
    D.h("요약")
    rel = " / ".join(
        f"{k} {c_(ps[k][7], 'num0')}~{c_(ps[k][9], 'won')}" for k in ("EV/EBITDA", "PER", "EV/Sales", "PBR") if k in ps
    )
    conv_live = m.rng("ConvLive")[0]
    srows = [
        [
            "평가 구조",
            "SOTP(모회사 DCF + 상장 종속회사 지분 시가 + 순현금·비영업)"
            if sotp
            else f"{basis_ko} DCF − 순차입금 + 비영업 − 비지배",
        ],
        [L("기본 DCF 주당(SRP 0~2%)"), f"{c_(grid[bi][-1], 'num0')}~{c_(grid[bi][0], 'won')} (SRP 0%: {c_(grid[bi][0], 'won')})"],
        [L("상대가치 주당(피어 사분위 q25~q75)"), rel],
        [
            L("지배 블록 1주당(참고, q25~q75)"),
            (
                f"{n('Block_q1', 'num0')}~{n('Block_q3', 'won')} (중앙 {n('Block_q2', 'won')})"
                if "Block_q1" in m.names
                else L(WITHHELD)
            ),
        ],
        ["수렴 시험(사전 고정)", f"{L(cv[1][0][0])}: {L(cv[1][5][0])} · 살아 있는 모델: {L(conv_live[5][0])}"],
        ["기준일 종가", n("Close", "won")],
    ]
    D.table(["항목", "값"], srows)
    warn3 = (
        [
            L("SRP 구간 표 미확보 → SRP 0·1·2% 세 열 병기"),
            L("모회사 시나리오(성장·이익률)는 프로젝트 가정"),
            L("MRP 8%의 2024~2026 한공회 최종 권고 원문 미확인"),
        ]
        if cap
        else [L(x) for x in cfg["report"]["warnings"]]
        if auto
        else [
            L("사전 고정 수렴 시험 미수렴(피어 베타 설명력 낮음)"),
            L("SRP 구간 표 미확보 → SRP 0·1·2% 세 열 병기"),
            L("우선주를 보통주와 같은 청구권으로 가정"),
        ]
    )
    D.p("주요 ⚠️")
    for t in warn3:
        D.b(t)

    _judge_section(D, m, R)  # P7-C1: confirmed workbench session (사람 판단 반영 내역)
    _diag_section(D, m, R)  # P7-B2 new section (unnumbered, earlier sections unchanged)

    # 1 ---------------------------------------------------------------- overview
    D.h(L("1. 평가 개요"))
    D.table(
        ["항목", "내용"],
        [
            ["평가대상", L(f"{name} ({market} {code})")],
            ["평가기준일", L(asof)],
            ["재무 기준일", L(f"{cfg['meta']['bs_date']} (반기보고서)")],
            ["기준가치", L("주당 내재가치 추정(가치산정, 가정 하의 예시). K-IFRS 1113·자본시장법의 '공정가치(공정가액)'가 아님")],
            ["평가 전제", "계속기업"],
            ["목적", "포트폴리오 예시(방법론 시연). 실제 거래·공시·과세 목적이 아님"],
            [
                "평가 구조",
                L(f"SOTP: 모회사 사업 DCF + 상장 종속회사({sub_name}) 지분 시가 + 모회사 순현금·비영업자산")
                if sotp
                else f"{basis_ko} DCF − 순차입금 + 비영업자산 − 비지배지분",
            ],
            ["작성 방식", "엑셀 모델(수식이 살아 있는 모델)의 계산값을 자동으로 옮긴 초안. 판단 문단은 사람 작성 칸"],
        ],
    )

    # 2 ---------------------------------------------------------------- company facts (disclosures)
    D.h(L("2. 대상 회사 개요 (공시 기반 사실)"))
    if cap:
        sub = cfg["nci"]["subsidiary"]
        D.b(
            L(
                f"{market} 상장. 연결 보고부문 2개: 모회사(패키지 사업)와 종속회사 {sub['name']}(KOSDAQ 474610, 상장) — 2026 반기보고서 주석 1·31(20260814001631)"
            )
        )
        D.b(
            f"모회사 지분율 {n('Stake', 'pct2')}, 위임 포함 의결권 {R.num(sub['voting_with_proxy'], 'pct2', 'config:nci.subsidiary.voting_with_proxy', 'config')}"
            + L(" → 사실상 지배(연결)")
        )
        D.b(
            L(
                "2026년 주식 사건: 주주배정 유상증자 납입(2026-06-26), 무상증자 1:1(신주 상장 2026-08-18), 자기주식 소각(2026-09-11) — "
                "무상증자결정 20260710000266, 주식소각결정 20260908900177"
            )
        )
        D.b(f"기준일 유통주식수 {n('Shares', 'int')}" + L("주(우선주 없음)"))
    elif auto:  # P7-B auto draft: fact lines generated from disclosures (draft.report_texts)
        for line in cfg["report"]["facts"]:
            D.b(L(line))
    else:
        D.b(L(f"{market} 상장, 단일 보고부문(제약). 상장 종속회사 없음(타법인 출자현황 확인)"))
        D.b(
            L("우선주 3종(상장 2종) — 반기보고서 20260814004216 주식의 총수. 주당가치 분모는 보통주와 우선주 유통주식수 합계 ")
            + n("Shares", "int")
            + L("주(같은 청구권 가정 ⚠️)")
        )
        D.b(L(f"신용등급 {cfg['kd']['rating']}: {cfg['kd']['rating_source']}"))
        D.b(L(f"재무상태표일 뒤 사건: {cfg['bridge']['post_bs_event']}"))
    D.b(J(f"기준일 종가 {n('Close', 'won')}", "은") + L(" 한국거래소 통계정보(보통주) 값이다"))

    # 3 ---------------------------------------------------------------- methods
    D.h(L("3. 평가방법과 선택 근거"))
    D.table(
        ["방법", "모델에서의 역할", "결과(주당)", "엑셀 시트"],
        [
            [
                "수익가치(DCF, FCFF)",
                L("3단계(명시 2H26~2032, 체감 2033~2040, 영구), 가치동인 영구가치"),
                c_(grid[bi][0], "won") + L("(기본·SRP 0%)"),
                "Forecast·DCF·Bridge",
            ],
            ["상대가치(피어 배수)", "EV/Sales·EV/EBITDA·PER·PBR 사분위(교차 확인)", "5장 표", "Peers"],
            [
                "시장가",
                L("기준일 종가·20거래일 VWAP(비교 기준으로만)"),
                f"{n('Close', 'won')} / VWAP {n('VWAP20', 'won')}",
                "Inputs·Premium",
            ],
            ["자산가치(순자산, 장부)", "지배주주지분 장부 ÷ 주식수(재평가 없음, 참고)", n("NavPerShare", "won"), "Bridge"],
            ["배당할인(DDM)", "적용하지 않음(채택 여부는 사람 판단)", "—", "—"],
            ["블록 프리미엄(참고)", "지배 블록 1주당 가격 범위. 지분 전체 가치에 곱하지 않음", "5.2절", "Premium"],
        ],
    )
    D.human(
        "평가방법 선택 근거·채택·가중치",
        "시가·자산가치·수익가치·상대가치 중 무엇을 채택하고 어떤 가중치를 두는지, DDM·순자산가치를 "
        "주 방법으로 쓰지 않는 이유를 평가자가 쓴다(자본시장법 개정 공정가액 산정 항목 대응). 자동 문장 금지",
    )
    D.table(
        ["방법", "채택 여부(사람)", "가중치(사람)", "근거(사람)"],
        [[x, "", "", ""] for x in ("시가", "자산가치", "수익가치(DCF)", "상대가치")],
    )

    # 4 ---------------------------------------------------------------- assumptions
    D.h(L("4. 주요 가정과 출처"))
    D.p(
        "값은 엑셀 Inputs·계산 시트의 값이고, 출처·상태(✅ 1차 출처 / 🔸 단일 출처·직접 계산 / ⚠️ 미확인·프로젝트 가정)는 Inputs 열을 그대로 옮겼다. "
        "규칙상 결과에 쓰이지 않는 값은 '미사용'으로 표시했다."
    )
    rows = []
    use = {"Kd_Actual": m.val("KdActualUse"), "Kd_Pre": m.val("KdUse"), "T_Kd": m.val("KdUse")}

    def irow(key, fmt):
        a = m.addr(key)
        r = inp.get(a)
        note = L(str(use[key])) if key in use else ""
        if r:
            rows.append([L(r["label"]), R.num(r["value"], fmt, a), L(r["src"]), L(r["asof"]), r["status"], note])
        else:
            rows.append([L(LABEL.get(key, key)), R.num(m.val(key), fmt, a), L(f"계산({a.split('!')[0]} 시트)"), "", "🔸", note])

    for key, fmt in (
        ("RfTenor", "int"),
        ("Rf_5Y", "pct3"),
        ("Rf_10Y", "pct3"),
        ("Rf", "pct3"),
        ("MRP", "pct2"),
        ("SRP_1", "pct1"),
        ("SRP_2", "pct1"),
        ("SRP_3", "pct1"),
        ("SRP_Cite", "pct2"),
        ("BetaU", "beta"),
        ("BetaR2Median", "beta"),
        ("T_Hamada", "pct1"),
        ("DE_Target", "beta"),
        ("Kd_Actual", "pct3"),
        ("Kd_Pre", "pct3"),
        ("T_Kd", "pct1"),
        ("WaccCalc", "pct3"),
        ("RONIC", "pct1"),
        ("GEff", "pct1"),
        ("ExitMult", "x"),
    ):
        irow(key, fmt)
    D.table(["항목", "값", "출처", "기준일", "상태", "사용 여부"], rows)
    D.p(L("WACC·RONIC·영구성장률은 기본 시나리오·SRP 열 1 기준. 베타 R² 점검: ") + L(str(m.val("BetaWarn"))), size=9)
    dtg = m.rng("DT_G")
    D.p(
        L(
            "Rf 만기: 기본은 국고채 5년(P3 공통 장부, 사전 고정)이다. 실무 외부평가 의견서는 10년이 대부분이다(P5-B, Rf 만기 표시 57건 중 10년 56건). "
            "10년을 쓰면 기본 시나리오·SRP 0% 주당 "
        )
        + c_(dtg[0][0], "won")
        + L(" → ")
        + J(c_(dtg[1][0], "won"), "이다")
        + L("(엑셀 Scenarios G 표, Inputs 'Rf 만기 선택'). SRP 인용 참고값은 민감도에만 쓴다(6장 G 표)."),
        size=9,
    )
    D.h(L("4.1 예측 경로"), 2)
    sn = m.rng("ScenNames")[0]
    ws_in = m.wb["Inputs"]
    hr_ = int(re.sub(r"[A-Z]+", "", sn[0][1].split("!")[1]))
    prow = []
    for k in range(1, (9 if cap else 2) + 1):
        lab = ws_in.cell(hr_ + k, 1).value
        fmt = "mn" if "매출" in str(lab) else "pct2"
        prow.append(
            [L(lab)]
            + [
                R.num(ws_in.cell(hr_ + k, 2 + j).value, fmt, f"Inputs!{ws_in.cell(hr_ + k, 2 + j).coordinate}")
                if isinstance(ws_in.cell(hr_ + k, 2 + j).value, (int, float))
                else "(파생)"
                for j in range(len(sn))
            ]
        )
    if cap:
        D.p(
            L(
                "모회사 시나리오(Inputs 표 3, 프로젝트 가정 ⚠️): 2026 매출 → 2027 성장률 → 2028~2032 직선 체감, 정상 이익률, 영구성장률. "
                "증권사 열은 증권사 추정치에서 종속회사 단순 가정을 뺀 파생값(참고, 엑셀 Forecast 시트)"
            )
        )
    else:
        D.p(
            L((cfg["report"]["path_note"] + " ") if auto else "기계적 경로(사전 고정 370efdb): 출발 성장률 = 매출 5년 CAGR ")
            + n("CAGR", "pct2")
            + L(" + 시나리오 이동, 2030년까지 g로 체감. 정상 영업이익률 = 과거 3년 평균 ")
            + n("HistMargin", "pct2")
            + L(" + 이동. D&A·CAPEX·회전일수는 과거 3년 평균. RONIC 상한 = 과거 3년 ROIC ")
            + n("RonicCap", "pct1")
        )
    D.table(["항목"] + [L(v) for v, _ in sn], prow)
    _p5b_reference(D, m, R)
    D.h(L("4.2 사업계획 검증(예측 vs 과거, 기본 시나리오)"), 2)
    D.table(["항목", "값"], [[L(r[0][0]), c_(r[2], "pct1")] for r in m.rng("PlanCheck")])
    D.p("괴리 경고 기준은 정하지 않았다(사람 판단). 차이는 사실로만 표시한다.", size=9)
    D.human(
        "정상화 조정(비경상 손익)",
        "과거 이익에 일회성 손익·영업 외 항목이 있는지, 예측 출발점이나 피어 배수(특히 PER)에 정상화가 필요한지 평가자가 판단해 쓴다. "
        "이 모델은 정상화 조정을 하지 않았다",
    )
    D.h(L("4.3 브리지(EV → 주식가치)"), 2)
    if sotp:
        br = [
            ("모회사 사업 EV(평가기준일)", "EV_930", "mn"),
            (f"종속회사({sub_name}) 지분가치(지분율 × 시가총액)", "StakeValue", "mn"),
            ("모회사 순현금(리스부채 차감)", "ParentNetCash", "mn"),
            ("모회사 비영업자산", "ParentNonOp", "mn"),
            ("주식가치", "Equity", "mn"),
            ("유통주식수(주)", "Shares", "int"),
        ]
    else:
        br = [
            ("EV(평가기준일)", "EV_930", "mn"),
            ("순차입금(차입금 + 리스부채 − 현금성)", "NetDebt", "mn"),
            ("주식가치", "Equity", "mn"),
            ("유통주식수(주)", "Shares", "int"),
        ]
        if "AffLoanTotal" in m.names:
            br.insert(2, ("참고: '기타 금융자산' 중 계열사 대여금 등(포함 기준, 엔진과 같음)", "AffLoanTotal", "mn"))
    br.append(("참고: 순자산가치(장부, 주당 원)", "NavPerShare", "won"))
    D.table(["항목", "값", "엑셀 칸"], [[L(lab), R.num(m.val(k), f, m.addr(k)), L(m.addr(k))] for lab, k, f in br])
    D.human(
        "우발채무·비영업자산 명세 확인",
        "소송·지급보증·약정 등 우발채무와 비영업자산 분류(특히 '기타 금융자산')를 주석으로 확인해 브리지 조정 필요 여부를 쓴다",
    )

    # 5 ---------------------------------------------------------------- results
    D.h(L("5. 결과 (가정 하의 추정 내재가치, 예시)"))
    hdr = ["시나리오"] + [L(f"SRP {fmtv(s, 'pct1')}") for s in srp]
    D.p("시나리오 × SRP 주당 가치(원, Gordon 영구가치). 엑셀 Scenarios 시트 A-1 표와 같은 값")
    D.table(hdr, [[L(names[i])] + [c_(cell, "num0") for cell in grid[i]] for i in range(len(names))])
    wg = m.rng("ScenGridWACC")
    D.p("같은 표의 WACC")
    D.table(hdr, [[L(names[i])] + [c_(cell, "pct2") for cell in wg[i]] for i in range(len(names))])
    D.p(
        L("기준일 종가 ")
        + J(n("Close", "won"), "과")
        + L(" 기본 시나리오(SRP 열 1) 값 ")
        + c_(grid[bi][0], "won")
        + L("의 차이는 성장·이익률·할인율 가정의 차이로 읽는다(판단 아님).")
    )
    D.h(L("5.1 영구가치 교차 확인 (Gordon vs Exit)"), 2)
    tv = m.rng("TVCross")
    D.table(
        ["방식", "주당(원)", "EV/EBITDA(배)", "영구성장률", "영구가치 비중"],
        [[L(r[0][0]), c_(r[2], "num0"), c_(r[3], "x2"), c_(r[4], "pct2"), c_(r[5], "pct1")] for r in tv],
    )
    D.p(
        L("Exit 배수 ")
        + J(c_(tv[1][3], "x"), "을")
        + L(" 쓰면 주당 ")
        + J(c_(tv[1][2], "won"), "이고")
        + L(", Gordon 영구가치의 함의 배수는 ")
        + J(c_(tv[0][3], "x"), "이다")
        + L("(주당 ")
        + c_(tv[0][2], "won")
        + L("). Exit 방식의 함의 영구성장률은 ")
        + J(c_(tv[1][4], "pct2"), "이고")
        + L(" 영구가치 비중은 Gordon ")
        + c_(tv[0][5], "pct1")
        + L(", Exit ")
        + J(c_(tv[1][5], "pct1"), "이다")
        + L(".")
    )
    D.h(L("5.2 상대가치(피어 배수)"), 2)
    D.table(
        ["배수", "n", "q25", "중앙값", "q75", "주당 q25(원)", "주당 중앙값(원)", "주당 q75(원)"],
        [
            [L(r[0][0]), c_(r[2], "int")] + [c_(r[k], "x2") for k in (3, 4, 5)] + [c_(r[k], "num0") for k in (7, 8, 9)]
            for r in ps.values()
        ],
    )
    if cap:
        D.p(
            L("PER의 분자(지배순이익)에는 이자수익·법인세 효과 등 영업 외 항목이 섞여 있어 PER 범위가 넓을 수 있다(피어 PER q75 ")
            + c_(ps["PER"][5], "x")
            + L(", n=")
            + c_(ps["PER"][2], "int")
            + L("). 이익 정상화는 하지 않았다.")
        )
    D.h(L("5.3 블록 프리미엄(참고, 지배 블록 1주당)"), 2)
    if "Block_q1" in m.names:
        D.p(
            L("경영권 프리미엄 DB(주 표본 n=510, 집계값만) 적용 규칙 D6: method ")
            + L(m.val("PremMethod"))
            + L(", 이유 ")
            + L(m.val("PremReason"))
            + L(". 기준일 시총 백분위(고정, 입력한 주가로 바뀌지 않음) " if "PremPctFixed" in m.names else ". 시총 백분위 ")
            + n("Prem_Pct", "days")
            + L(", 20거래일 VWAP(사용자 입력) " if "PremPctFixed" in m.names else ", 20거래일 VWAP ")
            + n("VWAP20", "won")
        )
        D.table(
            ["분위", "프리미엄", "블록 1주당(원)"],
            [[L(q), n(f"PremQ{i + 1}", "pct1"), n(f"Block_q{i + 1}", "num0")] for i, q in enumerate(("q25", "q50", "q75"))],
        )
    else:  # P7-C3 public deployment
        D.p(L(WITHHELD + "."))
    D.human(
        "DLOM·경영권 프리미엄 조정 여부와 근거",
        "이 산정은 시장성 할인(DLOM)과 경영권 프리미엄을 주식가치에 적용하지 않았다. "
        "평가 목적상 조정이 필요한지, 프리미엄 DB의 블록 띠를 어떻게 쓸지 평가자가 쓴다",
    )
    D.h(L("5.4 풋볼필드"), 2)
    png = football_png(
        m,
        (Path(fig_dir) if fig_dir else ROOT / "outputs" / "report" / "figures") / f"{meta_name}_football.png",
        f"{name} 풋볼필드 (초안, 기준일 {asof})",
    )
    from docx.shared import Cm

    D.d.add_picture(str(png), width=Cm(16))
    D.p("그림은 엑셀 Football 시트 표와 같은 값으로 그렸다(빨간 점선 = 기준일 종가, 점 = 대표값).", italic=True, size=8)
    ft = [r for r in m.rng("FootballTable") if "목표" not in str(r[1][0])]
    D.table(
        ["그룹", "항목", "낮음(원)", "높음(원)", "대표(원)"],
        [[L(r[0][0]), L(r[1][0])] + [c_(r[k], "num0") for k in (2, 3, 4)] for r in ft],
    )
    D.h(L("5.5 시장 가격이 전제하는 가정(역DCF)"), 2)
    rv = m.rng("ReverseTable")
    if cap:
        D.p("기준일 종가를 같은 모델 구조로 맞추려면 필요한 2027~2032 매출 성장률(정상 이익률별, 엔진 계산값):")
        D.table(
            ["정상 이익률", "필요 성장률", "2032 매출 함의(백만원)"],
            [[c_(r[0], "pct1"), c_(r[1], "pct1"), c_(r[2], "mn")] for r in rv],
        )
    else:
        D.p("기준일 종가를 같은 모델 구조로 맞추는 값(하나씩만 바꿈, 엔진 계산값):")
        D.table(["항목", "값"], [[L(r[0][0]), c_(r[1], "pct2")] for r in rv])
    D.h(L("5.6 수렴 시험(사전 고정 기준)"), 2)
    D.table(
        ["엔진 기록", "DCF 주당(원)", "사분위 q25(원)", "사분위 q75(원)", "n", "판정"],
        [[L(r[0][0])] + [c_(r[k], "num0") for k in (1, 2, 3)] + [c_(r[4], "int"), L(r[5][0])] for r in cv],
    )

    # 6 ---------------------------------------------------------------- sensitivity
    D.h(L("6. 민감도 (엑셀 데이터 표, 기본 시나리오)"))
    for key, title, tf, lf, rl, cl in (
        ("C", "WACC × 영구성장률", "pct2", "pct1", "영구성장률", "WACC"),
        (
            "D",
            "2027~2030 성장률 × 정상 이익률" if cap else "출발 성장률 이동 × 정상 이익률 이동",
            "pct1",
            "pct1",
            "성장",
            "이익률",
        ),
        ("M", "MRP × SRP", "pct1", "pct1", "MRP", "SRP"),
        ("G", "Rf 만기 × SRP(마지막 열 = 한공회 인용 참고값)", "pct2", "pct3", "Rf(국고채 5년 / 10년)", "SRP"),
    ):
        top = m.rng(f"DT_{key}_Top")[0]
        left = [r[0] for r in m.rng(f"DT_{key}_Left")]
        body = m.rng(f"DT_{key}")
        D.p(L(f"{key}. {title} — 주당 원 (행 = {rl}, 열 = {cl})"))
        D.table(
            [""] + [c_(cell, tf) for cell in top],
            [[c_(left[i], lf)] + [c_(cell, "num0") for cell in body[i]] for i in range(len(left))],
        )
    D.p(
        L(
            "데이터 표는 엑셀 What-If 표({=TABLE()})로 살아 있다. 보고서 값은 생성 시 저장된 값이며 실제 Excel 재계산 값과 1원 안에서 같다(P4-B·P4-C 검증)."
        ),
        size=9,
    )

    # 7 ---------------------------------------------------------------- human: reasonableness
    D.h(L("7. 주요 가정의 합리성"))
    D.human(
        "주요 가정의 합리성",
        "성장 경로·이익률·영구성장률·할인율(MRP·SRP·베타)·RONIC·브리지 항목이 각각 왜 합리적인지, "
        "외부 자료·과거 실적과 어떻게 비교되는지 평가자가 쓴다. 자동 문장 금지",
    )

    # 8 ---------------------------------------------------------------- limitations (grouped)
    D.h(L("8. 평가상 한계"))
    D.p("묶음별로 정리했다. '결과 영향'의 숫자는 엑셀 표·칸의 값이다(없으면 '엑셀 민감도 없음').")
    lim = _limitations(cfg, m, R, cap, grid, bi, ps, cv, dtm, mrps, auto)
    D.table(["묶음", "항목", "가정(값)", "왜 미확인·한계인가", "결과 영향"], lim)
    D.human("평가상 한계 보완", "자동 항목 외에 평가자가 아는 한계(정보 비대칭, 산업 위험, 모델 단순화 등)를 덧붙인다")

    # 9 ---------------------------------------------------------------- appendix
    D.h(L("9. 부록"))
    D.h(L("9.1 데이터 출처"), 2)
    fs = m.wb["FS_Hist"]
    rce = sorted(
        {
            str(fs.cell(6, j).value)
            for j in range(3, fs.max_column + 1)
            if fs.cell(6, j).value and str(fs.cell(6, j).value).isdigit()
        }
    )
    D.b(L("재무: DART 정기보고서(접수번호 " + ", ".join(rce) + ")"))
    D.b(L("금리: 한국은행 ECOS 817Y002(국고채 5년 010200001, 국고채 10년 010210000, 회사채 3년 AA- 010300000, BBB- 010320000)"))
    D.b(
        L(
            "외부평가 의견서 집계(P5-B): 스팩 합병 추정 달성률·Rf 만기·한공회 SRP 인용(2차 인용 🔸) — reports/p5b_final.md, 커밋 0a8d7c6"
        )
    )
    D.b(L("종가·시가총액·20일 VWAP·베타 회귀 결과·시총 백분위: 한국거래소 통계정보(기준일 단일 값·집계)"))
    D.b(L("경영권 프리미엄: 프로젝트 DB(KIND 서식 71207·71209, 주 표본 n=510) 집계값"))
    D.h(L("9.2 사전 고정 기록(커밋 해시·시각·메시지 첫 줄)"), 2)
    for h in ["1386d1d", "bf5211c", "7e14f06", P7B_PREREG] if auto else PREREG:
        D.b(L(git_record(h)))
    D.h(L("9.3 엑셀 check 요약"), 2)
    ck = m.rng("CheckTable")
    cnt = {}
    for r in ck:
        cnt[r[1][0]] = cnt.get(r[1][0], 0) + 1
    D.p(
        L(
            f"master check: {m.val('MasterCheck')} · "
            + " / ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda x: str(x[0])))
        )
    )
    for r in ck:
        if r[1][0] in ("WARN", "ERR", "DIFF"):
            D.b(L(f"{r[1][0]}: {r[0][0]}"))
    D.b(L(f"엑셀 파일: {Path(xlsx).name}"))
    D.h(L("9.4 설정 출처(Inputs 출처가 설정 파일인 항목)"), 2)
    cfg_rows = [
        [L(r["label"]), L(r["src"]), r["status"]]
        for r in inp.values()
        if (".yaml" in r["src"] or r["src"].startswith("config")) and not any(w in r["label"] for w in FORBIDDEN)
    ]
    D.table(["항목", "설정 출처", "상태"], cfg_rows)
    D.h(L("9.5 산출물 요건 대조(docs/output_structure.md 3-2·3-3)"), 2)
    D.table(["요건", "이 초안", "남은 것"], [[L(a), L(b), L(c)] for a, b, c in REQ_TABLE])

    out = out or ROOT / "outputs" / "report" / f"{meta_name}_{code}_report_draft.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    D.d.save(out)
    return out, R, Path(xlsx)


REQ_TABLE = [
    (
        "3-2 시가·자산·수익·상대가치 병행",
        "시가(종가·VWAP), 자산(장부 순자산 참고), 수익(DCF), 상대가치(피어 4종)",
        "DDM 미적용, 채택·가중치는 사람 칸(3장)",
    ),
    ("3-2 주요 가정의 합리성·평가상 한계 필수", "7장 사람 칸, 8장 자동 묶음 + 사람 칸", "합리성 서술(사람)"),
    ("3-3 #1 대상·기준일·기준가치·전제·목적", "1장 자동 기재", "—"),
    ("3-3 #2 초안 표시·판단 칸", "제목·머리말 '자동 생성 초안', 사람 칸 6개", "—"),
    ("3-3 #3 병행·가중 근거 기록", "3장 방법 표 + 가중치 표(빈칸)", "가중치·근거(사람)"),
    (
        "3-3 #4 사업계획 검증",
        "4.2절 예측 vs 과거 성장률·이익률 표, 4.1절 P5-B 스팩 합병 추정 달성률 참고 표(표시만), 가정마다 출처(4장)",
        "괴리 경고 기준(사람)",
    ),
    (
        "3-3 #5 할인율(Rf·MRP·SRP·베타)",
        "Rf 5년(10년 선택 칸·G 표), MRP 8%(7·9% 민감도), SRP 세 열 + 한공회 인용 참고값(민감도), Blume·Hamada",
        "SRP 연도별 구간 표 원문(구간 경계·대상 회사 구간)",
    ),
    ("3-3 #6 순차입금 브리지(리스 포함)·비영업·우발채무", "리스 포함 브리지, 비영업 분류", "우발채무 명세(사람 칸 4.3)"),
    ("3-3 #7 정상화 조정·회전일수", "회전일수 추정", "정상화 조정 안 함(사람 칸 4.2)"),
    ("3-3 #8 Gordon·Exit·implied·mid-year", "5.1절 교차 확인 표, mid-year", "—"),
    ("3-3 #9 민감도·시나리오·풋볼필드·범위", "6장 데이터 표 3개, 시나리오 × SRP, 5.4 풋볼필드", "—"),
    ("3-3 #10 DLOM·경영권 프리미엄 조정 여부", "블록 띠(참고) 표시, 조정 없음 명시", "조정 여부·근거(사람 칸 5.3)"),
    ("3-3 #11 엑셀 표준", "입력·계산·출력 분리, check·master check, Guide 시트", "—"),
]


def _limitations(cfg, m, R, cap, grid, bi, ps, cv, dtm, mrps, auto: bool = False) -> list[list[str]]:
    """Grouped limitations: what was assumed (value) · why it is unconfirmed · result impact (Excel numbers)."""
    L = R.lit
    n = lambda key, fmt: R.num(m.val(key), fmt, m.addr(key))  # noqa: E731
    c_ = lambda cell, fmt: R.num(cell[0], fmt, cell[1])  # noqa: E731
    names = [v for v, _ in m.rng("ScenNames")[0]]
    dtc = m.rng("DT_C")
    gl = [r[0] for r in m.rng("DT_C_Left")]
    ctop = m.rng("DT_C_Top")[0]
    jc = [v for v, _ in ctop].index(min((v for v, _ in ctop), key=lambda x: abs(x - m.val("WaccCalc")))) if ctop else 0
    dtg = m.rng("DT_G")
    rows = [
        [
            "할인율",
            "MRP",
            n("MRP", "pct2"),
            "한공회 2024~2026 최종 권고 범위 원문 미확인(가이던스 7~9%)",
            L("기본·SRP 0%: MRP ")
            + c_(mrps[0], "pct1")
            + " "
            + c_(dtm[0][0], "won")
            + L(" → ")
            + c_(mrps[-1], "pct1")
            + " "
            + c_(dtm[-1][0], "won"),
        ],
        [
            "할인율",
            "Rf 만기",
            n("Rf_5Y", "pct3") + L("(국고채 5년, 선택 10년 ") + n("Rf_10Y", "pct3") + L(")"),
            "실무 외부평가 의견서는 10년이 대부분(P5-B, Rf 만기 표시 57건 중 10년 56건). 기본 5년은 P3 공통 장부(사전 고정)",
            L("기본·SRP 0%: 5년 ") + c_(dtg[0][0], "won") + L(" → 10년 ") + c_(dtg[1][0], "won"),
        ],
        [
            "할인율",
            "SRP",
            L("0·1·2% 세 열(결정 D4)"),
            "한공회 규모위험프리미엄 구간 표 원문 미확보. 의견서 인용(P5-B, 2차 인용 🔸): "
            + _srp_cite_summary(m)
            + ". 구간 경계와 대상 회사가 속한 구간은 미확인",
            L("기본: SRP 0% ")
            + c_(grid[bi][0], "won")
            + L(" → 2% ")
            + c_(grid[bi][-1], "won")
            + L(" / 인용 참고값 ")
            + n("SRP_Cite", "pct2")
            + L(" ")
            + c_(dtg[0][-1], "won")
            + L("(Rf 5년)"),
        ],
        [
            "할인율",
            "베타",
            L("βu ") + n("BetaU", "beta") + L(", 피어 R² 중앙값 ") + n("BetaR2Median", "x2"),
            "주간 2년 회귀의 설명력이 낮을 수 있음(지수·기간 선택은 사전 고정)",
            "엑셀 민감도 없음(P3-C3 보고서 3절 베타 민감도)",
        ],
    ]
    if cap:
        rows.append(
            [
                "할인율",
                "Kd",
                n("Kd_Pre", "pct3") + L(" (무등급 → BBB- 3년)"),
                "무등급, 실제 차입은 정책 금리",
                L(str(m.val("KdUse"))) + L(" → 결과 영향 0"),
            ]
        )
        rows += [
            [
                "예측 경로",
                "모회사 시나리오",
                L("기본 2026 매출·성장·이익률(4.1절 표)"),
                "사용자 제공 시나리오 v2(프로젝트 가정)",
                L("SRP 0%: ") + " / ".join(f"{L(names[i])} {c_(grid[i][0], 'won')}" for i in range(len(names))),
            ],
            [
                "예측 경로",
                "상각 연수·신규 공장",
                L("유지 CAPEX ") + n("LifeM", "int") + L("년, 공장 ") + n("LifeB", "int") + L("년"),
                "생산설비 투자가 유지 CAPEX 비율 안에 있다고 가정",
                "엑셀 민감도 없음",
            ],
        ]
    else:
        kd_why = (
            (
                "등급 미확인 → 이자비용 ÷ 평균 차입금(하한 Rf)"
                if cfg["kd"].get("method") == "implied"
                else "등급 미확인 → 무등급 공통 규칙(BBB- 3년)"
            )
            if auto
            else "A- 민평 곡선 없음 → 공통 규칙(max(실제, AA-))"
        )
        rows += [
            ["할인율", "Kd·목표 D/E", n("Kd_Pre", "pct3") + L(", D/E ") + n("DE_Target", "beta"), kd_why, "엑셀 민감도 없음"],
            [
                "예측 경로",
                "기계적 경로",
                L("CAGR ") + n("CAGR", "pct2") + L(", 이익률 ") + n("HistMargin", "pct2") + L(", 시나리오 ±2%p"),
                "과거 규칙(판단 최소화)" if auto else "과거 규칙(판단 최소화), 신약 파이프라인 제외",
                L("SRP 0%: ") + " / ".join(f"{L(names[i])} {c_(grid[i][0], 'won')}" for i in range(len(names))),
            ],
        ]
    rows += [
        [
            "예측 경로",
            "체감·영구성장률",
            L("8년 체감, g ") + n("GEff", "pct1"),
            "프로젝트 가정",
            L("WACC 기본 열: g ")
            + c_(gl[0], "pct1")
            + " "
            + c_(dtc[0][jc], "won")
            + L(" → ")
            + c_(gl[-1], "pct1")
            + " "
            + c_(dtc[-1][jc], "won"),
        ],
        [
            "예측 경로",
            "Exit 배수",
            n("ExitMult", "x"),
            "피어 EV/EBITDA 중앙값(병행 표시)" + ("" if cap else ", 엔진에는 Exit 없음"),
            L("Exit 주당 ") + n("PerShareExit", "won") + L(" vs Gordon ") + n("PerShare", "won"),
        ],
    ]
    if cap:
        rows += [
            [
                "구조·브리지",
                "SOTP 판단",
                L("종속회사 지분 시가 반영"),
                "구조 규칙(비지배 시가 비중) 판정, 사용자 결정 D2",
                L("연결 교차 확인 주당 ") + n("CrossPerShare", "won") + L(" vs SOTP ") + n("PerShare", "won"),
            ],
            [
                "구조·브리지",
                "비영업자산",
                n("ParentNonOp", "mn") + L("백만원(장기금융자산)"),
                "장부가 = 공정가치 가정",
                "엑셀 민감도 없음",
            ],
        ]
    elif auto:
        pref = bool(cfg["shares"]["pref_issued"])
        rows += [
            [
                "구조·브리지",
                "비영업·현금성 분류",
                n("BridgeAdj", "mn") + L("백만원(EV 밖 항목 합계)"),
                "'기타 금융자산' 등 이름 기반 분류(보증금·대여금 혼재 가능), 우발채무 미반영",
                "엑셀 민감도 없음",
            ],
            [
                "구조·브리지",
                "우선주" if pref else "주식 수",
                (L("보통주와 같은 청구권, 분모 ") if pref else L("보통주 유통주식수 ")) + n("Shares", "int") + L("주"),
                "우선주 조건 미반영" if pref else "기준일 뒤 주식 수 변동 미반영(사람 판단 목록)",
                "엑셀 민감도 없음",
            ],
        ]
    else:
        rows += [
            [
                "구조·브리지",
                "비영업·계열사 대여금",
                n("AffLoanTotal", "mn") + L("백만원(포함)"),
                "'기타 금융자산'의 이름 기반 분류, 대부분 계열사 대여금",
                L("제외 시 주당 ") + n("AffLoanImpact", "won"),
            ],
            [
                "구조·브리지",
                "우선주",
                L("보통주와 같은 청구권, 분모 ") + n("Shares", "int") + L("주"),
                "우선주 조건 미반영",
                "엑셀 민감도 없음",
            ],
        ]
    rows += [
        ["데이터", "반기 재무", L("2026 반기(검토, 미감사) 값"), "감사 범위 밖", "—"],
        ["데이터", "시장 자료", "한국거래소 통계정보 기준일 단일 값·집계", "시계열 미수록(약관)", "—"],
        [
            "데이터",
            "피어 표본",
            L("n ") + " / ".join(f"{L(k)} {c_(ps[k][2], 'int')}" for k in ("EV/Sales", "EV/EBITDA", "PER", "PBR")),
            "표본이 작아 사분위 폭이 넓음",
            L("EV/EBITDA 주당 ") + c_(ps["EV/EBITDA"][7], "num0") + L("~") + c_(ps["EV/EBITDA"][9], "won"),
        ],
    ]
    if cap:
        rows.append(
            [
                "방법",
                "PER 분자",
                L("지배순이익(정상화 없음)"),
                "이자수익·법인세 효과 등 영업 외 항목 포함",
                L("피어 PER q75 ") + c_(ps["PER"][5], "x") + L("(n=") + c_(ps["PER"][2], "int") + L(")"),
            ]
        )
    rows += [
        [
            "방법",
            "블록 프리미엄",
            "관찰된 경영권 거래 프리미엄(시너지·과다지급 포함) 집계",
            "지분 전체 가치에 곱하지 않음",
            (n("Block_q1", "num0") + L("~") + n("Block_q3", "won") + L("(참고)"))
            if "Block_q1" in m.names
            else L("공개 배포: 비공개"),
        ],
        [
            "방법",
            "수렴 시험",
            L(cv[1][0][0]),
            L("사전 고정 기준(피어 EV/EBITDA 사분위)")
            if cap
            else L("기계적 경로라 기록만(P7-B 성공 기준 아님). 결과를 본 뒤 규칙을 바꾸지 않음")
            if auto
            else L("KOSPI 기준 피어 베타 설명력 낮음 → 낮은 WACC. 결과를 본 뒤 지수·SRP를 바꾸지 않음"),
            L(cv[1][5][0]) + L(": DCF ") + c_(cv[1][1], "won") + L(" vs ") + c_(cv[1][2], "num0") + L("~") + c_(cv[1][3], "won"),
        ],
    ]
    for row in rows:  # group / item / reason are fixed template text -> registered literals
        for k in (0, 1, 3):
            row[k] = L(row[k])
    return rows


def _judge_section(D, m, R) -> None:
    """P7-C1: the people's changes of the confirmed evaluation session (Excel Judgements sheet, same rows)."""
    if "JudgeTable" not in m.names:
        return
    L = R.lit
    rows = [r for r in m.rng("JudgeTable") if r[1][0] not in (None, "")]
    D.h(L("사람 판단 반영 내역 (평가 세션 확정)"))
    D.p(
        L(
            "자동 초안의 가정 중 사람이 바꾼 것. 확정값이 모델(엑셀 Inputs '사람 확정값'과 각 입력 칸)에 들어가 이 보고서의 숫자가 됐다."
        )
    )
    if not rows:
        D.p(L("바꾼 가정 없음(자동 초안 그대로 확정)."))
        return

    def cell(c):  # formatted text cells of the Judgements sheet (session record)
        return L("" if c[0] is None else str(c[0]))

    D.table(
        ["항목", "가정", "자동값", "확정값", "이유", "버전"],
        [[L(r[1][0]), L(r[2][0]), cell(r[3]), cell(r[4]), L(r[5][0] or ""), L(r[6][0])] for r in rows],
    )


def _diag_section(D, m, R) -> None:
    """'결과 해석 주의' (P7-B2): traffic lights, reverse, composition, anomalies, margin candidates, sensitivities and the
    top 5 of the ranked human-review list. Every number is a cell of the Excel Diagnostics sheet."""
    if "DiagLight" not in m.names:
        return
    L = R.lit
    n = lambda key, fmt: R.num(m.val(key), fmt, m.addr(key))  # noqa: E731
    c_ = lambda cell, fmt: R.num(cell[0], fmt, cell[1])  # noqa: E731
    D.h(L("결과 해석 주의 (자동 진단, 값은 바꾸지 않음)"))
    D.p(
        L("신호등(사전 고정 기준, 엑셀 Diagnostics A): 종합 ")
        + L(m.val("DiagLight"))
        + L(" — 피어 ")
        + L(m.val("DiagLightPeer"))
        + L("(DCF ")
        + n("DiagDcf", "won")
        + L(" vs 피어 ")
        + L(m.val("DiagPeerBasis"))
        + L(" 사분위 ")
        + n("DiagQ25", "num0")
        + L("~")
        + n("DiagQ75", "won")
        + L("), 시장 ")
        + L(m.val("DiagLightMkt"))
        + L("(DCF ÷ 종가 ")
        + n("DiagMktRatio", "x2")
        + L(")")
    )
    if "DiagHeadline" in m.names:  # P7-B2b validity guard and the v1 alternative
        hl = m.val("DiagHeadline")
        reasons = [r[0][0].replace("  사유: ", "") for r in m.rng("DiagGuardTable")[1:] if r[0][0]]
        D.p(L("대표값 판정(유효성 가드): ") + L(hl) + (L(" — 사유: " + "; ".join(reasons)) if reasons else L("")))
        if "DiagV1PS" in m.names:
            D.p(
                L("기본 경로 v2 주당 ")
                + n("DiagV2PS", "won")
                + L(", 대안 v1(3년 평균 이익률·5년 CAGR) 주당 ")
                + n("DiagV1PS", "won")
                + L(". v2 출발 이익률 ")
                + n("DiagV2M0", "pct2")
                + L(", 2032년까지 피어 쪽 이동 ")
                + n("DiagV2Conv", "pct2")
                + L(", 출발 성장률 ")
                + n("DiagV2G0", "pct2")
            )
        est = [r for r in m.rng("DiagDnaTable") if r[3][0] == "추정"]
        if est:
            D.p(
                L("D&A 추정 기간: ")
                + L(", ".join(str(r[0][0]) for r in est))
                + L(" — 원문에서 찾지 못해 자산 × 비율로 추정(엑셀 Diagnostics J, 판단 목록 맨 위)")
            )
    if "DiagSotpTable" in m.names:  # P7-B3 general SOTP section
        D.p(
            L(
                "SOTP(일반, config/p7b3.yaml): 모회사(별도 재무, 기본 경로 v2) 영업가치에 상장 종속회사 지분 시가(보유 주식수 × 종가)와 "
                "비상장 종속회사 장부가를 더했다. 별도 재무상태표의 종속기업 투자 줄은 빼고 바꿔 넣었다(엑셀 Bridge·Checks 이중 계산 점검)."
            )
        )
        D.table(
            ["SOTP 항목", "값"],
            [
                [L(r[0][0]), c_(r[1], "pct1" if "비중" in str(r[0][0]) else ("num0" if "주당" in str(r[0][0]) else "mn"))]
                for r in m.rng("DiagSotpTable")
            ],
        )
    if "DiagLossText" in m.names:  # P7-B3b loss path (config/p7b3b.yaml loss_path)
        D.p(
            L("적자 경로(config/p7b3b.yaml): ")
            + L(m.val("DiagLossText"))
            + L(". (a) 피어 EV/Sales 사분위 주당 ")
            + n("DiagLossQ25", "num0")
            + L("~")
            + n("DiagLossQ75", "won")
            + L("(범위 해석: ")
            + L(m.val("DiagLossValid"))
            + L("), (b) 전환 DCF 주당 ")
            + n("DiagLossDcf", "won")
            + L("(출발 LTM 영업이익률 ")
            + n("DiagLossM0", "pct2")
            + L("에서 2032년 피어 중앙값 ")
            + n("DiagLossMT", "pct2")
            + L("까지 직선), (c) 명시 기간 누적 FCF 최저 ")
            + n("DiagLossTrough", "mn")
            + L("백만원 vs 현금성 ")
            + n("DiagLossCash", "mn")
            + L("백만원 — 추가 자금 필요: ")
            + L(m.val("DiagLossNeed"))
            + L(". 피어는 흑자 회사라 범위는 이익률 개선을 전제한다.")
        )
    if "DiagTurnLtm" in m.names:  # P7-B3b turnaround detection (default unchanged)
        D.p(
            L("실적 전환 감지(config/p7b3b.yaml turnaround): LTM 영업이익률 ")
            + J(n("DiagTurnLtm", "pct2"), "이")
            + L(" 5년 중앙값 ")
            + J(n("DiagTurnM0", "pct2"), "과")
            + L(" 크게 다르다. LTM 이익률에서 출발하면 주당 ")
            + n("DiagTurnPS", "won")
            + L("(후보, 기본값은 5년 중앙값 그대로) — 어느 쪽이 정상 이익률인지 판단 목록 1순위")
        )
    if "DiagSotpGuard" in m.names and m.val("DiagSotpGuard") not in (None, "해당 없음"):
        D.p(L("SOTP 가드(config/p7b3b.yaml sotp_guard): ") + L(m.val("DiagSotpGuard")) + L(" → 대표값 보류"))
    if "DiagMistagTable" in m.names:
        mt = [r for r in m.rng("DiagMistagTable") if r[0][0] not in (None, "", "없음")]
        if mt:
            D.p(
                L(
                    "계정 오표기(원문 대조, config/p7b3b.yaml mistag): 원문 재무상태표의 차입금 줄이 API에서 다른 계정으로 와서 총차입금에 더했다 — "
                )
                + L("; ".join(f"{r[0][0]} {r[2][0]}" for r in mt))
                + L(" (")
                + c_(mt[0][1], "mn")
                + L("백만원 등, 엑셀 Diagnostics L)")
            )
    if "DiagPeerValid" in m.names and m.val("DiagPeerValid") == 0:
        sh, cell = m.ref("DiagPeerValid")
        why = m.wb[sh][cell].offset(column=1).value or ""
        D.p(L("피어 범위 해석 불가(config/p7b3.yaml peer_validity, 신호 회색): ") + L(str(why)))
    rev = m.rng("DiagRevTable")
    if isinstance(rev[0][0][0], str) and rev[0][0][0].startswith("RF"):
        D.p(L("RF 전용 경로: 원인 분해·후보·민감도는 일반 경로(자동 초안) 회사에만 계산한다. 역DCF는 5.5절."), size=9)
        return
    D.p(L("역산 — 피어 중앙값 주당을 맞추려면 필요한 값(하나만 움직임):"))
    fm = ["num0", "pct2", "pct2", "pct2", "num0"]
    D.table(
        ["항목", "기본 값", "필요 값", "차이"], [[L(r[0][0])] + [c_(r[k], fm[i]) for k in (1, 2, 3)] for i, r in enumerate(rev)]
    )
    comp = m.rng("DiagCompTable")
    D.p(L("주식가치 구성(백만원, 평가기준일):"))
    D.table(["항목", "금액", "주식가치 대비"], [[L(r[0][0]), c_(r[1], "mn"), c_(r[2], "pct1")] for r in comp])
    on = [r for r in m.rng("DiagFlagTable") if r[1][0] == "해당"]
    D.p(L(f"데이터 이상 신호 {len(on)}개(엑셀 Diagnostics D):"))
    for r in on:
        v = r[2]
        D.b(
            L(r[0][0])
            + (
                L(" — ") + c_(v, "int" if isinstance(v[0], int) else "pct1")
                if isinstance(v[0], (int, float))
                else (L(" — ") + L(v[0]) if v[0] not in (None, "-") else "")
            )
        )
    cand = m.rng("DiagCandTable")
    D.p(L("정상 이익률 후보(표시만, 기본값은 과거 3년 평균 그대로):"))
    D.table(
        ["후보", "이익률", "주당(원)", "기본 대비(원)"],
        [[L(r[0][0]), c_(r[1], "pct2"), c_(r[2], "num0"), c_(r[3], "num0")] for r in cand],
    )
    sens = m.rng("DiagSensTable")
    sf = ["mn", "mn", "mn", "pct1", "x2"]
    D.p(L("민감도(고객 자금 성격 현금, 비지배지분 차감 방법):"))
    D.table(
        ["항목", "값", "주당(원)", "기본 대비(원)"],
        [[L(r[0][0]), c_(r[1], sf[i]), c_(r[2], "num0"), c_(r[3], "num0")] for i, r in enumerate(sens)],
    )
    rk = [r for r in m.rng("DiagRankTable") if r[0][0] not in (None, "")]
    other = [r for r in m.rng("DiagOtherTable") if r[0][0] not in (None, "")]
    D.p(L("사람이 먼저 볼 곳 — 다른 선택의 주당 영향이 큰 순 상위 5(엑셀 Diagnostics G와 같은 순서):"))
    D.table(
        ["순위", "범주", "항목", "다른 선택", "주당 차이(원)", "기본 대비"],
        [[L(r[0][0]), L(r[1][0]), L(r[2][0]), L(r[3][0]), c_(r[5], "num0"), c_(r[6], "pct1")] for r in rk[:5]],
    )
    D.p(
        L(f"나머지 계산 항목 {max(len(rk) - 5, 0)}개와 계산할 수 없는 항목 {len(other)}개는 엑셀 Diagnostics G표에 있다."), size=9
    )


def _srp_cite_summary(m) -> str:
    """'Micro 3.35%·4.02%, 3분위 3.35%~4.02% ... (총 19건)' from the Inputs SrpCiteTable (band names as quoted)."""
    rows = m.rng("SrpCiteTable")
    by, total = {}, 0
    for r in rows:
        band, v, k = r[1][0], r[2][0], r[3][0]
        total += int(k)
        if band != "(미추출)":
            by.setdefault(band, set()).add(round(v, 6))
    parts = []
    for band in sorted(by, key=lambda b: (b != "Micro", b)):
        vs = sorted(by[band])
        parts.append(
            f"{band} "
            + ("·".join(fmtv(v, "pct2") for v in vs) if len(vs) <= 2 else f"{fmtv(vs[0], 'pct2')}~{fmtv(vs[-1], 'pct2')}")
        )
    return ", ".join(parts) + f"(총 {total}건)"


def _p5b_reference(D, m, R) -> None:
    """4.1: P5-B reference distribution (SPAC merger opinions) and the band of this model's forecast CAGR (display only)."""
    L = R.lit
    c_ = lambda cell, fmt: R.num(cell[0], fmt, cell[1])  # noqa: E731
    n = lambda key, fmt: R.num(m.val(key), fmt, m.addr(key))  # noqa: E731
    ach = m.rng("P5bAchTable")
    D.p(
        L(
            "참고: P5-B 스팩 합병 외부평가 추정의 실제 달성률(실적 ÷ 예측). 중앙값 [Q1, Q3] (n). 엑셀 Forecast 사업계획 검증 옆 표, 표시만 🔸"
        )
    )
    rows = []
    for acc in dict.fromkeys(r[0][0] for r in ach):
        cells = [r for r in ach if r[0][0] == acc]
        rows.append(
            [L(acc)]
            + [
                c_(r[3], "pct1") + " [" + c_(r[4], "pct1") + ", " + c_(r[5], "pct1") + "] (" + c_(r[2], "int") + ")"
                for r in cells
            ]
        )
    D.table(["계정", "1차연도", "2차연도", "3차연도"], rows)
    cg = m.rng("P5bCagrTable")
    D.table(
        ["예측 매출 CAGR 구간", "CAGR 범위", "거래 수", "매출 달성률 중앙값 1차", "2차", "3차"],
        [
            [
                L(r[0][0]),
                c_(r[1], "pct1") + "~" + c_(r[2], "pct1"),
                c_(r[3], "int"),
                c_(r[4], "pct1"),
                c_(r[6], "pct1"),
                c_(r[8], "pct1"),
            ]
            for r in cg
        ],
    )
    band = int(m.val("PlanBand"))
    D.p(
        L("이 모델(기본 시나리오)의 예측 매출 CAGR(첫 추정 회계연도부터 5개 연도) ")
        + n("PlanFcCAGR5", "pct1")
        + L(" → ")
        + L(cg[band - 1][0][0])
        + L(f"({m.val('PlanBandRange')}). 그 구간 매출 달성률 중앙값 1차 ")
        + n("PlanBandH1", "pct1")
        + L(", 2차 ")
        + n("PlanBandH2", "pct1")
        + L(", 3차 ")
        + J(n("PlanBandH3", "pct1"), "이다")
        + L(".")
    )
    D.p(
        L(
            "스팩 합병 외부평가 추정 기준 참고값이다. 대상 회사와 상황이 다르다. 달성률은 예측이 분모라 높은 예측일수록 낮게 나오는 기계적 성분이 있다. "
            "예측을 자동으로 깎거나 경고 판정하지 않는다. 출처: reports/p5b_final.md(커밋 0a8d7c6), DB p5b_error·p5b_forecast"
        ),
        size=9,
    )


LABEL = {
    "Rf": "Rf(모델 적용 = Inputs 'Rf 만기 선택')",
    "BetaU": "βu 중앙값(피어, Blume → Hamada)",
    "BetaR2Median": "피어 회귀 R² 중앙값",
    "Kd_Actual": "실제 가중 약정이자율",
    "Kd_Pre": "세전 Kd(공통 규칙, 하한 Rf)",
    "T_Kd": "세후 Kd 한계세율",
    "WaccCalc": "WACC(기본, SRP 열 1)",
    "RONIC": "RONIC(적용)",
    "GEff": "영구성장률 g",
    "DE_Target": "목표 D/E(자체 3년 평균)",
    "ExitMult": "Exit 배수(EV/EBITDA)",
}


def to_pdf(docx: Path) -> Path | None:
    """Export with an installed Word (new instance, read-only, original not modified). None if Word is unavailable."""
    import shutil
    import tempfile

    if not shutil.which("powershell"):
        return None
    pdf = docx.with_suffix(".pdf")
    ps = f"""
$ErrorActionPreference = 'Stop'
$w = [Activator]::CreateInstance([type]::GetTypeFromProgID('Word.Application'))
$w.Visible = $false; $w.DisplayAlerts = 0
try {{
  $d = $w.Documents.Open('{docx}', $false, $true)
  $d.ExportAsFixedFormat('{pdf}', 17)
  $d.Close(0)
}} finally {{ if ($w.Documents.Count -eq 0) {{ $w.Quit() }} }}
"""
    s = Path(tempfile.mkdtemp()) / "pdf.ps1"
    s.write_text(ps, encoding="utf-8-sig")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(s)], capture_output=True, text=True, timeout=600
    )
    return pdf if r.returncode == 0 and pdf.exists() else None


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/valuation_rf.yaml"
    p, reg, x = build_report(cfg)
    pdf = to_pdf(p) if "--pdf" in sys.argv else None
    print(f"written {p} ({len(reg.entries)} numbers from {x.name}){' + ' + str(pdf) if pdf else ''}")
