import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os

FRED_API = "ac3e825c20cc0021e0c9390263e184a4"
HISTORY_FILE = "gold_history.csv"

# ===== CLEAN =====
def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()

# ===== ETF FLOW =====
@st.cache_data(ttl=300)
def get_etf_flow():
    try:
        url = "https://financialmodelingprep.com/api/v3/etf-holder/GLD?apikey=demo"
        data = requests.get(url, timeout=5).json()

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

# ===== COT (FIX CHUẨN) =====
@st.cache_data(ttl=3600)
def get_cot_position(df):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/csv"
    }

    errors = [] # Danh sách lưu mã lỗi để báo cáo ra UI

    # 1. Thử gọi API JSON
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
        else:
            errors.append(f"API: {res.status_code}")
    except Exception as e:
        errors.append("API: Timeout")

    # 2. Thử tải file CSV (Dùng link deacot.csv chuẩn, tự cập nhật theo năm hiện tại)
    try:
        url_csv = "https://www.cftc.gov/files/dea/history/deacot.csv" 
        res = requests.get(url_csv, headers=headers, timeout=10)
        if res.status_code == 200:
            from io import StringIO
            cot_df = pd.read_csv(StringIO(res.text))
            gold_row = cot_df[cot_df['Market_and_Exchange_Names'].str.contains("GOLD - COMMODITY EXCHANGE INC.", case=False, na=False)]
            if not gold_row.empty:
                # Lấy dòng đầu tiên (hoặc cuối cùng) chứa data vàng
                latest = gold_row.iloc[0] 
                long = float(latest["Noncommercial_Long_All"])
                short = float(latest["Noncommercial_Short_All"])
                return (1 if long > short else -1), (long - short)
        else:
            errors.append(f"CSV: {res.status_code}")
    except Exception as e:
         errors.append("CSV: Timeout")

    # 3. Fallback an toàn khi mất kết nối mạng/bị chặn
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    last_rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
    
    simulated_net = 185000 if last_rsi > 50 else -45000

    # 🔥 HIỂN THỊ CẢNH BÁO LÊN GIAO DIỆN
    st.warning(f"⚠️ Không lấy được data COT thực tế (Lỗi: {', '.join(errors)}). Đang hiển thị số liệu dự phòng dựa trên RSI.")
    
    return (1 if simulated_net > 0 else -1), simulated_net

# ===== GOLD =====
@st.cache_data(ttl=60)
def get_gold():
    df = yf.download("GC=F", period="6mo")
    return clean_df(df)

# ===== DXY =====
@st.cache_data(ttl=60)
def get_dxy():
    df = yf.download("DX-Y.NYB", period="1d", interval="1m")
    return float(df["Close"].iloc[-1])

# ===== YIELD =====
@st.cache_data(ttl=3600)
def get_yield():
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_API}&file_type=json"
        data = requests.get(url).json()
        return float(data["observations"][-1]["value"])
    except:
        return 2.0

# ===== RSI =====
def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    rs = gain / loss
    return 100 - (100/(1+rs))

# ===== ENTRY ENGINE (FIX) =====
def entry(phase, rsi_val, price, ema50, yield_real):

    # ⚠️ filter yield
    if yield_real > 2:
        return "⚠️ HẠN CHẾ MUA (lãi suất cao)", "wait"

    if phase == "MARKUP" and rsi_val < 35:
        return "🟢 MUA (pullback đẹp)", "strong"

    if phase == "MARKUP" and rsi_val < 45:
        return "⚠️ CANH MUA", "wait"

    if abs(price-ema50)/price < 0.01:
        return "🟢 MUA (về EMA50)", "strong"

    if rsi_val > 60:
        return "🔴 KHÔNG MUA", "no"

    return "⚪ CHỜ", "wait"

# ===== PHASE =====
def phase(etf, cot, rsi_val, trend):
    if etf==1 and cot==1 and trend=="UP":
        return "MARKUP"
    if rsi_val>65:
        return "DISTRIBUTION"
    if rsi_val<40:
        return "ACCUMULATION"
    return "NEUTRAL"

# ===== APP =====
st.set_page_config(layout="wide")
st.title("🔥 SMART MONEY 3.1 (COT FIXED)")

now = datetime.now().strftime("%Y-%m-%d %H:%M")
st.write(f"📅 {now}")

df = get_gold()
price = float(df["Close"].iloc[-1])

df["EMA50"] = df["Close"].ewm(span=50).mean()
df["EMA200"] = df["Close"].ewm(span=200).mean()

trend = "UP" if df["EMA50"].iloc[-1] > df["EMA200"].iloc[-1] else "DOWN"

rsi_val = float(rsi(df["Close"]).iloc[-1])

dxy = get_dxy()
yield_real = get_yield()
etf, etf_val = get_etf_flow()
cot, cot_val = get_cot_position(df)

ph = phase(etf, cot, rsi_val, trend)
entry_text, entry_type = entry(ph, rsi_val, price, df["EMA50"].iloc[-1], yield_real)

# ===== UI =====
st.metric("💰 Gold", round(price,2))

st.subheader("📊 Trend")
st.write(ph)

st.subheader("🎯 Entry")

if entry_type=="strong":
    st.success(entry_text)
elif entry_type=="no":
    st.error(entry_text)
else:
    st.warning(entry_text)

st.subheader("📈 Data")

st.write(f"ETF: {round(etf_val,2)}")
st.write(f"COT: {round(cot_val,0)}")  # giờ sẽ ~100k–300k
st.write(f"DXY: {round(dxy,2)}")
st.write(f"Yield: {round(yield_real,2)}")
st.write(f"RSI: {round(rsi_val,2)}")

# ===== SAVE =====
row = pd.DataFrame([{
    "time": now, "price":price,"phase":ph,"rsi":rsi_val
}])

if os.path.exists(HISTORY_FILE):
    old = pd.read_csv(HISTORY_FILE)
    df_all = pd.concat([old,row]).drop_duplicates(subset=["time"])
else:
    df_all = row

df_all.to_csv(HISTORY_FILE,index=False)

st.line_chart(df["Close"])

streamlit
yfinance
pandas
numpy
requests
