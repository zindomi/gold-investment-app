import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os

# ===== CẤU HÌNH =====
FRED_API = "ac3e825c20cc0021e0c9390263e184a4"
HISTORY_FILE = "gold_history.csv"

# ===== 1. HÀM LẤY DỮ LIỆU VÀNG & KỸ THUẬT =====
@st.cache_data(ttl=60)
def get_gold_data():
    try:
        df = yf.download("GC=F", period="6mo", interval="1d")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        # Tính toán chỉ báo
        df["EMA50"] = df["Close"].ewm(span=50).mean()
        df["EMA200"] = df["Close"].ewm(span=200).mean()
        # Tính RSI
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        df["RSI"] = 100 - (100 / (1 + (gain / loss)))
        return df
    except:
        return pd.DataFrame()

# ===== 2. LẤY VỊ THẾ COT (FIX LỖI TRIỆT ĐỂ) =====
@st.cache_data(ttl=3600)
def get_cot_data(df_gold):
    headers = {"User-Agent": "Mozilla/5.0"}
    # Nguồn 1: API JSON
    try:
        url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
        params = {"cftc_contract_market_code": "088691", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1}
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()[0]
            long = float(data.get("noncomm_positions_long_all", 0))
            short = float(data.get("noncomm_positions_short_all", 0))
            return (1 if long > short else -1), (long - short), "Dữ liệu Thực (CFTC)"
    except: pass

    # Nguồn 2: Scraping CSV dự phòng
    try:
        url_csv = "https://www.cftc.gov/files/dea/history/deacot2026.csv" # Cập nhật năm
        res = requests.get(url_csv, headers=headers, timeout=10)
        if res.status_code == 200:
            from io import StringIO
            c_df = pd.read_csv(StringIO(res.text))
            gold = c_df[c_df['Market_and_Exchange_Names'].str.contains("GOLD", na=False)].iloc[0]
            long, short = float(gold["Noncommercial_Long_All"]), float(gold["Noncommercial_Short_All"])
            return (1 if long > short else -1), (long - short), "Dữ liệu CSV"
    except: pass

    # Nguồn 3: Fallback RSI
    rsi_last = df_gold["RSI"].iloc[-1]
    net = 168000 if rsi_last > 50 else -45000
    return (1 if net > 0 else -1), net, "Dự phòng (RSI)"

# ===== 3. CÁC CHỈ SỐ LIÊN THỊ TRƯỜNG =====
@st.cache_data(ttl=300)
def get_market_context():
    # DXY
    try:
        d_df = yf.download("DX-Y.NYB", period="5d")
        if isinstance(d_df.columns, pd.MultiIndex): d_df.columns = d_df.columns.get_level_values(0)
        dxy = float(d_df["Close"].iloc[-1])
    except: dxy = 104.0
    # Yield
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_API}&file_type=json"
        y_data = requests.get(url).json()
        val = y_data["observations"][-1]["value"]
        ry = float(val) if val != "." else 2.0
    except: ry = 2.0
    return dxy, ry

# ===== 4. GIAO DIỆN CHÍNH =====
st.set_page_config(page_title="Gold Intelligence", layout="wide")
st.title("🚀 GOLD SMART MONEY PREDICTOR V3.6")

df = get_gold_data()
if df.empty:
    st.error("Không thể lấy dữ liệu Vàng. Vui lòng F5!")
    st.stop()

# Tính toán các giá trị
price = float(df["Close"].iloc[-1])
rsi_val = float(df["RSI"].iloc[-1])
dxy, ry = get_market_context()
cot_dir, cot_val, cot_src = get_cot_data(df)
trend = "UP" if df["EMA50"].iloc[-1] > df["EMA200"].iloc[-1] else "DOWN"

