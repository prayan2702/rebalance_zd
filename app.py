"""
Zerodha Portfolio Rebalancer — Streamlit App
============================================
Deploy on Streamlit Cloud. Koi server nahi chahiye.

Secrets required (.streamlit/secrets.toml):
    APP_PIN          = "123456"
    KITE_API_KEY     = "your_api_key"
    KITE_API_SECRET  = "your_api_secret"
"""

import math
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    from kiteconnect import KiteConnect
except ImportError:
    st.error("kiteconnect install karo: pip install kiteconnect")
    st.stop()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Rebalance",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Secrets ───────────────────────────────────────────────────────────────────
try:
    APP_PIN    = str(st.secrets["APP_PIN"])
    API_KEY    = str(st.secrets["KITE_API_KEY"])
    API_SECRET = str(st.secrets["KITE_API_SECRET"])
except Exception:
    st.error("⚠️ Streamlit secrets set karo: APP_PIN · KITE_API_KEY · KITE_API_SECRET")
    st.info("Settings → Secrets mein yeh daalo:\n```\nAPP_PIN = \"123456\"\nKITE_API_KEY = \"...\"\nKITE_API_SECRET = \"...\"\n```")
    st.stop()

# ── Constants ─────────────────────────────────────────────────────────────────
STT_SELL  = 0.001    # 0.1%  STT on CNC sell
EXC_CH    = 0.0003   # ~0.03% exchange + SEBI
GST_RATE  = 0.18     # 18% GST on brokerage (₹20 flat per order)
STAMP_BUY = 0.00015  # 0.015% stamp duty on buy
BUF_PCT   = 0.006    # 0.6% buffer (covers brokerage + stamp + safety)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=IBM+Plex+Mono:wght@400;600&family=DM+Sans:wght@400;500;600&display=swap');

/* Hide all Streamlit chrome */
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="collapsedControl"],
[data-testid="stSidebarNav"]            { display: none !important; }

/* Full dark bg */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stBottom"]               { background: #080c14 !important; }

/* Content width */
.main .block-container {
    padding: 0 1rem 4rem !important;
    max-width: 500px;
    margin: 0 auto;
}
[data-testid="stVerticalBlock"]        { gap: 0.4rem !important; }

/* Base typography */
*, body { font-family: 'DM Sans', system-ui, sans-serif; color: #dce8f5; }

/* ── Inputs ── */
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
    background: #0e1420 !important;
    border: 1.5px solid rgba(255,255,255,0.1) !important;
    border-radius: 14px !important;
    color: #dce8f5 !important;
    font-size: 28px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    text-align: center !important;
    padding: 18px 16px !important;
    letter-spacing: 10px;
}
div[data-testid="stTextInput"] input:focus {
    border-color: #ffc94d !important;
    box-shadow: 0 0 0 3px rgba(255,201,77,0.15) !important;
}
div[data-testid="stTextInput"] label,
div[data-testid="stFileUploader"] label { display: none !important; }

