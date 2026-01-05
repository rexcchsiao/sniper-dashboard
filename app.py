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

# --- 1. 頁面設定 (手機優先) ---
st.set_page_config(
    page_title="Sniper Mobile V12.2",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS 魔改區 (V12.2 修復頂部觸控問題) ---
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    
    /* 🔥 關鍵修正：加大頂部間距，避開 Streamlit 系統 Header */
    .block-container {
        padding-top: 3.5rem !important; /* 原本是 1rem，現在改大一點 */
        padding-bottom: 3rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }

    /* 2. 數據網格 CSS */
    .metric-grid-3 {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 6px;
        margin-bottom: 6px;
    }
    .metric-grid-2 {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 6px;
        margin-bottom: 10px;
    }
    .metric-card {
        background-color: #1E2129;
        border: 1px solid #363B4C;
        border-radius: 6px;
        padding: 8px 4px;
        text-align: center;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .metric-label {
        font-size: 12px;
        color: #B0B0B0;
        margin-bottom: 2px;
    }
    .metric-value {
        font-size: 18px;
        font-weight: 600;
        color: #FFFFFF;
        line-height: 1.2;
    }
    .metric-delta {
        font-size: 11px;
        margin-top: 2px;
    }
    .up-color { color: #00E676; }
    .down-color { color: #FF5252; }
    .no-color { color: #B0B0B0; }

    /* 3. Tab 與其他樣式 */
    .stTabs [data-baseweb="tab-list"] { 
        gap: 2px; 
        overflow-x: auto;
        flex-wrap: nowrap;
        -webkit-overflow-scrolling: touch;
    }
    .stTabs [data-baseweb="tab"] {
        height: 35px;
        padding: 0px 10px;
        font-size: 14px;
        flex: 1 0 auto;
    }
    
    /* 4. 隱藏 Selectbox 的 label 空間 */
    div[data-testid="stSelectbox"] label {
        display: none;
    }
    
    /* 5. 調整按鈕高度，讓它跟選單一樣高 */
    div[data-testid="stButton"] button {
        height: 42px; /* 手動對齊 selectbox 高度 */
        margin-top: 0px;
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
        return []

# --- 3. 數據核心 ---
def get_technical_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        df = stock.history(period="1y")
        if df.empty: return None
        
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
            rsi = last['RSI_14'] if 'RSI_14' in df.columns else 0
            mfi = last['MFI_14'] if 'MFI_14' in df.columns else 0
            bias = last['BIAS_20'] if 'BIAS_20' in df.columns else 0
            
            prompt = f"""
            分析 {stock_name} ({ticker_code}) 技術面 (手機版簡報)：
            數據: 收盤{last['Close']:.1f}, RSI{rsi:.1f}, MFI{mfi:.1f}, 乖離{bias:.2f}%
            請用極簡條列式：1.趨勢評分 2.資金流向 3.操作點位
            """
        elif mode == "fundamental":
            inc_str = financials[0].iloc[:, :2].to_markdown() if financials and financials[0] is not None else "無"
            prompt = f"""
            分析 {stock_name} ({ticker_code}) 基本面 (手機版簡報)：
            損益表摘要:\n{inc_str}
            請簡潔說明：1.獲利趨勢 2.財務體質 3.投資建議 (買/賣)
            """

        with st.spinner('🤖'):
            response = model.generate_content(prompt)
            return response.text
    except Exception as e: return f"❌: {str(e)}"

# --- 5. 導航邏輯 ---
with st.sidebar:
    st.title("⚙️ 設定")
    if "GEMINI_API_KEY" in st.secrets:
        gemini_key = st.secrets["GEMINI_API_KEY"]
        st.success("API Key 已鎖定")
    else:
        gemini_key = st.text_input("Gemini API Key", type="password")

# Row 1: 刷新 + 選單
c_nav_1, c_nav_2 = st.columns([1, 4], gap="small")

with c_nav_1:
    if st.button("🔄", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with c_nav_2:
    ticker_list = get_positions()
    selected_option = None
    if ticker_list:
        selected_option = st.selectbox(
            "inventory", 
            ticker_list, 
            label_visibility="collapsed"
        )
    else:
        st.info("無庫存")

# Row 2: 查詢
manual_input = st.text_input(
    "search", 
    placeholder="或輸入代號查詢 (如 2330)", 
    label_visibility="collapsed"
)

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
        
        with st.spinner('Load...'):
            st.session_state.df = get_technical_data(final_ticker_code)
            st.session_state.info = get_company_info_safe(final_ticker_code)

    st.caption(f"📊 {final_ticker_name}")

    if st.session_state.df is None:
        st.error("查無資料")
    else:
        df = st.session_state.df
        info = st.session_state.info
        last = df.iloc[-1]
        
        def safe_num(col): 
            if col in df.columns and not pd.isna(last[col]): return last[col]
            return 0
            
        close = last['Close']
        prev_close = df['Close'].iloc[-2]
        change = close - prev_close
        pct = (change / prev_close) * 100
        
        color_cls = "up-color" if change > 0 else "down-color" if change < 0 else "no-color"
        sign = "+" if change > 0 else ""
        
        mfi = safe_num('MFI_14')
        rsi = safe_num('RSI_14')
        bias = safe_num('BIAS_20')
        pe = info.get('trailingPE', '-') if info else '-'

        st.markdown(f"""
        <div class="metric-grid-3">
            <div class="metric-card">
                <div class="metric-label">現價</div>
                <div class="metric-value {color_cls}">{close:.0f}</div>
                <div class="metric-delta {color_cls}">{sign}{pct:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">MFI (資金)</div>
                <div class="metric-value">{mfi:.0f}</div>
                <div class="metric-delta no-color">流量</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">RSI (強弱)</div>
                <div class="metric-value">{rsi:.0f}</div>
                <div class="metric-delta no-color">動能</div>
            </div>
        </div>
        <div class="metric-grid-2">
            <div class="metric-card">
                <div class="metric-label">BIAS (乖離率)</div>
                <div class="metric-value">{bias:.2f}%</div>
                <div class="metric-delta">20日</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">PE (本益比)</div>
                <div class="metric-value">{pe}</div>
                <div class="metric-delta">估值</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        tabs = st.tabs(["K線", "指標", "技AI", "財AI"])

        with tabs[0]:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='orange', width=1), name='MA20'), row=1, col=1)
            if 'OBV' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV', line=dict(color='cyan')), row=2, col=1)
            
            fig.update_layout(
                height=380, 
                template="plotly_dark", 
                xaxis_rangeslider_visible=False, 
                margin=dict(l=0,r=0,t=5,b=0),
                legend=dict(orientation="h", y=1, x=0, bgcolor='rgba(0,0,0,0)')
            )
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
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
                if st.button("🔄", key="r1", use_container_width=True):
                    st.session_state.tech_report = generate_ai_analysis("technical", final_ticker_name, df=df, info=info, api_key=gemini_key)
                    st.rerun()
            else:
                if st.button("✨ 技術分析", key="b1", use_container_width=True):
                    report = generate_ai_analysis("technical", final_ticker_name, df=df, info=info, api_key=gemini_key)
                    st.session_state.tech_report = report
                    st.rerun()

        with tabs[3]:
            if st.session_state.fund_report:
                st.markdown(st.session_state.fund_report)
                if st.button("🔄", key="r2", use_container_width=True):
                    inc, bal, cash = get_financial_data(final_ticker_code)
                    st.session_state.financials = (inc, bal, cash)
                    st.session_state.fund_report = generate_ai_analysis("fundamental", final_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                    st.rerun()
            else:
                if st.button("📥 財報分析", key="b2", use_container_width=True):
                    if not st.session_state.financials:
                        with st.spinner("下載..."):
                            inc, bal, cash = get_financial_data(final_ticker_code)
                            st.session_state.financials = (inc, bal, cash)
                    report = generate_ai_analysis("fundamental", final_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                    st.session_state.fund_report = report
                    st.rerun()
