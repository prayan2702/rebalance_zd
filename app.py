"""
Zerodha Portfolio Rebalancer — Streamlit App (No Kite API)
UI matches the Google Apps Script Portfolio Rebalancer design system.

Secrets required (.streamlit/secrets.toml):
    APP_PIN = "123456"
"""

import math
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    import yfinance as yf
except ImportError:
    st.error("yfinance install karo: pip install yfinance")
    st.stop()

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_AVAILABLE = True
except ImportError:
    _AUTOREFRESH_AVAILABLE = False

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Portfolio Rebalancer",
    page_icon="⚖️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Secrets ───────────────────────────────────────────────────────────────────
try:
    APP_PIN = str(st.secrets["APP_PIN"])
except Exception:
    st.error("⚠️ Streamlit secrets mein APP_PIN set karo")
    st.info('Settings → Secrets:\n```\nAPP_PIN = "123456"\n```')
    st.stop()

# ── Constants ─────────────────────────────────────────────────────────────────
# Zerodha Equity Delivery Charges (exact as per Zerodha calculator)
STT_RATE  = 0.001       # 0.1% on BUY & SELL both
TXN_NSE   = 0.0000307   # NSE 0.00307% transaction charge
SEBI_CH   = 0.000001    # SEBI ₹10/crore = 0.0001%
GST_RATE  = 0.18        # 18% on (TXN + SEBI), brokerage = ₹0
STAMP_BUY = 0.00015     # 0.015% buy side only
BUF_FIXED = 500         # Fixed buffer above actual buy charges (₹500 safety)

