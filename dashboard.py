import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
from datetime import datetime

# ==========================================
# 1. 設定
# ==========================================
st.set_page_config(page_title="AI 鑽石獵人戰情室 V7.2", layout="wide")

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
    "元大金": "2885.TW", "兆豐金": "2886.TW", "中鋼": "2002.TW",
    "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW",
    "緯創": "3231.TW", "廣達": "2382.TW", "技嘉": "2376.TW",
    "0050": "0050.TW", "0056": "0056.TW", "00878": "00878.TW", "00929": "00929.TW"
}

# 預設觀察清單
WATCHLIST = ["2330.TW", "2317.TW", "2454.TW", "2603.TW", "2891.TW", "2382.TW"]

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
def get_stock_info(ticker):
    """取得詳細基本面資料"""
    try:
        stock = yf.Ticker(ticker)
        return stock.info
    except:
        return {}

# --- 核心：鑽石獵人策略 (Fundamental + Technical) ---
def run_diamond_hunter(ticker_list, strict_mode=False):
    report = []
    
    for ticker in ticker_list:
        try:
            stock = yf.Ticker(ticker)
            
            # 1. 技術面：抓歷史股價算均線
            df = stock.history(period="1y") 
            if len(df) < 60: continue 

            df['MA60'] = df['Close'].rolling(window=60).mean() # 季線
            last = df.iloc[-1]
            price = last['Close']
            target_price = last['MA60']
            
            # 便宜度 (負數代表還沒跌到，正數代表便宜了幾%)
            gap_percent = (target_price - price) / target_price * 100
            
            # 2. 基本面：抓你的 3 大條件
            # 注意：免費 API 資料可能不全，我們做防呆處理
            info = stock.info
            
            # 條件 A: EPS > 1
            eps = info.get('trailingEps', 0)
            if eps is None: eps = 0
            
            # 條件 B: 殖利率 > 5% (0.05)
            yield_val = info.get('dividendYield', 0)
            if yield_val is None: yield_val = 0
            
            # 條件 C: ROE > 15% (0.15)
            roe = info.get('returnOnEquity', 0)
            if roe is None: roe = 0

            # === 評分機制 ===
            # 基本面標籤
            badges = []
            fundamental_score = 0
            
            if eps > 1:
                badges.append("💰EPS優")
                fundamental_score += 1
            if yield_val > 0.05:
                badges.append("🥥高股息")
                fundamental_score += 1
            if roe > 0.15:
                badges.append("🚀高ROE")
                fundamental_score += 1
                
            # 如果開啟「嚴格模式」，只要有一個基本面不合格就跳過
            if strict_mode and fundamental_score < 3:
                continue

            # 3. 綜合訊號判斷
            signal = "⏳ 觀察中"
            color = "gray"
            
            # 只有當「基本面不錯 (至少 2 分)」且「股價便宜 (跌破季線)」才亮燈
            if fundamental_score >= 2:
                if gap_percent > 0:
                    signal = "💎 鑽石買點"
                    color = "red" # 雙強：好公司 + 便宜
                elif gap_percent > -5:
                    signal = "👀 準備出手"
                    color = "orange" # 價格快到了
            
            # 顯示用的數據字串
            fund_info = f"EPS: {eps:.2f} | 殖利率: {yield_val*100:.1f}% | ROE: {roe*100:.1f}%"

            report.append({
                "代號": ticker,
                "現價": price,
                "目標價(MA60)": target_price,
                "距離%": gap_percent,
                "基本面標籤": " ".join(badges),
                "基本面數據": fund_info,
                "分數": fundamental_score,
                "訊號": signal,
                "color": color
            })

        except Exception as e:
            continue
            
    # 排序：先看「分數(好公司)」，再看「距離%(便宜度)」
    if not report: return pd.DataFrame()
    return pd.DataFrame(report).sort_values(["分數", "距離%"], ascending=[False, False])

def ask_ai_daily(holdings_text):
    model = genai.GenerativeModel('gemini-flash-latest')
    prompt = f"你是投資助理。用戶庫存：{holdings_text}。請簡短回報(100字內)：1.今日加碼機會 2.風險提醒。"
    response = model.generate_content(prompt)
    return response.text

# ==========================================
# 3. 主程式介面
# ==========================================
st.title("💎 AI 鑽石獵人戰情室 V7.2")

# 分頁
tab1, tab2 = st.tabs(["📡 鑽石獵場 (Screener)", "📊 我的金庫 (Portfolio)"])

# --- Tab 1: 鑽石獵場 ---
with tab1:
    st.subheader("🧐 尋找「好公司 + 便宜價」")
    st.caption("策略：篩選 EPS>1、殖利率>5%、ROE>15% 的優質股，並在跌破季線時通知。")
    
    col_scan, col_check = st.columns([1, 2])
    with col_scan:
        scan_btn = st.button("⚡ 全市場掃描", type="primary")
    with col_check:
        strict = st.checkbox("開啟嚴格模式 (只顯示 3 項全過的公司)", value=False)
    
    if scan_btn:
        # 掃描庫存 + 觀察名單
        scan_list = set(WATCHLIST)
        if os.path.exists(DATA_FILE):
            try:
                current_df = pd.read_csv(DATA_FILE)
                scan_list.update(current_df["代號"].unique().tolist())
            except: pass
            
        with st.spinner("正在進行財報與技術面分析..."):
            result_df = run_diamond_hunter(list(scan_list), strict_mode=strict)
            
        if not result_df.empty:
            for index, row in result_df.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([1.5, 3, 2])
                    
                    # 1. 代號與價格
                    c1.markdown(f"### {row['代號']}")
                    c1.caption(f"現價: {row['現價']:.1f}")
                    
                    # 2. 基本面數據 (重點！)
                    c2.markdown(f"**{row['基本面標籤']}**")
                    c2.text(f"{row['基本面數據']}")
                    
                    # 3. 買賣訊號
                    # 如果是鑽石買點，字體放大變色
                    color_style = f"color: {row['color']}; font-weight: bold;"
                    if "鑽石" in row['訊號']:
                        c3.markdown(f"### <span style='{color_style}'>{row['訊號']}</span>", unsafe_allow_html=True)
                        c3.caption(f"已便宜 {row['距離%']:.1f}%")
                    else:
                        c3.markdown(f"<span style='{color_style}'>{row['訊號']}</span>", unsafe_allow_html=True)
                        if row['距離%'] < 0:
                            c3.caption(f"還差 {abs(row['距離%']):.1f}%")
                    
                    st.divider()
        else:
            st.warning("沒有符合條件的股票 (如果是嚴格模式，試著關掉它看看)")

# --- Tab 2: 我的金庫 ---
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
