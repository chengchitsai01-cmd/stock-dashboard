import streamlit as st
import pandas as pd
import os
import yfinance as yf
import requests
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime
import time
import random

# ==========================================
# 1. 設定與系統診斷
# ==========================================
st.set_page_config(page_title="AI 戰情室 V15.0 (懶人軍師版)", layout="wide")

# 🟢 獵人名單
CANDIDATE_MODELS = [
    'gemini-1.5-flash',
    'gemini-1.5-flash-latest',
    'gemini-1.5-flash-001',
    'gemini-1.5-flash-002',
    'gemini-1.5-flash-8b',
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

def test_connection(api_key, model_name):
    if not api_key: return False, "無 Key"
    headers = {'Content-Type': 'application/json'}
    params = {'key': api_key}
    data = {"contents": [{"parts": [{"text": "Hi"}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    try:
        response = requests.post(url, headers=headers, params=params, json=data, timeout=3)
        if response.status_code == 200: return True, "OK"
        elif response.status_code == 429: return False, "額度滿 (429)"
        elif response.status_code == 404: return False, "找不到 (404)"
        else: return False, f"錯誤 {response.status_code}"
    except Exception as e:
        return False, str(e)

@st.cache_resource(show_spinner=False)
def hunt_for_working_model(api_key):
    if not api_key: return None, "無 Key"
    logs = []
    for model in CANDIDATE_MODELS:
        success, msg = test_connection(api_key, model)
        if success: return model, f"✅ 自動鎖定: {model}"
        logs.append(f"{model}: {msg}")
    return None, "\n".join(logs)

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
def get_stock_detail(ticker, period="2y"):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period=period) 
        dividends = stock.dividends
        return info, hist, dividends
    except:
        return None, None, None

def get_stock_news(ticker):
    try:
        stock = yf.Ticker(ticker)
        raw_news = stock.news
        valid_news = []
        if raw_news:
            for n in raw_news:
                if n.get('title') and n.get('link'):
                    valid_news.append(n)
        return valid_news[:3]
    except:
        return []

def calculate_indicators(df):
    # KD
    low_min = df['Low'].rolling(window=9).min()
    high_max = df['High'].rolling(window=9).max()
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
    
    # MACD
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # BB
    df['BB_Mid'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Up'] = df['BB_Mid'] + (df['BB_Std'] * 2)
    df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    
    # MA
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60_Line'] = df['Close'].rolling(window=60).mean()
    
    return df

def calculate_score(price, ma60, k, d, vol, vol_avg):
    score = 50
    if price > ma60: score += 15
    else: score -= 15
    if k > d: score += 10
    if k > 80: score -= 5
    if k < 20: score += 10
    if vol > vol_avg: score += 5
    return max(0, min(100, score))

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

# 🟢 V14.0 回測引擎
def run_backtest(df, strategy_type="KD"):
    capital = 100000
    shares = 0
    trade_count = 0
    win_count = 0
    in_position = False
    buy_price = 0
    
    for i in range(1, len(df)):
        price = df['Close'].iloc[i]
        signal_buy = False
        signal_sell = False
        
        # KD 策略
        if strategy_type == "KD":
            k_curr = df['K'].iloc[i]
            d_curr = df['D'].iloc[i]
            k_prev = df['K'].iloc[i-1]
            d_prev = df['D'].iloc[i-1]
            # 黃金交叉且低檔
            if k_prev < d_prev and k_curr > d_curr and k_curr < 40: signal_buy = True
            # 死亡交叉且高檔
            elif k_prev > d_prev and k_curr < d_curr and k_curr > 60: signal_sell = True
            
        # 均線策略
        elif strategy_type == "MA":
            ma5_curr = df['MA5'].iloc[i]
            ma20_curr = df['MA20'].iloc[i]
            ma5_prev = df['MA5'].iloc[i-1]
            ma20_prev = df['MA20'].iloc[i-1]
            if ma5_prev < ma20_prev and ma5_curr > ma20_curr: signal_buy = True
            elif ma5_prev > ma20_prev and ma5_curr < ma20_curr: signal_sell = True

        if not in_position and signal_buy:
            shares = capital / price
            buy_price = price
            in_position = True
            capital = 0
        elif in_position and signal_sell:
            capital = shares * price
            if price > buy_price: win_count += 1
            shares = 0
            in_position = False
            trade_count += 1
            
    if in_position:
        final_value = shares * df['Close'].iloc[-1]
    else:
        final_value = capital
        
    return_rate = ((final_value - 100000) / 100000) * 100
    win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
    return return_rate, win_rate, trade_count

# 🟢 V15.0 懶人軍師：自動比較並給出建議
def get_smart_advice(df):
    # 1. 自動跑兩種回測
    ret_kd, win_kd, _ = run_backtest(df, "KD")
    ret_ma, win_ma, _ = run_backtest(df, "MA")
    
    # 2. 判斷誰贏
    best_strategy = ""
    comment = ""
    warning = ""
    
    if ret_kd > ret_ma and ret_kd > 0:
        best_strategy = "KD 震盪策略 (適合盤整)"
        comment = "這檔股票股性比較黏，適合用 KD 低買高賣。"
        
        # 檢查現在 KD 狀態
        k_now = df['K'].iloc[-1]
        d_now = df['D'].iloc[-1]
        if k_now < 40 and k_now > d_now:
            warning = "🔥 **現在就是 KD 黃金交叉買點！機會難得！**"
        elif k_now > 80:
            warning = "⛔ 現在 KD 過高，千萬別追，等回檔。"
        else:
            warning = "😴 目前沒訊號，空手者請觀望。"
            
    elif ret_ma > ret_kd and ret_ma > 0:
        best_strategy = "均線 趨勢策略 (適合波段)"
        comment = "這檔股票一旦發動就是大波段，適合用均線操作。"
        
        # 檢查現在 MA 狀態
        ma5 = df['MA5'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        price = df['Close'].iloc[-1]
        
        if ma5 > ma20 and price > ma5:
            warning = "🚀 **現在是多頭排列，可沿著 5 日線操作！**"
        elif ma5 < ma20:
            warning = "❄️ 現在是空頭排列，請空手觀望。"
        else:
            warning = "👀 均線糾結中，等待方向突破。"
            
    else:
        best_strategy = "都不適合 (建議換一檔)"
        comment = "KD 和均線回測績效都很差，這檔股票可能很難搞 (妖股或死魚)。"
        warning = "💀 **建議不要浪費時間在這檔股票上。**"

    return best_strategy, comment, warning, ret_kd, ret_ma

# ==========================================
# 3. AI 核心
# ==========================================
def mock_ai_analysis(ticker, name, price, ma60, k, d):
    trend = "多頭" if price > ma60 else "空頭"
    action = "觀望"
    if trend == "多頭":
        if k < 20: action = "買進"
        elif k > 80: action = "減碼"
        else: action = "續抱"
    else:
        if k < 20: action = "搶反彈"
        else: action = "空手"
    return f"(⚠️ 代班 AI)\n1. 趨勢：{trend}\n2. 建議：{action}\n3. 指標：K={k:.1f}"

def mock_todo_list(portfolio_str):
    return "(⚠️ 代班 AI) 建議以季線為防守點，跌破季線減碼。"

def call_gemini_direct(prompt, api_key, model_name):
    if not api_key: return None
    if not model_name: return None
    headers = {'Content-Type': 'application/json'}
    params = {'key': api_key}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    try:
        response = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        return None
    except: return None

@st.cache_data(ttl=86400, show_spinner=False)
def ask_ai_single(ticker, stock_name, info_str, tech_str, model_to_use, price, ma60, k, d):
    if model_to_use:
        prompt = f"分析 {stock_name} ({ticker})。{tech_str}。建議：1.趨勢 2.操作 3.理由 (100字內)"
        res = call_gemini_direct(prompt, API_KEY, model_to_use)
        if res: return res
    return mock_ai_analysis(ticker, stock_name, price, ma60, k, d)

@st.cache_data(ttl=3600, show_spinner=False)
def ask_ai_news(news_list, model_to_use):
    if not news_list: return ""
    titles = [n['title'] for n in news_list]
    titles_str = "\n".join(titles)
    if model_to_use:
        prompt = f"新聞標題：{titles_str}。回答：1.氣氛 2.重點。"
        res = call_gemini_direct(prompt, API_KEY, model_to_use)
        if res: return f"🤖 {res}"
    return "⚠️ (離線) 無法解讀新聞"

@st.cache_data(ttl=3600, show_spinner=False)
def ask_ai_todo_list(portfolio_status_str, model_to_use):
    if model_to_use:
        prompt = f"庫存：{portfolio_status_str}。請給操作建議清單。"
        res = call_gemini_direct(prompt, API_KEY, model_to_use)
        if res: return res
    return mock_todo_list(portfolio_status_str)

# ==========================================
# 4. 主程式介面
# ==========================================
st.title("📱 AI 戰情室 V15.0 (懶人軍師版)")

with st.sidebar:
    st.header("🚑 系統診斷室")
    FINAL_MODEL = AUTO_MODEL
    use_manual = st.checkbox("手動指定模型")
    if use_manual:
        manual_model = st.text_input("輸入模型名稱", "gemini-1.5-flash-8b")
        if manual_model: FINAL_MODEL = manual_model
    
    if FINAL_MODEL:
        st.success(f"🎯 目標：{FINAL_MODEL}")
        AI_READY = True
    else:
        st.warning("⚠️ 啟用代班 AI 模式")
        AI_READY = False
        with st.expander("查看日誌"): st.text(HUNT_LOG)
    st.divider()
    
    st.header("🦁 資金控管")
    with st.expander("開啟計算器", expanded=False):
        capital = st.number_input("總資金", value=1000000)
        risk_per_trade = st.slider("單筆風險 (%)", 1.0, 5.0, 2.0)
        entry_price = st.number_input("進場價", value=100.0)
        stop_loss = st.number_input("停損價", value=90.0)
        if entry_price > stop_loss:
            risk_amount = capital * (risk_per_trade / 100)
            loss_per_share = entry_price - stop_loss
            shares_to_buy = int(risk_amount / loss_per_share)
            st.markdown(f"### 建議買入：**{shares_to_buy}** 股")
            st.caption(f"最多虧損：${risk_amount:,.0f}")
        else:
            st.error("停損價需低於進場價")

tab1, tab2, tab3 = st.tabs(["🔍 個股行情", "📡 鑽石掃描", "📊 我的資產"])

# --- Tab 1 ---
with tab1:
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        q_stock = st.text_input("輸入代號或名稱", "2330", label_visibility="collapsed")
    with col_btn:
        st.button("查詢", use_container_width=True)

    target_id = smart_stock_parser(q_stock)
    target_name = get_stock_name(target_id)
    
    # 預設抓 2 年以確保回測數據足夠
    info, hist, dividends = get_stock_detail(target_id, period="2y") 
    
    if info and not hist.empty:
        curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
        prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
        change = curr_price - prev_close
        
        hist['MA60_Line'] = hist['Close'].rolling(window=60).mean()
        ma60_val = hist['MA60_Line'].iloc[-1]
        vol_avg = hist['Volume'].rolling(window=5).mean().iloc[-1]
        
        hist = calculate_indicators(hist)
        k_val = hist['K'].iloc[-1]
        d_val = hist['D'].iloc[-1]
        
        power_score = calculate_score(curr_price, ma60_val, k_val, d_val, hist['Volume'].iloc[-1], vol_avg)
        badges, is_diamond, tech_status, eps, yield_val, roe = evaluate_stock(info, curr_price, ma60_val)

        # 🟢 V15.0 核心：生成懶人總結
        best_strat, strategy_comment, action_warning, ret_kd, ret_ma = get_smart_advice(hist)

        st.markdown(f"## {target_name} ({target_id})")
        
        def safe_get(dic, key, fmt="{:.2f}"):
            val = dic.get(key)
            if val is None: return "N/A"
            try: return fmt.format(val)
            except: return str(val)

        market_cap = info.get('marketCap')
        if market_cap:
            if market_cap > 100000000000: m_cap_str = f"{market_cap/100000000:.1f}億"
            else: m_cap_str = f"{market_cap/1000000:.0f}百萬"
        else: m_cap_str = "N/A"

        # 數據九宮格
        with st.container():
            c1, c2 = st.columns(2)
            c1.metric("現價", f"{curr_price:.1f}", f"{change:.1f}")
            c2.metric("52週波段", f"{safe_get(info, 'fiftyTwoWeekLow')} - {safe_get(info, 'fiftyTwoWeekHigh')}")
            st.divider()
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("P/E", safe_get(info, 'trailingPE'))
            d2.metric("P/B", safe_get(info, 'priceToBook'))
            d3.metric("EPS", safe_get(info, 'trailingEps'))
            d4.metric("市值", m_cap_str)

        st.divider()

        # 🔥🔥🔥 V15.0 新增：AI 懶人總結區 🔥🔥🔥
        st.markdown("### 🏆 AI 最終總結：這檔股票怎麼玩？")
        
        # 用不同顏色框框顯示重點
        if "KD" in best_strat:
            st.info(f"👉 **最佳策略：{best_strat}** (報酬率 {ret_kd:.1f}%)")
        elif "均線" in best_strat:
            st.success(f"👉 **最佳策略：{best_strat}** (報酬率 {ret_ma:.1f}%)")
        else:
            st.error(f"👉 **最佳策略：{best_strat}**")
            
        st.write(f"📝 **股性分析**：{strategy_comment}")
        st.markdown(f"### ⚡ **目前操作建議**：\n{action_warning}")
        
        with st.expander("查看詳細回測數據 (給想看細節的人)"):
            c1, c2 = st.columns(2)
            c1.metric("KD 策略報酬", f"{ret_kd:.1f}%")
            c2.metric("均線 策略報酬", f"{ret_ma:.1f}%")
            st.caption("註：回測數據基於過去 2 年股價模擬")

        st.divider()
        
        # AI 按鈕
        if st.button(f"🤖 呼叫 AI 深度分析 {target_name}"):
            if AI_READY:
                tech_text = f"現價{curr_price}, 季線{ma60_val:.1f}。K值{k_val:.1f}, D值{d_val:.1f}。"
                info_text = f"EPS{eps}, ROE{roe}, 殖利率{yield_val}。"
                with st.spinner(f"AI ({FINAL_MODEL}) 分析中..."):
                    ai_comment = ask_ai_single(target_id, target_name, info_text, tech_text, FINAL_MODEL, curr_price, ma60_val, k_val, d_val)
                    st.info(f"💡 **AI 觀點**：\n\n{ai_comment}")
            else: st.error("AI 未連線")

        st.subheader("📈 技術分析")
        chart_type = st.radio("指標切換：", ["KD 指標", "MACD 指標", "布林通道"], horizontal=True)
        
        high_1y = hist['Close'].max()
        low_1y = hist['Close'].min()
        diff = high_1y - low_1y
        fibo_0382 = high_1y - (diff * 0.382)
        fibo_0618 = high_1y - (diff * 0.618)

        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2])
        fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name='K線'), row=1, col=1)
        fig.add_hline(y=fibo_0382, line_dash="dot", line_color="purple", annotation_text="Fibo 0.382", row=1, col=1)
        fig.add_hline(y=fibo_0618, line_dash="dot", line_color="purple", annotation_text="Fibo 0.618", row=1, col=1)

        if chart_type == "布林通道":
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Up'], mode='lines', name='上軌', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Low'], mode='lines', name='下軌', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['BB_Mid'], mode='lines', name='中軌', line=dict(color='blue', width=1)), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60_Line'], mode='lines', name='季線', line=dict(color='orange', width=2)), row=1, col=1)

        if chart_type == "KD 指標":
            fig.add_trace(go.Scatter(x=hist.index, y=hist['K'], mode='lines', name='K', line=dict(color='red', width=1.5)), row=2, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['D'], mode='lines', name='D', line=dict(color='blue', width=1.5)), row=2, col=1)
            fig.add_hline(y=80, line_dash="dash", line_color="gray", row=2, col=1)
            fig.add_hline(y=20, line_dash="dash", line_color="gray", row=2, col=1)
        elif chart_type == "MACD 指標":
            colors_macd = ['red' if v >= 0 else 'green' for v in hist['Hist']]
            fig.add_trace(go.Bar(x=hist.index, y=hist['Hist'], name='MACD柱', marker_color=colors_macd), row=2, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MACD'], mode='lines', name='快線', line=dict(color='orange', width=1)), row=2, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['Signal'], mode='lines', name='慢線', line=dict(color='blue', width=1)), row=2, col=1)

        colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in hist.iterrows()]
        fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='量', marker_color=colors), row=3, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=800, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("📰 最新消息")
        news = get_stock_news(target_id)
        if news:
            if AI_READY:
                sentiment = ask_ai_news(news, FINAL_MODEL)
                if sentiment: st.success(f"{sentiment}")
            for n in news:
                st.markdown(f"- [{n.get('title')}]({n.get('link')})")
        else: st.caption("無新聞")
    else: st.warning("查無資料")

