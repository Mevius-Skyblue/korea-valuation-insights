"""Design tokens and the one shared stylesheet of the work screen (config/p7c2.yaml app.theme / fonts).

Tokens follow the design reference (data/design_ref/README.md, git-ignored): dark sidebar, warm grey page, white cards,
orange accent. `inject(kind)` writes the CSS once per run: kind 'work' (steps 1~5, B dashboard style) or 'ref'
(reference pages, A report style: white page, serif titles, no sidebar).
"""
from __future__ import annotations

import streamlit as st

T = {
    "sidebar": "#16181D", "sidebar_text": "#E8E8E8", "sidebar_sub": "#A8ABB2", "sidebar_line": "#3A3E47",
    "sidebar_active": "#2A2E36", "sidebar_input": "#23262D",
    "page": "#F4F4F2", "card": "#FFFFFF", "line": "#E4E4E0", "line_soft": "#F0F0EC",
    "text": "#15171B", "text_sub": "#5A5E66", "text_faint": "#A8ABB2",
    "accent": "#F07224", "warn_text": "#9A3412", "accent_bg": "#FFF1E6", "accent_line": "#F7C9A6",
    "warn": "#F59F00", "strong_warn": "#E8590C", "ok_text": "#1E6B3A", "ok_bg": "#E8F4EC",
    "bar_dark": "#4A4F59", "band": "#D9D9D4", "track": "#EFEFEC", "block_bar": "#F7B27A",
}
FONT_WORK = "'IBM Plex Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
FONT_SERIF = "'Noto Serif KR', 'Batang', serif"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700"
             "&family=Noto+Serif+KR:wght@600;700&display=swap")

# text / background pairs used on the screen (checked for WCAG AA in tests/test_p7c2.py)
CONTRAST_PAIRS = [("text", "card"), ("text", "page"), ("text_sub", "card"), ("text_sub", "page"), ("warn_text", "card"),
                  ("warn_text", "accent_bg"), ("text", "accent"), ("sidebar_text", "sidebar"), ("sidebar_sub", "sidebar"),
                  ("sidebar_text", "sidebar_active"), ("ok_text", "ok_bg"), ("text", "accent_bg"), ("text_sub", "line_soft")]


