import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime
import os

# ===== CẤU HÌNH HỆ THỐNG =====
FRED_API = "ac3e825c20cc0021e0c9390263e184a4" # Giữ nguyên API của bạn
HISTORY_FILE = "gold_history.csv" # File lưu lịch sử dự đoán

# ===== HÀM LÀM SẠCH DỮ LIỆU =====
def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()

# ===== LẤY DỮ LIỆU ETF (Dòng tiền quỹ lớn) =====
@st.cache_data(ttl=300)
def get_etf_flow():
    try:
        url = "https://financialmodelingprep.com/api/v3/etf-holder/GLD?apikey=demo"
        res = requests.get(url, timeout=5)
        data = res.json()
        if isinstance(data, list) and len(data) > 2:
            flow = float(data[0]["sharesNumber"]) - float(data[1]["sharesNumber"])
            strength = "Mạnh" if abs(flow) > 100000 else "Vừa"
            return (1 if flow > 0 else -1 if flow < 0 else 0), flow, strength
    except:
        pass
    
    # Fallback dùng Volume nếu API lỗi
    df = yf.download("GLD", period="15d")
    df = clean_df(df)
    df["flow"] = np.log(df["Close"]/df["Close"].shift(1)) * df["Volume"]
    flow = df["flow"].rolling(5).mean().iloc[-1]
    return (1 if flow > 0 else -1), flow, "Dựa trên Volume"

# ===== LẤY VỊ THẾ COT (Vị thế các nhà đầu cơ lớn) =====
@st.cache_data(ttl=3600)
def get_cot_position(df_gold):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # Thử lấy từ API CFTC trực tiếp (tốt nhất khi chạy trên Streamlit Cloud)
        url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
        params = {"cftc_contract_market_code": "088691", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1}
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()[0]
            long = float(data.get("noncomm_positions_long_all", 0))
            short = float(data.get("noncomm_positions_short_all", 0))
            net = long - short
            return (1 if net > 0 else -1), net, "Thực tế (CFTC)"
    except:
        pass
    
    # Fallback: Giả lập dựa trên RSI nếu bị chặn IP
    delta = df_gold["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi_val = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
    simulated_net = 168000 if rsi_val > 50 else -45000
    return (1 if simulated_net > 0 else -1), simulated_net, "Dự phòng (RSI)"

# ===== CHỈ SỐ DXY & YIELD (Sức mạnh USD & Lãi suất) =====
@st.cache_data(ttl=300)
def get_market_indicators():
    # DXY: Fix lỗi dữ liệu trống cuối tuần
    try:
        dxy_df = yf.download("DX-Y.NYB", period="5d", interval="1h")
        dxy = float(dxy_df["Close"].iloc[-1]) if not dxy_df.empty else 104.0
    except: dxy = 104.0

    # Real Yield (FRED)
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_API}&file_type=json"
        data = requests.get(url, timeout=10).json()
        yield_val = float(data["observations"][-1]["value"]) if data["observations"][-1]["value"] != "." else 2.0
    except: yield_val = 2.0
    
    return dxy, yield_val

# ===== LOGIC PHÂN TÍCH & CHIẾN THUẬT =====
def get_rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    return 100 - (100/(1+(gain/loss)))

def analyze_strategy(etf, cot, rsi_val, trend, yield_real, price, ema50):
    # Xác định Giai đoạn thị trường
    if etf == 1 and cot == 1 and trend == "UP": phase = "MARKUP (Tăng trưởng)"
    elif rsi_val > 70: phase = "DISTRIBUTION (Phân phối/Đỉnh)"
    elif rsi_val < 30: phase = "ACCUMULATION (Tích lũy/Đáy)"
    else: phase = "NEUTRAL (Trung lập)"

    # Quyết định điểm vào
    if yield_real > 2.1: # Ngưỡng lãi suất thực gây áp lực giảm vàng
        action, color = "⚠️ HẠN CHẾ MUA (Lãi suất cao)", "wait"
    elif phase.startswith("MARKUP") and rsi_val < 40:
        action, color = "🟢 MUA MẠNH (Pullback trong xu hướng tăng)", "strong"
    elif abs(price - ema50)/price < 0.01 and trend == "UP":
        action, color = "🟢 MUA (Gần hỗ trợ EMA50)", "strong"
    elif rsi_val > 65:
        action, color = "🔴 KHÔNG MUA (Rủi ro đu đỉnh cao)", "no"
    else:
        action, color = "⚪ CHỜ TÍN HIỆU (Quan sát thêm)", "wait"
    
    return phase, action, color

