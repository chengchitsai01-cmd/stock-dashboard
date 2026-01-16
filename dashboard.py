import streamlit as st
import pandas as pd
import os
import yfinance as yf
import google.generativeai as genai
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import time
import random

# ==========================================
# 1. 設定
# ==========================================
st.set_page_config(page_title="AI 操盤手戰情室 V9.2 (經典回歸版)", layout="wide")

# ==========================================
# 2. 系統診斷核心
# ==========================================
def init_ai():
    api_key = None
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        try:
            import toml
            secrets = toml.load(".streamlit/secrets.toml")
            if "GOOGLE_API_KEY" in secrets:
                api_key = secrets["GOOGLE_API_KEY"]
        except:
            pass
            
    if api_key:
        genai.configure(api_key=api_key)
        return True, api_key
    return False, None

ai_available, current_key = init_ai()

DATA_FILE = "trade_history.csv"

# ==========================================
# 3. 資料與工具
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
        dividends = stock.dividends
        return info, hist, dividends
    except:
        return None, None, None

def get_stock_news(ticker):
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        valid_news = []
        if news:
            for n in news:
                if 'title' in n and 'link' in n and n['title']:
                    valid_news.append(n)
        return valid_news[:3]
    except:
        return []

def calculate_kd(df, period=9):
    low_min = df['Low'].rolling(window=period).min()
    high_max = df['High'].rolling(window=period).max()
    df['RSV'] = 100 * (df['Close'] - low_min) / (high_max - low_min)
    df = df.dropna()
    k_list = []
    d_list = []
    k_curr, d_curr = 50, 50 
    for rsv in df['RSV']:
        k_curr = (2/3) * k_curr + (1/3) * rsv
        d_curr = (2/3) * d_curr + (1/3) * k_curr
        k_list.append(k_curr)
        d_list.append(d_curr)
    df['K'] = k_list
    df['D'] = d_list
    return df

def calculate_score(price, ma60, k, d, vol, vol_avg):
    score = 50
    if price > ma60: score += 15
    else: score -= 15
    if k > d: score += 10
    if k > 80: score -= 5
    if k < 20: score += 10
    if vol > vol_avg: score += 5
    return max(0, min(100, score))

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
# 4. AI 核心 (使用最經典的 gemini-pro)
# ==========================================
def ask_ai_test():
    """系統診斷專用：測試連線"""
    try:
        # 回歸最經典的 model，這一定相容
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content("Test connection.")
        return True, "成功連線 (Model: gemini-pro)"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=86400, show_spinner=False)
