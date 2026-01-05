import streamlit as st
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
import datetime
import google.generativeai as genai
import twstock
import time

# --- 1. 頁面設定 (手機優化模式) ---
st.set_page_config(
    page_title="Sniper Mobile",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="collapsed" # 手機版預設收起側邊欄
)

# --- CSS 魔改區 (關鍵！) ---
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    
    /* 1. 移除頂部巨大的留白，讓內容上移 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    /* 2. 優化指標卡片 (更緊湊) */
    div[data-testid="metric-container"] { 
        background-color: #1E2129; 
        border: 1px solid #363B4C; 
        padding: 8px; 
        border-radius: 8px; 
        min-height: 80px; /* 統一高度 */
    }
    div[data-testid="metric-container"] label {
        font-size: 14px !important; /* 標題縮小 */
    }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        font-size: 20px !important; /* 數值適中 */
    }
    
    /* 3. 調整 Tab 按鈕大小，方便手指點擊 */
    .stTabs [data-baseweb="tab-list"] { 
        gap: 4px; 
        flex-wrap: nowrap; /* 強制不換行，允許橫向滑動 */
        overflow-x: auto;
    }
    .stTabs [data-baseweb="tab"] {
        height: 35px;
        padding: 0px 12px;
        white-space: nowrap; /* 文字不換行 */
    }
    
    /* 4. 手機版 Radio Button 優化 */
    .stRadio > div {
        background-color: #262730;
        padding: 10px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet ---
@st.cache_data(ttl=60)
def get_positions():
    try:
        raw_json_str = st.secrets["G_SHEET_KEY"]
        pattern = r'("private_key":\s*")([\s\S]*?)(")'
        def replacer(match):
            return f"{match.group(1)}{match.group(2).replace(chr(10), '\\n')}{match.group(3)}"
        fixed_json = re.sub(pattern, replacer, raw_json_str)
        key_dict = json.loads(fixed_json, strict=False)

        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)
        sheet_url = st.secrets["SHEET_URL"]
        sheet = client.open_by_url(sheet_url).worksheet('Sniper')
        
        data = sheet.get_all_values()
        df = pd.DataFrame(data[1:], columns=data[0])
        df['狀態'] = df['狀態'].astype(str).str.strip()
        in_position_df = df[df['狀態'] == 'In Position']
        
        results = []
        if not in_position_df.empty:
            for code in in_position_df['代號'].astype(str).tolist():
                try: name = twstock.codes[code].name
                except: name = code
                results.append(f"{code} {name}")
        return results
    except Exception as e:
        return [] # 手機版出錯保持安靜，顯示空白即可

# --- 3. 數據核心 ---
def get_technical_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        df = stock.history(period="1y")
        if df.empty: return None
        
        # 為了手機效能，只計算必要的
        try: df.ta.macd(fast=12, slow=26, signal=9, append=True)
        except: pass
        try: df.ta.stoch(k=9, d=3, append=True)
        except: pass
        try: df.ta.rsi(length=14, append=True)
        except: pass
        try: df.ta.bbands(length=20, std=2, append=True)
        except: pass
        try: df.ta.obv(append=True)
        except: pass
        try: df.ta.mfi(length=14, append=True)
        except: pass
        try:
            ma20 = df['Close'].rolling(20).mean()
            df['BIAS_20'] = ((df['Close'] - ma20) / ma20) * 100
        except: pass
        return df
    except: return None

def get_company_info_safe(ticker):
    try: return yf.Ticker(ticker + ".TW").info
    except: return {} 

def get_financial_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        return stock.income_stmt, stock.balance_sheet, stock.cashflow
    except: return None, None, None

