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
import time # 用於重試延遲

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper Pro V8.1 (Anti-Crash)",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 美化
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    div[data-testid="metric-container"] { 
        background-color: #1E2129; 
        border: 1px solid #363B4C; 
        padding: 15px; 
        border-radius: 8px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        background-color: #262730;
        border-radius: 4px;
        padding: 0px 16px;
        color: #FAFAFA;
    }
    .stTabs [aria-selected="true"] {
        background-color: #D32F2F; /* Emergency Red style */
        color: white;
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
        
        if in_position_df.empty: return []
        return in_position_df['代號'].astype(str).tolist()
    except Exception as e:
        st.error(f"Sheet 連線錯誤: {str(e)}")
        return []

# --- 3. 技術數據核心 (安全模式) ---
# 🔥 修改重點：這裡不再回傳 info，只回傳 df，確保 K 線圖永遠能跑
def get_technical_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        df = stock.history(period="1y")
        
        if df.empty: return None

        # 計算指標
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.stoch(k=9, d=3, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.obv(append=True)
        df.ta.mfi(length=14, append=True)
        
        ma20 = df['Close'].rolling(20).mean()
        df['BIAS_20'] = ((df['Close'] - ma20) / ma20) * 100
        
        return df
    except Exception as e:
        st.error(f"股價抓取失敗: {e}")
        return None

# --- 4. 基本面數據核心 (防爆設計) ---
# 🔥 修改重點：獨立出來，並且加上 try-except，失敗了就回傳空字典，不會讓 APP 崩潰
def get_company_info_safe(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        # 這裡是最容易報錯的地方，我們把它包起來
        return stock.info
    except Exception:
        # 如果被 Rate Limit，回傳一個假的空資料，讓介面顯示 N/A
        return {} 

def get_financial_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        return stock.income_stmt, stock.balance_sheet, stock.cashflow
    except:
        return None, None, None

# --- 5. AI 分析引擎 ---
def generate_ai_analysis(mode, ticker, df=None, info=None, financials=None, api_key=None):
    if not api_key:
        return "⚠️ 請先設定 Gemini API Key 以啟用 AI 分析。"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # 處理 info 可能為空的情況
        info_summary = info.get('longBusinessSummary', '無資料 (API 限流中)') if info else "無資料"
        pe = info.get('trailingPE', 'N/A') if info else 'N/A'

        if mode == "technical":
            last = df.iloc[-1]
            prompt = f"""
            你是一位量化交易員。請分析 {ticker} 技術面：
            [數據] 收盤:{last['Close']:.1f}, RSI:{last['RSI_14']:.1f}, MFI:{last['MFI_14']:.1f}, 乖離率:{last['BIAS_20']:.2f}%
            [任務] 1.評分(1-10) 2.解讀背離 3.操作建議
            """
            
        elif mode == "fundamental":
            inc_str = financials[0].iloc[:, :2].to_markdown() if financials and financials[0] is not None else "無法取得"
            
            prompt = f"""
            你是一位基本面分析師。請分析 {ticker}：
            [簡介] {info_summary}
            [損益表摘要] {inc_str}
            [PE] {pe}
            [任務] 1.營收趨勢 2.估值分析 3.投資評級
            """

        with st.spinner(f'♊ Gemini 正在運算...'):
            response = model.generate_content(prompt)
            return response.text

    except Exception as e:
        return f"❌ AI 連線失敗: {str(e)}"

# --- 6. 側邊欄 ---
with st.sidebar:
    st.title("🛡️ Sniper Pro V8.1")
    if st.button("🔄 刷新數據", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    if "GEMINI_API_KEY" in st.secrets:
        gemini_key = st.secrets["GEMINI_API_KEY"]
        st.success("✅ AI Ready")
    else:
        gemini_key = st.text_input("Gemini API Key", type="password")
    
    ticker_list = get_positions()
    if ticker_list:
        selected_ticker = st.selectbox("📂 庫存監控", ticker_list)
    else:
        st.warning("無庫存，測試模式")
        selected_ticker = st.text_input("輸入代號", "2330")

# --- 7. 主畫面 ---
if selected_ticker:
    if 'data_fetched' not in st.session_state:
        st.session_state.data_fetched = False

    if st.session_state.get('current_ticker') != selected_ticker:
        st.session_state.data_fetched = False
        st.session_state.current_ticker = selected_ticker
        st.session_state.financials = None

    st.header(f"📊 {selected_ticker} 戰情中心")
    
    if not st.session_state.data_fetched:
        with st.spinner('正在載入技術指標...'):
            # 1. 先抓絕對不能失敗的 K 線
            df = get_technical_data(selected_ticker)
            
            # 2. 再嘗試抓容易失敗的 Info (失敗就算了)
            info = get_company_info_safe(selected_ticker)
            
            if df is not None:
                st.session_state.df = df
                st.session_state.info = info
                st.session_state.data_fetched = True
            else:
                st.error("❌ 嚴重錯誤：連股價都抓不到，請檢查代號或稍後再試。")

    if st.session_state.data_fetched:
        df = st.session_state.df
        info = st.session_state.info # 這可能是一個空字典 {}
        last = df.iloc[-1]
        
        # 頂部儀表板 (安全存取 info)
        c1, c2, c3, c4, c5 = st.columns(5)
        pct = ((last['Close'] - df['Close'].iloc[-2])/df['Close'].iloc[-2])*100
        
        c1.metric("現價", f"{last['Close']:.1f}", f"{pct:.2f}%")
        c2.metric("MFI", f"{last['MFI_14']:.1f}")
        c3.metric("乖離率", f"{last['BIAS_20']:.2f}%")
        
        # 如果 info 是空的，顯示 N/A，不要報錯
        pe_val = info.get('trailingPE', 'N/A') if info else 'Loading...'
        eps_val = info.get('trailingEps', 'N/A') if info else 'Loading...'
        
        c4.metric("本益比", f"{pe_val}")
        c5.metric("EPS", f"{eps_val}")

        st.markdown("---")
        
        # 如果 info 是空的，給個提示
        if not info:
            st.warning("⚠️ Yahoo API 限流中，部分基本面數據 (PE, EPS, 簡介) 暫時無法顯示，但技術圖表不受影響。")

        tabs = st.tabs(["📈 K線/籌碼", "🌊 進階指標", "🤖 技術 AI", "💰 財報 AI"])

        with tabs[0]:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='#FFA500'), name='月線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot'), name='上軌'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot'), name='下軌'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV', line=dict(color='cyan')), row=2, col=1)
            fig.update_layout(height=550, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("MFI & RSI")
                fig_mfi = go.Figure()
                fig_mfi.add_trace(go.Scatter(x=df.index, y=df['MFI_14'], name='MFI', line=dict(color='#00E676')))
                fig_mfi.add_trace(go.Scatter(x=df.index, y=df['RSI_14'], name='RSI', line=dict(color='#FF5252')))
                fig_mfi.add_hline(y=80, line_dash="dot", line_color="gray")
                fig_mfi.add_hline(y=20, line_dash="dot", line_color="gray")
                fig_mfi.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_mfi, use_container_width=True)
            with col2:
                st.subheader("BIAS & MACD")
                fig_bias = make_subplots(rows=2, cols=1, shared_xaxes=True)
                fig_bias.add_trace(go.Bar(x=df.index, y=df['BIAS_20'], name='乖離率', marker_color='#AB47BC'), row=1, col=1)
                fig_bias.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], name='MACD', marker_color='#29B6F6'), row=2, col=1)
                fig_bias.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), showlegend=False)
                st.plotly_chart(fig_bias, use_container_width=True)

        with tabs[2]:
            st.markdown("### 🤖 技術面診斷")
            if st.button("✨ 啟動技術分析", key="btn_tech"):
                report = generate_ai_analysis("technical", selected_ticker, df=df, info=info, api_key=gemini_key)
                st.markdown(report)

        with tabs[3]:
            st.markdown("### 💰 財報體質診斷")
            st.info("💡 點擊按鈕下載財報 (若 API 限流可能失敗，請稍後再試)")
            
            if st.button("📥 下載財報並分析", key="btn_fund"):
                if not st.session_state.financials:
                    with st.spinner("連線 Yahoo 財報資料庫..."):
                        inc, bal, cash = get_financial_data(selected_ticker)
                        st.session_state.financials = (inc, bal, cash)
                
                report = generate_ai_analysis("fundamental", selected_ticker, info=info, financials=st.session_state.financials, api_key=gemini_key)
                st.markdown(report)
