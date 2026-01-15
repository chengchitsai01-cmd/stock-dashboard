import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
import plotly.graph_objects as go
from datetime import datetime
import time
import random

# ==========================================
# 1. 設定
# ==========================================
st.set_page_config(page_title="AI 全方位看盤室 V7.7 (雙模引版本)", layout="wide")

try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        ai_available = True
    else:
        import toml
        secrets = toml.load(".streamlit/secrets.toml")
        genai.configure(api_key=secrets["GOOGLE_API_KEY"])
        ai_available = True
except:
    ai_available = False

DATA_FILE = "trade_history.csv"

# === 擴充對照表 ===
STOCK_MAP = {
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", 
    "台達電": "2308.TW", "聯電": "2303.TW", "廣達": "2382.TW", 
    "緯創": "3231.TW", "緯穎": "6669.TW", "技嘉": "2376.TW",
    "華碩": "2357.TW", "宏碁": "2353.TW", "光寶科": "2301.TW",
    "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW", 
    "兆豐金": "2886.TW", "玉山金": "2884.TW", "元大金": "2885.TW", 
    "中鋼": "2002.TW", "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW",
    "中華電": "2412.TW", "0050": "0050.TW", "0056": "0056.TW", 
    "00878": "00878.TW", "00929": "00929.TW", "00940": "00940.TW"
}

TICKER_TO_NAME = {v: k for k, v in STOCK_MAP.items()}
WATCHLIST = ["2330.TW", "2317.TW", "2454.TW", "2603.TW", "2891.TW", "00878.TW"]

def smart_stock_parser(user_input):
    user_input = user_input.strip()
    if user_input in STOCK_MAP: return STOCK_MAP[user_input]
    if user_input.isdigit(): return f"{user_input}.TW"
    user_input = user_input.upper()
    if not user_input.endswith(".TW") and user_input[0].isdigit(): return f"{user_input}.TW"
    return user_input

def get_stock_name(ticker):
    return TICKER_TO_NAME.get(ticker, ticker)

@st.cache_data(ttl=60)
def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.fast_info.last_price
    except:
        return 0.0

@st.cache_data(ttl=300)
def get_stock_detail(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="1y") 
        return info, hist
    except:
        return None, None

def evaluate_stock(info, price, ma60):
    badges = []
    score = 0
    eps = info.get('trailingEps', 0)
    if eps is None: eps = 0
    if eps > 1:
        badges.append("💰EPS優")
        score += 1

    yield_val = info.get('dividendYield', 0)
    if yield_val is None: yield_val = 0
    if yield_val > 0.05:
        badges.append("🥥高股息")
        score += 1

    roe = info.get('returnOnEquity', 0)
    if roe is None: roe = 0
    if roe > 0.15:
        badges.append("🚀高ROE")
        score += 1
    
    is_diamond = (score >= 2)
    gap = (ma60 - price) / ma60 * 100
    status_text = ""
    if gap > 0: status_text = f"🟢 便宜 (低於季線 {gap:.1f}%)"
    else: status_text = f"🔴 昂貴 (高於季線 {abs(gap):.1f}%)"

    return badges, is_diamond, status_text, eps, yield_val, roe

# ==========================================
# 🚀 AI 核心：雙模型保險機制 (Flash 2.0 -> Flash 1.5)
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def ask_ai_single(ticker, stock_name, info_str):
    # 策略：先試 2.0 (快)，失敗就轉 1.5 (穩)
    models_to_try = ['gemini-2.0-flash-exp', 'gemini-1.5-flash']
    
    for model_name in models_to_try:
        try:
            # 隨機等待一點點時間，避開並發鎖定
            time.sleep(random.uniform(0.5, 1.5))
            
            model = genai.GenerativeModel(model_name)
            prompt = f"""
            分析台股 {stock_name} ({ticker})：
            數據：{info_str}
            請用繁體中文給 3 點短評 (100字內)：1.亮點 2.風險 3.操作建議。
            """
            response = model.generate_content(prompt)
            return response.text
            
        except Exception as e:
            # 如果這個模型失敗，就換下一個，先不要報錯
            continue
            
    # 如果兩個模型都失敗了，才回傳錯誤訊息
    return "😅 系統目前繁忙中 (Google API 限流)，請休息 2 分鐘後再試。"

# 補上你原本缺少的 ask_ai_daily 函數
@st.cache_data(ttl=3600, show_spinner=False)
def ask_ai_daily(holdings_text):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"用戶庫存：{holdings_text}。請給 100 字內的繁體中文總評：加碼機會與風險提示。"
        response = model.generate_content(prompt)
        return response.text
    except:
        return "😅 AI 休息中，請稍後再試。"

# ==========================================
# 3. 主程式介面
# ==========================================
st.title("📱 AI 全方位看盤室 V7.7 (雙模引擎版)")

tab1, tab2, tab3 = st.tabs(["🔍 個股行情", "📡 鑽石掃描", "📊 我的資產"])

# Tab 1: 個股行情
with tab1:
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        q_stock = st.text_input("輸入代號或名稱", "2330", label_visibility="collapsed")
    with col_btn:
        st.button("查詢", use_container_width=True)

    target_id = smart_stock_parser(q_stock)
    target_name = get_stock_name(target_id)
    
    info, hist = get_stock_detail(target_id)
    
    if info and not hist.empty:
        curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
        prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
        change = curr_price - prev_close
        pct_change = (change / prev_close) * 100
        
        ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
        badges, is_diamond, tech_status, eps, yield_val, roe = evaluate_stock(info, curr_price, ma60)

        st.markdown(f"## {target_name} ({target_id})")
        
        c1, c