# --- 4. AI 分析引擎 ---
def generate_ai_analysis(mode, ticker_full_name, df=None, info=None, financials=None, api_key=None):
    if not api_key: return "⚠️ 未設定 API Key"
    
    parts = ticker_full_name.split(" ")
    ticker_code = parts[0]
    stock_name = parts[1] if len(parts) > 1 else ticker_code

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        if mode == "technical":
            last = df.iloc[-1]
            # 安全取值
            rsi = last['RSI_14'] if 'RSI_14' in df.columns else 0
            mfi = last['MFI_14'] if 'MFI_14' in df.columns else 0
            bias = last['BIAS_20'] if 'BIAS_20' in df.columns else 0
            
            prompt = f"""
            分析 {stock_name} ({ticker_code}) 技術面 (手機版簡報)：
            數據: 收盤{last['Close']:.1f}, RSI{rsi:.1f}, MFI{mfi:.1f}, 乖離{bias:.2f}%
            請用條列式給出：1.趨勢評分 2.資金流向判讀 3.短線操作點位
            """
        elif mode == "fundamental":
            inc_str = financials[0].iloc[:, :2].to_markdown() if financials and financials[0] is not None else "無"
            prompt = f"""
            分析 {stock_name} ({ticker_code}) 基本面 (手機版簡報)：
            損益表摘要:\n{inc_str}
            請簡潔說明：1.獲利趨勢 2.財務體質 3.投資建議 (買/賣)
            """

        with st.spinner('AI 思考中...'):
            response = model.generate_content(prompt)
            return response.text
    except Exception as e: return f"❌ 連線失敗: {str(e)}"

# --- 5. 導航邏輯 (手機版核心：Top Navigation) ---
# 側邊欄保留給進階設定 (API Key)
with st.sidebar:
    st.title("⚙️ 設定")
    if "GEMINI_API_KEY" in st.secrets:
        gemini_key = st.secrets["GEMINI_API_KEY"]
        st.success("API Key 已鎖定")
    else:
        gemini_key = st.text_input("Gemini API Key", type="password")

