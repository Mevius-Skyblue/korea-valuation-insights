"""P7-U2 browser-side helpers of the work screen (config/p7u2.yaml kpi_bar, shortcuts, save_guard), one small script.

Streamlit draws the page; a few things only the browser knows: whether the KPI band has scrolled out of view, key presses,
and the window being closed. A zero-height st.iframe (same origin, like the copy button) puts one <script> into the app
document once per version; the script reads the screen state from a hidden element (#kvi-state, drawn by Python on every
run) and only adds classes / clicks the screen's own buttons - it keeps no state of its own on the server.

    body.kvi-mini   the KPI band is out of view on a tab with the bar -> the fixed 44px bar (CSS in style.py) shows
    body.kvi-exp    the bar's [▾ 펼치기]: a copy of the six KPI cells lies under the bar (closed by ▴, outside click, top)
    keys            1-7 tabs, J / K judgement rows, Ctrl K or / search, Esc close, ? key list (ignored while typing)
    beforeunload    a warning when there are changes after the last confirmation (data-dirty > 0)
"""

from __future__ import annotations

import streamlit as st

from app.wb import components as ui

VERSION = "u2-2"
KEYS = [
    ("1 ~ 7", "작업 탭 이동"),
    ("J / K", "판단 목록 다음 · 이전 항목"),
    ("Ctrl K 또는 /", "회사 검색"),
    ("Esc", "열린 창 닫기"),
    ("?", "단축키 목록"),
]

_JS = r"""
(function () {
  var W = window, D = W.document;  // runs in the app document (put there by the iframe below)
  function S() { var e = D.getElementById('kvi-state'); return e ? e.dataset : {}; }
  function main() { return D.querySelector('section.stMain') || D.querySelector('[data-testid="stMain"]'); }
  function toTop() { var m = main(); if (m) m.scrollTop = 0; W.scrollTo(0, 0); }
  // ---------------------------------------------------------------- KPI bar
  var io = null, band = null, lastPage = null;
  function collapse() { D.body.classList.remove('kvi-exp'); var o = D.getElementById('kvi-overlay'); if (o) o.remove(); }
  function expand() {
    var b = D.querySelector('.st-key-kpiband'); if (!b) return;
    collapse();
    var o = b.cloneNode(true); o.id = 'kvi-overlay'; o.className = 'kvi-overlay';
    var rc = b.getBoundingClientRect(); o.style.left = (rc.left - 14) + 'px'; o.style.width = (rc.width + 28) + 'px';
    o.querySelectorAll('button, input, iframe').forEach(function (x) { x.setAttribute('tabindex', '-1'); x.disabled = true; });
    D.body.appendChild(o); D.body.classList.add('kvi-exp');
  }
  function watch() {
    var s = S(), b = D.querySelector('.st-key-kpiband');
    if (s.page && s.page !== lastPage) { if (lastPage !== null) { toTop(); collapse(); } lastPage = s.page; }
    if (s.bar !== '1' || !b) { D.body.classList.remove('kvi-mini'); collapse(); }
    if (b !== band) {
      if (io) io.disconnect();
      band = b;
      if (b) {
        io = new W.IntersectionObserver(function (es) {
          var vis = es[es.length - 1].isIntersecting;
          D.body.classList.toggle('kvi-mini', !vis && S().bar === '1');
          if (vis) collapse();
        }, { threshold: 0 });
        io.observe(b);
      }
    }
  }
  var pending = false;
  new W.MutationObserver(function () {
    if (pending) return; pending = true;
    W.requestAnimationFrame(function () { pending = false; watch(); });
  }).observe(D.body, { childList: true, subtree: true });
  D.addEventListener('click', function (e) {
    var t = e.target.closest ? e.target.closest('.kvi-exp-btn') : null;
    if (t) { e.preventDefault(); e.stopPropagation(); D.body.classList.contains('kvi-exp') ? collapse() : expand(); return; }
    if (e.target.closest && e.target.closest('.kvi-help-x')) { hideHelp(); return; }
    if (D.body.classList.contains('kvi-exp') && !(e.target.closest && (e.target.closest('#kvi-overlay') || e.target.closest('.st-key-minibar')))) collapse();
  }, true);
  // ---------------------------------------------------------------- shortcuts
  function focusSearch() {
    var i = D.querySelector('.st-key-search input'); if (!i) return;
    toTop(); i.focus(); i.click();
  }
  function help() { return D.getElementById('kvi-help'); }
  function hideHelp() { var h = help(); if (h) h.remove(); }
  function toggleHelp() {
    if (help()) { hideHelp(); return; }
    var h = D.createElement('div'); h.id = 'kvi-help'; h.setAttribute('role', 'dialog'); h.setAttribute('aria-label', '단축키');
    h.innerHTML = __HELP__;
    D.body.appendChild(h);
  }
  function moveJ(step) {
    var xs = Array.prototype.slice.call(D.querySelectorAll('[class*="st-key-jx_"]'));
    if (!xs.length) return;
    var cur = xs.findIndex(function (x) { var d = x.querySelector('details'); return d && d.open; });
    var nxt = cur < 0 ? (step > 0 ? 0 : xs.length - 1) : Math.min(Math.max(cur + step, 0), xs.length - 1);
    if (nxt === cur) return;
    if (cur >= 0) { var s0 = xs[cur].querySelector('summary'); if (s0) s0.click(); }
    var s1 = xs[nxt].querySelector('summary'); if (s1) { s1.click(); xs[nxt].scrollIntoView({ block: 'start', behavior: 'smooth' }); }
  }
  D.addEventListener('keydown', function (e) {
    var a = D.activeElement, tag = (a && a.tagName || '').toLowerCase();
    var typing = tag === 'input' || tag === 'textarea' || tag === 'select' || (a && a.isContentEditable);
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); focusSearch(); return; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key >= '1' && e.key <= '7') {
      var bs = D.querySelectorAll('.st-key-wbtabs button'); var b = bs[+e.key - 1];
      if (b) { e.preventDefault(); b.click(); }
      return;
    }
    if (e.key === '/') { e.preventDefault(); focusSearch(); return; }
    if (e.key === '?') { e.preventDefault(); toggleHelp(); return; }
    if (e.key === 'Escape') { hideHelp(); collapse(); return; }
    if (e.key === 'j' || e.key === 'J') { e.preventDefault(); moveJ(1); return; }
    if (e.key === 'k' || e.key === 'K') { e.preventDefault(); moveJ(-1); return; }
  });
  // ---------------------------------------------------------------- close warning
  function guard(e) { if (+(S().dirty || 0) > 0) { e.preventDefault(); e.returnValue = ''; return ''; } }
  W.addEventListener('beforeunload', guard);
  try { if (W.top && W.top !== W) W.top.addEventListener('beforeunload', guard); } catch (err) { /* another origin */ }
  watch();
})();
"""