def _css(kind: str) -> str:
    t = T
    base = f"""
@import url('{FONTS_URL}');
html, body, .stApp, [data-testid="stAppViewContainer"], button, input, textarea, select, label,
.stMarkdown, [data-testid="stMarkdownContainer"] {{ font-family: {FONT_WORK}; }}
.stApp {{ color: {t['text']}; font-feature-settings: 'tnum' 1; font-variant-numeric: tabular-nums; }}
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stToolbarActions"],
[data-testid="stAppDeployButton"], [data-testid="stSidebarNav"] {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; height: 2.5rem; }}
.block-container {{ padding: 2rem 2rem 3rem 2rem; max-width: 1400px; }}
h1, h2, h3 {{ color: {t['text']}; letter-spacing: -0.01em; }}
a {{ color: {t['text']}; }}
a:hover {{ color: {t['warn_text']}; }}
/* buttons: primary = orange with dark text (AA contrast), others white with a grey line */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{ border-radius: 8px; min-height: 40px; font-weight: 500; }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: {t['accent']}; border-color: {t['accent']}; color: {t['text']}; font-weight: 600; }}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {{ background: #E8650F; color: {t['text']}; }}
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {{ background: #FFFFFF; border: 1px solid #C9CBCF; color: {t['text']}; }}
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible {{ outline: 3px solid {t['text']}; outline-offset: 2px; }}
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{ border-radius: 8px !important; }}
/* cards: bordered containers with a key starting with card_ */
[class*="st-key-card_"] {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 12px; padding: 20px 22px; }}
[class*="st-key-card_"] [class*="st-key-card_"] {{ border: 0; padding: 0; }}
.wb-card {{ background: {t['card']}; border: 1px solid {t['line']}; border-radius: 12px; padding: 20px; display: flex;
  flex-direction: column; gap: 8px; height: 100%; box-sizing: border-box; }}
.wb-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 4px 0 8px 0; }}
.wb-kpi-label {{ font-size: 13px; color: {t['text_sub']}; }}
.wb-kpi-value {{ font-size: clamp(22px, 2.1vw, 30px); font-weight: 700; line-height: 1.15; color: {t['text']}; }}
.wb-kpi-value small {{ font-size: 15px; font-weight: 500; margin-left: 3px; }}
.wb-kpi-note {{ font-size: 12px; color: {t['text_sub']}; line-height: 1.5; }}
.wb-warn {{ color: {t['warn_text']}; font-weight: 600; }}
.wb-eyebrow {{ font-size: 13px; color: {t['text_sub']}; margin: 0; }}
.wb-title {{ margin: 2px 0 6px 0; font-size: 32px; font-weight: 700; letter-spacing: -0.01em; color: {t['text']}; line-height: 1.2; }}
.wb-h2 {{ margin: 0 0 4px 0; font-size: 18px; font-weight: 700; color: {t['text']}; }}
.wb-sub {{ margin: 0 0 8px 0; font-size: 13px; color: {t['text_sub']}; }}
.wb-badge {{ display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px; white-space: nowrap;
  border: 1px solid {t['line']}; background: {t['line_soft']}; color: {t['text']}; }}
.wb-badge.warn {{ background: {t['accent_bg']}; color: {t['warn_text']}; border-color: {t['accent_line']}; }}
.wb-badge.ok {{ background: {t['ok_bg']}; color: {t['ok_text']}; border-color: #BFDCC9; }}
.wb-badge.dark {{ background: {t['text']}; color: #FFFFFF; border-color: {t['text']}; }}
.wb-badge.accent {{ background: {t['accent']}; color: {t['text']}; border-color: {t['accent']}; }}
.wb-chip {{ display: inline-block; padding: 4px 10px; border-radius: 999px; background: {t['page']}; font-size: 12px; color: #33363C; margin: 0 6px 6px 0; }}
.wb-track {{ position: relative; height: 10px; background: {t['track']}; border-radius: 5px; margin: 4px 0; }}
.wb-track .band {{ position: absolute; top: 0; height: 10px; background: {t['band']}; border-radius: 5px; }}
.wb-track .mark {{ position: absolute; top: -3px; width: 4px; height: 16px; margin-left: -2px; background: {t['accent']}; border-radius: 2px; }}
.wb-table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
table.wb-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
table.wb-table th {{ color: {t['text_sub']}; font-weight: 500; text-align: left; padding: 7px 8px 7px 0; border-bottom: 1px solid {t['line']}; white-space: nowrap; }}
table.wb-table td {{ padding: 7px 8px 7px 0; border-bottom: 1px solid {t['line_soft']}; vertical-align: top; }}
table.wb-table td.num, table.wb-table th.num {{ text-align: right; white-space: nowrap; }}
table.wb-table tr:last-child td {{ border-bottom: 0; }}
.wb-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 14px; }}
.wb-list li {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid {t['line_soft']}; padding-bottom: 6px; }}
.wb-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: {t['accent']}; margin-right: 8px; vertical-align: middle; }}
.wb-band-top {{ background: {t['accent_bg']}; border: 1px solid {t['accent_line']}; color: {t['warn_text']}; border-radius: 10px;
  padding: 12px 16px; font-size: 14px; font-weight: 600; margin-bottom: 12px; }}
.wb-hold {{ background: {t['accent_bg']}; border: 1px solid {t['accent_line']}; border-radius: 12px; padding: 18px 20px; margin-bottom: 12px; }}
.wb-hold h3 {{ margin: 0 0 6px 0; font-size: 17px; color: {t['warn_text']}; }}
.wb-foot {{ font-size: 12px; line-height: 1.6; color: {t['text_sub']}; margin-top: 24px; border-top: 1px solid {t['line']}; padding-top: 12px; }}
.wb-quote {{ color: {t['text_sub']}; font-size: 12px; border-left: 3px solid {t['line']}; padding-left: 8px; display: block; margin-top: 4px; quotes: none; }}
abbr.wb-term {{ text-decoration: underline dotted {t['text_sub']}; cursor: help; }}
.wb-src {{ font-size: 11px; color: {t['text_sub']}; }}
.wb-src a {{ color: {t['text_sub']}; }}
.wb-step {{ display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; }}
/* sidebar (design: #16181D, 240px) */
section[data-testid="stSidebar"] {{ background: {t['sidebar']}; width: 240px !important; min-width: 240px !important; }}
section[data-testid="stSidebar"] > div {{ background: {t['sidebar']}; }}
section[data-testid="stSidebar"] * {{ color: {t['sidebar_text']}; }}
section[data-testid="stSidebar"] .wb-side-sub, section[data-testid="stSidebar"] label p {{ color: {t['sidebar_sub']} !important; font-size: 12px; }}
section[data-testid="stSidebar"] .stSelectbox div {{ background-color: {t['sidebar_input']} !important; color: #FFFFFF !important;
  border-color: {t['sidebar_line']} !important; }}
section[data-testid="stSidebar"] .stSelectbox input {{ color: #FFFFFF !important; }}
section[data-testid="stSidebar"] .stButton button {{ background: transparent !important; border: 0 !important; padding: 8px 12px;
  min-height: 38px; width: 100%; box-shadow: none !important; }}
section[data-testid="stSidebar"] .stButton button > div {{ justify-content: flex-start; width: 100%; }}
section[data-testid="stSidebar"] .stButton button p {{ color: #D6D6D6 !important; font-size: 14px; text-align: left; }}
section[data-testid="stSidebar"] .stButton button:hover p {{ color: #FFFFFF !important; }}
section[data-testid="stSidebar"] .stButton button[kind="primary"] {{ background: {t['sidebar_active']} !important; }}
section[data-testid="stSidebar"] .stButton button[kind="primary"] p {{ color: #FFFFFF !important; font-weight: 600; }}
section[data-testid="stSidebar"] .stButton button:disabled p {{ color: #8A8E96 !important; }}
section[data-testid="stSidebar"] .stButton button:focus-visible {{ outline: 2px solid {t['accent']} !important; }}
section[data-testid="stSidebar"] .st-key-nav_judge button {{ border: 1px solid {t['sidebar_line']} !important; }}
.st-key-sticky_panel {{ position: sticky; top: 3rem; }}
/* inputs on white cards: visible field box; selected chips and tags with AA text contrast */
.stMain [data-testid="stTextInputRootElement"], .stMain [data-testid="stDateInputField"] {{ background: #FAFAF8 !important;
  border: 1px solid #C9CBCF !important; border-radius: 8px !important; }}
.stMain .react-aria-ComboBox > div {{ background: #FAFAF8; border: 1px solid #C9CBCF; border-radius: 8px; }}
.stMain [data-testid="stTextInputRootElement"]:focus-within {{ border-color: {t['accent']} !important; }}
button[data-variant="segmented_control"][data-selected="true"] {{ background: {t['accent_bg']} !important; border-color: {t['accent']} !important; }}
button[data-variant="segmented_control"][data-selected="true"], button[data-variant="segmented_control"][data-selected="true"] * {{
  color: {t['warn_text']} !important; font-weight: 600; }}
[data-tag] {{ background: {t['accent_bg']} !important; border: 1px solid {t['accent_line']} !important; }}
[data-tag], [data-tag] * {{ color: {t['warn_text']} !important; }}
.wb-brand b {{ font-size: 22px; letter-spacing: 0.04em; color: #FFFFFF; display: block; }}
.wb-brand span {{ font-size: 13px; color: {t['sidebar_sub']}; }}
.wb-modebox {{ font-size: 12px; color: {t['sidebar_sub']} !important; border: 1px solid {t['sidebar_line']}; border-radius: 8px; padding: 10px 12px;
  line-height: 1.5; margin-top: 12px; }}
.wb-pending {{ font-size: 13px; background: {t['sidebar_active']}; border-radius: 8px; padding: 8px 12px; margin: 6px 0; }}
.wb-pending b {{ color: {t['accent']} !important; }}
@media (max-width: 640px) {{
  .block-container {{ padding: 1rem 1rem 2rem 1rem; }}
  .wb-title {{ font-size: 24px; }}
  .wb-kpi-value {{ font-size: 24px; }}
  .wb-kpis {{ grid-template-columns: 1fr; }}
}}
"""
    if kind == "ref":
        base += f"""
.stApp, [data-testid="stAppViewContainer"] {{ background: #FFFFFF; }}
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{ display: none !important; }}
.block-container {{ max-width: 1080px; }}
.wb-ref-title {{ font-family: {FONT_SERIF} !important; font-size: 36px; font-weight: 700; margin: 4px 0 10px 0; color: {t['text']}; line-height: 1.25; }}
.wb-ref-h2 {{ font-family: {FONT_SERIF} !important; font-size: 22px; font-weight: 700; margin: 26px 0 8px 0; color: {t['text']}; }}
.wb-ref-lead {{ font-size: 16px; line-height: 1.75; color: #33363C; max-width: 760px; }}
.wb-find {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin: 18px 0; }}
.wb-find div {{ border-top: 3px solid {t['text']}; padding-top: 10px; }}
.wb-find b {{ font-family: {FONT_SERIF} !important; font-size: 30px; display: block; color: {t['text']}; }}
.wb-find span {{ font-size: 14px; line-height: 1.6; color: #33363C; }}
.wb-refnav {{ border-bottom: 1px solid {t['line']}; padding-bottom: 10px; margin-bottom: 18px; }}
.wb-refnav b {{ font-weight: 700; letter-spacing: 0.04em; font-size: 18px; margin-right: 8px; }}
.wb-method p, .wb-method li {{ font-size: 15px; line-height: 1.75; color: #33363C; }}
"""
    else:
        base += f"""
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: {t['page']}; }}
"""
    return base


def inject(kind: str = "work") -> None:
    st.markdown(f"<style>{_css(kind)}</style>", unsafe_allow_html=True)


def _lum(hexcol: str) -> float:
    h = hexcol.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio of two hex colours."""
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)
