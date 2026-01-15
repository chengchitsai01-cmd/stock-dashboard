import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 設定與金鑰
# ==========================================
st.set_page_config(page_title="AI 投資戰情室 V3.0", layout="wide")

# 嘗試讀取 Secrets
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        ai_available = True
    else:
        # 為了讓你在 Codespaces 也能跑，嘗試讀取本地檔案
        import toml
        secrets = toml.load(".streamlit/secrets.toml")
        genai.configure(api_key=secrets["GOOGLE_API_KEY"])
        ai_available = True
except:
    ai_available = False
    # 這裡不顯示錯誤，只默默標記 AI 不可用

DATA_FILE = "trade_history.csv"

# ==========================================
# 2. 功能函數
# ==========================================
@st.cache_data(ttl=60) # 加入快取，避免每次都重新抓股價
def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.fast_info.last_price
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
    1. 風險評估 (集中度/波動)
    2. 獲利表現點評
    3. 下一步操作建議 (加碼/減碼/觀望)
    """
    with st.spinner('🤖 AI 大腦運算中...'):
        response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 介面邏輯
# ==========================================
st.title("🚀 AI 投資戰情室 V3.0")

# --- 讀取資料 ---
if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
else:
    df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])

# --- 側邊欄：下單區 ---
with st.sidebar:
    st.header("📝 新增交易")
    with st.form("trade_form"):
        stock_id = st.text_input("代號", "2330.TW")
        action = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
        
        # 預設填入現價
        cur_price = get_stock_price(stock_id)
        price_input = st.number_input("價格", value=float(cur_price) if cur_price > 0 else 100.0)
        shares = st.number_input("股數", min_value=1, value=1000, step=100)
        
        if st.form_submit_button("送出"):
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
            st.rerun()

# --- 主畫面邏輯 ---
if not df.empty:
    # 1. 計算庫存數據
    holdings = df[df["動作"].str.contains("買")].copy() # 簡化：只算買進
    if not holdings.empty:
        # 取得最新價格
        holdings["目前市價"] = holdings["代號"].apply(get_stock_price)
        holdings["市值"] = holdings["目前市價"] * holdings["股數"]
        holdings["原始成本"] = holdings["成本"] * holdings["股數"]
        holdings["帳面損益"] = holdings["市值"] - holdings["原始成本"]
        holdings["報酬率%"] = ((holdings["目前市價"] - holdings["成本"]) / holdings["成本"]) * 100

        # 2. 頂部 KPI 儀表板 (最吸睛的部分)
        total_assets = holdings["市值"].sum()
        total_profit = holdings["帳面損益"].sum()
        total_roi = (total_profit / holdings["原始成本"].sum()) * 100
        
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 總資產現值", f"${total_assets:,.0f}")
        col2.metric("📈 總帳面損益", f"${total_profit:,.0f}", f"{total_profit:,.0f}")
        col3.metric("🚀 整體報酬率", f"{total_roi:.2f}%", f"{total_roi:.2f}%")
        
        st.divider()

        # 3. 圖表區 (左邊圓餅，右邊明細)
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("📊 資產配置 (圓餅圖)")
            fig_pie = px.pie(holdings, values='市值', names='代號', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c2:
            st.subheader("📋 持股明細")
            st.dataframe(
                holdings[["代號", "股數", "成本", "目前市價", "報酬率%", "帳面損益"]].style.format({
                    "成本": "{:.1f}", "目前市價": "{:.1f}", "報酬率%": "{:.2f}%", "帳面損益": "{:,.0f}"
                }),
                use_container_width=True
            )

        # 4. AI 分析區
        st.subheader("🤖 AI 投資顧問建議")
        if st.button("呼叫 AI 分析師"):
            if ai_available:
                analysis = ask_ai(holdings[["代號", "股數", "報酬率%", "帳面損益"]])
                st.info(analysis)
            else:
                st.error("請檢查 API Key 設定")

        st.divider()

        # 5. 個股 K 線圖查詢功能
        st.subheader("📈 個股走勢診斷")
        selected_stock = st.selectbox("選擇要查看的股票", holdings["代號"].unique())
        
        if selected_stock:
            hist_df = get_stock_history(selected_stock)
            # 畫 K 線圖
            fig_k = go.Figure(data=[go.Candlestick(
                x=hist_df.index,
                open=hist_df['Open'], high=hist_df['High'],
                low=hist_df['Low'], close=hist_df['Close']
            )])
            fig_k.update_layout(title=f"{selected_stock} 近三個月走勢", xaxis_title="日期", yaxis_title="股價")
            st.plotly_chart(fig_k, use_container_width=True)

else:
    st.info("👈 請從左側新增第一筆交易，開始你的投資旅程！")
