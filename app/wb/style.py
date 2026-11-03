"""Design tokens and the one shared stylesheet of the work screen (P7-U1 config/p7u.yaml fonts; earlier config/p7c2.yaml).

Tokens follow the design reference data/design_ref/p7u/Main.dc.html (git-ignored): warm grey page, white cards, orange
accent #C2410C, Pretendard (served by the theme config from app/static, .streamlit/config.toml). Three weights only:
400 body and table numbers, 500 labels and item names, 600 section titles, KPI numbers and total rows.
`inject(kind)` writes the CSS once per run: kind 'work' (work screen) or 'ref' (reference pages).
"""

from __future__ import annotations

import streamlit as st

T = {
    "page": "#F4F4F2",
    "card": "#FFFFFF",
    "line": "#E4E4E0",
    "line_soft": "#F0F0EC",
    "line_strong": "#C9CBCF",
    "text": "#15171B",
    "text_sub": "#5A5E66",
    "text_faint": "#A0A3A8",
    "accent": "#C2410C",
    "accent_dark": "#9A3412",
    "warn_text": "#9A3412",
    "accent_bg": "#FFF1E6",
    "accent_line": "#F7C9A6",
    "shade": "#F7F7F5",
    "ok_text": "#1E6B3A",
    "ok_bg": "#E8F3EC",
    "yellow_text": "#7A5600",
    "yellow_bg": "#FFF4D6",
    "red_text": "#B42318",
    "red_bg": "#FDE8E7",
    "blue_line": "#2F5D8A",
    "prem_bg": "#FBF6EC",
    "bar_dark": "#4A4F59",
    "band": "#D9DAD6",
    "track": "#F4F4F2",
    "block_bar": "#F2E3C4",
    "block_mark": "#8A5A00",
    "dcf_bar": "#F7C9A6",
    "tag_bg": "#EEF2F7",
    "tag_text": "#334155",
}
FONT_WORK = "Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', system-ui, sans-serif"
FONT_SERIF = FONT_WORK  # P7-U1: one family (no web font from another host)

# text / background pairs used on the screen (checked for WCAG AA in tests/test_p7c2.py)
CONTRAST_PAIRS = [
    ("text", "card"),
    ("text", "page"),
    ("text_sub", "card"),
    ("text_sub", "page"),
    ("warn_text", "card"),
    ("warn_text", "accent_bg"),
    ("card", "accent"),
    ("ok_text", "ok_bg"),
    ("text", "accent_bg"),
    ("text_sub", "line_soft"),
    ("text_sub", "shade"),
    ("yellow_text", "yellow_bg"),
    ("red_text", "red_bg"),
    ("red_text", "card"),
    ("tag_text", "tag_bg"),
]