# --- Tab 2 & 3: 保持原樣 (省略以節省篇幅) ---
# ... (請貼上之前 V12 或 V13 的 Tab 2 和 Tab 3 程式碼) ...
# 注意：為了程式完整性，請務必補上 Tab 2 和 3 的程式碼！
with tab2:
    st.subheader("🧐 全市場鑽石獵人")
    if st.button("⚡ 開始掃描", type="primary"):
        report = []
        scan_list = list(set(WATCHLIST))
        if os.path.exists(DATA_FILE):
            try:
                df_inv = pd.read_csv(DATA_FILE)
                scan_list += df_inv["代號"].unique().tolist()
            except: pass
        with st.spinner("尋找便宜好股..."):
            for t in scan_list:
                info, hist, _ = get_stock_detail(t)
                if info and not hist.empty:
                    p = hist.iloc[-1]['Close']
                    m = hist['Close'].rolling(window=60).mean().iloc[-1]
                    badges, is_dia, status, _, _, _ = evaluate_stock(info, p, m)
                    name = get_stock_name(t)
                    if is_dia or (m > p): 
                        report.append({"代號": t, "名稱": name, "現價": p, "狀態": status, "標籤": " ".join(badges), "是鑽石嗎": is_dia})
        if report:
            df_res = pd.DataFrame(report).sort_values("是鑽石嗎", ascending=False)
            for _, row in df_res.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([1.5, 2, 2])
                    title = f"💎 {row['名稱']} ({row['代號']})" if row['是鑽石嗎'] else f"{row['名稱']} ({row['代號']})"
                    c1.markdown(f"### {title}")
                    c2.info(row['標籤'])
                    c3.write(row['狀態'])
                    st.divider()
        else: st.info("無符合結果")

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
            st.subheader("💰 資產總覽")
            holdings.insert(1, "名稱", holdings["代號"].apply(get_stock_name))
            holdings["現價"] = holdings["代號"].apply(get_stock_price)
            holdings["市值"] = holdings["現價"] * holdings["股數"]
            
            # V12.0 功能：熱力圖
            holdings["報酬率"] = ((holdings["現價"] - holdings["成本"]) / holdings["成本"]) * 100
            
            total = holdings["市值"].sum()
            profit = total - (holdings["成本"]*holdings["股數"]).sum()
            c1, c2 = st.columns(2)
            c1.metric("總資產", f"${total:,.0f}")
            c2.metric("總損益", f"${profit:,.0f}")
            
            st.subheader("🗺️ 庫存熱力圖")
            fig_map = px.treemap(holdings, path=['名稱'], values='市值', color='報酬率',
                                 color_continuous_scale='RdBu_r', color_continuous_midpoint=0)
            st.plotly_chart(fig_map, use_container_width=True)

            st.dataframe(holdings[["日期", "名稱", "代號", "股數", "成本", "現價", "市值", "報酬率"]], use_container_width=True)
            st.divider()
            
            st.subheader("📅 今日 AI 操盤待辦")
            if st.button("🚀 生成今日操作清單", type="primary"):
                with st.spinner(f"分析中..."):
                    portfolio_status = ""
                    for idx, row in holdings.iterrows():
                        t_id = row['代號']
                        t_name = row['名稱']
                        cost = row['成本']
                        _, hist, _ = get_stock_detail(t_id)
                        if not hist.empty:
                            current_p = hist.iloc[-1]['Close']
                            ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
                            hist = calculate_indicators(hist)
                            k_now = hist['K'].iloc[-1]
                            status = f"- {t_name}: 成本{cost}, 現價{current_p:.1f}, 季線{ma60:.1f}, KD值{k_now:.1f}\n"
                            portfolio_status += status
                    
                    todo_list = ask_ai_todo_list(portfolio_status, FINAL_MODEL)
                    st.success(todo_list)
        else: st.info("尚無庫存")
    else: st.info("無交易紀錄")
