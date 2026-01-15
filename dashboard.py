import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 設定
# ==========================================
st.set_page_config(page_title="AI 全方位看盤室 V7.3", layout="wide")

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

# 常用對照表
STOCK_MAP = {
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", "中華電": "2412.TW",
    "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW", "玉山金": "2884.TW",
    "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW",
    "廣達": "2382.TW", "緯創": "3231.TW", "技嘉": "2376.TW",
    "0050": "0050.TW", "0056": "0056.TW", "00878": "00878.TW", "00929": "00929.TW"
}

WATCHLIST = ["2330.TW", "2317.TW", "2454.TW", "2603.TW", "2891.TW"]

def smart_stock_parser(user_input):
    user_input = user_input.strip()
    if user_input in STOCK_MAP: return STOCK_MAP[user_input]
    if user_input.isdigit(): return f"{user_input}.TW"
    user_input = user_input.upper()
    if not user_input.endswith(".TW") and user_input[0].isdigit(): return f"{user_input}.TW"
    return user_input

@st.cache_data(ttl=60)
def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.fast_info.last_price
    except:
        return 0.0

@st.cache_data(ttl=300)
def get_stock_detail(ticker):
    """取得詳細個股資料 (含K線與財報)"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="1y") 
        return info, hist
    except:
        return None, None

# --- 核心：鑽石評分邏輯 ---
def evaluate_stock(info, price, ma60):
    """回傳：分數, 標籤列表, 符合鑽石條件嗎"""
    badges = []
    score = 0
    
    # 1. 基本面檢查
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
    
    is_diamond = (score >= 2) # 符合兩項就算不錯
    
    # 2. 技術面狀態
    gap = (ma60 - price) / ma60 * 100
    status_text = ""
    if gap > 0:
        status_text = f"🟢 便宜 (低於季線 {gap:.1f}%)"
    else:
        status_text = f"🔴 昂貴 (高於季線 {abs(gap):.1f}%)"

    return badges, is_diamond, status_text, eps, yield_val, roe

def ask_ai_single(ticker, info_str):
    model = genai.GenerativeModel('gemini-flash-latest')
    prompt = f"分析個股 {ticker}：{info_str}。請簡短說明：1.這家公司在做什麼？ 2.目前估值與風險。 3.適合存股嗎？"
    response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 主程式介面
# ==========================================
st.title("📱 AI 全方位看盤室 V7.3")

# 分頁：把「個股行情」放到第一個，因為這是你最常看的
tab1, tab2, tab3 = st.tabs(["🔍 個股行情", "📡 鑽石掃描", "📊 我的資產"])

# ==========================================
# Tab 1: 個股行情 (Broker App 風格)
# ==========================================
with tab1:
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        q_stock = st.text_input("輸入代號或名稱 (例如: 鴻海)", "2330", label_visibility="collapsed", placeholder="輸入代號...")
    with col_btn:
        search_pressed = st.button("查詢", use_container_width=True)

    target_id = smart_stock_parser(q_stock)
    
    # 取得資料
    info, hist = get_stock_detail(target_id)
    
    if info and not hist.empty:
        # --- A. 頂部報價區 ---
        curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
        prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
        change = curr_price - prev_close
        pct_change = (change / prev_close) * 100
        
        # 計算 MA60 與 鑽石評分
        ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
        badges, is_diamond, tech_status, eps, yield_val, roe = evaluate_stock(info, curr_price, ma60)

        # 顯示大標題
        st.markdown(f"## {info.get('longName', target_id)} ({target_id})")
        
        # 價格與鑽石標章
        c1, c2 = st.columns([2, 3])
        with c1:
            st.metric("股價", f"{curr_price:.1f}", f"{change:.1f} ({pct_change:.2f}%)")
        with c2:
            if is_diamond:
                st.success(f"💎 **鑽石好股認證** ({' '.join(badges)})")
            else:
                st.info(f"一般個股 ({' '.join(badges)})")
            st.caption(f"目前位置：{tech_status}")

        st.divider()

        # --- B. 基本面儀表板 (你的存股三率) ---
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("EPS (近12月)", f"{eps:.2f}", delta="> 1" if eps>1 else None, delta_color="normal")
        k2.metric("殖利率", f"{yield_val*100:.2f}%", delta="> 5%" if yield_val>0.05 else None, delta_color="normal")
        k3.metric("ROE", f"{roe*100:.1f}%", delta="> 15%" if roe>0.15 else None, delta_color="normal")
        k4.metric("本益比", f"{info.get('trailingPE', 'N/A')}")
        
        # --- C. K線圖 (含季線) ---
        st.subheader("📈 技術走勢 (含 MA60 季線)")
        hist['MA60_Line'] = hist['Close'].rolling(window=60).mean()
        
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name='K線'))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60_Line'], mode='lines', name='季線 (MA60)', line=dict(color='orange', width=2)))
        fig.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        # --- D. AI 分析 ---
        if st.button("🤖 呼叫 AI 分析師"):
            if ai_available:
                info_text = f"價{curr_price}, EPS{eps}, ROE{roe}, 殖利率{yield_val}, 產業{info.get('sector','未知')}"
                res = ask_ai_single(target_id, info_text)
                st.info(res)
            else: st.error("無 AI Key")

    else:
        st.warning("查無資料，請確認代號。")

# ==========================================
# Tab 2: 鑽石掃描 (原本的 V7.2 功能)
# ==========================================
with tab2:
    st.subheader("🧐 全市場鑽石獵人")
    if st.button("⚡ 開始掃描", type="primary"):
        # 簡單掃描邏輯
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
                    
                    # 只顯示鑽石股或便宜股
                    if is_dia or (m > p): 
                        report.append({"代號": t, "現價": p, "狀態": status, "標籤": " ".join(badges), "是鑽石嗎": is_dia})
        
        if report:
            df_res = pd.DataFrame(report).sort_values("是鑽石嗎", ascending=False)
            for _, row in df_res.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([1, 2, 2])
                    title = f"💎 {row['代號']}" if row['是鑽石嗎'] else f"{row['代號']}"
                    c1.markdown(f"### {title}")
                    c2.info(row['標籤'])
                    c3.write(row['狀態'])
                    st.divider()
        else: st.info("目前觀察名單中沒有符合條件的股票")

# ==========================================
# Tab 3: 我的資產 (簡易記帳)
# ==========================================
with tab3:
    with st.sidebar:
        st.header("📝 交易")
        with st.form("trade"):
            t_input = st.text_input("代號", "2330")
            act = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
            pr = st.number_input("價格", min_value=0.0)
            sh = st.number_input("股數", min_value=1, value=1000)
            if st.form_submit_button("送出"):
                t_id = smart_stock_parser(t_input)
                if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE)
                else: df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])
                new = pd.DataFrame({"日期":[datetime.now().strftime("%Y-%m-%d")],"代號":[t_id],"動作":[act],"成本":[pr],"股數":[sh]})
                pd.concat([new, df]).to_csv(DATA_FILE, index=False)
                st.success("OK")
                st.rerun()

    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        holdings = df[df["動作"].str.contains("買")].copy()
        if not holdings.empty:
            holdings["現價"] = holdings["代號"].apply(get_stock_price)
            holdings["市值"] = holdings["現價"] * holdings["股數"]
            total = holdings["市值"].sum()
            profit = total - (holdings["成本"]*holdings["股數"]).sum()
            
            c1, c2 = st.columns(2)
            c1.metric("總資產", f"${total:,.0f}")
            c2.metric("總損益", f"${profit:,.0f}")
            st.dataframe(holdings, use_container_width=True)
