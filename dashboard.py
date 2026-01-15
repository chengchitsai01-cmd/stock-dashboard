import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime

# ==========================================
# 1. 設定與金鑰讀取
# ==========================================
st.set_page_config(page_title="AI 投資戰情室 V2", layout="wide")

# 嘗試讀取 API Key (處理本地與雲端差異)
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
    ai_available = True
except:
    ai_available = False
    st.warning("⚠️ 未設定 Google API Key，AI 功能無法使用。")

DATA_FILE = "trade_history.csv"

# ==========================================
# 2. 核心功能函數
# ==========================================
def get_current_price(ticker):
    """取得即時股價"""
    try:
        stock = yf.Ticker(ticker)
        # 嘗試抓取即時價格，若盤中抓不到則抓收盤價
        price = stock.fast_info.last_price
        return price
    except:
        return 0.0

def ask_ai_advisor(df):
    """傳送庫存給 AI 分析"""
    model = genai.GenerativeModel('gemini-flash-latest')
    
    # 把庫存資料轉成文字
    inventory_text = df.to_string()
    
    prompt = f"""
    你是一位投資顧問。這是使用者的庫存與交易紀錄：
    {inventory_text}
    
    請針對這個投資組合給出 3 點簡短的評語與建議。
    重點分析：是否過度集中？目前獲利狀況如何？
    請用繁體中文回答。
    """
    with st.spinner('🤖 AI 正在大腦風暴中...'):
        response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 介面邏輯
# ==========================================
st.title("🚀 AI 投資戰情室 V2.0")

# --- 讀取資料 ---
if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
else:
    df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])

# --- 左側：下單區 ---
with st.sidebar.form("trade_form"):
    st.header("📝 新增交易")
    stock_id = st.text_input("代號", "2330.TW")
    action = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
    
    # 自動抓取目前股價當作參考
    current_market_price = get_current_price(stock_id)
    price_input = st.number_input("價格", value=float(current_market_price) if current_market_price > 0 else 100.0)
    
    shares = st.number_input("股數", min_value=1, value=1000, step=100)
    submitted = st.form_submit_button("送出")

    if submitted:
        new_row = pd.DataFrame({
            "日期": [datetime.now().strftime("%Y-%m-%d")],
            "代號": [stock_id],
            "動作": [action],
            "成本": [price_input],
            "股數": [shares]
        })
        df = pd.concat([new_row, df], ignore_index=True)
        df.to_csv(DATA_FILE, index=False)
        st.success("已儲存！")
        st.experimental_rerun() # 重新整理頁面

# --- 右側：資產看板 ---
if not df.empty:
    # 簡單計算庫存 (這裡簡化邏輯：只顯示買進的紀錄並計算現值)
    # 實戰中需要更複雜的加減邏輯
    holdings = df[df["動作"] == "🔴 買進"].copy()
    
    if not holdings.empty:
        # 批次取得現價 (比較慢，實戰可優化)
        st.subheader("💰 庫存即時損益表")
        
        # 這裡運用一個小技巧：對每一列去抓現價
        # 注意：如果資料多，這裡會卡，建議用 Cache
        holdings["目前市價"] = holdings["代號"].apply(get_current_price)
        holdings["市值"] = holdings["目前市價"] * holdings["股數"]
        holdings["原始成本"] = holdings["成本"] * holdings["股數"]
        holdings["帳面損益"] = holdings["市值"] - holdings["原始成本"]
        holdings["報酬率%"] = ((holdings["目前市價"] - holdings["成本"]) / holdings["成本"]) * 100

        # 顯示漂亮的表格
        st.dataframe(
            holdings[["日期", "代號", "股數", "成本", "目前市價", "報酬率%", "帳面損益"]].style.format({
                "成本": "{:.1f}", 
                "目前市價": "{:.1f}", 
                "報酬率%": "{:.2f}%",
                "帳面損益": "{:,.0f}"
            })
        )
        
        # --- AI 分析按鈕 ---
        st.divider()
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🤖 呼叫 AI 顧問"):
                if ai_available:
                    analysis = ask_ai_advisor(holdings)
                    st.session_state["ai_result"] = analysis
                else:
                    st.error("請先設定 API Key")
        
        with col2:
            if "ai_result" in st.session_state:
                st.info(st.session_state["ai_result"])

else:
    st.info("尚無交易紀錄")