def ask_ai_single(ticker, stock_name, info_str, tech_str):
    # 使用 gemini-pro，解決 404 問題
    model_name = 'gemini-pro'
    
    try:
        time.sleep(1)
        model = genai.GenerativeModel(model_name)
        prompt = f"""
        你是技術分析師。分析 {stock_name} ({ticker})。
        【技術】{tech_str}
        【基本】{info_str}
        請用繁體中文給建議 (100字內)：1.趨勢 2.操作 3.理由
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"🚫 連線失敗: {str(e)}"

@st.cache_data(ttl=3600, show_spinner=False)
def ask_ai_news(news_list):
    # 使用 gemini-pro
    model_name = 'gemini-pro'
    
    if not news_list: return ""
    titles = [n['title'] for n in news_list if 'title' in n]
    if not titles: return ""
    titles_str = "\n".join(titles)
    
    try:
        model = genai.GenerativeModel(model_name)
        prompt = f"新聞標題：{titles_str}。回答：1.氣氛 2.重點。"
        response = model.generate_content(prompt)
        return response.text
    except: 
        return ""

@st.cache_data(ttl=3600, show_spinner=False)
def ask_ai_todo_list(portfolio_status_str):
    # 使用 gemini-pro
    model_name = 'gemini-pro'
    try:
        model = genai.GenerativeModel(model_name)
        prompt = f"庫存：{portfolio_status_str}。請給操作建議清單。"
        response = model.generate_content(prompt)
        return response.text
    except: 
        return "😅 AI 休息中..."

# ==========================================
# 5. 主程式介面
# ==========================================
st.title("📱 AI 操盤手戰情室 V9.2 (經典回歸版)")

# --- 側邊欄：系統診斷區 ---
with st.sidebar:
    st.header("🚑 系統診斷室")
    if ai_available:
        st.success("✅ API Key 已載入")
        if current_key:
            st.caption(f"Key 前四碼: {current_key[:4]}...")
    else:
        st.error("❌ 找不到 API Key")

    st.divider()
    
    if st.button("🛠️ 測試 AI 連線"):
        if ai_available:
            with st.spinner("正在連線 (gemini-pro)..."):
                success, msg = ask_ai_test()
                if success:
                    st.success("🎉 連線成功！")
                    st.info(msg)
                else:
                    st.error("💀 連線失敗")
                    st.code(msg)
        else:
            st.warning("請先設定 API Key")
    
    st.divider()

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
    
    info, hist, dividends = get_stock_detail(target_id)
    
    if info and not hist.empty:
        curr_price = info.get('currentPrice', hist.iloc[-1]['Close'])
        prev_close = info.get('previousClose', hist.iloc[-2]['Close'])
        change = curr_price - prev_close
        pct_change = (change / prev_close) * 100
        
        hist['MA60_Line'] = hist['Close'].rolling(window=60).mean()
        ma60_val = hist['MA60_Line'].iloc[-1]
        vol_avg = hist['Volume'].rolling(window=5).mean().iloc[-1]
        hist = calculate_kd(hist)
        k_val = hist['K'].iloc[-1]
        d_val = hist['D'].iloc[-1]
        power_score = calculate_score(curr_price, ma60_val, k_val, d_val, hist['Volume'].iloc[-1], vol_avg)
        
        badges, is_diamond, tech_status, eps, yield_val, roe = evaluate_stock(info, curr_price, ma60_val)

        st.markdown(f"## {target_name} ({target_id})")
        
        c1, c2 = st.columns([1, 1])
        with c1:
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number", value = power_score, domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "多空戰力指數"},
                gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "darkblue"},
                    'steps': [{'range': [0, 40], 'color': "lightgreen"}, {'range': [40, 60], 'color': "lightgray"}, {'range': [60, 100], 'color': "salmon"}],
                    'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': power_score}}))
            fig_gauge.update_layout(height=250, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_gauge, use_container_width=True)

        with c2:
            st.subheader("🏥 六宮格體檢")
            g1, g2, g3 = st.columns(3)
            g4, g5, g6 = st.columns(3)
            if curr_price > ma60_val: g1.metric("趨勢", "多頭", "季線上")
            else: g1.metric("趨勢", "空頭", "季線下", delta_color="inverse")
            if hist['Volume'].iloc[-1] > vol_avg: g2.metric("量能", "爆量", "大於均量")
            else: g2.metric("量能", "縮量", "小於均量", delta_color="off")
            if k_val > 80: g3.metric("熱度", "過熱", f"K={k_val:.0f}", delta_color="inverse")
            elif k_val < 20: g3.metric("熱度", "超賣", f"K={k_val:.0f}")
            else: g3.metric("熱度", "正常", f"K={k_val:.0f}", delta_color="off")
            pe = info.get('trailingPE', 0)
            if pe is None: pe = 0
            if pe > 0 and pe < 15: g4.metric("估值", "便宜", f"PE={pe:.1f}")
            elif pe > 25: g4.metric("估值", "昂貴", f"PE={pe:.1f}", delta_color="inverse")
            else: g4.metric("估值", "合理", f"PE={pe:.1f}", delta_color="off")
            if yield_val > 0.05: g5.metric("股息", "高息", f"{yield_val*100:.1f}%")
            else: g5.metric("股息", "一般", f"{yield_val*100:.1f}%", delta_color="off")
            if pct_change > 0: g6.metric("動能", "強", f"{pct_change:.1f}%")
            else: g6.metric("動能", "弱", f"{pct_change:.1f}%", delta_color="inverse")

        st.divider()
        
        if st.button(f"🤖 呼叫 AI 分析 {target_name}"):
            if ai_available:
                tech_text = f"現價{curr_price}, 季線{ma60_val:.1f}。K值{k_val:.1f}, D值{d_val:.1f}。"
                if curr_price > ma60_val: tech_text += "股價在季線上(強)。"
                else: tech_text += "股價在季線下(弱)。"
                info_text = f"EPS{eps}, ROE{roe}, 殖利率{yield_val}。"
                
                with st.spinner("AI 分析中..."):
                    ai_comment = ask_ai_single(target_id, target_name, info_text, tech_text)
                    st.info(f"💡 **AI 觀點**：\n\n{ai_comment}")
            else:
                st.error("請先在側邊欄檢查 AI 連線")

        st.subheader("📈 技術分析")
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2])
        fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name='K線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60_Line'], mode='lines', name='季線', line=dict(color='orange', width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist.index, y=hist['K'], mode='lines', name='K', line=dict(color='red', width=1.5)), row=2, col=1)
        fig.add_trace(go.Scatter(x=hist.index, y=hist['D'], mode='lines', name='D', line=dict(color='blue', width=1.5)), row=2, col=1)
        fig.add_hline(y=80, line_dash="dash", line_color="gray", row=2, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="gray", row=2, col=1)
        colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in hist.iterrows()]
        fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='量', marker_color=colors), row=3, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=800, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("📰 最新消息")
        news = get_stock_news(target_id)
        if news:
            if ai_available:
                sentiment = ask_ai_news(news)
                if sentiment: st.success(f"🤖 {sentiment}")
            for n in news:
                st.markdown(f"- [{n['title']}]({n['link']})")
        else: st.caption("無新聞")
        
    else: st.warning("查無資料")

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
        with st.spinner("尋找便宜好股..."):
            for t in scan_list:
                info, hist, _ = get_stock_detail(t)
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

with tab3:
    with st.sidebar:
        st.header("📝 交易登記")
        with st.form("trade_form"):
            t_input = st.text_input("代號", "2330")
            act = st.selectbox("動作", ["🔴 買進", "🟢 賣出"])
            t_id = smart_stock_parser(t_input)
            cur_p = get_stock_price(t_id)
            pr = st.number_input("價格", min_value=0.0, value=float(cur_p) if cur_p>0 else 0.0)
            sh = st.number_input("股數", min_value=1, value=1000, step=100)
            if st.form_submit_button("送出交易"):
                if os.path.exists(DATA_FILE): df = pd.read_csv(DATA_FILE)
                else: df = pd.DataFrame(columns=["日期", "代號", "動作", "成本", "股數"])
                new = pd.DataFrame({"日期":[datetime.now().strftime("%Y-%m-%d")],"代號":[t_id],"動作":[act],"成本":[pr],"股數":[sh]})
                pd.concat([new, df]).to_csv(DATA_FILE, index=False)
                st.success("已記錄")
                st.rerun()
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        holdings = df[df["動作"].str.contains("買")].copy()
        if not holdings.empty:
            st.subheader("💰 資產總覽")
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
            st.subheader("📅 今日 AI 操盤待辦")
            if st.button("🚀 生成今日操作清單", type="primary"):
                if ai_available:
                    with st.spinner("AI 正在逐一檢視..."):
                        portfolio_status = ""
                        for idx, row in holdings.iterrows():
                            t_id = row['代號']
                            t_name = row['名稱']
                            cost = row['成本']
                            _, hist, _ = get_stock_detail(t_id)
                            if not hist.empty:
                                current_p = hist.iloc[-1]['Close']
                                ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
                                hist = calculate_kd(hist)
                                k_now = hist['K'].iloc[-1]
                                status = f"- {t_name}: 成本{cost}, 現價{current_p:.1f}, 季線{ma60:.1f}, KD值{k_now:.1f}\n"
                                portfolio_status += status
                        todo_list = ask_ai_todo_list(portfolio_status)
                        st.success(todo_list)
                else: st.error("無 AI Key")
        else: st.info("尚無庫存")
    else: st.info("無交易紀錄")
