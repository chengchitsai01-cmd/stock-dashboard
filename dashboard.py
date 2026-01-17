import streamlit as st
import pandas as pd
import os
import yfinance as yf
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import time
import random

# ==========================================
# 1. 設定
# ==========================================
st.set_page_config(page_title="AI 戰情室 V13.0 (新手教練版)", layout="wide")

# 🟢 獵人名單
CANDIDATE_MODELS = [
    'gemini-1.5-flash',
    'gemini-1.5-flash-latest',
    'gemini-2.0-flash-exp',
    'gemini-1.5-pro',
    'gemini-pro'
]

def init_key():
    api_key = None
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        try:
            import toml
            secrets = toml.load(".streamlit/secrets.toml")
            if "GOOGLE_API_KEY" in secrets:
                api_key = secrets["GOOGLE_API_KEY"]
        except:
            pass
    return api_key

API_KEY = init_key()

# 測試連線
def test_connection(api_key, model_name):
    if not api_key: return False, "無 Key"
    headers = {'Content-Type': 'application/json'}
    params = {'key': api_key}
    data = {"contents": [{"parts": [{"text": "Hi"}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    try:
        response = requests.post(url, headers=headers, params=params, json=data, timeout=3)
        if response.status_code == 200: return True, "OK"
        return False, str(response.status_code)
    except Exception as e:
        return False, str(e)

# 自動獵人
@st.cache_resource(show_spinner=False)
def hunt_for_working_model(api_key):
    if not api_key: return None, "無 Key"
    for model in CANDIDATE_MODELS:
        success, msg = test_connection(api_key, model)
        if success: return model, f"✅ 自動鎖定: {model}"
    return None, "😭 全軍覆沒"

AUTO_MODEL = None
HUNT_LOG = ""
if API_KEY:
    AUTO_MODEL, HUNT_LOG = hunt_for_working_model(API_KEY)

AI_AVAILABLE = True if AUTO_MODEL else False
DATA_FILE = "trade_history.csv"

# ==========================================
# 2. 資料與工具
# ==========================================
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
        dividends = stock.dividends
        return info, hist, dividends
    except:
        return None, None, None

def calculate_kd(df, period=9):
    low_min = df['Low'].rolling(window=period).min()
    high_max = df['High'].rolling(window=period).max()
    df['RSV'] = 100 * (df['Close'] - low_min) / (high_max - low_min)
    df = df.dropna()
    k_list, d_list = [], []
    k, d = 50, 50
    for rsv in df['RSV']:
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
        k_list.append(k)
        d_list.append(d)
    df['K'] = k_list
    df['D'] = d_list
    
    # 順便算 MA60, MACD
    df['MA60'] = df['Close'].rolling(window=60).mean()
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    return df

# 🟢 檢查庫存狀態
def check_user_holding(ticker):
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            user_stock = df[df['代號'] == ticker]
            # 計算淨股數 (買 - 賣)
            buys = user_stock[user_stock['動作'].str.contains('買')]['股數'].sum()
            sells = user_stock[user_stock['動作'].str.contains('賣')]['股數'].sum()
            net_shares = buys - sells
            
            if net_shares > 0:
                # 算平均成本 (簡單版)
                total_cost = (user_stock[user_stock['動作'].str.contains('買')]['成本'] * user_stock[user_stock['動作'].str.contains('買')]['股數']).sum()
                avg_cost = total_cost / buys if buys > 0 else 0
                return True, net_shares, avg_cost
        except:
            pass
    return False, 0, 0

# ==========================================
# 3. AI 核心 (教練模式)
# ==========================================
def call_gemini_direct(prompt, api_key, model_name):
    if not api_key: return "無 API Key"
    if not model_name: return "無可用 AI 模型"
    headers = {'Content-Type': 'application/json'}
    params = {'key': api_key}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    try:
        response = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        return "AI 思考中斷 (請稍後再試)"
    except: return "連線失敗"

@st.cache_data(ttl=3600, show_spinner=False)
def ask_ai_coach(ticker, name, has_stock, cost, price, k, d, ma60, model_to_use):
    # 根據有無庫存，切換 Prompt
    status = f"持有 {cost:.1f} 元" if has_stock else "空手 (未持有)"
    
    prompt = f"""
    你是一位對新手非常友善的投資教練。
    學員正在詢問 {name} ({ticker})。
    
    【學員狀態】：{status}
    【目前股價】：{price}
    【技術指標】：KD值(K={k:.1f}, D={d:.1f})，季線(MA60)={ma60:.1f}
    
    請用白話文給出建議 (不要用艱深術語)：
    1. {"如果想賣，現在適合嗎？" if has_stock else "如果想買，現在適合嗎？"}
    2. 這張圖現在是強還是弱？(看季線)
    3. 下一步具體行動建議。
    """
    return call_gemini_direct(prompt, API_KEY, model_to_use)

# ==========================================
# 4. 主程式介面
# ==========================================
st.title("📱 AI 戰情室 V13.0 (新手教練版)")

# --- 側邊欄 ---
with st.sidebar:
    st.header("🚑 系統狀態")
    if AI_AVAILABLE:
        st.success(f"AI 連線正常 ({AUTO_MODEL})")
    else:
        st.error("AI 連線失敗 (只能看圖)")
    
    FINAL_MODEL = AUTO_MODEL
    if st.checkbox("手動指定模型"):
        FINAL_MODEL = st.text_input("模型名稱", "gemini-1.5-flash-8b")

tab1, tab2, tab3 = st.tabs(["🔍 教練帶我看盤", "📡 鑽石掃描", "📊 我的資產"])

# --- Tab 1: 教練帶我看盤 ---
with tab1:
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        q_stock = st.text_input("輸入股票代號 (如 2330)", "2330", label_visibility="collapsed")
    with col_btn:
        st.button("查詢", use_container_width=True)

    target_id = smart_stock_parser(q_stock)
    target_name = get_stock_name(target_id)
    
    info, hist, dividends = get_stock_detail(target_id)
    
    if info and not hist.empty:
        curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
        prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
        change = curr_price - prev_close
        pct_change = (change / prev_close) * 100
        
        # 計算指標
        hist = calculate_kd(hist)
        last_k = hist['K'].iloc[-1]
        last_d = hist['D'].iloc[-1]
        ma60_val = hist['MA60'].iloc[-1]
        
        # 🟢 檢查庫存 (關鍵功能)
        has_stock, shares, cost = check_user_holding(target_id)

        # Header
        st.markdown(f"## {target_name} ({target_id})")
        
        # 狀態卡片 (新手最需要這個)
        if has_stock:
            profit = (curr_price - cost) * shares
            color = "red" if profit > 0 else "green"
            st.info(f"👮‍♂️ **教練提醒**：你手上持有 **{shares} 股**，成本 **{cost:.1f}**，目前損益 **${profit:,.0f}**")
        else:
            st.info("👮‍♂️ **教練提醒**：你目前 **沒有** 這檔股票。")

        # 數據欄
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("股價", f"{curr_price:.1f}", f"{change:.1f}")
        c2.metric("KD指標", f"K{last_k:.0f} / D{last_d:.0f}", delta="黃金交叉" if last_k > last_d else "死亡交叉", delta_color="normal")
        c3.metric("季線(生命線)", f"{ma60_val:.1f}", delta="股價在線上(強)" if curr_price > ma60_val else "股價在線下(弱)")
        c4.metric("AI 建議", "點擊下方按鈕", delta_color="off")

        st.divider()

        # 🟢 AI 教練按鈕
        if st.button(f"🤖 請問教練：我現在該怎麼做？"):
            if AI_AVAILABLE:
                with st.spinner("教練正在看你的庫存和線圖..."):
                    advice = ask_ai_coach(target_id, target_name, has_stock, cost, curr_price, last_k, last_d, ma60_val, FINAL_MODEL)
                    st.success(advice)
            else:
                st.error("AI 休息中")

        # --- 圖表區 (加上翻譯吐司) ---
        st.subheader("📈 趨勢圖解")
        
        # 1. K線圖
        st.caption("👇 這張是 **K線圖**。橘色線是 **季線(60日均線)**。")
        st.caption("✅ 簡單看法：K棒在橘色線上面 = **好 (多頭)**；在下面 = **壞 (空頭)**。")
        
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name='K線'))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60'], mode='lines', name='季線', line=dict(color='orange', width=2)))
        fig.update_layout(height=400, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

        # 2. KD圖
        st.caption("👇 這張是 **KD指標**。用來抓轉折點。")
        kd_msg = ""
        if last_k > 80: kd_msg = "🔥 現在 K 值大於 80 (過熱)：小心股價太貴，隨時可能跌下來。"
        elif last_k < 20: kd_msg = "❄️ 現在 K 值小於 20 (超賣)：股價很便宜，可能快要反彈了。"
        elif last_k > last_d: kd_msg = "📈 紅線在藍線上面 (黃金交叉)：短期趨勢向上。"
        else: kd_msg = "📉 紅線在藍線下面 (死亡交叉)：短期趨勢向下。"
        st.info(kd_msg)

        fig_kd = go.Figure()
        fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['K'], mode='lines', name='K(快線)', line=dict(color='red', width=1.5)))
        fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['D'], mode='lines', name='D(慢線)', line=dict(color='blue', width=1.5)))
        fig_kd.add_hline(y=80, line_dash="dash", line_color="gray")
        fig_kd.add_hline(y=20, line_dash="dash", line_color="gray")
        fig_kd.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="KD值")
        st.plotly_chart(fig_kd, use_container_width=True)
        
    else: st.warning("查無資料")

