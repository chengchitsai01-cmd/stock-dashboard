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
# 1. 設定與金鑰檢查
# ==========================================
st.set_page_config(page_title="AI 全方位看盤室 V7.8 (完全修復版)", layout="wide")

# 嘗試讀取 Secrets
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        ai_available = True
    else:
        # 本地端測試用
        import toml
        secrets = toml.load(".streamlit/secrets.toml")
        genai.configure(api_key=secrets["GOOGLE_API_KEY"])
        ai_available = True
except:
    ai_available = False

DATA_FILE = "trade_history.csv"

# ==========================================
# 2. 資料對照表與工具函數
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
# 3. AI 核心：防塞車雙保險 (Ask Single)
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def ask_ai_single(ticker, stock_name, info_str):
    models_to_try = ['gemini-2.0-flash-exp', 'gemini-1.5-flash']
    
    for model_name in models_to_try:
        try:
            time.sleep(random.uniform(0.5, 1.5)) # 隨機等待
            model = genai.GenerativeModel(model_name)
            prompt = f"""
            分析台股 {stock_name} ({ticker})：
            數據：{info_str}
            請用繁體中文給 3 點短評 (100字內)：1.亮點 2.風險 3.操作建議。
            """
            response = model.generate_content(prompt)
            return response.text
        except:
            continue
            
    return "😅 系統繁忙 (Google API 限流)，請休息 2 分鐘後再試。"

# ==========================================
# 4. AI 核心：庫存總評 (Ask Daily)
# ==========================================
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
# 5. 主程式介面
# ==========================================
st.title("📱 AI 全方位看盤室 V7.8 (完全修復版)")

tab1, tab2, tab3 = st.tabs(["🔍 個股行情", "📡 鑽石掃描", "📊 我的資產"])

# --- Tab 1: 個股行情 ---
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
        
        c1, c2 = st.columns([2, 3])
        with c1:
            st.metric("股價", f"{curr_price:.1f}", f"{change:.1f} ({pct_change:.2f}%)")
        with c2:
            if is_diamond: st.success(f"💎 **鑽石好股** ({' '.join(badges)})")
            else: st.info(f"一般個股 ({' '.join(badges)})")
            st.caption(f"目前位置：{tech_status}")

        st.divider()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("EPS", f"{eps:.2f}")
        k2.metric("殖利率", f"{yield_val*100:.2f}%")
        k3.metric("ROE", f"{roe*100:.1f}%")
        k4.metric("本益比", f"{info.get('trailingPE', 'N/A')}")
        
        st.subheader(f"📈 {target_name} 走勢圖")
        hist['MA60_Line'] = hist['Close'].rolling(window=60).mean()
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name='K線'))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60_Line'], mode='lines', name='季線', line=dict(color='orange', width=2)))
        fig.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        if st.button(f"🤖 呼叫 AI 分析 {target_name}"):
            if ai_available:
                with st.spinner("AI 正在思考中..."):
                    info_text = f"價{curr_price}, EPS{eps}, ROE{roe}, 殖利率{yield_val}"
                    res = ask_ai_single(target_id, target_name, info_text)
                    st.info(res)
            else: st.error("無 AI Key")
    else: st.warning("查無資料")

# --- Tab 2: 鑽石掃描 ---
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
            
        with st.spinner("正在尋找便宜好股..."):
            for t in scan_list:
                info, hist = get_stock_detail(t)
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

# --- Tab 3: 我的資產 (模擬交易功能回歸！) ---
with tab3:
    # 這裡就是消失的側邊欄，我把它加回來了！
    with st.sidebar:
        st.header("📝 交易登記 (模擬)")
        with st.form("trade_form"):
            t_input = st.text_input("代號 (如 2330)", "2330")
            act = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
            
            # 自動抓現在股價當預設值
            t_id = smart_stock_parser(t_input)
            cur_p = get_stock_price(t_id)
            
            pr = st.number_input("價格", min_value=0.0, value=float(cur_p) if cur_p>0 else 0.0)
            sh = st.number_input("股數", min_value=1, value=1000, step=100)
            
            if st.form_submit_button("送出交易"):
                if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE)
                else: df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])
                
                new = pd.DataFrame({
                    "日期":[datetime.now().strftime("%Y-%m-%d")],
                    "代號":[t_id],
                    "動作":[act],
                    "成本":[pr],
                    "股數":[sh]
                })
                # 存檔
                pd.concat([new, df]).to_csv(DATA_FILE, index=False)
                st.success(f"已記錄：{act} {t_id}")
                st.rerun() # 重新整理頁面顯示最新資料

    # 顯示資產表格
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
            
            st.divider()
            
            # AI 庫存分析按鈕
            if st.button("🤖 庫存健檢 (AI 分析)"):
                if ai_available:
                     with st.spinner("AI 正在檢視你的投資組合..."):
                        res = ask_ai_daily(holdings[["名稱", "股數", "成本", "現價"]].to_string())
                        st.info(res)
                else: st.error("無 AI Key")
        else: st.info("尚無庫存，請從側邊欄新增第一筆交易！")
    else: st.info("目前無交易紀錄，請從側邊欄 (Sidebar) 新增交易。")