# --- 主畫面頂部導航區 ---
# 這裡用 expander 讓使用者可以收合選單，節省空間
with st.expander("🔍 股票切換與控制 (點擊展開)", expanded=True):
    col_refresh, col_input = st.columns([1, 2])
    with col_refresh:
        if st.button("🔄 刷新", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    ticker_list = get_positions()
    
    # 手機版邏輯：用 selectbox 代替 radio，比較省空間
    if ticker_list:
        selected_option = st.selectbox("選擇庫存", ticker_list)
    else:
        selected_option = None
        st.info("無庫存")
        
    manual_input = st.text_input("或輸入代號查詢", placeholder="例如 2330", label_visibility="collapsed")

# 決定代號
final_ticker_code = None
final_ticker_name = None

if manual_input:
    clean_code = manual_input.strip()
    final_ticker_code = clean_code
    try: name = twstock.codes[clean_code].name
    except: name = clean_code
    final_ticker_name = f"{clean_code} {name}"
elif selected_option:
    final_ticker_code = selected_option.split(" ")[0]
    final_ticker_name = selected_option
else:
    final_ticker_code = "2330"
    final_ticker_name = "2330 台積電 (Demo)"

# --- 6. 內容顯示區 ---
if final_ticker_code:
    # Session State
    if 'current_ticker' not in st.session_state:
        st.session_state.current_ticker = ""
        st.session_state.tech_report = None
        st.session_state.fund_report = None
        st.session_state.df = None
        st.session_state.info = None
        st.session_state.financials = None

    if st.session_state.current_ticker != final_ticker_code:
        st.session_state.current_ticker = final_ticker_code
        st.session_state.tech_report = None
        st.session_state.fund_report = None
        st.session_state.df = None
        st.session_state.info = None
        st.session_state.financials = None
        
        with st.spinner('載入中...'):
            st.session_state.df = get_technical_data(final_ticker_code)
            st.session_state.info = get_company_info_safe(final_ticker_code)

    st.subheader(f"📊 {final_ticker_name}")

    if st.session_state.df is None:
        st.error("查無資料")
    else:
        df = st.session_state.df
        info = st.session_state.info
        last = df.iloc[-1]
        
        def safe_get(col, fmt="{:.1f}"):
            if col in df.columns and not pd.isna(last[col]): return fmt.format(last[col])
            return "-"

        pct = ((last['Close'] - df['Close'].iloc[-2])/df['Close'].iloc[-2])*100
        
        # 🔥 手機版排版優化：3列 + 2列 (避免單行太長)
        # 第一排：核心價格資訊
        m1, m2, m3 = st.columns(3)
        m1.metric("現價", f"{last['Close']:.0f}", f"{pct:.2f}%")
        m2.metric("MFI", safe_get('MFI_14', "{:.0f}"))
        m3.metric("RSI", safe_get('RSI_14', "{:.0f}"))
        
        # 第二排：進階資訊
        m4, m5 = st.columns(2)
        m4.metric("乖離率", safe_get('BIAS_20', "{:.2f}%"))
        pe = info.get('trailingPE', '-') if info else '-'
        m5.metric("本益比", str(pe))

        # 分頁區
        tabs = st.tabs(["K線", "指標", "技AI", "財AI"])

        with tabs[0]:
            # 手機版圖表高度縮小，margin 歸零
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.05)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='orange', width=1), name='MA20'), row=1, col=1)
            if 'OBV' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV', line=dict(color='cyan')), row=2, col=1)
            
            # 手機版 Layout：隱藏 Range Slider，減少圖例佔位
            fig.update_layout(
                height=400, # 高度縮小適配手機
                template="plotly_dark", 
                xaxis_rangeslider_visible=False, 
                margin=dict(l=0,r=0,t=10,b=0),
                legend=dict(orientation="h", y=1, x=0) # 圖例放上面
            )
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
            # 合併成一個大圖表，方便手機滑動
            st.caption("MACD & KD")
            fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True)
            if 'MACDh_12_26_9' in df.columns: 
                fig2.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], marker_color='#29B6F6', name='MACD'), row=1, col=1)
            if 'STOCHk_9_3_3' in df.columns:
                fig2.add_trace(go.Scatter(x=df.index, y=df['STOCHk_9_3_3'], line=dict(color='yellow', width=1), name='K'), row=2, col=1)
                fig2.add_trace(go.Scatter(x=df.index, y=df['STOCHd_9_3_3'], line=dict(color='red', width=1), name='D'), row=2, col=1)
            fig2.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

        with tabs[2]:
            if st.session_state.tech_report:
                st.markdown(st.session_state.tech_report)
                if st.button("🔄 重算", key="r1", use_container_width=True):
                    st.session_state.tech_report = generate_ai_analysis("technical", final_ticker_name, df=df, info=info, api_key=gemini_key)
                    st.rerun()
            else:
                if st.button("✨ 分析技術面", key="b1", use_container_width=True):
                    report = generate_ai_analysis("technical", final_ticker_name, df=df, info=info, api_key=gemini_key)
                    st.session_state.tech_report = report
                    st.rerun()

        with tabs[3]:
            if st.session_state.fund_report:
                st.markdown(st.session_state.fund_report)
                if st.button("🔄 重算", key="r2", use_container_width=True):
                    inc, bal, cash = get_financial_data(final_ticker_code)
                    st.session_state.financials = (inc, bal, cash)
                    st.session_state.fund_report = generate_ai_analysis("fundamental", final_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                    st.rerun()
            else:
                if st.button("📥 下載財報並分析", key="b2", use_container_width=True):
                    if not st.session_state.financials:
                        with st.spinner("下載中..."):
                            inc, bal, cash = get_financial_data(final_ticker_code)
                            st.session_state.financials = (inc, bal, cash)
                    report = generate_ai_analysis("fundamental", final_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                    st.session_state.fund_report = report
                    st.rerun()