# --- Tab 2: 鑽石掃描 (保持原樣) ---
with tab2:
    st.subheader("🧐 尋找便宜好股")
    if st.button("⚡ 開始掃描"):
        st.info("功能維護中 (V13.0 先專注於個股教學)")

# --- Tab 3: 我的資產 ---
with tab3:
    with st.sidebar:
        st.header("📝 交易登記")
        with st.form("trade_form"):
            t_input = st.text_input("代號", "2330")
            act = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
            t_id = smart_stock_parser(t_input)
            cur_p = get_stock_price(t_id)
            pr = st.number_input("價格", min_value=0.0, value=float(cur_p) if cur_p>0 else 0.0)
            sh = st.number_input("股數", min_value=1, value=1000, step=100)
            if st.form_submit_button("送出交易"):
                if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE)
                else: df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])
                new = pd.DataFrame({"日期":[datetime.now().strftime("%Y-%m-%d")],"代號":[t_id],"動作":[act],"成本":[pr],"股數":[sh]})
                pd.concat([new, df]).to_csv(DATA_FILE, index=False)
                st.success("已記錄")
                st.rerun()
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        holdings = df[df["動作"].str.contains("買")].copy()
        if not holdings.empty:
            holdings.insert(1, "名稱", holdings["代號"].apply(get_stock_name))
            holdings["現價"] = holdings["代號"].apply(get_stock_price)
            holdings["市值"] = holdings["現價"] * holdings["股數"]
            total = holdings["市值"].sum()
            profit = total - (holdings["成本"]*holdings["股數"]).sum()
            c1, c2 = st.columns(2)
            c1.metric("總資產", f"${total:,.0f}")
            c2.metric("總損益", f"${profit:,.0f}")
            st.dataframe(holdings[["日期", "名稱", "代號", "股數", "成本", "現價", "市值"]], use_container_width=True)
        else: st.info("尚無庫存")
    else: st.info("無交易紀錄")
