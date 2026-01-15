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
st.set_page_config(page_title="AI 每日獵人戰情室 V7.1", layout="wide")

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

# 存股 & 觀察清單
STOCK_MAP = {
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", "中華電": "2412.TW",
    "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW", "玉山金": "2884.TW",
    "0050": "0050.TW", "台灣50": "0050.TW", 
    "0056": "0056.TW", "高股息": "0056.TW",
    "00878": "00878.TW", "國泰永續": "00878.TW",
    "00929": "00929.TW", "006208": "006208.TW"
}

# 預設觀察清單 (你可以隨時回來改這裡)
WATCHLIST = ["2330.TW", "00878.TW", "2881.TW", "2412.TW", "2317.TW"]

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
def get_stock_details(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="1y") 
        return info, hist
    except:
        return None, None

# --- 核心：獵人策略 (Hunter Strategy) ---
def run_hunter_check(ticker_list):
    report = []
    
    for ticker in ticker_list:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="1y") 
            if len(df) < 60: continue 

            # 設定目標價：季線 (MA60) 為「合理便宜價」
            df['MA60'] = df['Close'].rolling(window=60).mean()
            
            last = df.iloc[-1]
            price = last['Close']
            target_price = last['MA60']
            
            # 計算距離
            # 負數代表還沒跌到 (還差幾%)
            # 正數代表已經跌破 (便宜了幾%)
            gap_percent = (target_price - price) / target_price * 100
            
            # 訊號邏輯
            signal = "⏳ 等待中"
            color = "gray"
            status_text = f"還差 {abs(gap_percent):.1f}%"
            
            if gap_percent > 0: # 價格 < 目標價 (跌破季線)
                signal = "🎯 射擊 (買進)"
                color = "red" # 紅色代表機會
                status_text = f"已便宜 {gap_percent:.1f}%！"
                
                # 如果便宜超過 10% (跌很深)
                if gap_percent > 10:
                    signal = "🔥 黃金機會 (大買)"
                    status_text = f"嚴重超跌 {gap_percent:.1f}%"
            
            elif gap_percent < -10: # 價格 > 目標價 10% (漲太多)
                signal = "✋ 太貴了"
                color = "green" # 台股綠色是跌，但在這裡用綠色表示「冷靜/安全/持有」
                status_text = f"比合理價貴 {abs(gap_percent):.1f}%"

            report.append({
                "代號": ticker,
                "現價": price,
                "目標價(MA60)": target_price,
                "訊號": signal,
                "狀態": status_text,
                "距離%": gap_percent, # 用來排序
                "color": color
            })

        except Exception as e:
            continue
            
    # 排序：把最便宜 (gap_percent 最大) 的排最上面，讓你一眼看到機會
    return pd.DataFrame(report).sort_values("距離%", ascending=False)

def ask_ai_daily(holdings_text):
    model = genai.GenerativeModel('gemini-flash-latest')
    prompt = f"""
    你是用戶的每日投資助理。這是用戶目前的庫存：
    {holdings_text}
    請用非常簡短、口語化的繁體中文 (像是朋友傳 LINE) 告訴用戶：
    1. 今天有沒有哪支股票跌很多，適合加碼？
    2. 整體資產還好嗎？需要擔心嗎？
    (字數 100 字以內，不要廢話)
    """
    response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 主程式介面
# ==========================================
st.title("🏹 AI 每日獵人戰情室 V7.1")

# 分頁
tab1, tab2 = st.tabs(["📡 每日獵場 (Radar)", "📊 我的戰利品 (Portfolio)"])

# --- Tab 1: 每日獵場 (這頁放最前面，因為你每天只想看這個) ---
with tab1:
    st.subheader("🧐 今天有便宜貨嗎？")
    st.caption("獵人策略：股價跌破季線 (MA60) 才是出手機會。排序越上面越便宜。")
    
    if st.button("⚡ 掃描獵物", type="primary"):
        # 掃描庫存 + 觀察名單
        scan_list = set(WATCHLIST)
        if os.path.exists(DATA_FILE):
            try:
                current_df = pd.read_csv(DATA_FILE)
                scan_list.update(current_df["代號"].unique().tolist())
            except: pass
            
        with st.spinner("正在測量距離..."):
            result_df = run_hunter_check(list(scan_list))
            
        if not result_df.empty:
            for index, row in result_df.iterrows():
                # 使用簡單的卡片式佈局
                with st.container():
                    c1, c2, c3, c4 = st.columns([1.5, 1.5, 2, 2])
                    
                    # 1. 代號
                    c1.markdown(f"### {row['代號']}")
                    
                    # 2. 現價 vs 目標
                    c2.metric("現價", f"{row['現價']:.1f}", 
                              f"目標: {row['目標價(MA60)']:.1f}", 
                              delta_color="off") # 這裡不顯示顏色，只看數字
                    
                    # 3. 訊號 (大字體)
                    color_style = f"color: {row['color']}; font-weight: bold; font-size: 20px;"
                    c3.markdown(f"<span style='{color_style}'>{row['訊號']}</span>", unsafe_allow_html=True)
                    
                    # 4. 狀態描述 (進度條概念)
                    c4.info(f"{row['狀態']}")
                    
                    st.divider()
        else:
            st.warning("暫無數據，請確認網路連線。")

# --- Tab 2: 我的戰利品 (庫存) ---
with tab2:
    with st.sidebar:
        st.header("📝 交易登記")
        with st.form("trade_form"):
            raw_input = st.text_input("股票", "2330")
            stock_id = smart_stock_parser(raw_input)
            st.caption(f"偵測: {stock_id}")
            action = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
            cur_price = get_stock_price(stock_id)
            price_input = st.number_input("價格", value=float(cur_price) if cur_price>0 else 0.0)
            shares = st.number_input("股數", min_value=1, value=1000, step=100)
            if st.form_submit_button("送出"):
                if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE)
                else: df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])
                new_row = pd.DataFrame({
                    "日期": [datetime.now().strftime("%Y-%m-%d")],
                    "代號": [stock_id], "動作": [action],
                    "成本": [price_input], "股數": [shares]
                })
                df = pd.concat([new_row, df], ignore_index=True)
                df.to_csv(DATA_FILE, index=False)
                st.success("紀錄成功！")
                st.rerun()

    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        holdings = df[df["動作"].str.contains("買")].copy()
        if not holdings.empty:
            holdings["目前市價"] = holdings["代號"].apply(get_stock_price)
            holdings["市值"] = holdings["目前市價"] * holdings["股數"]
            holdings["成本總額"] = holdings["成本"] * holdings["股數"]
            unrealized_profit = holdings["市值"].sum() - holdings["成本總額"].sum()
            
            c1, c2 = st.columns(2)
            c1.metric("總資產", f"${holdings['市值'].sum():,.0f}")
            c2.metric("未實現損益", f"${unrealized_profit:,.0f}", delta=f"{unrealized_profit:,.0f}")
            
            st.dataframe(holdings[["代號", "股數", "成本", "目前市價", "市值"]], use_container_width=True)

            if st.button("🤖 呼叫助理簡報"):
                if ai_available:
                    res = ask_ai_daily(holdings[["代號", "股數", "成本", "目前市價"]].to_string())
                    st.success(res)
                else: st.error("無 AI Key")
        else: st.info("尚無庫存")
    else: st.info("請從側邊欄新增交易")