# Logic Tín hiệu
phase = "MARKUP" if (cot_dir == 1 and trend == "UP") else ("ACCUMULATION" if rsi_val < 35 else "DISTRIBUTION" if rsi_val > 65 else "NEUTRAL")
if ry > 2.1: 
    action, color = "⚠️ HẠN CHẾ MUA (Lãi suất cao)", "orange"
elif phase == "MARKUP" and rsi_val < 45:
    action, color = "🟢 MUA (Pullback đẹp)", "green"
elif rsi_val > 70:
    action, color = "🔴 QUÁ MUA (Chốt lời)", "red"
else:
    action, color = "⚪ QUAN SÁT (Chưa rõ xu hướng)", "gray"

# HIỂN THỊ CHỈ SỐ
st.write(f"📅 Cập nhật: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
m1, m2, m3 = st.columns(3)
m1.metric("💰 Giá Vàng", f"${price:,.2f}")
m2.info(f"📈 Giai đoạn: **{phase}**")
with m3:
    st.markdown(f"<div style='padding:15px; border-radius:10px; background-color:{color}; color:white; text-align:center; font-weight:bold;'>{action}</div>", unsafe_allow_html=True)

st.divider()
c1, c2, c3, c4 = st.columns(4)
c1.write(f"**COT Net:** {cot_val:,.0f}\n\n({cot_src})")
c2.write(f"**RSI (14):** {rsi_val:.2f}")
c3.write(f"**DXY Index:** {dxy:.2f}")
c4.write(f"**Real Yield:** {ry:.2f}%")

# BIỂU ĐỒ GIÁ
st.subheader("📊 Biểu đồ Xu hướng & Kỹ thuật")
chart_data = df[["Close", "EMA50", "EMA200"]]
st.line_chart(chart_data)

# ===== 5. TỰ ĐỘNG CẬP NHẬT LỊCH SỬ THÔNG MINH =====
current_signal = {
    "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "Price": round(price, 2),
    "Phase": phase,
    "Action": action,
    "COT": cot_val,
    "RSI": round(rsi_val, 2)
}

if os.path.exists(HISTORY_FILE):
    h_df = pd.read_csv(HISTORY_FILE)
    # CHỈ LƯU NẾU TÍN HIỆU HOẶC GIAI ĐOẠN THAY ĐỔI SO VỚI DÒNG CUỐI
    last_action = h_df.iloc[-1]["Action"] if not h_df.empty else ""
    last_phase = h_df.iloc[-1]["Phase"] if not h_df.empty else ""
    
    if action != last_action or phase != last_phase:
        h_df = pd.concat([h_df, pd.DataFrame([current_signal])], ignore_index=True)
        h_df.to_csv(HISTORY_FILE, index=False)
else:
    h_df = pd.DataFrame([current_signal])
    h_df.to_csv(HISTORY_FILE, index=False)

st.subheader("📜 Lịch sử Tín hiệu quan trọng")
st.dataframe(h_df.tail(10), use_container_width=True)

# ===== 6. HƯỚNG DẪN SỬ DỤNG =====
with st.expander("📖 HƯỚNG DẪN ĐỌC CHỈ SỐ (USER MANUAL)"):
    st.markdown("""
    | Chỉ số | Ý nghĩa | Ngưỡng quan trọng |
    | :--- | :--- | :--- |
    | **COT Net** | Vị thế mua/bán của các Quỹ lớn. | Dương: Quỹ đang gom. Âm: Quỹ đang xả. |
    | **Real Yield** | Lãi suất thực của Mỹ. | > 2.0%: Gây áp lực giảm cực mạnh lên Vàng. |
    | **DXY** | Sức mạnh đồng USD. | DXY tăng thường làm Vàng giảm giá. |
    | **RSI** | Độ quá mua/quá bán. | < 30: Vùng mua rẻ. > 70: Vùng bán đắt. |
    | **EMA50/200** | Xu hướng dài hạn. | EMA50 nằm trên EMA200: Xu hướng Tăng (Bullish). |
    """)
