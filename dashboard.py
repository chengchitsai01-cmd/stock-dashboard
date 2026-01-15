import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 設定與工具函數
# ==========================================
st.set_page_config(page_title="AI 投資戰情室 V4.0", layout="wide")

# 嘗試讀取 Secrets
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

# 智慧對照表
STOCK_MAP = {
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", "廣達": "2382.TW",
    "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW", "玉山金": "2884.TW",
    "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW", "長榮航": "2618.TW",
    "華航": "2610.TW", "緯創": "3231.TW", "緯穎": "6669.TW", "技嘉": "2376.TW",
    "英業達": "2356.TW", "台達電": "2308.TW", "聯電": "2303.TW", "中華電": "2412.TW",
    "0050": "0050.TW", "台灣50": "0050.TW", "0056": "0056.TW", "00878": "00878.TW",
    "00929": "00929.TW", "00940": "00940.TW", "華邦電": "2344.TW"
}

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

@st.cache_data(ttl=300) # 快取 5 分鐘
def get_stock_details(ticker):
    """取得詳細個股資訊 (本益比、市值等)"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="3mo")
        return info, hist
    except:
        return None, None

def ask_ai_portfolio(summary_text):
    """針對庫存分析"""
    model = genai.GenerativeModel('gemini-flash-latest')
    prompt = f"你是投資顧問。用戶庫存：{summary_text}。請用繁體中文給出 3 點短評：風險、獲利、建議。"
    response = model.generate_content(prompt)
    return response.text

def ask_ai_single_stock(ticker, info_text):
    """針對單一股票分析"""
    model = genai.GenerativeModel('gemini-flash-latest')
    prompt = f"""
    你是專業分析師。請分析這檔股票 {ticker}：
    基本面數據：{info_text}
    
    請用繁體中文回答：
    1. 這家公司在做什麼？(簡短一句)
    2. 目前估值合理嗎？(參考本益比、殖利率)
    3. 技術面或籌碼面有什麼要注意的風險？
    """
    response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 主程式介面
# ==========================================
st.title("🚀 AI 投資戰情室 V4.0")

# 建立分頁
tab1, tab2 = st.tabs(["📊 我的資產 (Portfolio)", "🔍 個股詳情 (Quote)"])

# ==========================================
# 分頁 1: 我的資產 (原本的功能)
# ==========================================
with tab1:
    # --- 側邊欄邏輯 (只在 Tab 1 顯示比較好，或者共用) ---
    with st.sidebar:
        st.header("📝 庫存下單")
        with st.form("trade_form"):
            raw_input = st.text_input("股票 (如 2330)", "2330")
            stock_id = smart_stock_parser(raw_input)
            st.caption(f"偵測: {stock_id}")
            action = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
            cur_price = get_stock_price(stock_id)
            default_price = float(cur_price) if cur_price > 0 else 0.0
            price_input = st.number_input("價格", value=default_price, min_value=0.0)
            shares = st.number_input("股數", min_value=1, value=1000, step=100)
            
            if st.form_submit_button("送出交易"):
                if price_input <= 0: st.error("價格錯誤")
                else:
                    if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE)
                    else: df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])
                    
                    new_row = pd.DataFrame({
                        "日期": [datetime.now().strftime("%Y-%m-%d")],
                        "代號": [stock_id], "動作": [action],
                        "成本": [price_input], "股數": [shares]
                    })
                    df = pd.concat([new_row, df], ignore_index=True)
                    df.to_csv(DATA_FILE, index=False)
                    st.success("交易成功！")
                    st.rerun()

    # --- 讀取庫存 ---
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="editor_p")
        
        if not edited_df.equals(df):
            edited_df.to_csv(DATA_FILE, index=False)
            st.rerun()

        # 計算損益
        holdings = edited_df[edited_df["動作"].str.contains("買")].copy()
        if not holdings.empty:
            holdings["目前市價"] = holdings["代號"].apply(get_stock_price)
            holdings["市值"] = holdings["目前市價"] * holdings["股數"]
            holdings["原始成本"] = holdings["成本"] * holdings["股數"]
            holdings["帳面損益"] = holdings["市值"] - holdings["原始成本"]
            
            # KPI
            t_profit = holdings["帳面損益"].sum()
            t_cost = holdings["原始成本"].sum()
            t_roi = (t_profit/t_cost*100) if t_cost>0 else 0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("總資產", f"${holdings['市值'].sum():,.0f}")
            c2.metric("總損益", f"${t_profit:,.0f}", delta=f"{t_profit:,.0f}")
            c3.metric("報酬率", f"{t_roi:.2f}%", delta=f"{t_roi:.2f}%")
            
            # AI 按鈕
            st.divider()
            if st.button("🤖 分析我的投資組合"):
                if ai_available:
                    res = ask_ai_portfolio(holdings[["代號", "股數", "帳面損益"]].to_string())
                    st.info(res)
                else: st.error("無 AI 金鑰")
        else:
            st.info("尚無庫存")
    else:
        st.info("請從側邊欄新增第一筆交易")

# ==========================================
# 分頁 2: 個股詳情 (新功能！✨)
# ==========================================
with tab2:
    st.subheader("🔍 個股全方位診斷")
    
    # 搜尋框
    col_search, col_btn = st.columns([3, 1])
    with col_search:
        q_stock = st.text_input("輸入代號或名稱 (例如: 鴻海)", "2330")
    with col_btn:
        st.write("") # 排版用
        st.write("")
        search_btn = st.button("查詢", use_container_width=True)

    target_id = smart_stock_parser(q_stock)
    
    if target_id:
        info, hist = get_stock_details(target_id)
        
        if info and not hist.empty:
            # --- 1. 股價看板 (Header) ---
            curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
            prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
            change = curr_price - prev_close
            pct_change = (change / prev_close) * 100
            
            st.metric(
                label=f"{info.get('longName', target_id)} ({target_id})",
                value=f"{curr_price:.1f}",
                delta=f"{change:.1f} ({pct_change:.2f}%)"
            )
            
            # --- 2. 基本面數據網格 (Fundamental Grid) ---
            st.markdown("### 📊 關鍵數據")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("開盤", f"{info.get('open', 0):.1f}")
            c2.metric("最高", f"{info.get('dayHigh', 0):.1f}")
            c3.metric("最低", f"{info.get('dayLow', 0):.1f}")
            c4.metric("成交量", f"{info.get('volume', 0)/1000:.0f} 張")
            
            st.divider()
            
            k1, k2, k3, k4 = st.columns(4)
            # 處理有些股票沒有本益比的情況 (如虧損或 ETF)
            pe_ratio = info.get('trailingPE', 'N/A') 
            pe_str = f"{pe_ratio:.1f}" if isinstance(pe_ratio, (int, float)) else "N/A"
            
            yield_val = info.get('dividendYield', 0)
            yield_str = f"{yield_val*100:.2f}%" if yield_val else "N/A"
            
            mkt_cap = info.get('marketCap', 0)
            mkt_cap_str = f"{mkt_cap/100000000:.1f} 億" # 換算成億
            
            k1.metric("本益比 (P/E)", pe_str)
            k2.metric("殖利率 (Yield)", yield_str)
            k3.metric("總市值", mkt_cap_str)
            k4.metric("52週高點", f"{info.get('fiftyTwoWeekHigh', 0):.1f}")

            # --- 3. K線圖 ---
            st.markdown("### 📈 走勢圖")
            fig = go.Figure(data=[go.Candlestick(
                x=hist.index,
                open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'],
                name=target_id
            )])
            fig.update_layout(xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            # --- 4. 個股 AI 分析 ---
            st.markdown("### 🤖 AI 個股健檢")
            if st.button(f"呼叫 AI 分析 {target_id}", key="btn_ai_single"):
                if ai_available:
                    # 整理要給 AI 看的數據
                    info_text = f"股價:{curr_price}, 本益比:{pe_str}, 殖利率:{yield_str}, 市值:{mkt_cap_str}, 產業:{info.get('sector','未知')}"
                    with st.spinner("AI 正在閱讀財報..."):
                        analysis = ask_ai_single_stock(target_id, info_text)
                    st.info(analysis)
                else:
                    st.error("API Key 未設定")
                    
        else:
            st.warning("查無資料，請確認代號正確 (或是 ETF 可能缺少部分基本面資料)")
