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

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper Pro V10.1",
    page_icon="🦅",
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
        padding: 10px; 
        border-radius: 8px; 
    }
    .stRadio > div {
        background-color: #262730;
        padding: 10px;
        border-radius: 8px;
    }
    /* 讓 Tab 標籤更明顯 */
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.1rem;
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
                try:
                    name = twstock.codes[code].name
                except:
                    name = code
                results.append(f"{code} {name}")
        return results
    except Exception as e:
        st.error(f"Sheet 連線錯誤: {str(e)}")
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
    except Exception as e:
        return None

def get_company_info_safe(ticker):
    try: return yf.Ticker(ticker + ".TW").info
    except: return {} 

def get_financial_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        return stock.income_stmt, stock.balance_sheet, stock.cashflow
    except:
        return None, None, None

# --- 4. AI 分析引擎 ---
def generate_ai_analysis(mode, ticker_full_name, df=None, info=None, financials=None, api_key=None):
    if not api_key: return "⚠️ 請先設定 Gemini API Key。"

    parts = ticker_full_name.split(" ")
    ticker_code = parts[0]
    stock_name = parts[1] if len(parts) > 1 else ticker_code

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        info_summary = info.get('longBusinessSummary', 'Yahoo 資料暫缺') if info else 'Yahoo 資料暫缺'
        pe = info.get('trailingPE', 'N/A') if info else 'N/A'

        if mode == "technical":
            last = df.iloc[-1]
            rsi = last['RSI_14'] if 'RSI_14' in df.columns else 0
            mfi = last['MFI_14'] if 'MFI_14' in df.columns else 0
            bias = last['BIAS_20'] if 'BIAS_20' in df.columns else 0
            
            prompt = f"""
            你是一位量化交易員。請分析 {stock_name} ({ticker_code}) 技術面：
            [數據] 收盤:{last['Close']:.1f}, RSI:{rsi:.1f}, MFI:{mfi:.1f}, 乖離率:{bias:.2f}%
            [任務] 1.評分(1-10) 2.解讀資金流向(MFI)與背離 3.短線操作建議(進場/停損/停利)
            """
            
        elif mode == "fundamental":
            inc_str = financials[0].iloc[:, :2].to_markdown() if financials and financials[0] is not None else "無"
            bal_str = financials[1].iloc[:, :2].to_markdown() if financials and financials[1] is not None else "無"
            
            prompt = f"""
            你是一位基本面分析師。請分析：**{stock_name} ({ticker_code})**。
            [財報數據] 損益表:\n{inc_str}\n\n資產負債表:\n{bal_str}
            [參考] PE: {pe}
            [任務] 1.公司產業地位(請自行補全) 2.獲利能力診斷 3.財務體質(負債/現金) 4.投資評級(買進/持有/賣出)
            """

        with st.spinner(f'♊ Gemini 正在分析 {stock_name}...'):
            response = model.generate_content(prompt)
            return response.text

    except Exception as e:
        return f"❌ AI 連線失敗: {str(e)}"

