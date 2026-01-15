import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 設定與台股對照表
# ==========================================
st.set_page_config(page_title="AI 投資戰情室 V3.1", layout="wide")

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

# 【台股熱門代號對照表】(你可以自己擴充)
STOCK_MAP = {
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", "廣達": "2382.TW",
    "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW", "玉山金": "2884.TW",
    "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW", "長榮航": "2618.TW",
    "華航": "2610.TW", "緯創": "3231.TW", "緯穎": "6669.TW", "技嘉": "2376.TW",
    "英業達": "2356.TW", "台達電": "2308.TW", "聯電": "2303.TW", "中華電": "2412.TW",
    "0050": "0050.TW", "台灣50": "0050.TW", 
    "0056": "0056.TW", "高股息": "0056.TW",
    "00878": "00878.TW", "國泰永續": "00878.TW",
    "00929": "00929.TW", "00940": "00940.TW",
    "華邦電": "2344.TW" # 幫你加上這檔
}

# ==========================================
# 2. 核心功能：智慧輸入處理
# ==========================================
def smart_stock_parser(user_input):
    """
    輸入處理邏輯：
    1. 如果是中文名字 -> 查表
    2. 如果是純數字 -> 加上 .TW
    3. 如果已經有 .TW -> 保持原樣
    """
    user_input = user_input.strip() # 去除空白
    
    # 情況 A: 輸入中文 (查表)
    if user_input in STOCK_MAP:
        return STOCK_MAP[user_input]
    
    # 情況 B: 輸入純數字 (自動加台股後綴)
    # 判斷是否全為數字 (isdigit)
    if user_input.isdigit():
        return f"{user_input}.TW"
    
    # 情況 C: 輸入英文代號但沒加 TW (例如 2330.tw)
    user_input = user_input.upper()
    if not user_input.endswith(".TW") and user_input[0].isdigit():
         return f"{user_input}.TW"
         
    return user_input

@st.cache_data(ttl=60)
def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        # 嘗試抓即時價格
        price = stock.fast_info.last_price
        return price
    except:
        return 0.0

def get_stock_history(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="3mo")
    return df

def ask_ai(df_summary):
    model = genai.GenerativeModel('gemini-flash-latest')
    summary_text = df_summary.to_string()
    prompt = f"""
    你是專業投資顧問。這是用戶目前的庫存：
    {summary_text}
    請用繁體中文給出 3 點簡短犀利的點評：
    1. 風險評估
    2. 獲利表現
    3. 操作建議
    """
    with st.spinner('🤖 AI 分析中...'):
        response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 介面邏輯
# ==========================================
st.title("🚀 AI 投資戰情室 V3.1 (智慧輸入版)")

# --- 讀取資料 ---
if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
else:
    df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])

# --- 側邊欄：智慧下單區 ---
with st.sidebar:
    st.header("📝 智慧下單")
    with st.form("trade_form"):
        # 這裡改成提示更明顯
        raw_input = st.text_input("股票 (輸入 2330 或 台積電)", "2330")
        
        # 即時轉換給使用者看
        stock_id = smart_stock_parser(raw_input)
        st.caption(f"✅ 系統偵測為：{stock_id}")
        
        action = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
        
        # 抓取價格
        cur_price = get_stock_price(stock_id)
        # 如果抓不到價格(例如休市或是代號錯)，預設為 0 讓使用者自己填
        default_price = float(cur_price) if cur_price > 0 else 0.0
        
        price_input = st.number_input("成交價格", value=default_price, min_value=0.0)
        shares = st.number_input("股數", min_value=1, value=1000, step=100)
        
        if st.form_submit_button("送出交易"):
            if price_input <= 0:
                st.error("❌ 價格不能為 0，請手動輸入正確價格")
            else:
                new_row = pd.DataFrame({
                    "日期": [datetime.now().strftime("%Y-%m-%d")],
                    "代號": [stock_id],
                    "動作": [action],
                    "成本": [price_input],
                    "股數": [shares]
                })
                df = pd.concat([new_row, df], ignore_index=True)
                df.to_csv(DATA_FILE, index=False)
                st.success(f"已買入 {stock_id}！")
                st.rerun()

