"""
Zerodha Portfolio Rebalancer — Streamlit App (No Kite API)
==========================================================
Kite API permissions ki zaroorat nahi.
Data sources:
  • Screener Excel   → sell / buy lists
  • Zerodha Holdings CSV (console.zerodha.com se download)  → qty
  • yfinance         → live LTP (NSE)
  • Manual input     → available cash

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
    page_title="Rebalance",
    page_icon="📊",
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
STT_SELL  = 0.001
EXC_CH    = 0.0003
GST_RATE  = 0.18
STAMP_BUY = 0.00015
BUF_PCT   = 0.006

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=IBM+Plex+Mono:wght@400;600&family=DM+Sans:wght@400;500;600&display=swap');

#MainMenu, footer, header,
[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stStatusWidget"],[data-testid="collapsedControl"],
[data-testid="stSidebarNav"] { display: none !important; }

.stApp,[data-testid="stAppViewContainer"],
[data-testid="stMain"],[data-testid="stBottom"] { background: #080c14 !important; }

.main .block-container { padding: 0 1rem 4rem !important; max-width: 500px; margin: 0 auto; }
[data-testid="stVerticalBlock"] { gap: 0.4rem !important; }
*, body { font-family: 'DM Sans', system-ui, sans-serif; color: #dce8f5; }

div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
    background: #0e1420 !important; border: 1.5px solid rgba(255,255,255,0.1) !important;
    border-radius: 14px !important; color: #dce8f5 !important; font-size: 28px !important;
    font-family: 'IBM Plex Mono', monospace !important; text-align: center !important;
    padding: 18px 16px !important; letter-spacing: 10px;
}
div[data-testid="stTextInput"] input:focus {
    border-color: #ffc94d !important; box-shadow: 0 0 0 3px rgba(255,201,77,0.15) !important;
}
div[data-testid="stTextInput"] label { display: none !important; }

div[data-testid="stButton"] button {
    width: 100%; background: #534AB7 !important; color: #fff !important;
    border: none !important; border-radius: 14px !important; font-size: 15px !important;
    font-weight: 700 !important; font-family: 'Syne', sans-serif !important;
    padding: 16px !important; transition: all 0.2s !important; min-height: 54px;
}
div[data-testid="stButton"] button:hover  { background: #7F77DD !important; }
div[data-testid="stButton"] button:active { transform: scale(0.98) !important; }
div[data-testid="stButton"] button[kind="secondary"] {
    background: #141b28 !important; border: 1px solid rgba(255,255,255,0.1) !important;
    color: #8fa3bc !important; font-size: 13px !important; min-height: 44px;
}
[data-testid="stFileUploader"] {
    background: #0e1420; border: 2px dashed rgba(255,255,255,0.1);
    border-radius: 16px; padding: 1rem 1.5rem;
}
[data-testid="stFileUploader"]:hover { border-color: rgba(83,74,183,0.5); }
div[data-testid="stSpinner"] p { color: #8fa3bc !important; }
div[data-testid="stAlert"]     { border-radius: 14px !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for _k, _v in {
    "stage": "pin", "sell_syms": [], "buy_syms": [], "data": None,
    "pin_attempts": 0, "auto_refresh": True,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Shared card CSS ───────────────────────────────────────────────────────────
st.markdown("""<style>
.logo      { font-family:'Syne',sans-serif; font-size:26px; font-weight:800; color:#dce8f5; padding:1.4rem 0 .2rem; }
.logo span { color:#ffc94d; }
.sub       { font-size:13px; color:#5a6a82; margin-bottom:1.8rem; line-height:1.6; }
.step-pill { display:inline-flex; align-items:center; gap:6px; background:rgba(83,74,183,.18);
             border:1px solid rgba(83,74,183,.3); border-radius:100px;
             padding:4px 12px; font-size:12px; color:#AFA9EC; margin-bottom:1rem; }
.pin-wrap  { text-align:center; padding:.5rem 0; }
.strip     { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-bottom:4px; }
.s-pill    { background:#0e1420; border:1px solid rgba(255,255,255,.07); border-radius:12px; padding:10px 8px; text-align:center; }
.s-pill.inv{ border-color:rgba(0,214,143,.3); } .s-pill.buf{ border-color:rgba(255,68,88,.25); }
.s-lbl     { display:block; font-size:8px; font-weight:700; letter-spacing:.7px; text-transform:uppercase; color:#5a6a82; margin-bottom:4px; }
.s-val     { display:block; font-family:'IBM Plex Mono',monospace; font-size:12px; font-weight:600; }
.s-val.g{ color:#00d68f; } .s-val.r{ color:#ff4458; } .s-val.y{ color:#ffc94d; }
.ts        { font-size:10px; color:#5a6a82; margin-bottom:10px; }
.sec-title { font-family:'Syne',sans-serif; font-size:21px; font-weight:800; margin:18px 0 10px; }
.sec-title.sell{ color:#ff4458; } .sec-title.buy{ color:#00d68f; }
.per-note  { font-size:12px; color:#8fa3bc; margin:-4px 0 12px; }
.per-note b{ color:#00d68f; font-family:'IBM Plex Mono',monospace; }
.card      { background:#0e1420; border-radius:14px; padding:14px; margin-bottom:10px; }
.card-sell { border:1px solid rgba(255,68,88,.25); } .card-buy{ border:1px solid rgba(0,214,143,.2); }
.card.dim  { opacity:.45; }
.c-top     { display:flex; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:6px; margin-bottom:11px; }
.c-sym     { font-family:'Syne',sans-serif; font-size:19px; font-weight:800; color:#dce8f5; }
.c-ltp     { font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8fa3bc;
             background:#141b28; padding:3px 9px; border-radius:100px;
             border:1px solid rgba(255,255,255,.07); margin-left:auto; }
.w-badge   { font-size:9px; font-weight:700; text-transform:uppercase; padding:2px 7px;
             border-radius:100px; background:rgba(255,201,77,.15); color:#ffc94d; }
.c-g3{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }
.c-g2{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.c-box     { background:#141b28; border-radius:9px; padding:9px 10px; }
.c-lbl     { display:block; font-size:7.5px; font-weight:700; letter-spacing:.7px; text-transform:uppercase; color:#5a6a82; margin-bottom:4px; }
.c-num     { display:block; font-family:'IBM Plex Mono',monospace; font-size:14px; font-weight:600; color:#dce8f5; word-break:break-all; }
.c-num.sell{ color:#ff4458; font-size:22px; } .c-num.buy{ color:#00d68f; font-size:22px; } .c-num.sm{ font-size:11px; }
.c-chg     { font-size:10px; color:#5a6a82; margin-top:9px; font-family:'IBM Plex Mono',monospace; }
.bridge    { background:rgba(255,201,77,.07); border:1px solid rgba(255,201,77,.2); border-radius:14px; padding:14px; margin:6px 0 2px; }
.b-row     { display:flex; justify-content:space-between; align-items:center; padding:6px 0;
             border-bottom:1px solid rgba(255,255,255,.05); font-size:12px; color:#8fa3bc; }
.b-row:last-child{ border-bottom:none; }
.b-val     { font-family:'IBM Plex Mono',monospace; font-weight:600; font-size:12px; }
.b-val.g{ color:#00d68f; } .b-val.r{ color:#ff4458; }
.b-row.total{ color:#ffc94d; font-weight:700; font-size:14px; }
.b-row.total .b-val{ color:#ffc94d; font-size:15px; }
.leftover  { background:#0e1420; border:1px solid rgba(255,255,255,.07); border-radius:14px;
             padding:13px 16px; display:flex; justify-content:space-between; align-items:center; margin-top:10px; }
.leftover .ll{ font-size:12px; color:#8fa3bc; }
.leftover .lv{ font-family:'IBM Plex Mono',monospace; font-size:17px; font-weight:600; color:#ffc94d; }
.ftxt      { text-align:center; font-size:10px; color:#5a6a82; margin-top:1.5rem; line-height:1.9; }
.divider   { height:1px; background:rgba(255,255,255,.06); margin:12px 0; }
.info-box  { background:#0e1420; border:1px solid rgba(83,74,183,.3); border-radius:12px;
             padding:10px 14px; font-size:12px; color:#8fa3bc; line-height:1.7; margin-bottom:6px; }
.info-box b{ color:#AFA9EC; }
</style>""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def inr(n: float, decimals: int = 0) -> str:
    if n is None:
        return "₹—"
    return f"₹{{:,.{decimals}f}}".format(abs(n))


def get_ltp_yfinance(symbols: list) -> dict:
    """
    NSE symbols → LTP via yfinance.
    Strategy:
      1. Batch download period=5d, interval=1d  (most reliable for NSE)
      2. Individual .history() fallback for zeros
      3. fast_info.last_price last resort
    """
    ltp_map = {s: 0.0 for s in symbols}
    tickers = [f"{s}.NS" for s in symbols]

    # ── Step 1: Batch download ────────────────────────────────────────────────
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
                        # group_by="ticker" → (ticker, OHLCV)
                        series = data[ticker]["Close"].dropna()
                    else:
                        series = data["Close"].dropna()
                    if not series.empty:
                        ltp_map[sym] = round(float(series.iloc[-1]), 2)
                except Exception:
                    pass
    except Exception:
        pass

    # ── Step 2: Individual .history() for zeros ───────────────────────────────
    missing = [s for s in symbols if ltp_map[s] == 0.0]
    for sym in missing:
        try:
            hist = yf.Ticker(f"{sym}.NS").history(period="5d", interval="1d")
            if not hist.empty:
                ltp_map[sym] = round(float(hist["Close"].dropna().iloc[-1]), 2)
        except Exception:
            pass

    # ── Step 3: fast_info last resort ─────────────────────────────────────────
    still_missing = [s for s in symbols if ltp_map[s] == 0.0]
    for sym in still_missing:
        try:
            info = yf.Ticker(f"{sym}.NS").fast_info
            val  = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            if val:
                ltp_map[sym] = round(float(val), 2)
        except Exception:
            pass

    return ltp_map


def parse_holdings_file(file) -> dict:
    """
    Zerodha holdings file → {SYMBOL: qty}
    Supports CSV aur XLSX dono.
    XLSX: 'Equity' sheet, header auto-detect, 'Quantity Available' column.
    """
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
                        if c.lower() in ("instrument", "symbol", "tradingsymbol", "stock")), None)
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


def fetch_all(sell_syms: list, buy_syms: list, hold_map: dict, cash: float) -> dict:
    all_syms = list(set(sell_syms + buy_syms))
    ltp_map  = get_ltp_yfinance(all_syms)

    sell_rows, gross_tot, charge_tot = [], 0.0, 0.0
    for sym in sell_syms:
        ltp   = ltp_map.get(sym, 0.0)
        qty   = hold_map.get(sym, 0)
        gross = qty * ltp
        stt   = gross * STT_SELL
        exc   = gross * EXC_CH
        brk   = min(20, gross * 0.0003)
        gst   = brk * GST_RATE
        tc    = stt + exc + brk + gst
        net   = gross - tc
        gross_tot  += gross
        charge_tot += tc
        sell_rows.append({"sym": sym, "ltp": ltp, "qty": qty, "gross": gross,
                          "stt": stt, "exc": exc, "brk": brk, "gst": gst,
                          "total_charges": tc, "net": net, "held": qty > 0})

    sell_net = gross_tot - charge_tot
    pool     = sell_net + cash
    buf      = pool * BUF_PCT
    invest   = pool - buf
    n_buy    = len(buy_syms)
    per_stk  = invest / n_buy if n_buy > 0 else 0.0

    buy_rows, buy_cost = [], 0.0
    for sym in buy_syms:
        ltp       = ltp_map.get(sym, 0.0)
        qty       = math.floor(per_stk / ltp) if ltp > 0 else 0
        cost      = qty * ltp
        charges_b = cost * EXC_CH + cost * STAMP_BUY + min(20, cost * 0.0003) * (1 + GST_RATE)
        buy_cost += cost + charges_b
        buy_rows.append({"sym": sym, "ltp": ltp, "qty": qty, "cost": cost, "charges": charges_b})

    return {
        "ts": datetime.now().strftime("%d %b %Y, %I:%M:%S %p"),
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
  <div class="c-top"><span class="c-sym">{r['sym']}</span>{warn}
    <span class="c-ltp">₹{r['ltp']:,.2f}</span></div>
  <div class="c-g3">
    <div class="c-box"><span class="c-lbl">SELL QTY</span><span class="c-num sell">{r['qty']}</span></div>
    <div class="c-box"><span class="c-lbl">GROSS</span><span class="c-num sm">{inr(r['gross'])}</span></div>
    <div class="c-box"><span class="c-lbl">NET (after charges)</span><span class="c-num sm">{inr(r['net'])}</span></div>
  </div>
  <div class="c-chg">STT {inr(r['stt'],2)} · Exchange {inr(r['exc'],2)} · Brokerage+GST {inr(r['brk']+r['gst'],2)}</div>
</div>"""


def buy_card(r):
    return f"""<div class="card card-buy">
  <div class="c-top"><span class="c-sym">{r['sym']}</span>
    <span class="c-ltp">₹{r['ltp']:,.2f}</span></div>
  <div class="c-g2">
    <div class="c-box"><span class="c-lbl">BUY QTY</span><span class="c-num buy">{r['qty']}</span></div>
    <div class="c-box"><span class="c-lbl">TOTAL COST (w/ charges)</span><span class="c-num sm">{inr(r['cost']+r['charges'])}</span></div>
  </div>
  <div class="c-chg">Base: {inr(r['cost'])} · Charges: {inr(r['charges'],2)}</div>
</div>"""


def bridge_html(d):
    return f"""<div class="bridge">
  <div class="b-row"><span>Sell net proceeds</span><span class="b-val g">{inr(d['sell_net'])}</span></div>
  <div class="b-row"><span>+ Available cash</span><span class="b-val g">{inr(d['cash'])}</span></div>
  <div class="b-row"><span>− Buffer 0.6% (charges)</span><span class="b-val r">−{inr(d['buf'])}</span></div>
  <div class="b-row total"><span>= Investable fund</span><span class="b-val">{inr(d['invest'])}</span></div>
</div>"""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: PIN                                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_pin():
    st.markdown("""
    <style>
    /* PIN screen — full viewport centering */
    .pin-outer {
        min-height: 88vh;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 2rem 0 1rem;
    }

    /* Glowing icon badge */
    .pin-icon {
        width: 72px; height: 72px;
        background: linear-gradient(135deg, #534AB7 0%, #7F77DD 100%);
        border-radius: 22px;
        display: flex; align-items: center; justify-content: center;
        font-size: 32px;
        margin-bottom: 1.4rem;
        box-shadow: 0 0 0 8px rgba(83,74,183,.12), 0 0 0 16px rgba(83,74,183,.06);
    }

    /* Wordmark */
    .pin-title {
        font-family: 'Syne', sans-serif;
        font-size: 30px; font-weight: 800;
        color: #dce8f5;
        letter-spacing: -0.5px;
        margin-bottom: 4px;
        text-align: center;
    }
    .pin-title span { color: #ffc94d; }

    .pin-tagline {
        font-size: 13px; color: #4a5a72;
        text-align: center;
        margin-bottom: 2.4rem;
        letter-spacing: 0.3px;
    }

    /* Input card */
    .pin-card {
        background: #0d1320;
        border: 1px solid rgba(255,255,255,.07);
        border-radius: 22px;
        padding: 28px 28px 24px;
        width: 100%;
        max-width: 340px;
        box-shadow: 0 24px 60px rgba(0,0,0,.45);
    }

    .pin-label {
        font-size: 11px; font-weight: 700; letter-spacing: 1.2px;
        text-transform: uppercase; color: #4a5a72;
        text-align: center;
        margin-bottom: 14px;
    }

    /* Attempts badge */
    .att-row {
        display: flex; justify-content: center; gap: 6px;
        margin-top: 14px;
    }
    .att-dot {
        width: 7px; height: 7px; border-radius: 50%;
        background: rgba(255,255,255,.1);
    }
    .att-dot.used { background: #ff4458; }

    /* Divider line */
    .pin-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(83,74,183,.3), transparent);
        margin: 20px 0 16px;
    }

    /* Footer */
    .pin-footer {
        font-size: 10px; color: #2a3a52;
        text-align: center;
        margin-top: 1.6rem;
        letter-spacing: 0.3px;
    }
    </style>

    <div class="pin-outer">
      <div class="pin-icon">📊</div>
      <div class="pin-title">Re<span>balance</span></div>
      <div class="pin-tagline">Zerodha · Personal Portfolio Rebalancer</div>

      <div class="pin-card">
        <div class="pin-label">Enter your PIN</div>
    """, unsafe_allow_html=True)

    if st.session_state.pin_attempts >= 5:
        st.error("Bahut zyada galat attempts. Page reload karo.")
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    pin = st.text_input(
        "pin", placeholder="· · · · · ·", max_chars=6,
        type="password", label_visibility="collapsed",
        key="pin_input"
    )

    if st.button("Unlock  →", use_container_width=True):
        if pin == APP_PIN:
            st.session_state.stage = "upload"
            st.session_state.pin_attempts = 0
            st.rerun()
        else:
            st.session_state.pin_attempts += 1
            remaining = 5 - st.session_state.pin_attempts
            if remaining > 0:
                st.error(f"Galat PIN — {remaining} attempts baaki")
            else:
                st.error("Bahut zyada galat attempts. Page reload karo.")

    # Attempt dots
    used = st.session_state.pin_attempts
    dots_html = "".join(
        f'<div class="att-dot{"  used" if i < used else ""}"></div>'
        for i in range(5)
    )
    st.markdown(f"""
        <div class="att-row">{dots_html}</div>
        <div class="pin-divider"></div>
        <p style="font-size:11px;color:#2a3a52;text-align:center;margin:0">
          Secured · Personal use only
        </p>
      </div>
    </div>

    <div class="pin-footer">prayan03.streamlit.app</div>
    """, unsafe_allow_html=True)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: UPLOAD                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_upload():
    st.markdown("""
    <div class="logo">Re<span>balance</span></div>
    <div class="step-pill">Data Upload</div>
    """, unsafe_allow_html=True)

    # ① Screener Excel
    st.markdown('<div class="info-box"><b>① Screener Excel</b> — "Portfolio Rebalancing" sheet wala file</div>',
                unsafe_allow_html=True)
    screener_file = st.file_uploader("screener", type=["xlsx", "xls"],
                                     label_visibility="collapsed", key="su_screener")

    # ② Holdings CSV
    st.markdown("""<div class="info-box" style="margin-top:8px">
      <b>② Zerodha Holdings File</b> —
      <a href="https://console.zerodha.com/portfolio/holdings" target="_blank"
         style="color:#AFA9EC">console.zerodha.com</a>
      → Holdings → ⬇ Download (CSV ya XLSX dono chalega)
    </div>""", unsafe_allow_html=True)
    holdings_file = st.file_uploader("holdings", type=["csv", "xlsx", "xls"],
                                     label_visibility="collapsed", key="su_holdings")

    # ③ Cash
    st.markdown('<div class="info-box" style="margin-top:8px"><b>③ Available Cash (₹)</b> — Zerodha Funds mein jo "Available margin" dikhaye</div>',
                unsafe_allow_html=True)
    cash_val = st.number_input("cash", min_value=0.0, value=0.0, step=1000.0,
                               format="%.0f", label_visibility="collapsed")

    sells, buys, hold_map = [], [], {}

    if screener_file:
        try:
            df = pd.read_excel(screener_file, sheet_name="Portfolio Rebalancing", header=0)
            sc = next((c for c in df.columns if "sell" in c.lower()), None)
            bc = next((c for c in df.columns if "buy"  in c.lower()), None)
            if not sc or not bc:
                st.error("Screener Excel mein 'Sell' ya 'Buy' column nahi mili.")
            else:
                sells = [s.strip() for s in df[sc].dropna().tolist()
                         if str(s).strip().upper() not in ("SELL STOCKS", "")]
                buys  = [b.strip() for b in df[bc].dropna().tolist()
                         if str(b).strip().upper() not in ("BUY STOCKS", "")]
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"<p style='color:#ff4458;font-weight:700;margin:8px 0 4px'>SELL · {len(sells)}</p>",
                                unsafe_allow_html=True)
                    for s in sells:
                        st.markdown(f"<p style='font-family:monospace;font-size:12px;margin:2px 0;color:#dce8f5'>{s}</p>",
                                    unsafe_allow_html=True)
                with col2:
                    st.markdown(f"<p style='color:#00d68f;font-weight:700;margin:8px 0 4px'>BUY · {len(buys)}</p>",
                                unsafe_allow_html=True)
                    for b in buys:
                        st.markdown(f"<p style='font-family:monospace;font-size:12px;margin:2px 0;color:#dce8f5'>{b}</p>",
                                    unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Screener Excel error: {e}")

    if holdings_file:
        try:
            hold_map = parse_holdings_file(holdings_file)
            st.markdown(f"<p style='color:#00d68f;font-size:12px;margin:6px 0'>✓ Holdings loaded — {len(hold_map)} stocks</p>",
                        unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Holdings CSV error: {e}")

    st.markdown("<br>", unsafe_allow_html=True)

    if (sells or buys) and hold_map:
        if st.button("Dashboard Load Karo →"):
            st.session_state.sell_syms = sells
            st.session_state.buy_syms  = buys
            with st.spinner("yfinance se live prices aa rahe hain… (30-60 sec)"):
                try:
                    d = fetch_all(sells, buys, hold_map, float(cash_val))
                    st.session_state.data  = d
                    st.session_state.stage = "dashboard"
                    st.rerun()
                except Exception as exc:
                    st.error(f"Data fetch failed: {exc}")
    else:
        st.markdown("<p style='color:#5a6a82;font-size:12px;text-align:center'>"
                    "Screener Excel aur Holdings CSV dono upload karo</p>",
                    unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    if st.button("← Wapas (PIN screen)", type="secondary"):
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

    # ── Auto-refresh: har 60 sec pe prices update ─────────────────────────────
    if _AUTOREFRESH_AVAILABLE and st.session_state.auto_refresh:
        refresh_count = st_autorefresh(interval=60_000, key="price_autorefresh")
        if refresh_count > 0:
            try:
                hm = {r["sym"]: r["qty"] for r in d["sell_rows"]}
                st.session_state.data = fetch_all(
                    st.session_state.sell_syms, st.session_state.buy_syms,
                    hm, d["cash"]
                )
                d = st.session_state.data
            except Exception:
                pass  # silently fail, purana data dikhta rahe

    ar_on    = st.session_state.auto_refresh
    ar_label = "🟢 Auto-refresh ON" if ar_on else "⚪ Auto-refresh OFF"
    ar_icon  = "⏸ Pause" if ar_on else "▶ Resume"

    st.markdown(f"""
    <div style="padding:.8rem 0 .2rem">
      <div class="logo" style="font-size:20px;padding:.4rem 0 .6rem">Re<span>balance</span></div>
      <div class="strip">
        <div class="s-pill inv"><span class="s-lbl">Investable</span><span class="s-val g">{inr(d['invest'])}</span></div>
        <div class="s-pill buf"><span class="s-lbl">Buffer</span><span class="s-val r">−{inr(d['buf'])}</span></div>
        <div class="s-pill"><span class="s-lbl">Leftover</span><span class="s-val y">{inr(d['leftover'])}</span></div>
      </div>
      <div class="ts" style="display:flex;align-items:center;gap:8px;margin-top:6px">
        <span>Updated: {d['ts']}</span>
        <span style="background:{'rgba(0,214,143,.12)' if ar_on else 'rgba(255,255,255,.06)'};
              color:{'#00d68f' if ar_on else '#5a6a82'};
              border:1px solid {'rgba(0,214,143,.3)' if ar_on else 'rgba(255,255,255,.08)'};
              border-radius:100px;padding:2px 8px;font-size:10px;font-weight:700">
          {ar_label}
        </span>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Controls: manual refresh + pause/resume ───────────────────────────────
    col_r, col_p = st.columns([1, 1])
    with col_r:
        if st.button("⟳  Abhi Refresh Karo", use_container_width=True):
            with st.spinner("Prices aa rahe hain…"):
                try:
                    hm = {r["sym"]: r["qty"] for r in d["sell_rows"]}
                    st.session_state.data = fetch_all(
                        st.session_state.sell_syms, st.session_state.buy_syms, hm, d["cash"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"Refresh failed: {exc}")
    with col_p:
        if st.button(ar_icon, use_container_width=True, type="secondary"):
            st.session_state.auto_refresh = not st.session_state.auto_refresh
            st.rerun()

    # Zero LTP warning
    zero_syms = [r["sym"] for r in d["sell_rows"] + d["buy_rows"] if r["ltp"] == 0.0]
    if zero_syms:
        st.warning(f"⚠️ LTP nahi mila: **{', '.join(zero_syms)}** — market band ho ya symbol mismatch")

    st.markdown(f'<div class="sec-title sell">SELL &nbsp;<span style="font-size:14px;color:#5a6a82">{len(d["sell_rows"])} stocks</span></div>',
                unsafe_allow_html=True)
    for r in d["sell_rows"]:
        st.markdown(sell_card(r), unsafe_allow_html=True)

    st.markdown(bridge_html(d), unsafe_allow_html=True)

    st.markdown(f'<div class="sec-title buy">BUY &nbsp;<span style="font-size:14px;color:#5a6a82">{d["n_buy"]} stocks</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="per-note">Equal split → <b>{inr(d["per_stk"])}</b> per stock</div>',
                unsafe_allow_html=True)
    for r in d["buy_rows"]:
        st.markdown(buy_card(r), unsafe_allow_html=True)

    st.markdown(f"""<div class="leftover">
      <span class="ll">Remaining cash (after all buys + charges)</span>
      <span class="lv">{inr(d['leftover'])}</span>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("↑ Nayi Upload", type="secondary"):
            st.session_state.stage = "upload"
            st.session_state.data  = None
            st.rerun()
    with col2:
        if st.button("⏏ Reset", type="secondary"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    st.markdown("""<div class="ftxt">
      Charges: STT 0.1% sell · Exchange ~0.03% · Brokerage ₹20/order + 18% GST<br>
      Buy: Stamp duty 0.015% · Buffer 0.6% of pool · LTP source: yfinance (NSE)<br>
      Estimates only — Kite pe verify karke order lagao.
    </div>""", unsafe_allow_html=True)


# ── Router ────────────────────────────────────────────────────────────────────
_router = {"pin": stage_pin, "upload": stage_upload, "dashboard": stage_dashboard}
_router.get(st.session_state.stage, stage_pin)()