# ===== GIAO DIỆN STREAMLIT =====
st.set_page_config(page_title="Gold Master Predictor", layout="wide")
st.title("🔥 GOLD SMART MONEY MASTER V3.5")

# 1. Lấy dữ liệu cơ sở
df_gold = clean_df(yf.download("GC=F", period="6mo"))
price = float(df_gold["Close"].iloc[-1])
df_gold["EMA50"] = df_gold["Close"].ewm(span=50).mean()
df_gold["EMA200"] = df_gold["Close"].ewm(span=200).mean()

# 2. Tính toán kỹ thuật
rsi_val = float(get_rsi(df_gold["Close"]).iloc[-1])
trend = "UP" if df_gold["EMA50"].iloc[-1] > df_gold["EMA200"].iloc[-1] else "DOWN"

# 3. Lấy chỉ số liên thị trường
dxy, yield_real = get_market_indicators()
etf_dir, etf_val, etf_s = get_etf_flow()
cot_dir, cot_val, cot_s = get_cot_position(df_gold)

# 4. Phân tích chiến thuật
phase, action, color_type = analyze_strategy(etf_dir, cot_dir, rsi_val, trend, yield_real, price, df_gold["EMA50"].iloc[-1])

# --- HIỂN THỊ ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")
st.write(f"📅 Cập nhật hệ thống: **{now}**")

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("💰 Giá Vàng (Future)", f"${price:,.2f}", f"{price - df_gold['Close'].iloc[-2]:,.2f}")
col_m2.info(f"📈 Giai đoạn: **{phase}**")
with col_m3:
    if color_type == "strong": st.success(f"🎯 Khuyến nghị: {action}")
    elif color_type == "no": st.error(f"🎯 Khuyến nghị: {action}")
    else: st.warning(f"🎯 Khuyến nghị: {action}")

st.divider()

# Chi tiết các thông số dòng tiền
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.write("**Dòng tiền ETF (GLD)**")
    st.write(f"{'🟢 VÀO' if etf_dir==1 else '🔴 RA'}: {etf_val:,.0f}")
    st.caption(f"Độ mạnh: {etf_s}")
with c2:
    st.write("**Vị thế Quỹ (COT)**")
    st.write(f"{'🟢 MUA RÒNG' if cot_dir==1 else '🔴 BÁN RÒNG'}: {cot_val:,.0f}")
    st.caption(f"Nguồn: {cot_s}")
with c3:
    st.write("**Chỉ số USD (DXY)**")
    st.write(f"📊 {dxy:.2f}")
    st.caption("DXY giảm thường tốt cho Vàng")
with c4:
    st.write("**Lãi suất thực (Yield)**")
    st.write(f"📉 {yield_real:.2f}%")
    st.caption("Yield > 2.0% là áp lực giảm")

# Biểu đồ kỹ thuật
st.subheader("📊 Biểu đồ xu hướng (Price & EMA50/200)")
st.line_chart(df_gold[["Close", "EMA50", "EMA200"]])

# ===== XỬ LÝ LỊCH SỬ (Dựa trên app 2.0.py) =====
new_data = pd.DataFrame([{
    "Date": now, "Price": price, "Phase": phase, "Action": action, 
    "RSI": round(rsi_val, 2), "DXY": dxy, "Yield": yield_real, "COT_Net": cot_val
}])

if os.path.exists(HISTORY_FILE):
    history_df = pd.read_csv(HISTORY_FILE)
    # Chỉ lưu nếu thời gian khác nhau (tránh trùng lặp khi F5 liên tục)
    if history_df.empty or history_df.iloc[-1]["Date"] != now:
        history_df = pd.concat([history_df, new_data], ignore_index=True)
else:
    history_df = new_data

history_df.to_csv(HISTORY_FILE, index=False)

st.divider()
st.subheader("📜 Lịch sử dự đoán & Tín hiệu")
st.dataframe(history_df.tail(10), use_container_width=True)

st.download_button(
    label="📥 Tải lịch sử dự đoán (CSV)",
    data=history_df.to_csv(index=False),
    file_name="gold_investment_history.csv",
    mime="text/csv"
)