# --- 主畫面 ---
if not df.empty:
    # 1. 可編輯表格 (Data Editor) - 取代原本的 Dataframe
    st.subheader("📋 持股明細 (可直接點兩下修改)")
    
    # 顯示編輯器
    edited_df = st.data_editor(
        df, 
        num_rows="dynamic", # 允許新增刪除列
        use_container_width=True,
        key="editor"
    )

    # 偵測是否有修改，如果有就存檔
    if not edited_df.equals(df):
        edited_df.to_csv(DATA_FILE, index=False)
        st.toast("💾 資料已更新並存檔！")
        # 這裡不一定要 rerun，讓使用者改完再手動重整也可以，體驗比較順

    # --- 以下是計算邏輯，使用 edited_df (最新數據) ---
    # 為了計算方便，我們只取「買進」的部位
    holdings = edited_df[edited_df["動作"].str.contains("買")].copy()
    
    if not holdings.empty:
        # 取得最新價格
        holdings["目前市價"] = holdings["代號"].apply(get_stock_price)
        holdings["市值"] = holdings["目前市價"] * holdings["股數"]
        holdings["原始成本"] = holdings["成本"] * holdings["股數"]
        holdings["帳面損益"] = holdings["市值"] - holdings["原始成本"]
        
        # 避免除以零
        total_cost = holdings["原始成本"].sum()
        total_profit = holdings["帳面損益"].sum()
        total_roi = (total_profit / total_cost * 100) if total_cost > 0 else 0

        # 2. KPI 儀表板
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 總資產現值", f"${holdings['市值'].sum():,.0f}")
        col2.metric("📈 總帳面損益", f"${total_profit:,.0f}", f"{total_profit:,.0f}")
        col3.metric("🚀 整體報酬率", f"{total_roi:.2f}%", f"{total_roi:.2f}%")
        
        st.divider()

        # 3. 圖表區
        c1, c2 = st.columns([1, 2])
        with c1:
            st.subheader("資產配置")
            fig_pie = px.pie(holdings, values='市值', names='代號', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c2:
            st.subheader("損益詳細計算")
            # 這裡顯示計算過的結果 (唯讀)
            # 這裡顯示計算過的結果 (唯讀)
            display_cols = holdings[["代號", "股數", "成本", "目前市價", "帳面損益"]]
            
            # 修正：針對不同欄位設定不同的格式，避免把「代號」當成數字處理而報錯
            st.dataframe(
                display_cols.style.format({
                    "股數": "{:,.0f}",      # 整數，加逗號
                    "成本": "{:,.1f}",      # 小數點 1 位
                    "目前市價": "{:,.1f}",  # 小數點 1 位
                    "帳面損益": "{:,.0f}"    # 整數，加逗號 (比較清爽)
                }),
                use_container_width=True
            )

        # 4. AI & K線圖
        st.divider()
        col_ai, col_k = st.columns([1, 1])
        
        with col_ai:
            st.subheader("🤖 AI 投資顧問")
            if st.button("呼叫 AI 分析"):
                if ai_available:
                    analysis = ask_ai(holdings[["代號", "股數", "成本", "帳面損益"]])
                    st.info(analysis)
                else:
                    st.error("API Key 未設定")
                    
        with col_k:
            st.subheader("📈 K線圖查詢")
            stock_list = holdings["代號"].unique()
            if len(stock_list) > 0:
                target = st.selectbox("選擇股票", stock_list)
                if target:
                    hist = get_stock_history(target)
                    fig = go.Figure(data=[go.Candlestick(
                        x=hist.index,
                        open=hist['Open'], high=hist['High'],
                        low=hist['Low'], close=hist['Close']
                    )])
                    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("👈 請從左側輸入代號 (例如: 2330 或 台積電) 開始使用！")