/* ── Buttons ── */
div[data-testid="stButton"] button {
    width: 100%;
    background: #534AB7 !important;
    color: #fff !important;
    border: none !important;
    border-radius: 14px !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    font-family: 'Syne', sans-serif !important;
    padding: 16px !important;
    letter-spacing: 0.3px;
    transition: all 0.2s !important;
    min-height: 54px;
}
div[data-testid="stButton"] button:hover  { background: #7F77DD !important; }
div[data-testid="stButton"] button:active { transform: scale(0.98) !important; }

div[data-testid="stButton"] button[kind="secondary"] {
    background: #141b28 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #8fa3bc !important;
    font-size: 13px !important;
    min-height: 44px;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] {
    background: #0e1420;
    border: 2px dashed rgba(255,255,255,0.1);
    border-radius: 16px;
    padding: 1.5rem;
    text-align: center;
}
[data-testid="stFileUploader"]:hover { border-color: rgba(83,74,183,0.5); }

/* ── Spinner ── */
div[data-testid="stSpinner"] p { color: #8fa3bc !important; }

/* ── Alerts ── */
div[data-testid="stAlert"] { border-radius: 14px !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
_defaults = {
    "stage":        "pin",   # pin → login → upload → dashboard
    "kite":         None,
    "sell_syms":    [],
    "buy_syms":     [],
    "data":         None,
    "pin_attempts": 0,
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Kite redirect capture (runs on every load) ───────────────────────────────
# FIX: st.rerun() bilkul nahi — woh browser-level HTTP redirect loop banata tha.
# Token process karo, session set karo, params clear karo, aur router naturally
# stage_upload() call karega. Koi rerun nahi = koi redirect loop nahi.
_qp = st.query_params
if "request_token" in _qp:
    _req = str(_qp["request_token"])   # token pehle capture karo
    st.query_params.clear()            # URL clean karo (no HTTP redirect triggered)
    try:
        _kite = KiteConnect(api_key=API_KEY)
        _sess = _kite.generate_session(_req, api_secret=API_SECRET)
        _kite.set_access_token(_sess["access_token"])
        st.session_state.kite         = _kite
        st.session_state.stage        = "upload"
        st.session_state.pin_attempts = 0
    except Exception as _e:
        st.session_state.stage        = "login"
        st.session_state["_kite_err"] = str(_e)
    # NO st.rerun() — router at bottom handles stage automatically


# ── Helpers ───────────────────────────────────────────────────────────────────

def inr(n: float, decimals: int = 0) -> str:
    if n is None:
        return "₹—"
    fmt = f"₹{{:,.{decimals}f}}"
    return fmt.format(abs(n))


def fetch_all(kite: KiteConnect, sell_syms: list, buy_syms: list) -> dict:
    """Fetch holdings, LTP, margins → calculate everything."""
    exchange = "NSE"
    all_syms = list(set(sell_syms + buy_syms))

    # Holdings
    raw_hold   = kite.holdings()
    hold_map   = {h["tradingsymbol"]: h["quantity"] for h in raw_hold if h["quantity"] > 0}

    # LTP
    instr      = [f"{exchange}:{s}" for s in all_syms]
    quotes     = kite.ltp(instr)
    ltp_map    = {k.split(":")[1]: v["last_price"] for k, v in quotes.items()}

    # Margins
    cash = 0.0
    try:
        mg   = kite.margins(segment="equity")
        cash = float(mg.get("net", 0))
    except Exception:
        pass

    # ── Sell calculations ─────────────────────────────────────────────────────
    sell_rows, gross_tot, charge_tot = [], 0.0, 0.0
    for sym in sell_syms:
        ltp   = ltp_map.get(sym, 0.0)
        qty   = hold_map.get(sym, 0)
        gross = qty * ltp
        stt   = gross * STT_SELL
        exc   = gross * EXC_CH
        brk   = min(20, gross * 0.0003)   # Zerodha: ₹20 flat or 0.03%
        gst   = brk * GST_RATE
        total_charges = stt + exc + brk + gst
        net   = gross - total_charges
        gross_tot  += gross
        charge_tot += total_charges
        sell_rows.append({
            "sym": sym, "ltp": ltp, "qty": qty,
            "gross": gross, "stt": stt, "exc": exc,
            "brk": brk, "gst": gst,
            "total_charges": total_charges, "net": net,
            "held": qty > 0,
        })

    sell_net = gross_tot - charge_tot

    # ── Fund pool ─────────────────────────────────────────────────────────────
    pool    = sell_net + cash
    buf     = pool * BUF_PCT
    invest  = pool - buf
    n_buy   = len(buy_syms)
    per_stk = invest / n_buy if n_buy > 0 else 0.0

    # ── Buy calculations ──────────────────────────────────────────────────────
    buy_rows, buy_cost = [], 0.0
    for sym in buy_syms:
        ltp  = ltp_map.get(sym, 0.0)
        qty  = math.floor(per_stk / ltp) if ltp > 0 else 0
        cost = qty * ltp
        # Estimated charges on buy
        exc_b   = cost * EXC_CH
        stamp_b = cost * STAMP_BUY
        brk_b   = min(20, cost * 0.0003)
        gst_b   = brk_b * GST_RATE
        charges_b = exc_b + stamp_b + brk_b + gst_b
        buy_cost += cost + charges_b
        buy_rows.append({
            "sym": sym, "ltp": ltp, "qty": qty,
            "cost": cost, "charges": charges_b,
        })

    return {
        "ts":          datetime.now().strftime("%d %b %Y, %I:%M:%S %p"),
        "sell_rows":   sell_rows,
        "buy_rows":    buy_rows,
        "gross_tot":   round(gross_tot,   2),
        "charge_tot":  round(charge_tot,  2),
        "sell_net":    round(sell_net,    2),
        "cash":        round(cash,        2),
        "pool":        round(pool,        2),
        "buf":         round(buf,         2),
        "invest":      round(invest,      2),
        "per_stk":     round(per_stk,     2),
        "buy_cost":    round(buy_cost,    2),
        "leftover":    round(invest - buy_cost, 2),
        "n_buy":       n_buy,
    }


# ── HTML card builders ────────────────────────────────────────────────────────

def sell_card(r: dict) -> str:
    dim  = " dim" if not r["held"] else ""
    warn = '<span class="w-badge">Holdings mein nahi</span>' if not r["held"] else ""
    return f"""
<div class="card card-sell{dim}">
  <div class="c-top">
    <span class="c-sym">{r['sym']}</span>
    {warn}
    <span class="c-ltp">₹{r['ltp']:,.2f}</span>
  </div>
  <div class="c-g3">
    <div class="c-box">
      <span class="c-lbl">SELL QTY</span>
      <span class="c-num sell">{r['qty']}</span>
    </div>
    <div class="c-box">
      <span class="c-lbl">GROSS</span>
      <span class="c-num sm">{inr(r['gross'])}</span>
    </div>
    <div class="c-box">
      <span class="c-lbl">NET (after charges)</span>
      <span class="c-num sm">{inr(r['net'])}</span>
    </div>
  </div>
  <div class="c-chg">
    STT {inr(r['stt'],2)} · Exchange {inr(r['exc'],2)} · Brokerage+GST {inr(r['brk']+r['gst'],2)}
  </div>
</div>"""


def buy_card(r: dict) -> str:
    return f"""
<div class="card card-buy">
  <div class="c-top">
    <span class="c-sym">{r['sym']}</span>
    <span class="c-ltp">₹{r['ltp']:,.2f}</span>
  </div>
  <div class="c-g2">
    <div class="c-box">
      <span class="c-lbl">BUY QTY</span>
      <span class="c-num buy">{r['qty']}</span>
    </div>
    <div class="c-box">
      <span class="c-lbl">TOTAL COST (w/ charges)</span>
      <span class="c-num sm">{inr(r['cost'] + r['charges'])}</span>
    </div>
  </div>
  <div class="c-chg">Base: {inr(r['cost'])} · Charges: {inr(r['charges'],2)}</div>
</div>"""


def bridge_html(d: dict) -> str:
    return f"""
<div class="bridge">
  <div class="b-row">
    <span>Sell net proceeds</span>
    <span class="b-val g">{inr(d['sell_net'])}</span>
  </div>
  <div class="b-row">
    <span>+ Available cash / margin</span>
    <span class="b-val g">{inr(d['cash'])}</span>
  </div>
  <div class="b-row">
    <span>− Brokerage + charges buffer (0.6%)</span>
    <span class="b-val r">−{inr(d['buf'])}</span>
  </div>
  <div class="b-row total">
    <span>= Investable fund</span>
    <span class="b-val">{inr(d['invest'])}</span>
  </div>
</div>"""


# ── Card + shared CSS injected once ───────────────────────────────────────────
CARD_CSS = """
<style>
.logo       { font-family:'Syne',sans-serif; font-size:26px; font-weight:800;
              color:#dce8f5; padding:1.4rem 0 .2rem; }
.logo span  { color:#ffc94d; }
.sub        { font-size:13px; color:#5a6a82; margin-bottom:1.8rem; line-height:1.6; }
.step-pill  { display:inline-flex; align-items:center; gap:6px; background:rgba(83,74,183,.18);
              border:1px solid rgba(83,74,183,.3); border-radius:100px;
              padding:4px 12px; font-size:12px; color:#AFA9EC; margin-bottom:1rem; }
.pin-wrap   { text-align:center; padding:.5rem 0; }
.strip      { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-bottom:4px; }
.s-pill     { background:#0e1420; border:1px solid rgba(255,255,255,.07);
              border-radius:12px; padding:10px 8px; text-align:center; }
.s-pill.inv { border-color:rgba(0,214,143,.3); }
.s-pill.buf { border-color:rgba(255,68,88,.25); }
.s-lbl      { display:block; font-size:8px; font-weight:700; letter-spacing:.7px;
              text-transform:uppercase; color:#5a6a82; margin-bottom:4px; }
.s-val      { display:block; font-family:'IBM Plex Mono',monospace;
              font-size:12px; font-weight:600; }
.s-val.g    { color:#00d68f; } .s-val.r { color:#ff4458; } .s-val.y { color:#ffc94d; }
.ts         { font-size:10px; color:#5a6a82; margin-bottom:10px; }
.sec-title  { font-family:'Syne',sans-serif; font-size:21px; font-weight:800;
              margin:18px 0 10px; }
.sec-title.sell { color:#ff4458; } .sec-title.buy { color:#00d68f; }
.per-note   { font-size:12px; color:#8fa3bc; margin:-4px 0 12px; }
.per-note b { color:#00d68f; font-family:'IBM Plex Mono',monospace; }
.card       { background:#0e1420; border-radius:14px; padding:14px; margin-bottom:10px; }
.card-sell  { border:1px solid rgba(255,68,88,.25); }
.card-buy   { border:1px solid rgba(0,214,143,.2); }
.card.dim   { opacity:.45; }
.c-top      { display:flex; align-items:center; flex-wrap:wrap;
              justify-content:space-between; gap:6px; margin-bottom:11px; }
.c-sym      { font-family:'Syne',sans-serif; font-size:19px; font-weight:800; color:#dce8f5; }
.c-ltp      { font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8fa3bc;
              background:#141b28; padding:3px 9px; border-radius:100px;
              border:1px solid rgba(255,255,255,.07); margin-left:auto; }
.w-badge    { font-size:9px; font-weight:700; text-transform:uppercase; padding:2px 7px;
              border-radius:100px; background:rgba(255,201,77,.15); color:#ffc94d; }
.c-g3       { display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }
.c-g2       { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.c-box      { background:#141b28; border-radius:9px; padding:9px 10px; }
.c-lbl      { display:block; font-size:7.5px; font-weight:700; letter-spacing:.7px;
              text-transform:uppercase; color:#5a6a82; margin-bottom:4px; }
.c-num      { display:block; font-family:'IBM Plex Mono',monospace;
              font-size:14px; font-weight:600; color:#dce8f5; word-break:break-all; }
.c-num.sell { color:#ff4458; font-size:22px; }
.c-num.buy  { color:#00d68f; font-size:22px; }
.c-num.sm   { font-size:11px; }
.c-chg      { font-size:10px; color:#5a6a82; margin-top:9px; font-family:'IBM Plex Mono',monospace; }
.bridge     { background:rgba(255,201,77,.07); border:1px solid rgba(255,201,77,.2);
              border-radius:14px; padding:14px; margin:6px 0 2px; }
.b-row      { display:flex; justify-content:space-between; align-items:center;
              padding:6px 0; border-bottom:1px solid rgba(255,255,255,.05);
              font-size:12px; color:#8fa3bc; }
.b-row:last-child { border-bottom:none; }
.b-val      { font-family:'IBM Plex Mono',monospace; font-weight:600; font-size:12px; }
.b-val.g    { color:#00d68f; } .b-val.r { color:#ff4458; }
.b-row.total         { color:#ffc94d; font-weight:700; font-size:14px; }
.b-row.total .b-val  { color:#ffc94d; font-size:15px; }
.leftover   { background:#0e1420; border:1px solid rgba(255,255,255,.07);
              border-radius:14px; padding:13px 16px;
              display:flex; justify-content:space-between; align-items:center; margin-top:10px; }
.leftover .ll { font-size:12px; color:#8fa3bc; }
.leftover .lv { font-family:'IBM Plex Mono',monospace; font-size:17px;
                font-weight:600; color:#ffc94d; }
.login-btn  { display:block; width:100%; background:#534AB7; color:#fff;
              text-decoration:none; border-radius:14px; font-size:15px;
              font-weight:700; font-family:'Syne',sans-serif; padding:17px;
              text-align:center; margin-bottom:12px; box-sizing:border-box; }
.login-btn:hover { background:#7F77DD; }
.ftxt       { text-align:center; font-size:10px; color:#5a6a82;
              margin-top:1.5rem; line-height:1.9; }
.divider    { height:1px; background:rgba(255,255,255,.06); margin:12px 0; }
</style>
"""
st.markdown(CARD_CSS, unsafe_allow_html=True)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: PIN                                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_pin():
    st.markdown("""
    <div class="pin-wrap">
      <div class="logo">Re<span>balance</span></div>
      <div class="sub">Zerodha portfolio rebalancer<br>PIN enter karo</div>
    </div>
    """, unsafe_allow_html=True)

    pin = st.text_input("pin", placeholder="• • • • • •", max_chars=6,
                        type="password", label_visibility="collapsed")

    if st.session_state.pin_attempts >= 5:
        st.error("Bahut zyada galat attempts. App reload karo.")
        return

    if st.button("Unlock →"):
        if pin == APP_PIN:
            st.session_state.stage = "login"
            st.session_state.pin_attempts = 0
            st.rerun()
        else:
            st.session_state.pin_attempts += 1
            left = 5 - st.session_state.pin_attempts
            st.error(f"Galat PIN. {left} attempts baaki hain.")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: LOGIN                                                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_login():
    kite      = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()

    st.markdown("""
    <div class="logo">Re<span>balance</span></div>
    <div class="step-pill">Step 1 &nbsp;·&nbsp; Zerodha Login</div>
    """, unsafe_allow_html=True)

    # Kite session error tha to yahan dikhao
    if "_kite_err" in st.session_state:
        st.error(f"Kite login fail hua: {st.session_state.pop('_kite_err')}")

    st.markdown("""
    <p style="color:#8fa3bc;font-size:13px;line-height:1.7;margin-bottom:1.2rem">
    Neeche button tap karo → Zerodha login page khulega →
    apne credentials se login karo → automatically yahan wapas aa jaayega.
    </p>
    """, unsafe_allow_html=True)

    # Opens Kite login, Zerodha redirects back with ?request_token=
    st.markdown(
        f'<a class="login-btn" href="{login_url}" target="_self">🔐 &nbsp;Zerodha se Login Karo</a>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    if st.button("← Wapas (PIN screen)", type="secondary"):
        st.session_state.stage = "pin"
        st.rerun()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STAGE: UPLOAD                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
def stage_upload():
    st.markdown("""
    <div class="logo">Re<span>balance</span></div>
    <div class="step-pill">Step 2 &nbsp;·&nbsp; Excel Upload</div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <p style="color:#8fa3bc;font-size:13px;line-height:1.7;margin-bottom:1rem">
    Screener Excel file upload karo. <b style="color:#dce8f5">"Portfolio Rebalancing"</b>
    sheet se Sell aur Buy lists automatically read ho jaayengi.
    </p>
    """, unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Excel", type=["xlsx", "xls"], label_visibility="collapsed"
    )

    if uploaded:
        try:
            df = pd.read_excel(
                uploaded, sheet_name="Portfolio Rebalancing", header=0
            )
            sell_col = next(
                (c for c in df.columns if "sell" in c.lower()), None
            )
            buy_col = next(
                (c for c in df.columns if "buy" in c.lower()), None
            )

            if not sell_col or not buy_col:
                st.error("'Sell Stocks' ya 'Buy Stocks' column nahi mili.")
                return

            sells = [
                s.strip() for s in df[sell_col].dropna().tolist()
                if str(s).strip().upper() not in ("SELL STOCKS", "")
            ]
            buys = [
                b.strip() for b in df[buy_col].dropna().tolist()
                if str(b).strip().upper() not in ("BUY STOCKS", "")
            ]

            if not sells and not buys:
                st.error("Sell aur Buy dono lists empty hain.")
                return

            # Preview
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    f"<p style='color:#ff4458;font-weight:700;margin-bottom:6px'>"
                    f"SELL · {len(sells)}</p>",
                    unsafe_allow_html=True,
                )
                for s in sells:
                    st.markdown(
                        f"<p style='font-family:monospace;font-size:13px;"
                        f"margin:2px 0;color:#dce8f5'>{s}</p>",
                        unsafe_allow_html=True,
                    )
            with col2:
                st.markdown(
                    f"<p style='color:#00d68f;font-weight:700;margin-bottom:6px'>"
                    f"BUY · {len(buys)}</p>",
                    unsafe_allow_html=True,
                )
                for b in buys:
                    st.markdown(
                        f"<p style='font-family:monospace;font-size:13px;"
                        f"margin:2px 0;color:#dce8f5'>{b}</p>",
                        unsafe_allow_html=True,
                    )

            st.markdown("<br>", unsafe_allow_html=True)

            if st.button("Dashboard Load Karo →"):
                st.session_state.sell_syms = sells
                st.session_state.buy_syms  = buys
                with st.spinner("Holdings, LTP aur fund data aa raha hai..."):
                    try:
                        d = fetch_all(st.session_state.kite, sells, buys)
                        st.session_state.data  = d
                        st.session_state.stage = "dashboard"
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Data fetch failed: {exc}")

        except Exception as exc:
            st.error(f"Excel error: {exc}")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    if st.button("← Logout (Zerodha se)", type="secondary"):
        for k in ["kite", "sell_syms", "buy_syms", "data"]:
            st.session_state[k] = None if k == "kite" else ([] if "syms" in k else None)
        st.session_state.stage = "login"
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

    # ── Sticky-style header ──────────────────────────────────────────────────
    st.markdown(f"""
    <div style="padding:.8rem 0 .4rem">
      <div class="logo" style="font-size:20px;padding:.4rem 0 .6rem">
        Re<span>balance</span>
      </div>
      <div class="strip">
        <div class="s-pill inv">
          <span class="s-lbl">Investable</span>
          <span class="s-val g">{inr(d['invest'])}</span>
        </div>
        <div class="s-pill buf">
          <span class="s-lbl">Buffer</span>
          <span class="s-val r">−{inr(d['buf'])}</span>
        </div>
        <div class="s-pill">
          <span class="s-lbl">Leftover</span>
          <span class="s-val y">{inr(d['leftover'])}</span>
        </div>
      </div>
      <div class="ts">Updated: {d['ts']}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Refresh button ───────────────────────────────────────────────────────
    if st.button("⟳   Refresh (Kite mein sell ke baad tap karo)"):
        with st.spinner("Holdings, LTP aur funds refresh ho rahe hain..."):
            try:
                d = fetch_all(
                    st.session_state.kite,
                    st.session_state.sell_syms,
                    st.session_state.buy_syms,
                )
                st.session_state.data = d
                st.rerun()
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")

    # ── SELL section ─────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-title sell">SELL &nbsp;<span style="font-size:14px;'
        f'color:#5a6a82">{len(d["sell_rows"])} stocks</span></div>',
        unsafe_allow_html=True,
    )
    for r in d["sell_rows"]:
        st.markdown(sell_card(r), unsafe_allow_html=True)

    # ── Fund bridge ──────────────────────────────────────────────────────────
    st.markdown(bridge_html(d), unsafe_allow_html=True)

    # ── BUY section ──────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-title buy">BUY &nbsp;<span style="font-size:14px;'
        f'color:#5a6a82">{d["n_buy"]} stocks</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="per-note">Equal split → <b>{inr(d["per_stk"])}</b> per stock</div>',
        unsafe_allow_html=True,
    )
    for r in d["buy_rows"]:
        st.markdown(buy_card(r), unsafe_allow_html=True)

    # ── Leftover ─────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="leftover">
      <span class="ll">Remaining cash (after all buys + charges)</span>
      <span class="lv">{inr(d['leftover'])}</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Actions ──────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        if st.button("↑ Nayi File", type="secondary"):
            st.session_state.stage = "upload"
            st.session_state.data  = None
            st.rerun()
    with col2:
        if st.button("⏏ Logout", type="secondary"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="ftxt">
      Charges: STT 0.1% sell · Exchange ~0.03% · Brokerage ₹20/order + 18% GST<br>
      Buy: Stamp duty 0.015% · Buffer 0.6% of pool covers all buy-side charges<br>
      Estimates only — actual fill price may differ. Kite pe verify karke order lagao.
    </div>
    """, unsafe_allow_html=True)


# ── Router ────────────────────────────────────────────────────────────────────
_router = {
    "pin":       stage_pin,
    "login":     stage_login,
    "upload":    stage_upload,
    "dashboard": stage_dashboard,
}
_router.get(st.session_state.stage, stage_pin)()