def _css(kind: str) -> str:
    t = T
    base = f"""
html, body, .stApp, [data-testid="stAppViewContainer"], button, input, textarea, select, label,
.stMarkdown, [data-testid="stMarkdownContainer"] {{ font-family: {FONT_WORK}; }}
.stApp {{ color: {t["text"]}; font-variant-numeric: tabular-nums; font-feature-settings: 'tnum' 1; letter-spacing: -0.1px;
  -webkit-font-smoothing: antialiased; }}
.stApp p, .stApp li, [data-testid="stMarkdownContainer"] p {{ font-size: 15px; line-height: 1.6; }}
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stToolbarActions"],
[data-testid="stAppDeployButton"], [data-testid="stSidebarNav"] {{ display: none !important; }}
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
.block-container {{ padding: 16px 28px 40px 28px; max-width: 1280px; }}
h1, h2, h3 {{ color: {t["text"]}; font-weight: 600; letter-spacing: -0.01em; }}
a {{ color: {t["accent_dark"]}; }}
a:hover {{ color: #7C2D12; }}
[data-testid="stVerticalBlock"] {{ gap: 16px; }}
/* buttons: primary = orange with white text (AA), others white with a grey line */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, [data-testid="stPopover"] > div > button {{
  border-radius: 8px; min-height: 40px; font-weight: 500; font-size: 15px; }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: {t["accent"]}; border-color: {t["accent"]}; color: #FFFFFF; font-weight: 500; }}
.stButton > button[kind="primary"] *, .stDownloadButton > button[kind="primary"] * {{ color: #FFFFFF !important; }}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {{ background: {t["accent_dark"]}; border-color: {t["accent_dark"]}; }}
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {{ background: #FFFFFF; border: 1px solid {t["line"]}; color: {t["text"]}; }}
.stButton > button[kind="tertiary"] {{ color: {t["accent_dark"]}; font-weight: 500; min-height: 32px; padding: 0 4px; }}
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible {{ outline: 3px solid {t["text"]}; outline-offset: 2px; }}
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{ border-radius: 8px !important; }}
.stMain [data-testid="stTextInputRootElement"] {{ background: #FFFFFF !important; border: 1px solid {t["line"]} !important; border-radius: 8px !important; }}
.stMain [data-testid="stTextInputRootElement"]:focus-within {{ border-color: {t["accent"]} !important; }}
.stMain [data-testid="stTextInputRootElement"] input {{ font-size: 14px; }}
.stMain [class*="st-key-in_"] input, .stMain .st-key-prem_stake input {{ text-align: right; }}
[class*="st-key-evm_"] button {{ min-height: 30px !important; padding: 0 6px !important; font-size: 13px !important; white-space: nowrap; }}
label[data-testid="stWidgetLabel"] p {{ font-size: 13px !important; color: {t["text_sub"]}; font-weight: 500; }}
/* cards: containers with a key starting with card_ */
[class*="st-key-card_"] {{ background: {t["card"]}; border: 1px solid {t["line"]}; border-radius: 12px; padding: 18px 22px; gap: 10px; }}
[class*="st-key-card_"] [class*="st-key-card_"] {{ border: 0; padding: 0; }}
.wb-h2 {{ margin: 0; font-size: 16px; font-weight: 600; color: {t["text"]}; line-height: 1.4; }}
.wb-h2 .wb-h2-sub {{ font-weight: 400; color: {t["text_sub"]}; margin-left: 4px; }}
.wb-sub, .wb-kpi-note {{ margin: 0; font-size: 13px; color: {t["text_sub"]}; line-height: 1.5; }}
.wb-warn {{ color: {t["warn_text"]}; font-weight: 500; }}
.wb-red {{ color: {t["red_text"]}; }}
.wb-badge {{ display: inline-block; font-size: 13px; font-weight: 500; padding: 2px 10px; border-radius: 999px; white-space: nowrap;
  background: {t["track"]}; color: {t["text_sub"]}; }}
.wb-badge.warn {{ background: {t["accent_bg"]}; color: {t["warn_text"]}; }}
.wb-badge.ok {{ background: {t["ok_bg"]}; color: {t["ok_text"]}; }}
.wb-badge.yellow {{ background: {t["yellow_bg"]}; color: {t["yellow_text"]}; }}
.wb-badge.red {{ background: {t["red_bg"]}; color: {t["red_text"]}; }}
.wb-badge.dark {{ background: {t["text"]}; color: #FFFFFF; }}
.wb-badge.tag {{ background: {t["tag_bg"]}; color: {t["tag_text"]}; }}
abbr.wb-term, .wb-term {{ text-decoration: underline dotted {t["line_strong"]}; text-underline-offset: 3px; cursor: help; }}
.wb-help {{ font-size: 13px; color: {t["accent_dark"]}; font-weight: 500; cursor: help; }}
/* top bar and sub row */
.st-key-topbar {{ background: {t["card"]}; border: 1px solid {t["line"]}; border-radius: 12px; padding: 12px 16px 10px; gap: 8px; }}
.wb-brand {{ display: flex; align-items: baseline; gap: 8px; white-space: nowrap; padding-top: 8px; }}
.wb-brand b {{ font-weight: 500; font-size: 20px; letter-spacing: 0.5px; }}
.wb-brand span {{ font-size: 14px; color: {t["text_sub"]}; }}
.wb-ver {{ font-size: 14px; color: {t["text_sub"]}; white-space: nowrap; padding-top: 10px; text-align: right; overflow: hidden; text-overflow: ellipsis; }}
.wb-ver.warn {{ color: {t["warn_text"]}; }}
.wb-subrow {{ display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px; font-size: 14px; color: {t["text_sub"]}; min-height: 32px; }}
.wb-subrow b {{ color: {t["text"]}; font-weight: 500; }}
.wb-band-top {{ background: {t["accent_bg"]}; border: 1px solid {t["accent_line"]}; color: {t["warn_text"]}; border-radius: 8px;
  padding: 8px 14px; font-size: 14px; font-weight: 500; }}
.st-key-search [data-baseweb="select"] > div, .st-key-search .react-aria-ComboBox > div {{ min-height: 46px; border: 1.5px solid {t["line_strong"]} !important;
  border-radius: 10px !important; font-size: 17px; font-weight: 500; background: #FFFFFF; }}
.st-key-units button, .st-key-modeseg button {{ min-height: 28px !important; padding: 0 8px !important; font-size: 13px !important; }}
/* work tabs = segmented control styled as underline tabs */
.st-key-wbtabs [data-testid="stButtonGroup"], .st-key-wbtabs div:has(> button) {{ border-bottom: 1px solid {t["line"]}; overflow-x: auto;
  flex-wrap: nowrap !important; gap: 2px; }}
.st-key-wbtabs button {{ background: none !important; border: none !important; border-radius: 0 !important; min-height: 48px; padding: 0 14px;
  color: {t["text_sub"]} !important; font-weight: 500; font-size: 15px; box-shadow: none !important; white-space: nowrap; flex: 0 0 auto !important;
  max-width: none !important; }}
.st-key-wbtabs button p {{ overflow: visible !important; text-overflow: clip !important; white-space: nowrap; }}
.st-key-wbtabs button[data-selected="true"], .st-key-wbtabs button[aria-checked="true"] {{ color: {t["text"]} !important; font-weight: 500;
  box-shadow: inset 0 -3px 0 {t["accent"]} !important; }}
.st-key-wbtabs button[data-selected="true"] *, .st-key-wbtabs button[aria-checked="true"] * {{ color: {t["text"]} !important; font-weight: 500 !important; }}
/* KPI band */
.st-key-kpiband {{ background: {t["card"]}; border: 1px solid {t["line"]}; border-radius: 10px; box-shadow: 0 2px 6px rgba(21,23,27,0.06); padding: 0; gap: 0; }}
.st-key-kpiband [data-testid="stHorizontalBlock"] {{ gap: 0; flex-wrap: wrap; }}
.st-key-kpiband [data-testid="stColumn"] {{ flex: 1 1 0 !important; min-width: 0 !important; padding: 12px 16px; border-left: 1px solid {t["line_soft"]}; }}
.st-key-kpiband [data-testid="stColumn"]:first-child {{ border-left: none; }}
.wb-kpi .k {{ font-size: 12px; color: {t["text_sub"]}; line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.wb-kpi .v {{ font-size: 20px; font-weight: 600; line-height: 1.3; white-space: nowrap; }}
.wb-kpi .v.accent {{ color: {t["accent"]}; }}
.wb-kpi .v.muted {{ color: {t["text_sub"]}; }}
.wb-kpi .s {{ font-size: 12px; color: {t["text_sub"]}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.st-key-kpiband [data-testid="stPopover"] button {{ min-height: 26px !important; padding: 0 8px !important; font-size: 12px !important; margin-top: 2px; }}
@media (max-width: 1180px) {{
  .st-key-kpiband [data-testid="stColumn"] {{ flex: 1 1 33% !important; min-width: 33% !important; border-top: 1px solid {t["line_soft"]}; }}
  .st-key-kpiband [data-testid="stColumn"]:nth-child(4) {{ border-left: none; }}
}}
@media (max-width: 640px) {{
  .st-key-kpiband [data-testid="stColumn"] {{ flex: 1 1 50% !important; min-width: 50% !important; }}
  .st-key-kpiband [data-testid="stColumn"]:nth-child(odd) {{ border-left: none; }}
  .block-container {{ padding: 12px 16px 32px 16px; }}
  .wb-ff .ticks span:nth-child(2), .wb-ff .ticks span:nth-child(4) {{ display: none; }}
  .wb-ff .row {{ grid-template-columns: 84px minmax(0, 1fr) 56px; }}
}}
/* tables */
.wb-tw {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
table.wb-t {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.wb-t th {{ height: 42px; padding: 0 10px; border-bottom: 1px solid {t["text"]}; font-size: 13px; font-weight: 500; color: {t["text_sub"]};
  white-space: nowrap; text-align: right; }}
table.wb-t th.l, table.wb-t td.l {{ text-align: left; }}
table.wb-t th.grp {{ height: 28px; font-size: 12px; text-align: center; border-bottom: 1px solid {t["line_strong"]}; }}
table.wb-t th.blank {{ border-bottom: none; }}
table.wb-t td {{ height: 42px; padding: 0 10px; border-bottom: 1px solid {t["line_soft"]}; white-space: nowrap; text-align: right; font-weight: 400; }}
table.wb-t td.wrap {{ white-space: normal; }}
table.wb-t.compact th, table.wb-t.compact td {{ padding: 0 6px; font-size: 13px; height: 38px; }}
table.wb-t tr.strong td {{ font-weight: 600; }}
table.wb-t tr.top td {{ border-top: 1px solid {t["line_strong"]}; }}
table.wb-t tr.dim td {{ color: {t["text_faint"]}; }}
table.wb-t .sh {{ background: {t["shade"]}; }}
table.wb-t td.neg {{ color: {t["red_text"]}; }}
table.wb-t td.hl {{ background: {t["accent_bg"]}; color: {t["accent_dark"]}; font-weight: 500; }}
table.wb-t td.gap {{ color: {t["accent_dark"]}; font-weight: 500; }}
/* cells and small blocks */
.wb-cells {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
.wb-cells > div {{ display: flex; flex-direction: column; gap: 1px; padding: 8px 12px; border-radius: 8px; background: {t["shade"]}; min-width: 0; }}
.wb-cells .k {{ font-size: 12px; color: {t["text_sub"]}; }}
.wb-cells .v {{ font-size: 14px; font-weight: 500; }}
.wb-cells .s {{ font-size: 12px; color: {t["text_sub"]}; }}
.wb-lines > div {{ display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; font-size: 14px; border-top: 1px solid {t["line_soft"]}; }}
.wb-lines > div.top {{ border-top: 1px solid {t["line_strong"]}; font-weight: 600; }}
.wb-lines > div span:last-child {{ font-weight: 500; white-space: nowrap; text-align: right; }}
.wb-lines > div.top span:last-child {{ font-weight: 600; }}
.wb-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.wb-chip {{ font-size: 13px; font-weight: 500; padding: 4px 10px; border-radius: 999px; background: {t["track"]}; color: {t["text_sub"]}; }}
.wb-chip.g {{ background: {t["ok_bg"]}; color: {t["ok_text"]}; }}
.wb-chip.y {{ background: {t["yellow_bg"]}; color: {t["yellow_text"]}; }}
.wb-chip.r {{ background: {t["red_bg"]}; color: {t["red_text"]}; }}
.wb-prem {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; text-align: center; }}
.wb-prem > div {{ display: flex; flex-direction: column; padding: 8px 4px; border-radius: 8px; background: {t["prem_bg"]}; }}
.wb-prem .k {{ font-size: 12px; color: {t["text_sub"]}; }}
.wb-prem .v {{ font-size: 17px; font-weight: 600; }}
.wb-prem .s {{ font-size: 12px; }}
.wb-progress {{ height: 6px; border-radius: 3px; background: {t["line_soft"]}; margin: 2px 0 6px; }}
.wb-progress > div {{ height: 6px; border-radius: 3px; background: {t["ok_text"]}; }}
.wb-ff {{ display: flex; flex-direction: column; gap: 10px; }}
.wb-ff .row {{ display: grid; grid-template-columns: 104px minmax(0, 1fr) 64px; align-items: center; gap: 10px; }}
.wb-ff .lab {{ display: flex; flex-direction: column; }}
.wb-ff .lab b {{ font-size: 14px; font-weight: 500; }}
.wb-ff .lab span {{ font-size: 12px; color: {t["text_sub"]}; }}
.wb-ff .track {{ position: relative; height: 20px; background: {t["track"]}; border-radius: 4px; }}
.wb-ff .val {{ font-size: 14px; font-weight: 500; text-align: right; }}
.wb-ff .ticks {{ display: flex; justify-content: space-between; font-size: 12px; color: {t["text_sub"]}; }}
.wb-legend {{ display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }}
.wb-evrow {{ display: grid; grid-template-columns: 92px minmax(0, 1fr) 64px 120px; gap: 0 12px; align-items: center; min-height: 40px; font-size: 14px; }}
.wb-evdiv {{ display: flex; align-items: center; gap: 10px; height: 30px; font-size: 13px; color: {t["accent_dark"]}; font-weight: 500; }}
.wb-evdiv span:last-child {{ flex: 1; border-top: 1px dashed {t["accent_line"]}; }}
.wb-foot {{ font-size: 13px; line-height: 1.6; color: {t["text_sub"]}; margin-top: 8px; }}
.wb-quote {{ color: {t["text_sub"]}; font-size: 13px; border-left: 3px solid {t["line"]}; padding-left: 8px; display: block; margin-top: 4px; quotes: none; }}
.wb-step {{ display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; }}
.wb-hold {{ background: {t["card"]}; border: 1px solid {t["accent_line"]}; border-radius: 12px; padding: 24px 28px; }}
.wb-hold h1 {{ margin: 6px 0; font-size: 22px; font-weight: 600; line-height: 1.4; }}
[data-testid="stExpander"] details {{ border-radius: 8px; border-color: {t["line_soft"]}; }}
[data-testid="stExpander"] summary p {{ font-size: 14px; font-weight: 500; }}
button[data-variant="segmented_control"][data-selected="true"] {{ background: {t["accent_bg"]} !important; border-color: {t["accent"]} !important; }}
button[data-variant="segmented_control"][data-selected="true"], button[data-variant="segmented_control"][data-selected="true"] * {{
  color: {t["accent_dark"]} !important; font-weight: 500; }}
[data-tag] {{ background: {t["accent_bg"]} !important; border: 1px solid {t["accent_line"]} !important; }}
[data-tag], [data-tag] * {{ color: {t["accent_dark"]} !important; }}
/* fixed KPI bar, expand overlay, shortcut window, computing state, phone top row */
.st-key-kviclient {{ height: 0 !important; min-height: 0 !important; overflow: hidden; margin: 0 !important; }}
.st-key-kviclient iframe {{ height: 0 !important; border: 0; }}
.st-key-minibar {{ display: none !important; }}
body.kvi-mini .st-key-minibar {{ display: flex !important; position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
  height: 44px; padding: 0 28px; background: {t["card"]}; border-bottom: 1px solid {t["line"]};
  box-shadow: 0 2px 8px rgba(21, 23, 27, 0.06); align-items: center; }}
.st-key-minibar [data-testid="stHorizontalBlock"] {{ align-items: center; flex-wrap: nowrap; gap: 12px; }}
.st-key-minibar button {{ min-height: 30px !important; height: 30px; font-size: 13px !important; }}
.kvi-mini-items {{ display: flex; gap: 20px; align-items: baseline; overflow-x: auto; white-space: nowrap; font-size: 14px; }}
.kvi-mini-items .i {{ display: inline-flex; gap: 6px; align-items: baseline; }}
.kvi-mini-items .k {{ font-size: 12px; color: {t["text_sub"]}; }}
.kvi-mini-items .v {{ font-weight: 600; }}
.kvi-mini-items .d {{ font-size: 12px; color: {t["text_sub"]}; }}
body.kvi-exp .kvi-mini-items {{ visibility: hidden; }}
.kvi-exp-btn {{ height: 30px; padding: 0 10px; border: 1px solid {t["line"]}; border-radius: 6px; background: {t["card"]};
  color: {t["text_sub"]}; font-size: 13px; cursor: pointer; white-space: nowrap; font-family: inherit; }}
.kvi-exp-btn .x, body.kvi-exp .kvi-exp-btn .o {{ display: none; }}
body.kvi-exp .kvi-exp-btn .x {{ display: inline; }}
.kvi-overlay {{ position: fixed; top: 44px; z-index: 999; background: {t["card"]}; padding: 10px 14px; border: 1px solid {t["line"]};
  border-top: 0; border-radius: 0 0 10px 10px; box-shadow: 0 8px 20px rgba(21, 23, 27, 0.12); }}
body.kvi-mini [data-testid="stToastContainer"] {{ top: 52px !important; bottom: auto !important; }}
#kvi-help {{ position: fixed; right: 24px; bottom: 24px; z-index: 1001; width: 280px; padding: 14px 16px; background: {t["card"]};
  border: 1px solid {t["line"]}; border-radius: 10px; box-shadow: 0 8px 24px rgba(21, 23, 27, 0.14); font-size: 14px;
  font-family: {FONT_WORK}; color: {t["text"]}; display: flex; flex-direction: column; gap: 6px; }}
#kvi-help .h {{ display: flex; justify-content: space-between; align-items: center; }}
#kvi-help .h b {{ font-weight: 600; }}
#kvi-help .h button {{ border: none; background: none; color: {t["text_sub"]}; cursor: pointer; font-size: 14px; }}
#kvi-help .r {{ display: flex; justify-content: space-between; gap: 12px; color: {t["text_sub"]}; }}
#kvi-help kbd {{ font-family: inherit; font-size: 13px; padding: 0 6px; border: 1px solid {t["line"]}; border-radius: 4px; color: {t["text"]}; white-space: nowrap; }}
.wb-ver .calc {{ display: none; }}
.stApp[data-test-script-state="running"] .wb-ver .n {{ display: none; }}
.stApp[data-test-script-state="running"] .wb-ver .calc {{ display: inline; color: {t["accent_dark"]}; }}
.stApp[data-test-script-state="running"] .wb-kpi .v, .stApp[data-test-script-state="running"] .kvi-mini-items .v {{ opacity: 0.35; }}
[class*="st-key-jc_s_"] button {{ height: auto !important; min-height: 40px; padding: 4px 8px; }}
[class*="st-key-jc_s_"] button p, [class*="st-key-jc_s_"] button div {{ white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; line-height: 1.3; font-size: 13px !important; }}
[class*="st-key-jc_s_"][class*="_on"] button, [class*="st-key-jc_f_"][class*="_on"] button {{ border: 2px solid {t["accent"]} !important; color: {t["accent_dark"]} !important; background: {t["accent_bg"]} !important; }}
[class*="st-key-jc_f_"] button {{ height: auto !important; min-height: 40px; padding: 4px 10px; }}
[class*="st-key-jc_f_"] button p, [class*="st-key-jc_f_"] button div {{ white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; line-height: 1.3; }}
[class*="st-key-copyhead_"] [data-testid="stColumn"]:last-child {{ flex: 0 0 60px !important; min-width: 60px !important; }}
[class*="st-key-copyhead_"] [data-testid="stColumn"]:first-child {{ flex: 1 1 auto !important; min-width: 0 !important; }}
.wb-foot a {{ color: {t["text_sub"]}; }}
[class*="st-key-sensgrid_"] {{ gap: 4px !important; }}
[class*="st-key-sensgrid_"] [data-testid="stHorizontalBlock"] {{ gap: 3px !important; }}
[class*="st-key-sensgrid_"] [data-testid="stColumn"] {{ min-width: 0 !important; }}
[class*="st-key-sc_"] button {{ min-height: 30px !important; height: 30px; padding: 0 2px !important; border-radius: 4px;
  border: 1px solid {t["line_soft"]}; background: {t["card"]}; }}
[class*="st-key-sc_"] button p {{ font-size: 13px !important; white-space: nowrap; font-variant-numeric: tabular-nums; }}
[class*="st-key-sc_"][class*="_base"] button {{ background: {t["accent_bg"]} !important; }}
[class*="st-key-sc_"][class*="_base"] button p {{ color: {t["accent_dark"]} !important; }}
[class*="st-key-sc_"][class*="_sel"] button {{ border: 2px solid {t["accent"]} !important; }}
.wb-sg-h {{ font-size: 12px; color: {t["text_sub"]}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 2px 0; }}
.wb-sg-h.r {{ text-align: center; }}
[class*="st-key-sensgrid_"] [data-testid="stMarkdownContainer"], [class*="st-key-sensgrid_"] .stMarkdown {{ margin-bottom: 0 !important; }}
[class*="st-key-sensgrid_"] [data-testid="stHorizontalBlock"]:first-of-type {{ min-height: 22px; margin-bottom: 2px; }}
.wb-sg-r {{ font-size: 13px; color: {t["text_sub"]}; white-space: nowrap; padding-top: 5px; }}
.st-key-topbar [data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"],
.st-key-topbar [data-testid="stPopoverButton"] > div > div[aria-hidden="true"] {{ display: none !important; }}
.st-key-topbar [data-testid="stPopoverButton"] {{ min-width: 44px; justify-content: center; }}
.st-key-topbar [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {{ font-size: 22px; }}
[class*="st-key-plain_tab_"] {{ margin-top: -6px; }}
[data-testid="stElementContainer"]:has(#kvi-state), body:not(.kvi-mini) [data-testid="stLayoutWrapper"]:has(> .st-key-minibar) {{ display: none !important; }}
.wb-sens-pv {{ font-size: 14px; padding: 8px 12px; border-radius: 8px; background: {t["shade"]}; }}
.st-key-sensapply {{ background: {t["accent_bg"]}; border: 1px solid {t["accent_line"]}; border-radius: 10px; padding: 8px 12px; margin-bottom: 8px; }}
.wb-ver-note {{ font-size: 12px; color: {t["warn_text"]}; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: help; }}
.st-key-scenrow [data-testid="stButtonGroup"], .st-key-scenrow [data-testid="stElementContainer"] {{ display: flex; justify-content: flex-end; }}
@media (max-width: 767px) {{
  .st-key-topbar [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; gap: 6px; }}
  .st-key-topbar [data-testid="stColumn"] {{ min-width: 0 !important; width: auto !important; flex: 1 1 auto !important; }}
  .st-key-topbar [data-testid="stColumn"]:has(.st-key-top_history) {{ display: none !important; }}
  .wb-brand span, .wb-ver-note {{ display: none; }}
  .st-key-topbar [data-testid="stColumn"]:has(.wb-brand) {{ flex: 0 0 40px !important; min-width: 40px !important; }}
  .wb-brand b {{ font-size: 15px; }}
  .st-key-topbar [data-testid="stColumn"]:has(.st-key-top_export) {{ flex: 0 0 96px !important; min-width: 96px !important; }}
  .st-key-topbar [data-testid="stColumn"]:has([data-testid="stPopover"]) {{ flex: 0 0 44px !important; min-width: 44px !important; }}
  .st-key-topbar [data-testid="stColumn"]:has(.wb-ver) {{ flex: 0 1 84px !important; min-width: 0 !important; overflow: hidden; }}
  .wb-ver {{ font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .st-key-top_export button p {{ font-size: 0 !important; }}
  .st-key-top_export button p::after {{ content: '확정'; font-size: 14px; }}
  body.kvi-mini .st-key-minibar {{ padding: 0 12px; }}
  .kvi-mini-items .i:nth-child(n+3) {{ display: none; }}
}}
"""
    if kind == "ref":
        base += f"""
.stApp, [data-testid="stAppViewContainer"] {{ background: #FFFFFF; }}
.block-container {{ max-width: 1080px; }}
.wb-ref-title {{ font-size: 30px; font-weight: 600; margin: 4px 0 10px 0; color: {t["text"]}; line-height: 1.3; }}
.wb-ref-h2 {{ font-size: 20px; font-weight: 600; margin: 24px 0 8px 0; color: {t["text"]}; }}
.wb-ref-lead {{ font-size: 16px; line-height: 1.75; color: #33363C; max-width: 760px; }}
.wb-find {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin: 18px 0; }}
.wb-find div {{ border-top: 3px solid {t["text"]}; padding-top: 10px; }}
.wb-find b {{ font-size: 28px; font-weight: 600; display: block; color: {t["text"]}; }}
.wb-find span {{ font-size: 14px; line-height: 1.6; color: #33363C; }}
.wb-refnav {{ border-bottom: 1px solid {t["line"]}; padding-bottom: 10px; margin-bottom: 18px; }}
.wb-refnav b {{ font-weight: 500; letter-spacing: 0.04em; font-size: 18px; margin-right: 8px; }}
.wb-method p, .wb-method li {{ font-size: 15px; line-height: 1.75; color: #33363C; }}
.wb-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 4px 0 8px 0; }}
.wb-card {{ background: {t["card"]}; border: 1px solid {t["line"]}; border-radius: 12px; padding: 18px; display: flex; flex-direction: column; gap: 6px; }}
.wb-kpi-label {{ font-size: 13px; color: {t["text_sub"]}; }}
.wb-kpi-value {{ font-size: 24px; font-weight: 600; line-height: 1.2; }}
.wb-kpi-value small {{ font-size: 14px; font-weight: 500; margin-left: 3px; }}
table.wb-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.wb-table th {{ color: {t["text_sub"]}; font-weight: 500; text-align: left; padding: 7px 8px 7px 0; border-bottom: 1px solid {t["line"]}; white-space: nowrap; }}
table.wb-table td {{ padding: 7px 8px 7px 0; border-bottom: 1px solid {t["line_soft"]}; vertical-align: top; }}
table.wb-table td.num, table.wb-table th.num {{ text-align: right; white-space: nowrap; }}
.wb-table-wrap {{ overflow-x: auto; }}
"""
    else:
        base += f"""
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: {t["page"]}; }}
.wb-table-wrap {{ overflow-x: auto; }}
table.wb-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.wb-table th {{ color: {t["text_sub"]}; font-weight: 500; text-align: left; padding: 7px 8px 7px 0; border-bottom: 1px solid {t["line"]}; white-space: nowrap; }}
table.wb-table td {{ padding: 7px 8px 7px 0; border-bottom: 1px solid {t["line_soft"]}; vertical-align: top; }}
table.wb-table td.num, table.wb-table th.num {{ text-align: right; white-space: nowrap; }}
"""
    return base


def inject(kind: str = "work") -> None:
    st.markdown(f"<style>{_css(kind)}</style>", unsafe_allow_html=True)


def _lum(hexcol: str) -> float:
    h = hexcol.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio of two hex colours."""
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)