# ── Global CSS — matching rebalancer HTML app design system ───────────────────
st.markdown("""
<style>
/* ── Reset & base ── */
#MainMenu, footer, header,
[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stStatusWidget"],[data-testid="collapsedControl"],
[data-testid="stSidebarNav"] { display: none !important; }

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif !important;
    font-size: 13px;
    background: #f0f2f5 !important;
    color: #1a1f2e !important;
}

.main .block-container {
    padding: 0 0 4rem !important;
    max-width: 540px;
    margin: 0 auto;
}
[data-testid="stVerticalBlock"] { gap: 0.35rem !important; }

/* ── Streamlit widget overrides ── */
/* All inputs */
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
    background: #ffffff !important;
    border: 1.5px solid #e4e8ef !important;
    border-radius: 6px !important;
    color: #1a1f2e !important;
    font-size: 13px !important;
    font-family: 'Segoe UI', system-ui, sans-serif !important;
    font-weight: 700 !important;
    text-align: right !important;
    padding: 8px 10px !important;
    letter-spacing: 0 !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus {
    border-color: #1565c0 !important;
    box-shadow: 0 0 0 2px rgba(21,101,192,0.12) !important;
    outline: none !important;
}
div[data-testid="stTextInput"] label,
div[data-testid="stNumberInput"] label { display: none !important; }

/* PIN input special */
.pin-input-wrap div[data-testid="stTextInput"] input {
    font-size: 28px !important;
    letter-spacing: 14px !important;
    text-align: center !important;
    background: rgba(255,255,255,.08) !important;
    border: 2px solid rgba(255,255,255,.2) !important;
    border-radius: 14px !important;
    color: #fff !important;
    padding: 18px 20px !important;
    font-family: 'Courier New', monospace !important;
}
.pin-input-wrap div[data-testid="stTextInput"] input:focus {
    border-color: #ffca28 !important;
    background: rgba(255,202,40,.1) !important;
    box-shadow: none !important;
}

/* Primary buttons */
div[data-testid="stButton"] button {
    width: 100%;
    background: #1a237e !important;
    color: #fff !important;
    border: none !important;
    border-radius: 6px !important;
    font-size: 13px !important;
    font-weight: 700 !important;
    font-family: 'Segoe UI', system-ui, sans-serif !important;
    padding: 10px 16px !important;
    transition: all 0.15s !important;
    min-height: 40px;
    letter-spacing: 0.2px;
}
div[data-testid="stButton"] button:hover  { opacity: .88 !important; transform: translateY(-1px) !important; }
div[data-testid="stButton"] button:active { transform: translateY(0) !important; }
div[data-testid="stButton"] button[kind="secondary"] {
    background: #ffffff !important;
    border: 1.5px solid #e4e8ef !important;
    color: #5a6478 !important;
}
div[data-testid="stButton"] button[kind="secondary"]:hover {
    background: #f8f9fb !important;
    opacity: 1 !important;
}

/* PIN unlock button (yellow) */
.pin-btn-wrap div[data-testid="stButton"] button {
    background: linear-gradient(135deg, #ffca28, #ffa000) !important;
    color: #1a237e !important;
    border-radius: 12px !important;
    font-size: 15px !important;
    font-weight: 900 !important;
    padding: 14px !important;
    min-height: 52px;
    box-shadow: 0 4px 20px rgba(255,202,40,.4);
}
.pin-btn-wrap div[data-testid="stButton"] button:hover {
    transform: translateY(-2px) !important;
    opacity: 1 !important;
    box-shadow: 0 6px 28px rgba(255,202,40,.55) !important;
}

/* File uploader — force light theme on all devices/dark-mode */
[data-testid="stFileUploader"] {
    background: #ffffff !important;
    border: 2px dashed #e4e8ef !important;
    border-radius: 8px !important;
    padding: .8rem 1rem !important;
    color-scheme: light !important;
}
[data-testid="stFileUploader"]:hover { border-color: #1565c0 !important; }
[data-testid="stFileUploader"] label { display: none !important; }
[data-testid="stFileUploader"] section,
[data-testid="stFileUploader"] section > div,
[data-testid="stFileUploadDropzone"] {
    background: #ffffff !important;
    color: #1a1f2e !important;
}
[data-testid="stFileUploadDropzone"] button {
    background: #e8eaf6 !important;
    color: #1a237e !important;
    border-color: #9fa8da !important;
}
[data-testid="stFileUploader"] span,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] p {
    color: #5a6478 !important;
}
/* Uploaded file chip */
[data-testid="stFileUploaderDeleteBtn"],
[data-testid="stUploadedFileData"] {
    background: #f0f2f5 !important;
    color: #1a1f2e !important;
}
[data-testid="stUploadedFileName"] { color: #1a1f2e !important; }
[data-testid="stUploadedFileSize"] { color: #5a6478 !important; }

/* Spinner */
div[data-testid="stSpinner"] p { color: #5a6478 !important; }

/* Alerts */
div[data-testid="stAlert"] { border-radius: 8px !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #e4e8ef; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ── Component CSS (cards, panels) ─────────────────────────────────────────────
st.markdown("""<style>
/* ── PIN OVERLAY ── */
.pin-overlay {
    position: fixed; inset: 0; z-index: 9000;
    background: linear-gradient(135deg, #0a0e2e 0%, #1a237e 55%, #1565c0 100%);
    display: flex; align-items: center; justify-content: center;
    flex-direction: column; padding: 1rem;
    min-height: 100vh;
}
.pin-box { text-align: center; width: 100%; max-width: 340px; }
.pin-logo { font-size: 48px; margin-bottom: 10px; filter: drop-shadow(0 4px 12px rgba(0,0,0,.4)); }
.pin-title { color: #fff; font-size: 20px; font-weight: 800; margin-bottom: 4px; letter-spacing: .3px; }
.pin-subtitle { color: rgba(255,255,255,.5); font-size: 12px; margin-bottom: 24px; }
.pin-hint { color: rgba(255,255,255,.35); font-size: 11px; margin: 8px 0 16px; }
.pin-error-box { color: #ff6b6b; font-size: 12.5px; font-weight: 700;
                 min-height: 20px; margin-top: 10px; letter-spacing: .2px; }
.pin-footer { font-size: 10px; color: rgba(255,255,255,.2);
              margin-top: 28px; letter-spacing: .3px; }

/* Attempt dots */
.att-row { display: flex; justify-content: center; gap: 7px; margin: 12px 0 4px; }
.att-dot { width: 8px; height: 8px; border-radius: 50%;
           background: rgba(255,255,255,.15); display: inline-block; }
.att-dot.used { background: #ff6b6b; }

/* ── HEADER BAR ── */
.rb-header {
    height: 52px;
    background: linear-gradient(135deg, #1a237e, #283593);
    color: #fff;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 14px;
    position: sticky; top: 0; z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,.25);
    margin-bottom: 0;
}
.rb-header-title {
    font-size: 15px; font-weight: 700;
    display: flex; align-items: center; gap: 8px;
}
.rb-header-right { display: flex; align-items: center; gap: 8px; }
.ar-badge {
    font-size: 10.5px; font-weight: 800; border-radius: 14px;
    padding: 3px 10px; border: 1.5px solid; white-space: nowrap;
}
.ar-badge.on  { background: rgba(46,125,50,.2); border-color: #a5d6a7; color: #a5d6a7; }
.ar-badge.off { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.2); color: rgba(255,255,255,.5); }
.ts-badge { font-size: 10px; color: rgba(255,255,255,.5); white-space: nowrap; }

/* ── SUMMARY STRIP ── */
.sum-strip {
    display: grid; grid-template-columns: 1fr 1fr 1fr;
    gap: 6px; padding: 8px 12px;
    background: linear-gradient(90deg, #1a237e, #283593);
}
.sum-pill {
    background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.15);
    border-radius: 8px; padding: 8px 10px; text-align: center;
}
.sum-pill.inv { border-color: rgba(165,214,167,.4); background: rgba(46,125,50,.2); }
.sum-pill.buf { border-color: rgba(239,154,154,.3); background: rgba(198,40,40,.15); }
.sum-pill.lft { border-color: rgba(255,202,40,.3); background: rgba(255,143,0,.15); }
.sum-lbl { display: block; font-size: 8px; font-weight: 700; letter-spacing: .7px;
           text-transform: uppercase; color: rgba(255,255,255,.55); margin-bottom: 3px; }
.sum-val { display: block; font-size: 13px; font-weight: 800; font-family: 'Courier New', monospace; }
.sum-val.g { color: #81c784; }
.sum-val.r { color: #ef9a9a; }
.sum-val.y { color: #ffca28; }

/* ── PANEL / SECTION ── */
.panel {
    background: #ffffff; border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,.08);
    border: 1px solid #e4e8ef;
    margin: 8px 10px; overflow: hidden;
}
.panel-hdr {
    padding: 8px 12px; font-weight: 700; font-size: 11.5px;
    text-transform: uppercase; letter-spacing: .5px;
    display: flex; justify-content: space-between; align-items: center;
    border-bottom: 2px solid;
}
.ph-sell { background: #ffebee; color: #c62828; border-color: #ef9a9a; }
.ph-buy  { background: #e8f5e9; color: #2e7d32; border-color: #a5d6a7; }
.ph-info { background: #e3f2fd; color: #1565c0; border-color: #90caf9; }
.ph-amb  { background: #fffde7; color: #e65100; border-color: #ffe082; }
.ph-navy { background: #e8eaf6; color: #1a237e; border-bottom-color: #9fa8da; }

/* ── STOCK CARDS ── */
.card {
    border-radius: 8px; padding: 12px 14px;
    margin-bottom: 8px; border: 1.5px solid;
}
.card-sell { background: #ffebee; border-color: #ef9a9a; }
.card-buy  { background: #e8f5e9; border-color: #a5d6a7; }
.card.dim  { opacity: .45; }
.c-top {
    display: flex; align-items: center; flex-wrap: wrap;
    justify-content: space-between; gap: 6px; margin-bottom: 10px;
}
.c-sym { font-size: 17px; font-weight: 800; color: #1a1f2e; letter-spacing: .2px; }
.c-ltp {
    font-size: 11px; font-family: 'Courier New', monospace;
    background: #ffffff; color: #5a6478;
    padding: 3px 9px; border-radius: 100px;
    border: 1px solid #e4e8ef; margin-left: auto;
    font-weight: 700;
}
.w-badge {
    font-size: 9px; font-weight: 700; text-transform: uppercase;
    padding: 2px 7px; border-radius: 100px;
    background: #fffde7; color: #e65100; border: 1px solid #ffe082;
}
.c-g3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
.c-g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.c-box { background: #ffffff; border-radius: 6px; padding: 8px 10px;
         border: 1px solid #e4e8ef; }
.c-lbl { display: block; font-size: 9px; font-weight: 700; letter-spacing: .7px;
         text-transform: uppercase; color: #9aa0ad; margin-bottom: 3px; }
.c-num { display: block; font-family: 'Courier New', monospace;
         font-size: 13px; font-weight: 700; color: #1a1f2e; word-break: break-all; }
.c-num.sell { color: #c62828; font-size: 22px; }
.c-num.buy  { color: #2e7d32; font-size: 22px; }
.c-num.sm   { font-size: 11.5px; }
.c-chg { font-size: 10px; color: #9aa0ad; margin-top: 8px;
         font-family: 'Courier New', monospace; }

/* ── BRIDGE ── */
.bridge {
    background: #fffde7; border: 1.5px solid #ffe082;
    border-radius: 8px; padding: 12px 14px; margin: 6px 10px;
}
.b-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 5px 0; border-bottom: 1px solid rgba(0,0,0,.06);
    font-size: 12px; color: #5a6478;
}
.b-row:last-child { border-bottom: none; }
.b-val { font-family: 'Courier New', monospace; font-weight: 700; font-size: 12px; }
.b-val.g { color: #2e7d32; } .b-val.r { color: #c62828; }
.b-row.total { color: #e65100; font-weight: 800; font-size: 14px; padding-top: 8px; }
.b-row.total .b-val { color: #e65100; font-size: 15px; }

/* ── LEFTOVER ── */
.leftover {
    background: #e8f5e9; border: 1.5px solid #a5d6a7;
    border-radius: 8px; padding: 12px 14px;
    display: flex; justify-content: space-between; align-items: center;
    margin: 6px 10px;
}
.leftover .ll { font-size: 12px; color: #5a6478; }
.leftover .lv { font-family: 'Courier New', monospace; font-size: 17px;
                font-weight: 800; color: #2e7d32; }

/* ── UPLOAD SCREEN ── */
.step-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: #e8eaf6; border: 1px solid #9fa8da;
    border-radius: 100px; padding: 4px 12px;
    font-size: 12px; color: #3949ab; font-weight: 600;
    margin-bottom: 10px;
}
.upload-hdr {
    background: linear-gradient(135deg, #1a237e, #283593);
    color: #fff; padding: 14px 16px 12px;
    font-size: 15px; font-weight: 700;
    display: flex; align-items: center; gap: 8px;
}
.info-card {
    background: #e3f2fd; border: 1px solid #90caf9;
    border-radius: 8px; padding: 9px 12px;
    font-size: 12px; color: #1565c0; line-height: 1.7;
    margin-bottom: 6px;
}
.info-card b { color: #0d47a1; }
.info-card a { color: #1565c0; }
.loaded-ok {
    background: #e8f5e9; border: 1px solid #a5d6a7;
    border-radius: 6px; padding: 6px 10px;
    font-size: 12px; color: #2e7d32; font-weight: 600;
    margin: 4px 0;
}
.sym-row-s { font-family: monospace; font-size: 12px;
             color: #c62828; margin: 2px 0; font-weight: 600; }
.sym-row-b { font-family: monospace; font-size: 12px;
             color: #2e7d32; margin: 2px 0; font-weight: 600; }

/* ── SEC TITLES ── */
.sec-title-sell {
    font-size: 13px; font-weight: 800; text-transform: uppercase;
    letter-spacing: .5px; color: #c62828;
    padding: 8px 12px 6px;
    border-bottom: 2px solid #ef9a9a;
    background: #ffebee;
    display: flex; align-items: center; gap: 8px;
}
.sec-title-buy {
    font-size: 13px; font-weight: 800; text-transform: uppercase;
    letter-spacing: .5px; color: #2e7d32;
    padding: 8px 12px 6px;
    border-bottom: 2px solid #a5d6a7;
    background: #e8f5e9;
    display: flex; align-items: center; gap: 8px;
}
.badge-count {
    background: #c62828; color: #fff;
    border-radius: 10px; padding: 1px 7px;
    font-size: 10px;
}
.badge-buy { background: #2e7d32; }
.per-note { font-size: 12px; color: #5a6478; padding: 4px 12px 8px; }
.per-note b { color: #2e7d32; font-family: 'Courier New', monospace; }

/* ── FOOTER ── */
.ftxt {
    text-align: center; font-size: 10px; color: #9aa0ad;
    margin: 16px 10px 8px; line-height: 1.9;
}
.divider { height: 1px; background: #e4e8ef; margin: 8px 10px; }

/* ── Ctrl buttons bar ── */
.ctrl-bar {
    display: flex; gap: 6px; padding: 6px 10px;
    background: #f8f9fb; border-top: 1px solid #e4e8ef;
    position: sticky; top: 52px; z-index: 90;
}

/* ── Mobile ── */
@media (max-width: 480px) {
    .c-g3 { grid-template-columns: 1fr 1fr; }
    .c-num.sell, .c-num.buy { font-size: 18px; }
    .sum-val { font-size: 11px; }
}
</style>""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for _k, _v in {
    "stage": "pin", "sell_syms": [], "buy_syms": [],
    "data": None, "pin_attempts": 0, "auto_refresh": True,
    "pin_key": 0,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Helpers ───────────────────────────────────────────────────────────────────

def inr(n: float, decimals: int = 0) -> str:
    if n is None:
        return "₹—"
    return f"₹{{:,.{decimals}f}}".format(abs(n))


def get_ltp_yfinance(symbols: list) -> dict:
    ltp_map = {s: 0.0 for s in symbols}
    tickers  = [f"{s}.NS" for s in symbols]
    try:
        data = yf.download(
            tickers, period="5d", interval="1d",
            progress=False, auto_adjust=True,
            threads=True, group_by="ticker"
        )
        if not data.empty:
            for sym, ticker in zip(symbols, tickers):
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        series = data[ticker]["Close"].dropna()
                    else:
                        series = data["Close"].dropna()
                    if not series.empty:
                        ltp_map[sym] = round(float(series.iloc[-1]), 2)
                except Exception:
                    pass
    except Exception:
        pass
    missing = [s for s in symbols if ltp_map[s] == 0.0]
    for sym in missing:
        try:
            hist = yf.Ticker(f"{sym}.NS").history(period="5d", interval="1d")
            if not hist.empty:
                ltp_map[sym] = round(float(hist["Close"].dropna().iloc[-1]), 2)
        except Exception:
            pass
    still = [s for s in symbols if ltp_map[s] == 0.0]
    for sym in still:
        try:
            info = yf.Ticker(f"{sym}.NS").fast_info
            val  = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            if val:
                ltp_map[sym] = round(float(val), 2)
        except Exception:
            pass
    return ltp_map


def parse_holdings_file(file) -> dict:
    fname = getattr(file, "name", "")
    ext   = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if ext in ("xlsx", "xls", "xlsm"):
        raw = pd.read_excel(file, sheet_name="Equity", header=None)
        header_row = None
        for idx, row in raw.iterrows():
            vals = [str(v).strip().lower() for v in row.dropna().values]
            if "symbol" in vals:
                header_row = idx
                break
        if header_row is None:
            raise ValueError("'Equity' sheet mein 'Symbol' header row nahi mili.")
        df = pd.read_excel(file, sheet_name="Equity", header=header_row)
        df.columns = df.columns.str.strip()
        sym_col = next((c for c in df.columns if c.lower() == "symbol"), None)
        qty_col = next((c for c in df.columns if "quantity available" in c.lower()), None)
        if not qty_col:
            qty_col = next((c for c in df.columns
                            if "qty" in c.lower() or "quantity" in c.lower()), None)
    else:
        df = pd.read_csv(file)
        df.columns = df.columns.str.strip()
        sym_col = next((c for c in df.columns
                        if c.lower() in ("instrument","symbol","tradingsymbol","stock")), None)
        qty_col = next((c for c in df.columns
                        if "qty" in c.lower() or "quantity" in c.lower()), None)
    if not sym_col or not qty_col:
        raise ValueError(
            f"Holdings file mein Symbol/Quantity columns nahi mile.\n"
            f"Mili columns: {list(df.columns)}"
        )
    hold_map = {}
    for _, row in df.iterrows():
        sym = str(row[sym_col]).strip().upper()
        try:
            qty = int(float(str(row[qty_col]).replace(",", "")))
        except Exception:
            qty = 0
        if sym and sym not in ("NAN", "SYMBOL", "") and qty > 0:
            hold_map[sym] = qty
    return hold_map


def fetch_all(sell_syms, buy_syms, hold_map, cash):
    all_syms = list(set(sell_syms + buy_syms))
    ltp_map  = get_ltp_yfinance(all_syms)
    sell_rows, gross_tot, charge_tot = [], 0.0, 0.0
    for sym in sell_syms:
        ltp   = ltp_map.get(sym, 0.0)
        qty   = hold_map.get(sym, 0)
        gross = qty * ltp
        stt   = gross * STT_RATE             # 0.1% on sell
        txn   = gross * TXN_NSE              # NSE 0.00307%
        sebi  = gross * SEBI_CH              # ₹10/crore
        gst   = (txn + sebi) * GST_RATE      # 18% on txn+sebi (brk=0)
        tc    = stt + txn + sebi + gst
        net   = gross - tc
        gross_tot  += gross
        charge_tot += tc
        sell_rows.append({"sym": sym, "ltp": ltp, "qty": qty, "gross": gross,
                          "stt": stt, "txn": txn, "sebi": sebi, "gst": gst,
                          "total_charges": tc, "net": net, "held": qty > 0})
    sell_net = gross_tot - charge_tot
    pool     = sell_net + cash
    n_buy    = len(buy_syms)

    # ── Pass 1: estimate buy charges with buf=0 to find actual charges ──
    buy_charges_est = 0.0
    if n_buy > 0:
        per_stk_est = pool / n_buy
        for sym in buy_syms:
            ltp_e = ltp_map.get(sym, 0.0)
            qty_e = math.floor(per_stk_est / ltp_e) if ltp_e > 0 else 0
            cost_e = qty_e * ltp_e
            c_e = (cost_e * STT_RATE + cost_e * TXN_NSE +
                   cost_e * SEBI_CH + cost_e * STAMP_BUY +
                   (cost_e * TXN_NSE + cost_e * SEBI_CH) * GST_RATE)
            buy_charges_est += c_e

    # Buffer = actual estimated buy charges + ₹500 fixed safety
    buf     = buy_charges_est + BUF_FIXED
    invest  = pool - buf
    per_stk = invest / n_buy if n_buy > 0 else 0.0

    # ── Pass 2: final buy rows with corrected invest ──
    buy_rows, buy_cost = [], 0.0
    for sym in buy_syms:
        ltp       = ltp_map.get(sym, 0.0)
        qty       = math.floor(per_stk / ltp) if ltp > 0 else 0
        cost      = qty * ltp
        stt_b     = cost * STT_RATE              # 0.1% on buy
        txn_b     = cost * TXN_NSE               # NSE 0.00307%
        sebi_b    = cost * SEBI_CH               # ₹10/crore
        stamp_b   = cost * STAMP_BUY             # 0.015% buy only
        gst_b     = (txn_b + sebi_b) * GST_RATE  # 18% on txn+sebi
        charges_b = stt_b + txn_b + sebi_b + stamp_b + gst_b
        buy_cost += cost + charges_b
        buy_rows.append({"sym": sym, "ltp": ltp, "qty": qty, "cost": cost,
                         "stt": stt_b, "txn": txn_b, "sebi": sebi_b,
                         "stamp": stamp_b, "gst": gst_b, "charges": charges_b})
    return {
        "ts": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "sell_rows": sell_rows, "buy_rows": buy_rows,
        "gross_tot": round(gross_tot, 2), "charge_tot": round(charge_tot, 2),
        "sell_net": round(sell_net, 2), "cash": round(cash, 2),
        "pool": round(pool, 2), "buf": round(buf, 2), "invest": round(invest, 2),
        "per_stk": round(per_stk, 2), "buy_cost": round(buy_cost, 2),
        "leftover": round(invest - buy_cost, 2), "n_buy": n_buy,
    }


# ── Card builders ─────────────────────────────────────────────────────────────

def sell_card(r):
    dim  = " dim" if not r["held"] else ""
    warn = '<span class="w-badge">Holdings mein nahi</span>' if not r["held"] else ""
    return f"""<div class="card card-sell{dim}">
  <div class="c-top">
    <span class="c-sym">{r['sym']}</span>{warn}
    <span class="c-ltp">₹{r['ltp']:,.2f}</span>
  </div>
  <div class="c-g3">
    <div class="c-box"><span class="c-lbl">Sell Qty</span>
      <span class="c-num sell">{r['qty']}</span></div>
    <div class="c-box"><span class="c-lbl">Gross Value</span>
      <span class="c-num sm">{inr(r['gross'])}</span></div>
    <div class="c-box"><span class="c-lbl">Net (after charges)</span>
      <span class="c-num sm">{inr(r['net'])}</span></div>
  </div>
  <div class="c-chg">STT {inr(r['stt'],2)} · Txn {inr(r['txn'],2)} · SEBI {inr(r['sebi'],2)} · GST {inr(r['gst'],2)}</div>
</div>"""


def buy_card(r):
    return f"""<div class="card card-buy">
  <div class="c-top">
    <span class="c-sym">{r['sym']}</span>
    <span class="c-ltp">₹{r['ltp']:,.2f}</span>
  </div>
  <div class="c-g2">
    <div class="c-box"><span class="c-lbl">Buy Qty</span>
      <span class="c-num buy">{r['qty']}</span></div>
    <div class="c-box"><span class="c-lbl">Total Cost (incl. charges)</span>
      <span class="c-num sm">{inr(r['cost']+r['charges'])}</span></div>
  </div>
  <div class="c-chg">Base {inr(r['cost'])} · STT {inr(r['stt'],2)} · Txn {inr(r['txn'],2)} · Stamp {inr(r['stamp'],2)} · GST {inr(r['gst'],2)}</div>
</div>"""


def bridge_html(d):
    return f"""<div class="bridge">
  <div class="b-row"><span>Sell net proceeds</span>
    <span class="b-val g">{inr(d['sell_net'])}</span></div>
  <div class="b-row"><span>+ Available cash / margin</span>
    <span class="b-val g">{inr(d['cash'])}</span></div>
  <div class="b-row"><span>− Buffer (buy charges + ₹500)</span>
    <span class="b-val r">−{inr(d['buf'])}</span></div>
  <div class="b-row total"><span>= Investable Fund</span>
    <span class="b-val">{inr(d['invest'])}</span></div>
</div>"""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: PIN  — navy gradient overlay, yellow button (exact match)          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_pin():
    used = st.session_state.pin_attempts
    err  = st.session_state.pop("_pin_err", "")

    # ── Full-page navy gradient + PIN input overrides ─────────────────────────
    st.markdown("""
    <style>
    /* ── PIN page: full-screen navy gradient ── */
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        background: linear-gradient(135deg,#0a0e2e 0%,#1a237e 55%,#1565c0 100%) !important;
        min-height: 100vh !important;
        min-height: -webkit-fill-available !important;
    }
    .main .block-container {
        background: transparent !important;
        max-width: 340px !important;
        margin: 0 auto !important;
        padding: 0 16px 40px !important;
        padding-top: max(72px, 14vh) !important;
    }
    [data-testid="stVerticalBlock"] { gap: 0.2rem !important; }

    /* PIN input — high specificity + iOS fix */
    .stApp div[data-testid="stTextInput"] input,
    .main div[data-testid="stTextInput"] input {
        -webkit-appearance: none !important;
        appearance: none !important;
        background: rgba(15,25,80,0.6) !important;
        background-color: rgba(15,25,80,0.6) !important;
        border: 2px solid rgba(255,255,255,.22) !important;
        border-radius: 14px !important;
        color: #fff !important;
        -webkit-text-fill-color: #fff !important;
        font-size: 28px !important;
        font-family: 'Courier New', monospace !important;
        font-weight: 800 !important;
        text-align: center !important;
        padding: 18px 20px !important;
        letter-spacing: 14px !important;
        caret-color: #ffca28 !important;
        box-shadow: none !important;
        transition: border-color .2s, background .2s;
    }
    .stApp div[data-testid="stTextInput"] input::placeholder,
    .main div[data-testid="stTextInput"] input::placeholder {
        letter-spacing: 8px !important;
        font-size: 18px !important;
        color: rgba(255,255,255,.3) !important;
        -webkit-text-fill-color: rgba(255,255,255,.3) !important;
    }
    .stApp div[data-testid="stTextInput"] input:focus,
    .main div[data-testid="stTextInput"] input:focus {
        border-color: #ffca28 !important;
        background-color: rgba(255,202,40,.12) !important;
        box-shadow: 0 0 0 3px rgba(255,202,40,.18) !important;
        outline: none !important;
    }
    /* iOS autofill override */
    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus {
        -webkit-box-shadow: 0 0 0 1000px #0f1950 inset !important;
        -webkit-text-fill-color: #fff !important;
    }
    /* Hide label, instructions */
    [data-testid="stTextInput"] label,
    [data-testid="stTextInput"] [data-testid="InputInstructions"] {
        display: none !important;
    }
    /* Hide button (auto-submit, no button needed) */
    div[data-testid="stButton"] { display: none !important; }
    /* Show/hide password icon — visible on dark bg */
    div[data-testid="stTextInput"] button {
        background: transparent !important;
        border: none !important;
        color: rgba(255,255,255,.5) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Locked state ──────────────────────────────────────────────────────────
    if st.session_state.pin_attempts >= 5:
        st.markdown("""
        <div style="text-align:center;padding:20px 0">
          <div style="background:rgba(255,107,107,.15);border:1.5px solid #ff6b6b;
               border-radius:10px;padding:20px;color:#ff6b6b;
               font-weight:700;font-size:14px;line-height:1.7;">
            🔒 Bahut zyada galat attempts.<br>
            <span style="font-size:12px;opacity:.8;">Page reload karo.</span>
          </div>
        </div>""", unsafe_allow_html=True)
        return

    # ── Logo + titles ─────────────────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;margin-bottom:22px;">
      <div style="font-size:52px;margin-bottom:10px;
           filter:drop-shadow(0 4px 12px rgba(0,0,0,.4));">⚖️</div>
      <div style="color:#fff;font-size:20px;font-weight:800;
           letter-spacing:.3px;margin-bottom:4px;">Portfolio Rebalancer</div>
      <div style="color:rgba(255,255,255,.5);font-size:12px;">
           Enter your 6-digit PIN to continue</div>
    </div>
    """, unsafe_allow_html=True)

    # ── PIN input — auto-submits on 6 digits, no button needed ───────────────
    pin = st.text_input(
        "pin",
        placeholder="——————",
        max_chars=6,
        type="password",
        label_visibility="collapsed",
        key=f"pin_field_{st.session_state.pin_key}",
    )

    # ── Hint + attempt dots + error msg ──────────────────────────────────────
    dots = "".join(
        f'<span class="att-dot{" used" if i < used else ""}"></span>'
        for i in range(5)
    )
    st.markdown(f"""
    <p style="color:rgba(255,255,255,.3);font-size:11px;
       text-align:center;margin:6px 0 4px;">
       Type on keyboard or use phone keypad</p>
    <div class="att-row" style="margin:8px 0 4px;">{dots}</div>
    <div style="color:#ff6b6b;font-size:12.5px;font-weight:700;
         text-align:center;min-height:20px;letter-spacing:.2px;">{err}</div>
    <div style="color:rgba(255,255,255,.18);font-size:10px;
         text-align:center;margin-top:28px;letter-spacing:.3px;">
      prayan03.streamlit.app · Personal use only
    </div>
    """, unsafe_allow_html=True)

    # ── Auto-verify on 6 digits ───────────────────────────────────────────────
    if len(pin) == 6:
        if pin == APP_PIN:
            st.session_state.stage        = "upload"
            st.session_state.pin_attempts = 0
            st.session_state.pin_key     += 1
            st.rerun()
        else:
            st.session_state.pin_attempts += 1
            st.session_state.pin_key     += 1   # clears the input box
            remaining = 5 - st.session_state.pin_attempts
            st.session_state["_pin_err"] = (
                f"❌ Galat PIN — {remaining} attempts baaki" if remaining > 0
                else "🔒 Locked — page reload karo"
            )
            st.rerun()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: UPLOAD                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_upload():
    # Header bar — matches rebalancer header
    st.markdown("""
    <div class="rb-header">
      <div class="rb-header-title">⚖️ Portfolio Rebalancer</div>
      <div class="rb-header-right">
        <span style="font-size:10.5px;background:rgba(255,202,40,.2);
              border:1.5px solid #ffca28;color:#ffca28;border-radius:14px;
              padding:3px 10px;font-weight:800;">📤 Data Upload</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ① Screener Excel
    st.markdown("""
    <div style="padding:10px 12px 4px;">
      <div class="info-card">
        <b>① Screener Excel</b> — "Portfolio Rebalancing" sheet wala file upload karo
      </div>
    </div>""", unsafe_allow_html=True)
    screener_file = st.file_uploader(
        "screener", type=["xlsx","xls"],
        label_visibility="collapsed", key="su_screener"
    )

    # ② Holdings
    st.markdown("""
    <div style="padding:4px 12px;">
      <div class="info-card">
        <b>② Zerodha Holdings</b> —
        <a href="https://console.zerodha.com/portfolio/holdings"
           target="_blank">console.zerodha.com</a>
        → Holdings → ⬇ Download (XLSX ya CSV dono chalega)
      </div>
    </div>""", unsafe_allow_html=True)
    holdings_file = st.file_uploader(
        "holdings", type=["csv","xlsx","xls"],
        label_visibility="collapsed", key="su_holdings"
    )

    # ③ Cash
    st.markdown("""
    <div style="padding:4px 12px;">
      <div class="info-card">
        <b>③ Available Cash ₹</b> — Zerodha Funds → "Available margin" wali value
      </div>
    </div>""", unsafe_allow_html=True)

    # Number input styled inline
    st.markdown("""
    <div style="padding:0 12px 4px;display:flex;align-items:center;
         gap:10px;background:#fff;border-top:1px solid #e4e8ef;
         border-bottom:1px solid #e4e8ef;padding:8px 12px;">
      <span style="font-size:12px;font-weight:600;color:#5a6478;flex:1;">
        💰 Available Cash (₹)</span>
    </div>""", unsafe_allow_html=True)
    cash_val = st.number_input(
        "cash", min_value=0.0, value=0.0, step=1000.0,
        format="%.0f", label_visibility="collapsed"
    )

    sells, buys, hold_map = [], [], {}

    if screener_file:
        try:
            df       = pd.read_excel(screener_file,
                                     sheet_name="Portfolio Rebalancing", header=0)
            sc       = next((c for c in df.columns if "sell" in c.lower()), None)
            bc       = next((c for c in df.columns if "buy"  in c.lower()), None)
            if not sc or not bc:
                st.error("Screener Excel mein 'Sell' ya 'Buy' column nahi mili.")
            else:
                sells = [s.strip() for s in df[sc].dropna().tolist()
                         if str(s).strip().upper() not in ("SELL STOCKS","")]
                buys  = [b.strip() for b in df[bc].dropna().tolist()
                         if str(b).strip().upper() not in ("BUY STOCKS","")]

                # Preview panel
                st.markdown("""<div class="panel" style="margin-top:8px;">
                  <div class="panel-hdr ph-navy">📋 Stock Preview</div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;">""",
                    unsafe_allow_html=True)

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(
                        f'<div class="sec-title-sell">🔴 SELL '
                        f'<span class="badge-count">{len(sells)}</span></div>',
                        unsafe_allow_html=True)
                    for s in sells:
                        st.markdown(f'<div class="sym-row-s">▸ {s}</div>',
                                    unsafe_allow_html=True)
                with col2:
                    st.markdown(
                        f'<div class="sec-title-buy">🟢 BUY '
                        f'<span class="badge-count badge-buy">{len(buys)}</span></div>',
                        unsafe_allow_html=True)
                    for b in buys:
                        st.markdown(f'<div class="sym-row-b">▸ {b}</div>',
                                    unsafe_allow_html=True)
                st.markdown("</div></div>", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Screener Excel error: {e}")

    if holdings_file:
        try:
            hold_map = parse_holdings_file(holdings_file)
            st.markdown(
                f'<div class="loaded-ok" style="margin:4px 12px;">✅ '
                f'Holdings loaded — <b>{len(hold_map)} stocks</b></div>',
                unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Holdings file error: {e}")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if (sells or buys) and hold_map:
        if st.button("⚖️  Rebalance Dashboard Load Karo →",
                     use_container_width=True):
            st.session_state.sell_syms = sells
            st.session_state.buy_syms  = buys
            with st.spinner("⏳ yfinance se live LTP aa raha hai… (30-60 sec lag sakta hai)"):
                try:
                    d = fetch_all(sells, buys, hold_map, float(cash_val))
                    st.session_state.data  = d
                    st.session_state.stage = "dashboard"
                    st.rerun()
                except Exception as exc:
                    st.error(f"Data fetch failed: {exc}")
    else:
        st.markdown(
            '<p style="color:#9aa0ad;font-size:12px;text-align:center;'
            'padding:8px;">Screener Excel aur Holdings file dono upload karo</p>',
            unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    if st.button("← Wapas (PIN screen)", type="secondary",
                 use_container_width=True):
        st.session_state.stage = "pin"
        st.rerun()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: DASHBOARD                                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_dashboard():
    d = st.session_state.data
    if not d:
        st.session_state.stage = "upload"
        st.rerun()
        return

    ar_on = st.session_state.auto_refresh

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    if _AUTOREFRESH_AVAILABLE and ar_on:
        rc = st_autorefresh(interval=60_000, key="price_autorefresh")
        if rc > 0:
            try:
                hm = {r["sym"]: r["qty"] for r in d["sell_rows"]}
                st.session_state.data = fetch_all(
                    st.session_state.sell_syms, st.session_state.buy_syms,
                    hm, d["cash"])
                d = st.session_state.data
            except Exception:
                pass

    ar_on    = st.session_state.auto_refresh
    ar_cls   = "on" if ar_on else "off"
    ar_lbl   = "🟢 Auto-refresh ON" if ar_on else "⚪ Auto-refresh OFF"
    ar_icon  = "⏸ Pause" if ar_on else "▶ Resume"

    # ── Sticky header ─────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="rb-header">
      <div class="rb-header-title">⚖️ Portfolio Rebalancer</div>
      <div class="rb-header-right">
        <span class="ts-badge">{d['ts']}</span>
        <span class="ar-badge {ar_cls}">{ar_lbl}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Summary strip ─────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="sum-strip">
      <div class="sum-pill inv">
        <span class="sum-lbl">Investable</span>
        <span class="sum-val g">{inr(d['invest'])}</span>
      </div>
      <div class="sum-pill buf">
        <span class="sum-lbl">Buffer (+₹500)</span>
        <span class="sum-val r">−{inr(d['buf'])}</span>
      </div>
      <div class="sum-pill lft">
        <span class="sum-lbl">Leftover</span>
        <span class="sum-val y">{inr(d['leftover'])}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Controls ──────────────────────────────────────────────────────────────
    col_r, col_p = st.columns([3, 2])
    with col_r:
        if st.button("🔄  Abhi Refresh Karo", use_container_width=True):
            with st.spinner("Prices aa rahe hain…"):
                try:
                    hm = {r["sym"]: r["qty"] for r in d["sell_rows"]}
                    st.session_state.data = fetch_all(
                        st.session_state.sell_syms,
                        st.session_state.buy_syms, hm, d["cash"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"Refresh failed: {exc}")
    with col_p:
        if st.button(ar_icon, use_container_width=True, type="secondary"):
            st.session_state.auto_refresh = not st.session_state.auto_refresh
            st.rerun()

    # Zero LTP warning
    zero_syms = [r["sym"] for r in d["sell_rows"] + d["buy_rows"]
                 if r["ltp"] == 0.0]
    if zero_syms:
        st.warning(
            f"⚠️ LTP nahi mila: **{', '.join(zero_syms)}** "
            f"— market band ho ya NSE symbol mismatch"
        )

    # ── SELL section ──────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="panel">
      <div class="sec-title-sell">
        🔴 Sell Stocks
        <span class="badge-count">{len(d['sell_rows'])}</span>
      </div>
      <div style="padding:8px 10px 4px;">
    """, unsafe_allow_html=True)
    for r in d["sell_rows"]:
        st.markdown(sell_card(r), unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

    # ── Fund bridge ───────────────────────────────────────────────────────────
    st.markdown(bridge_html(d), unsafe_allow_html=True)

    # ── BUY section ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="panel">
      <div class="sec-title-buy">
        🟢 Buy Stocks
        <span class="badge-count badge-buy">{d['n_buy']}</span>
      </div>
      <div class="per-note">
        Equal split → <b>{inr(d['per_stk'])}</b> per stock
      </div>
      <div style="padding:0 10px 4px;">
    """, unsafe_allow_html=True)
    for r in d["buy_rows"]:
        st.markdown(buy_card(r), unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

    # ── Leftover ──────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="leftover">
      <span class="ll">Remaining cash after all buys + charges</span>
      <span class="lv">{inr(d['leftover'])}</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Action buttons ────────────────────────────────────────────────────────
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📤 Nayi Upload", type="secondary",
                     use_container_width=True):
            st.session_state.stage = "upload"
            st.session_state.data  = None
            st.rerun()
    with col2:
        if st.button("🔒 Reset / Logout", type="secondary",
                     use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # ── Footer ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="ftxt">
      Zerodha Delivery: Zero Brokerage · STT 0.1% B&amp;S · Txn 0.00307% · SEBI ₹10/cr · GST 18%<br>
      Buy: Stamp 0.015% · Buffer = Buy charges + ₹500 · LTP: yfinance (NSE) · Estimates only
    </div>
    """, unsafe_allow_html=True)


# ── Router ────────────────────────────────────────────────────────────────────
_router = {"pin": stage_pin, "upload": stage_upload, "dashboard": stage_dashboard}
_router.get(st.session_state.stage, stage_pin)()
