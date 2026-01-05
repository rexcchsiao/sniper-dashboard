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
import google.generativeai as genai # 👈 Google AI 核心庫

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper Pro (Gemini Edition)",
    page_icon="♊", # 換成 Gemini 的 Logo 意象
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
        background-color: #4285F4; /* Google Blue */
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
        st.error(f"連線錯誤: {str(e)}")
        return []

# --- 3. 數據核心 ---
def get_full_data(ticker):
    stock = yf.Ticker(ticker + ".TW")
    df = stock.history(period="1y")
    if df.empty: return None, None

    # 計算指標
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    stoch = df.ta.stoch(k=9, d=3)
    df = pd.concat([df, stoch], axis=1)
    df.ta.rsi(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.obv(append=True)

    return df, stock.info

# --- 4. Gemini AI 報告生成引擎 (V6.0) ---
def generate_gemini_report(ticker, df, info, api_key=None):
    # 準備數據摘要
    last_close = df['Close'].iloc[-1]
    change_pct = ((last_close - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
    rsi = df['RSI_14'].iloc[-1]
    macd_hist = df['MACDh_12_26_9'].iloc[-1]
    k_val = df['STOCHk_9_3_3'].iloc[-1]
    d_val = df['STOCHd_9_3_3'].iloc[-1]
    vol_ratio = df['Volume'].iloc[-1] / df['Volume'].iloc[-5:].mean()
    
    # A. 呼叫 Gemini API (如果 Key 存在)
    if api_key:
        try:
            # 設定 API
            genai.configure(api_key=api_key)
            
            # 使用 Gemini 1.5 Flash (速度快、免費額度高)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            prompt = f"""
            你是一位華爾街等級的台股分析師。請根據以下即時數據，為股票代號 {ticker} 撰寫一份精簡但犀利的分析報告。
            請使用 Markdown 格式，並包含表情符號。
            
            [即時數據]
            - 收盤價: {last_close:.1f} (漲跌幅 {change_pct:.2f}%)
            - RSI(14): {rsi:.1f} (強弱指標)
            - MACD柱狀體: {macd_hist:.2f} (趨勢動能)
            - KD值: K={k_val:.1f}, D={d_val:.1f}
            - 量能倍數: {vol_ratio:.2f} (今日量/5日均量)
            - 公司簡介: {info.get('longBusinessSummary', '無')}
            
            [報告要求]
            1. 第一段：用一句話給出「買進/觀望/賣出」的明確評級。
            2. 第二段：技術面分析 (請解讀指標背後的意義，不要只列數字)。
            3. 第三段：量價結構與籌碼解讀。
            4. 第四段：給出具體的操作區間 (支撐位/壓力位預估)。
            """
            
            with st.spinner('♊ Gemini 正在思考中...'):
                response = model.generate_content(prompt)
                return response.text
                
        except Exception as e:
            return f"Gemini 連線失敗: {e} (將切換回備用模式)"

    # B. 備用專家系統 (無 Key 時使用)
    trend_str = "多頭排列" if last_close > df['Close'].rolling(20).mean().iloc[-1] else "弱勢整理"
    return f"""
    ### 🤖 系統自動診斷 (未啟用 Gemini)
    
    * **趨勢:** {trend_str}
    * **RSI:** {rsi:.1f}
    * **MACD:** {macd_hist:.2f}
    
    *(請在側邊欄輸入 Gemini API Key 以解鎖完整 AI 分析功能)*
    """

# --- 5. 側邊欄 ---
with st.sidebar:
    st.title("♊ Sniper Pro")
    if st.button("🔄 刷新數據"):
        st.cache_data.clear()
        st.rerun()
    
    # Gemini Key 輸入框
    gemini_key = st.text_input("Gemini API Key (選填)", type="password", help="填入後啟用 Gemini 1.5 Flash 模型")
    
    ticker_list = get_positions()
    if ticker_list:
        selected_ticker = st.selectbox("📂 庫存監控", ticker_list)
    else:
        st.warning("無庫存，測試模式")
        selected_ticker = st.text_input("輸入代號", "2330")

# --- 6. 主畫面 ---
if selected_ticker:
    if 'data_fetched' not in st.session_state:
        st.session_state.data_fetched = False

    if st.session_state.get('current_ticker') != selected_ticker:
        st.session_state.data_fetched = False
        st.session_state.current_ticker = selected_ticker

    st.header(f"📊 {selected_ticker} 戰情中心 (Gemini Powered)")
    
    if not st.session_state.data_fetched:
        with st.spinner('正在載入數據...'):
            df, info = get_full_data(selected_ticker)
            if df is not None:
                st.session_state.df = df
                st.session_state.info = info
                st.session_state.data_fetched = True
            else:
                st.error("查無資料")

    if st.session_state.data_fetched:
        df = st.session_state.df
        info = st.session_state.info
        
        last = df['Close'].iloc[-1]
        prev = df['Close'].iloc[-2]
        pct = ((last - prev)/prev)*100
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現價", f"{last:.1f}", f"{pct:.2f}%")
        c2.metric("MACD", f"{df['MACDh_12_26_9'].iloc[-1]:.2f}")
        c3.metric("KD", f"{df['STOCHk_9_3_3'].iloc[-1]:.0f}/{df['STOCHd_9_3_3'].iloc[-1]:.0f}")
        c4.metric("RSI", f"{df['RSI_14'].iloc[-1]:.1f}")

        st.markdown("---")
        
        tabs = st.tabs(["📈 K線/籌碼", "🌊 指標", "♊ Gemini 報告", "📋 基本面"])

        with tabs[0]:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='#FFA500'), name='月線'), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='量', marker_color=['red' if o<c else 'green' for o,c in zip(df['Open'], df['Close'])]), row=2, col=1)
            fig.update_layout(height=550, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
            c_m, c_k = st.columns(2)
            with c_m:
                st.subheader("MACD")
                fig_m = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                fig_m.add_trace(go.Scatter(x=df.index, y=df['MACD_12_26_9'], name='DIF'), row=1, col=1)
                fig_m.add_trace(go.Scatter(x=df.index, y=df['MACDs_12_26_9'], name='DEM'), row=1, col=1)
                fig_m.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], name='OSC'), row=2, col=1)
                fig_m.update_layout(height=350, template="plotly_dark", showlegend=False, margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig_m, use_container_width=True)
            with c_k:
                st.subheader("KD")
                fig_k = go.Figure()
                fig_k.add_trace(go.Scatter(x=df.index, y=df['STOCHk_9_3_3'], name='K'))
                fig_k.add_trace(go.Scatter(x=df.index, y=df['STOCHd_9_3_3'], name='D'))
                fig_k.update_layout(height=350, template="plotly_dark", showlegend=False, margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig_k, use_container_width=True)

        with tabs[2]:
            st.markdown("### ♊ Gemini 深度分析")
            if gemini_key:
                if st.button("✨ 呼叫 Gemini 立即分析"):
                    report = generate_gemini_report(selected_ticker, df, info, gemini_key)
                    st.markdown(report)
                else:
                    st.info("點擊按鈕，讓 Google Gemini 為您解讀盤勢。")
            else:
                st.warning("請先在左側輸入 Gemini API Key。")

        with tabs[3]:
            st.dataframe(pd.DataFrame({
                "項目": ["市值", "PE", "EPS", "殖利率"],
                "數值": [
                    f"{info.get('marketCap',0)/1e8:.1f}億",
                    f"{info.get('trailingPE','N/A')}",
                    f"{info.get('trailingEps','N/A')}",
                    f"{info.get('dividendYield',0)*100:.2f}%" if info.get('dividendYield') else "N/A"
                ]
            }), use_container_width=True)
            st.markdown(f"**簡介:** {info.get('longBusinessSummary','無')}")
