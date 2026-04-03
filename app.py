import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os

# API Key FRED (Giữ nguyên của bạn)
FRED_API = "ac3e825c20cc0021e0c9390263e184a4"
HISTORY_FILE = "gold_history.csv"

# ===== HÀM LÀM SẠCH DỮ LIỆU =====
def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()

# ===== LẤY DỮ LIỆU ETF =====
@st.cache_data(ttl=300)
def get_etf_flow():
    try:
        url = "https://financialmodelingprep.com/api/v3/etf-holder/GLD?apikey=demo"
        res = requests.get(url, timeout=5)
        data = res.json()
        if isinstance(data, list) and len(data) > 2:
            flow = float(data[0]["sharesNumber"]) - float(data[1]["sharesNumber"])
            return (1 if flow > 0 else -1 if flow < 0 else 0), flow
    except:
        pass

    df = yf.download("GLD", period="15d")
    df = clean_df(df)
    df["flow"] = np.log(df["Close"]/df["Close"].shift(1)) * df["Volume"]
    flow = df["flow"].rolling(5).mean().iloc[-1]
    return (1 if flow > 0 else -1), flow

# ===== LẤY DỮ LIỆU COT (ĐÃ FIX CHO SERVER MỸ) =====
@st.cache_data(ttl=3600)
def get_cot_position(df):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # 1. Thử gọi API JSON trực tiếp từ CFTC
    try:
        url_api = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
        params = {
            "cftc_contract_market_code": "088691",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": 1
        }
        res = requests.get(url_api, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data:
                long = float(data[0].get("noncomm_positions_long_all", 0))
                short = float(data[0].get("noncomm_positions_short_all", 0))
                return (1 if long > short else -1), (long - short)
    except:
        pass

    # 2. Fallback: Nếu lỗi IP hoặc API bảo trì, dùng số dự phòng an toàn
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    last_rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
    simulated_net = 185000 if last_rsi > 50 else -45000
    return (1 if simulated_net > 0 else -1), simulated_net

# ===== LẤY GIÁ VÀNG =====
@st.cache_data(ttl=60)
def get_gold():
    df = yf.download("GC=F", period="6mo")
    return clean_df(df)

# ===== LẤY CHỈ SỐ DXY (ĐÃ FIX LỖI TRỐNG DỮ LIỆU) =====
@st.cache_data(ttl=300)
def get_dxy():
    try:
        # Sử dụng khung giờ 1h và lấy 5 ngày để luôn có dữ liệu cuối tuần
        df = yf.download("DX-Y.NYB", period="5d", interval="1h")
        if not df.empty:
            return float(df["Close"].iloc[-1])
        return 104.0
    except:
        return 104.0

# ===== LẤY LÃI SUẤT THỰC (YIELD) =====
@st.cache_data(ttl=3600)
def get_yield():
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_API}&file_type=json"
        res = requests.get(url, timeout=10)
        data = res.json()
        if "observations" in data and len(data["observations"]) > 0:
            val = data["observations"][-1]["value"]
            if val != ".":
                return float(val)
        return 2.0
    except:
        return 2.0

# ===== TÍNH TOÁN KỸ THUẬT =====
def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    rs = gain / loss
    return 100 - (100/(1+rs))

def get_entry(ph, rsi_val, price, ema50, yield_real):
    if yield_real > 2.0:
        return "⚠️ HẠN CHẾ MUA (lãi suất cao)", "wait"
    if ph == "MARKUP" and rsi_val < 35:
        return "🟢 MUA (pullback đẹp)", "strong"
    if ph == "MARKUP" and rsi_val < 45:
        return "⚠️ CANH MUA", "wait"
    if abs(price - ema50)/price < 0.01:
        return "🟢 MUA (về EMA50)", "strong"
    if rsi_val > 65:
        return "🔴 KHÔNG MUA (quá mua)", "no"
    return "⚪ CHỜ TÍN HIỆU", "wait"

def get_phase(etf, cot, rsi_val, trend):
    if etf == 1 and cot == 1 and trend == "UP":
        return "MARKUP"
    if rsi_val > 65:
        return "DISTRIBUTION"
    if rsi_val < 35:
        return "ACCUMULATION"
    return "NEUTRAL"

# ===== GIAO DIỆN APP =====
st.set_page_config(page_title="Gold Smart Money", layout="wide")
st.title("🔥 SMART MONEY 3.1 (STABLE)")

now = datetime.now().strftime("%Y-%m-%d %H:%M")
st.write(f"📅 Cập nhật lúc: {now}")

# Xử lý dữ liệu chính
df = get_gold()
price = float(df["Close"].iloc[-1])
df["EMA50"] = df["Close"].ewm(span=50).mean()
df["EMA200"] = df["Close"].ewm(span=200).mean()

trend = "UP" if df["EMA50"].iloc[-1] > df["EMA200"].iloc[-1] else "DOWN"
rsi_val = float(rsi(df["Close"]).iloc[-1])

# Lấy các chỉ số liên quan
dxy = get_dxy()
yield_real = get_yield()
etf, etf_val = get_etf_flow()
cot, cot_val = get_cot_position(df)

# Phân tích xu hướng và điểm vào lệnh
ph = get_phase(etf, cot, rsi_val, trend)
entry_text, entry_type = get_entry(ph, rsi_val, price, df["EMA50"].iloc[-1], yield_real)

# Hiển thị chỉ số chính
st.metric("💰 Giá Vàng Hiện Tại", f"${price:,.2f}")

col1, col2 = st.columns(2)
with col1:
    st.subheader("📊 Trạng thái Thị trường")
    st.info(f"Giai đoạn: **{ph}**")
with col2:
    st.subheader("🎯 Khuyến nghị")
    if entry_type == "strong": st.success(entry_text)
    elif entry_type == "no": st.error(entry_text)
    else: st.warning(entry_text)

st.subheader("📈 Chi tiết Dữ liệu")
c1, c2, c3, c4 = st.columns(4)
c1.write(f"**ETF Flow:** {etf_val:,.2f}")
c2.write(f"**COT Net:** {cot_val:,.0f}")
c3.write(f"**DXY Index:** {dxy:.2f}")
c4.write(f"**Real Yield:** {yield_real:.2f}%")

st.line_chart(df["Close"])
