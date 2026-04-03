import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os

# ================= CONFIG =================
FRED_API = "ac3e825c20cc0021e0c9390263e184a4"
HISTORY_FILE = "gold_history_v4.csv"

st.set_page_config(page_title="Gold Intelligence V4", layout="wide")
st.title("🏦 GOLD SMART MONEY PREDICTOR V4 — INSTITUTIONAL")

# ================= DATA =================
@st.cache_data(ttl=300)
def get_gold_data():
    df = yf.download("GC=F", period="1y", interval="1d")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    df["EMA50"] = df["Close"].ewm(span=50).mean()
    df["EMA200"] = df["Close"].ewm(span=200).mean()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + (gain / loss)))

    return df

@st.cache_data(ttl=3600)
def get_cot():
    try:
        url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
        params = {
            "cftc_contract_market_code": "088691",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": 1
        }
        res = requests.get(url, params=params, timeout=10)
        data = res.json()[0]

        long = float(data["noncomm_positions_long_all"])
        short = float(data["noncomm_positions_short_all"])

        net = long - short
        return net, "REAL"
    except:
        return None, "ERROR"

@st.cache_data(ttl=300)
def get_macro():
    try:
        dxy = float(yf.download("DX-Y.NYB", period="5d")["Close"].iloc[-1])
    except:
        dxy = None

    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_API}&file_type=json"
        data = requests.get(url).json()
        ry = float(data["observations"][-1]["value"])
    except:
        ry = None

    return dxy, ry

# ================= LOGIC =================
def compute_score(cot, trend, rsi, dxy, ry):
    score = 0

    if cot is not None:
        score += 2 if cot > 0 else -2

    score += 1 if trend == "UP" else -1

    if rsi < 40:
        score += 1
    elif rsi > 70:
        score -= 1

    if dxy is not None and not pd.isna(dxy):
        score += -1 if dxy > 103 else 1

    if ry is not None and not pd.isna(ry):
        score += -1 if ry > 2 else 1

    return score


def get_phase(cot, trend):
    if cot is None:
        return "UNKNOWN"

    if cot > 0 and trend == "UP":
        return "MARKUP"
    elif cot > 0 and trend == "DOWN":
        return "ACCUMULATION"
    elif cot < 0 and trend == "UP":
        return "DISTRIBUTION"
    else:
        return "MARKDOWN"


def get_action(score):
    if score >= 3:
        return "🟢 STRONG BUY", "green"
    elif score >= 1:
        return "🟡 BUY", "orange"
    elif score <= -3:
        return "🔴 STRONG SELL", "red"
    elif score <= -1:
        return "🟠 SELL", "orange"
    else:
        return "⚪ NEUTRAL", "gray"

# ================= RUN =================
df = get_gold_data()
price = df["Close"].iloc[-1]
rsi = df["RSI"].iloc[-1]
trend = "UP" if df["EMA50"].iloc[-1] > df["EMA200"].iloc[-1] else "DOWN"

cot, cot_status = get_cot()
dxy, ry = get_macro()

score = compute_score(cot, trend, rsi, dxy, ry)
phase = get_phase(cot, trend)
action, color = get_action(score)

# ================= UI =================
st.write(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")

c1, c2, c3 = st.columns(3)
c1.metric("Gold Price", f"${price:,.2f}")
c2.metric("Phase", phase)
c3.markdown(f"<div style='background:{color};padding:15px;border-radius:10px;text-align:center;color:white'>{action}</div>", unsafe_allow_html=True)

st.divider()

c1, c2, c3, c4, c5 = st.columns(5)
c1.write(f"COT: {cot if cot else 'N/A'} ({cot_status})")
c2.write(f"RSI: {rsi:.2f}")
c3.write(f"Trend: {trend}")
c4.write(f"DXY: {dxy if dxy else 'N/A'}")
c5.write(f"Yield: {ry if ry else 'N/A'}")

st.subheader("📊 Chart")
st.line_chart(df[["Close", "EMA50", "EMA200"]])

# ================= HISTORY =================
row = {
    "time": datetime.now(),
    "price": price,
    "score": score,
    "action": action,
    "phase": phase
}

if os.path.exists(HISTORY_FILE):
    h = pd.read_csv(HISTORY_FILE)
    h = pd.concat([h, pd.DataFrame([row])])
else:
    h = pd.DataFrame([row])

h.to_csv(HISTORY_FILE, index=False)

st.subheader("📜 History")
st.dataframe(h.tail(20), use_container_width=True)

# ================= DEBUG PANEL =================
with st.expander("🧠 Debug Logic"):
    st.write({
        "score": score,
        "cot": cot,
        "trend": trend,
        "rsi": rsi,
        "dxy": dxy,
        "yield": ry
    })