def _help_html() -> str:
    rows = "".join(f"<div class='r'><span>{ui.esc(d)}</span><kbd>{ui.esc(k)}</kbd></div>" for k, d in KEYS)
    return f"<div class='h'><b>단축키</b><button type='button' class='kvi-help-x' aria-label='닫기'>✕</button></div>{rows}"


def state(page: str, bar: bool, dirty: int, public: bool) -> None:
    """The hidden element the script reads (drawn on every run)."""
    st.markdown(
        f"<div id='kvi-state' style='display:none' data-page='{ui.esc(page)}' data-bar='{int(bar)}' "
        f"data-dirty='{int(dirty)}' data-public='{int(public)}'></div>",
        unsafe_allow_html=True,
    )


def inject() -> None:
    """Zero-height iframe that puts the script into the app document once per VERSION."""
    import json

    js = _JS.replace("__HELP__", json.dumps(_help_html(), ensure_ascii=False))
    v = json.dumps(VERSION)
    boot = (
        f"(function(){{var P=window.parent;if(P.__kvi==={v})return;P.__kvi={v};"
        f"var s=P.document.createElement('script');s.textContent={json.dumps(js)};P.document.head.appendChild(s);}})();"
    )
    html = "<script>" + boot.replace("</", "<\\/") + "</script>"
    with st.container(key="kviclient"):
        st.iframe(html, height=1)


def keys_text() -> str:
    """The key list for the ⋯ menu."""
    return " · ".join(f"{k} {d}" for k, d in KEYS)
