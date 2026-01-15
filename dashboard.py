import streamlit as st
import pandas as pd
import os
from datetime import datetime

# ==========================================
# 1. 設定與讀取資料 (用 CSV 當資料庫)
# ==========================================
DATA_FILE = "trade_history.csv"

# 設定網頁標題與版面
st.set_page_config(page_title="我的 AI 投資戰情室", layout="wide")
st.title("🚀 我的 AI 投資戰情室 (模擬倉)")

# 讀取或建立 CSV 檔案
if not os.path.exists(DATA_FILE):
    # 如果檔案不存在，建立一個空的 DataFrame
    df = pd.DataFrame(columns=["日期", "代號", "動作", "價格", "股數", "總金額"])
    df.to_csv(DATA_FILE, index=False)
else:
    df = pd.read_csv(DATA_FILE)

# ==========================================
# 2. 左側邊欄：下單區
# ==========================================
st.sidebar.header("📝 交易紀錄下單")

with st.sidebar.form("trade_form"):
    stock_id = st.text_input("股票代號", value="2330.TW")
    action = st.selectbox("動作", ["買進 (Buy)", "賣出 (Sell)"])
    price = st.number_input("成交價格", min_value=0.0, value=1000.0, step=0.5)
    shares = st.number_input("股數", min_value=1, value=1000, step=100)
    
    # 送出按鈕
    submitted = st.form_submit_button("送出交易")

    if submitted:
        # 計算總金額
        total_amt = price * shares
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 判斷動作標籤
        action_tag = "🔴 買進" if "Buy" in action else "🟢 賣出"
        
        # 新增一筆資料
        new_data = pd.DataFrame({
            "日期": [date_str],
            "代號": [stock_id],
            "動作": [action_tag],
            "價格": [price],
            "股數": [shares],
            "總金額": [total_amt]
        })
        
        # 存回 CSV
        df = pd.concat([new_data, df], ignore_index=True)
        df.to_csv(DATA_FILE, index=False)
        st.success(f"✅ 已記錄：{action_tag} {stock_id} {shares}股")

# ==========================================
# 3. 主畫面：資產分析看板
# ==========================================

# --- A. 計算簡單的庫存概況 ---
# (這裡做一個簡單的邏輯：把所有買進加總，所有賣出扣掉，不算手續費)
total_invested = 0
total_sold = 0

if not df.empty:
    # 篩選買進與賣出
    buys = df[df["動作"].str.contains("買")]
    sells = df[df["動作"].str.contains("賣")]
    
    total_invested = buys["總金額"].sum()
    total_sold = sells["總金額"].sum()

# 目前淨現金流 (負數代表還在投入中，正數代表已落袋為安)
net_cashflow = total_sold - total_invested

# --- B. 顯示頂部數據卡 (Metrics) ---
col1, col2, col3 = st.columns(3)
col1.metric("交易總次數", f"{len(df)} 次")
col2.metric("總投入金額 (歷史)", f"${total_invested:,.0f}")
col3.metric("目前淨現金流", f"${net_cashflow:,.0f}", delta_color="normal")

st.divider()

# --- C. 顯示交易明細表格 ---
st.subheader("📋 歷史交易明細")
if not df.empty:
    # 讓表格有些顏色 (買是紅字，賣是綠字)
    def color_action(val):
        color = 'red' if '買' in val else 'green'
        return f'color: {color}'

    st.dataframe(
        df.style.applymap(color_action, subset=['動作']),
        use_container_width=True
    )
else:
    st.info("目前還沒有交易紀錄，請從左側新增！")

# --- D. 簡單圖表 ---
if not df.empty:
    st.subheader("📈 資金變動趨勢")
    # 這裡簡單畫一個價格紀錄圖 (示意用)
    st.line_chart(df["價格"])