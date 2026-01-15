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
st.set_page_config(page_title="AI 全方位看盤室 V7.4 (中文版)", layout="wide")

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

# === 擴充對照表 (這裡越多，中文顯示越完整) ===
STOCK_MAP = {
    # 電子龍頭
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", 
    "台達電": "2308.TW", "聯電": "2303.TW", "廣達": "2382.TW", 
    "緯創": "3231.TW", "緯穎": "6669.TW", "技嘉": "2376.TW",
    "華碩": "2357.TW", "宏碁": "2353.TW", "光寶科": "2301.TW",
    "日月光": "3711.TW", "大立光": "3008.TW", "研華": "2395.TW",
    
    # 金融
    "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW", 
    "兆豐金": "2886.TW", "玉山金": "2884.TW", "元大金": "2885.TW", 
    "第一金": "2892.TW", "合庫金": "5880.TW", "華南金": "2880.TW",
    "台新金": "2887.TW", "永豐金": "2890.TW", "開發金": "2883.TW",

    # 傳產 & 航運
    "中鋼": "2002.TW", "台塑": "1301.TW", "南亞": "1303.TW",
    "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW",
    "長榮航": "2618.TW", "華航": "2610.TW", "中華電": "2412.TW",
    "統一": "1216.TW", "遠東新": "1402.TW", "台泥": "1101.TW",

    # ETF
    "0050": "0050.TW", "元大台灣50": "0050.TW", 
    "0056": "0056.TW", "元大高股息": "0056.TW",
    "00878": "00878.TW", "國泰永續高股息": "00878.TW",
    "00929": "00929.TW", "復華台灣科技優息": "00929.TW",
    "00919": "00919.TW", "群益台灣精選高息": "00919.TW",
    "006208": "006208.TW", "富邦台50": "006208.TW",
    "00940": "00940.TW", "元大台灣價值高息": "00940.TW"
}

# 建立反向查詢表 (代號 -> 中文)
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
    """輸入代號，回傳中文名稱 (如果有的話)，否則回傳代號"""
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

# --- 鑽石評分邏輯 ---
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
# 修改這一段函數 (加入錯誤處理機制)
# ==========================================
def ask_ai_single(ticker, stock_name, info_str):
    try:
        # 這裡改用更穩定的 1.5 flash 模型
        model = genai.GenerativeModel('gemini-1.5-flash') 
        prompt = f"分析個股 {stock_name} ({ticker})：{info_str}。請用繁體中文簡短說明：1.公司業務簡介 2.目前估值狀態 3.存股建議。"
        
        # 設定等待逾時，避免卡住
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        # 如果出錯 (例如額度滿了)，回傳這句溫柔的話，而不是報錯
        return f"😅 AI 目前大塞車 (額度已滿)，請休息 1 分鐘後再試試！(錯誤代碼: {str(e)})"

# ==========================================
# 3. 主程式介面
# ==========================================
st.title("📱 AI 全方位看盤室 V7.4 (中文優化版)")

tab1, tab2, tab3 = st.tabs(["🔍 個股行情", "📡 鑽石掃描", "📊 我的資產"])

# ==========================================
# Tab 1: 個股行情
# ==========================================
with tab1:
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        q_stock = st.text_input("輸入代號或名稱 (如: 2330, 鴻海)", "2330", label_visibility="collapsed")
    with col_btn:
        st.button("查詢", use_container_width=True)

    target_id = smart_stock_parser(q_stock)
    target_name = get_stock_name(target_id) # 取得中文名
    
    info, hist = get_stock_detail(target_id)
    
    if info and not hist.empty:
        curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
        prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
        change = curr_price - prev_close
        pct_change = (change / prev_close) * 100
        
        ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
        badges, is_diamond, tech_status, eps, yield_val, roe = evaluate_stock(info, curr_price, ma60)

        # 這裡顯示中文名稱！
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
        
        st.subheader(f"📈 {target_name} 走勢圖 (含季線)")
        hist['MA60_Line'] = hist['Close'].rolling(window=60).mean()
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name='K線'))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60_Line'], mode='lines', name='季線', line=dict(color='orange', width=2)))
        fig.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        if st.button(f"🤖 呼叫 AI 分析 {target_name}"):
            if ai_available:
                info_text = f"價{curr_price}, EPS{eps}, ROE{roe}, 殖利率{yield_val}"
                res = ask_ai_single(target_id, target_name, info_text)
                st.info(res)
            else: st.error("無 AI Key")
    else: st.warning("查無資料")

# ==========================================
# Tab 2: 鑽石掃描
# ==========================================
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
                    name = get_stock_name(t) # 取得中文名
                    
                    if is_dia or (m > p): 
                        report.append({"代號": t, "名稱": name, "現價": p, "狀態": status, "標籤": " ".join(badges), "是鑽石嗎": is_dia})
        
        if report:
            df_res = pd.DataFrame(report).sort_values("是鑽石嗎", ascending=False)
            for _, row in df_res.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([1.5, 2, 2])
                    # 顯示中文名稱
                    title = f"💎 {row['名稱']} ({row['代號']})" if row['是鑽石嗎'] else f"{row['名稱']} ({row['代號']})"
                    c1.markdown(f"### {title}")
                    c2.info(row['標籤'])
                    c3.write(row['狀態'])
                    st.divider()
        else: st.info("無符合結果")

# ==========================================
# Tab 3: 我的資產 (含中文顯示)
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
            # 加上中文名稱欄位
            holdings.insert(1, "名稱", holdings["代號"].apply(get_stock_name))
            
            holdings["現價"] = holdings["代號"].apply(get_stock_price)
            holdings["市值"] = holdings["現價"] * holdings["股數"]
            total = holdings["市值"].sum()
            profit = total - (holdings["成本"]*holdings["股數"]).sum()
            
            c1, c2 = st.columns(2)
            c1.metric("總資產", f"${total:,.0f}")
            c2.metric("總損益", f"${profit:,.0f}")
            
            # 顯示表格 (含名稱)
            st.dataframe(holdings[["日期", "名稱", "代號", "股數", "成本", "現價", "市值"]], use_container_width=True)
        else: st.info("尚無庫存")
    else: st.info("請從側邊欄新增交易")

