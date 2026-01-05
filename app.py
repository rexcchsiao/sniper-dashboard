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

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper Pro V8 (AI Financials)",
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
        background-color: #00B8D4; /* Cyberpunk Blue */
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet (維持不變) ---
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
        st.error(f"連線錯誤: {str(e)}")
        return []

# --- 3. 技術數據核心 (新增 MFI, Bias, W%R) ---
def get_technical_data(ticker):
    stock = yf.Ticker(ticker + ".TW")
    df = stock.history(period="1y")
    if df.empty: return None, None

    # 1. 基礎指標
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.stoch(k=9, d=3, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.obv(append=True)

    # 2. 🔥 新增進階指標
    # MFI (資金流量指標)
    df.ta.mfi(length=14, append=True)
    
    # BIAS (乖離率 - 以20日線為基準)
    # pandas_ta 的 bias 計算方式可能略有不同，我們手動算最準
    ma20 = df['Close'].rolling(20).mean()
    df['BIAS_20'] = ((df['Close'] - ma20) / ma20) * 100
    
    # Williams %R (威廉指標)
    df.ta.willr(length=14, append=True)

    return df, stock.info

# --- 4. 財報數據核心 (按需加載) ---
def get_financial_data(ticker):
    stock = yf.Ticker(ticker + ".TW")
    # 抓取最新的年度/季度報表
    income = stock.income_stmt
    balance = stock.balance_sheet
    cashflow = stock.cashflow
    return income, balance, cashflow

# --- 5. AI 分析引擎 (技術 + 財報) ---
def generate_ai_analysis(mode, ticker, df=None, info=None, financials=None, api_key=None):
    if not api_key:
        return "⚠️ 請先設定 Gemini API Key 以啟用 AI 分析。"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash') # 使用最新穩定版
        
        if mode == "technical":
            # 準備技術數據
            last = df.iloc[-1]
            prompt = f"""
            你是一位頂尖的量化交易員。請分析 {ticker} 的技術面數據：
            
            [數據]
            - 收盤: {last['Close']:.1f}
            - RSI(14): {last['RSI_14']:.1f} (強弱)
            - MFI(14): {last['MFI_14']:.1f} (資金流向)
            - 乖離率(20): {last['BIAS_20']:.2f}% (正乖離過大易回檔，負乖離易反彈)
            - MACD柱狀: {last['MACDh_12_26_9']:.2f}
            - KD: K={last['STOCHk_9_3_3']:.1f}, D={last['STOCHd_9_3_3']:.1f}
            
            [任務]
            1. 給出「技術面評分」(1-10分)。
            2. 解讀 MFI 與 RSI 是否出現背離或過熱。
            3. 分析乖離率，判斷是否需要修正。
            4. 給出短線操作建議 (進場/停損/停利點)。
            """
            
        elif mode == "fundamental":
            # 準備財報數據 (簡化成 Markdown 表格字串傳給 AI)
            inc_str = financials[0].iloc[:, :2].to_markdown() if financials[0] is not None else "無"
            bal_str = financials[1].iloc[:, :2].to_markdown() if financials[1] is not None else "無"
            
            prompt = f"""
            你是一位巴菲特學派的基本面分析師。請分析 {ticker} 的最新財報數據：
            
            [公司簡介] {info.get('longBusinessSummary', '無')}
            [損益表摘要] \n{inc_str}
            [資產負債表摘要] \n{bal_str}
            [關鍵指標] PE={info.get('trailingPE')}, EPS={info.get('trailingEps')}, 殖利率={info.get('dividendYield')}
            
            [任務]
            1. 分析營收與獲利趨勢 (成長或衰退)。
            2. 評估財務體質 (負債比、現金流狀況)。
            3. 計算簡單的合理估值 (若資料不足請給出估算區間)。
            4. 給出「長線投資評級」 (強烈買進/持有/賣出)。
            """

        with st.spinner(f'♊ Gemini 正在進行深度{ "技術" if mode=="technical" else "財報" }分析...'):
            response = model.generate_content(prompt)
            return response.text

    except Exception as e:
        return f"❌ AI 連線失敗: {str(e)}"

# --- 6. 側邊欄 ---
with st.sidebar:
    st.title("🦅 Sniper Pro V8")
    if st.button("🔄 刷新數據", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    if "GEMINI_API_KEY" in st.secrets:
        gemini_key = st.secrets["GEMINI_API_KEY"]
        st.success("✅ Gemini AI Ready")
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
    # 狀態管理
    if 'data_fetched' not in st.session_state:
        st.session_state.data_fetched = False

    if st.session_state.get('current_ticker') != selected_ticker:
        st.session_state.data_fetched = False
        st.session_state.current_ticker = selected_ticker
        st.session_state.financials = None # 清空舊財報

    st.header(f"📊 {selected_ticker} 全方位戰情中心")
    
    if not st.session_state.data_fetched:
        with st.spinner('正在載入技術指標...'):
            df, info = get_technical_data(selected_ticker)
            if df is not None:
                st.session_state.df = df
                st.session_state.info = info
                st.session_state.data_fetched = True
            else:
                st.error("查無資料")

    if st.session_state.data_fetched:
        df = st.session_state.df
        info = st.session_state.info
        last = df.iloc[-1]
        
        # 頂部儀表板 (新增 乖離率 & MFI)
        c1, c2, c3, c4, c5 = st.columns(5)
        pct = ((last['Close'] - df['Close'].iloc[-2])/df['Close'].iloc[-2])*100
        c1.metric("現價", f"{last['Close']:.1f}", f"{pct:.2f}%")
        c2.metric("MFI (資金)", f"{last['MFI_14']:.1f}", help="資金流量指標，>80超買，<20超賣")
        c3.metric("乖離率 (20)", f"{last['BIAS_20']:.2f}%", help="股價與月線的距離，過大易回檔")
        c4.metric("KD (K/D)", f"{last['STOCHk_9_3_3']:.0f}/{last['STOCHd_9_3_3']:.0f}")
        c5.metric("RSI", f"{last['RSI_14']:.1f}")

        st.markdown("---")
        
        # 多分頁架構
        tabs = st.tabs(["📈 K線/籌碼", "🌊 進階指標 (MFI/Bias)", "🤖 技術 AI", "💰 財報 AI"])

        # Tab 1: 主圖
        with tabs[0]:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='#FFA500'), name='月線'), row=1, col=1)
            # 布林通道
            fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot'), name='上軌'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot'), name='下軌'), row=1, col=1)
            # OBV
            fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV能量潮', line=dict(color='cyan')), row=2, col=1)
            fig.update_layout(height=550, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)

        # Tab 2: 進階指標群 (新增)
        with tabs[1]:
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("MFI 資金流量 & RSI")
                fig_mfi = go.Figure()
                fig_mfi.add_trace(go.Scatter(x=df.index, y=df['MFI_14'], name='MFI', line=dict(color='#00E676')))
                fig_mfi.add_trace(go.Scatter(x=df.index, y=df['RSI_14'], name='RSI', line=dict(color='#FF5252')))
                fig_mfi.add_hline(y=80, line_dash="dot", line_color="gray")
                fig_mfi.add_hline(y=20, line_dash="dot", line_color="gray")
                fig_mfi.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_mfi, use_container_width=True)

            with col2:
                st.subheader("BIAS 乖離率 & MACD")
                fig_bias = make_subplots(rows=2, cols=1, shared_xaxes=True)
                fig_bias.add_trace(go.Bar(x=df.index, y=df['BIAS_20'], name='乖離率(%)', marker_color='#AB47BC'), row=1, col=1)
                fig_bias.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], name='MACD柱', marker_color='#29B6F6'), row=2, col=1)
                fig_bias.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), showlegend=False)
                st.plotly_chart(fig_bias, use_container_width=True)

        # Tab 3: 技術面 AI
        with tabs[2]:
            st.markdown("### 🤖 技術面診斷 (Gemini)")
            if st.button("✨ 啟動技術分析", key="btn_tech"):
                report = generate_ai_analysis("technical", selected_ticker, df=df, api_key=gemini_key)
                st.markdown(report)

        # Tab 4: 財報面 AI (新增)
        with tabs[3]:
            st.markdown("### 💰 財報體質診斷 (Gemini)")
            st.info("💡 點擊按鈕後，將下載最新財報並由 AI 進行解讀。")
            
            if st.button("📥 下載財報並分析", key="btn_fund"):
                if not st.session_state.financials:
                    with st.spinner("正在向 Yahoo 請求財務數據..."):
                        inc, bal, cash = get_financial_data(selected_ticker)
                        st.session_state.financials = (inc, bal, cash)
                
                # 生成報告
                report = generate_ai_analysis("fundamental", selected_ticker, info=info, financials=st.session_state.financials, api_key=gemini_key)
                st.markdown(report)
                
                # 顯示原始數據 (折疊)
                with st.expander("查看原始財報數據"):
                    st.write("損益表 (Income Statement)", st.session_state.financials[0])
                    st.write("資產負債表 (Balance Sheet)", st.session_state.financials[1])