# --- 5. 側邊欄邏輯 (混合查詢修復版) ---
with st.sidebar:
    st.title("🦅 Sniper Pro V10.1")
    if st.button("🔄 刷新數據", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    if "GEMINI_API_KEY" in st.secrets:
        gemini_key = st.secrets["GEMINI_API_KEY"]
    else:
        gemini_key = st.text_input("Gemini API Key", type="password")

    st.markdown("---")
    
    # 🔥 UI 優化：手動輸入與列表並存
    st.subheader("🔍 股票查詢")
    manual_input = st.text_input("輸入代號 (留空則使用庫存清單)", placeholder="例如 2330")
    
    st.subheader("📂 庫存監控")
    ticker_list = get_positions()
    
    # 這裡做了修改：無論有沒有輸入，Radio Button 都會顯示
    # 這樣列表就不會消失了
    selected_option = None
    if ticker_list:
        selected_option = st.radio("庫存列表", ticker_list, label_visibility="collapsed")
    else:
        st.info("目前無庫存")

    # 決定最終代號
    final_ticker_code = None
    final_ticker_name = None

    if manual_input:
        # 有輸入字，優先使用手動輸入
        clean_code = manual_input.strip()
        final_ticker_code = clean_code
        try:
            name = twstock.codes[clean_code].name
        except:
            name = clean_code
        final_ticker_name = f"{clean_code} {name}"
    elif selected_option:
        # 沒輸入字，使用選單
        final_ticker_code = selected_option.split(" ")[0]
        final_ticker_name = selected_option
    else:
        # 什麼都沒有
        final_ticker_code = "2330"
        final_ticker_name = "2330 台積電 (測試)"

# --- 6. 主畫面邏輯 ---
if final_ticker_code:
    # Session State 初始化
    if 'current_ticker' not in st.session_state:
        st.session_state.current_ticker = ""
        st.session_state.tech_report = None
        st.session_state.fund_report = None
        st.session_state.df = None
        st.session_state.info = None
        st.session_state.financials = None

    # 切換股票時重置
    if st.session_state.current_ticker != final_ticker_code:
        st.session_state.current_ticker = final_ticker_code
        st.session_state.tech_report = None
        st.session_state.fund_report = None
        st.session_state.df = None
        st.session_state.info = None
        st.session_state.financials = None # 清空財報
        
        with st.spinner('正在載入數據...'):
            st.session_state.df = get_technical_data(final_ticker_code)
            st.session_state.info = get_company_info_safe(final_ticker_code)

    st.header(f"📊 {final_ticker_name}")

    if st.session_state.df is None:
        st.error("❌ 無法抓取資料，請確認代號正確。")
    else:
        df = st.session_state.df
        info = st.session_state.info
        last = df.iloc[-1]
        
        c1, c2, c3, c4, c5 = st.columns(5)
        def safe_get(col, fmt="{:.1f}"):
            if col in df.columns and not pd.isna(last[col]): return fmt.format(last[col])
            return "N/A"

        pct = ((last['Close'] - df['Close'].iloc[-2])/df['Close'].iloc[-2])*100
        c1.metric("現價", f"{last['Close']:.1f}", f"{pct:.2f}%")
        c2.metric("MFI", safe_get('MFI_14'))
        c3.metric("乖離率", safe_get('BIAS_20', "{:.2f}%"))
        pe_val = info.get('trailingPE', 'N/A') if info else 'N/A'
        c4.metric("本益比", f"{pe_val}")
        c5.metric("RSI", safe_get('RSI_14'))

        st.markdown("---")

        tabs = st.tabs(["📈 K線/籌碼", "🌊 進階指標", "🤖 技術 AI", "💰 財報 AI"])

        with tabs[0]:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='#FFA500'), name='月線'), row=1, col=1)
            if 'BBU_20_2.0' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot'), name='上軌'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot'), name='下軌'), row=1, col=1)
            if 'OBV' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV', line=dict(color='cyan')), row=2, col=1)
            fig.update_layout(height=550, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("MFI & RSI")
                fig_mfi = go.Figure()
                if 'MFI_14' in df.columns: fig_mfi.add_trace(go.Scatter(x=df.index, y=df['MFI_14'], name='MFI', line=dict(color='#00E676')))
                if 'RSI_14' in df.columns: fig_mfi.add_trace(go.Scatter(x=df.index, y=df['RSI_14'], name='RSI', line=dict(color='#FF5252')))
                fig_mfi.add_hline(y=80, line_dash="dot", line_color="gray")
                fig_mfi.add_hline(y=20, line_dash="dot", line_color="gray")
                fig_mfi.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_mfi, use_container_width=True)
            with col2:
                st.subheader("BIAS & MACD")
                fig_bias = make_subplots(rows=2, cols=1, shared_xaxes=True)
                if 'BIAS_20' in df.columns: fig_bias.add_trace(go.Bar(x=df.index, y=df['BIAS_20'], name='乖離率', marker_color='#AB47BC'), row=1, col=1)
                if 'MACDh_12_26_9' in df.columns: fig_bias.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], name='MACD', marker_color='#29B6F6'), row=2, col=1)
                fig_bias.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), showlegend=False)
                st.plotly_chart(fig_bias, use_container_width=True)

        # Tab 3: 技術 AI (優化跳頁問題)
        with tabs[2]:
            st.markdown("### 🤖 技術面診斷")
            if st.session_state.tech_report:
                st.markdown(st.session_state.tech_report)
                if st.button("🔄 重新分析 (技術)", key="btn_tech_retry"):
                    st.session_state.tech_report = generate_ai_analysis("technical", final_ticker_name, df=df, info=info, api_key=gemini_key)
                    st.rerun()
            else:
                if st.button("✨ 啟動技術分析", key="btn_tech"):
                    report = generate_ai_analysis("technical", final_ticker_name, df=df, info=info, api_key=gemini_key)
                    st.session_state.tech_report = report
                    st.rerun() # 寫入後立刻刷新，確保 UI 同步

        # Tab 4: 財報 AI
        with tabs[3]:
            st.markdown(f"### 💰 {final_ticker_name} 財報體質診斷")
            if st.session_state.fund_report:
                st.markdown(st.session_state.fund_report)
                if st.button("🔄 重新分析 (財報)", key="btn_fund_retry"):
                    inc, bal, cash = get_financial_data(final_ticker_code)
                    st.session_state.financials = (inc, bal, cash)
                    st.session_state.fund_report = generate_ai_analysis("fundamental", final_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                    st.rerun()
            else:
                st.info("💡 下載財報並分析 (AI 將自動補全公司背景)")
                if st.button("📥 下載財報並分析", key="btn_fund"):
                    if not st.session_state.financials:
                        with st.spinner("連線 Yahoo 財報資料庫..."):
                            inc, bal, cash = get_financial_data(final_ticker_code)
                            st.session_state.financials = (inc, bal, cash)
                    
                    report = generate_ai_analysis("fundamental", final_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                    st.session_state.fund_report = report
                    st.rerun()
