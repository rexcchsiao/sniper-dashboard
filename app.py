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

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper 戰情室 (V4.0)",
    page_icon="🎯",
    layout="wide"
)

# CSS 美化
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    div[data-testid="metric-container"] { 
        background-color: #262730; 
        border: 1px solid #464B5C; 
        padding: 10px; 
        border-radius: 5px; 
    }
    /* 讓按鈕顯眼一點 */
    div.stButton > button {
        width: 100%;
        background-color: #00ADB5;
        color: white;
        border: none;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet (維持 V3.0 不變) ---
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

# --- 3. 股價與指標 (輕量級) ---
# 只抓 K 線，不抓 info，減少負擔
def get_price_history(ticker):
    stock = yf.Ticker(ticker + ".TW")
    # 這裡只抓 history，通常不會被鎖
    df = stock.history(period="1y")
    
    if df.empty: return None
    
    # 計算技術指標
    df.ta.rsi(length=14, append=True)
    df.ta.macd(append=True)
    df.ta.bbands(length=20, std=2, append=True)
    return df

# --- 4. 基本面資料 (重量級 - 需手動觸發) ---
def get_fundamental_info(ticker):
    stock = yf.Ticker(ticker + ".TW")
    return stock.info

# --- 5. AI 報告生成 ---
def generate_ai_report(ticker, df, info=None):
    last_close = df['Close'].iloc[-1]
    rsi = df['RSI_14'].iloc[-1]
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    trend = "多頭強勢 🔥" if last_close > ma20 else "回檔整理 ❄️"
    
    action = "觀望"
    reason = "數據中性"
    
    if rsi > 70:
        action = "注意停利"
        reason = "RSI 過熱 (>70)"
    elif rsi < 30:
        action = "超跌反彈"
        reason = "RSI 超賣 (<30)"
    elif last_close > ma20 and df['Volume'].iloc[-1] > df['Volume'].iloc[-5:].mean():
        action = "續抱/加碼"
        reason = "站上月線且量增"

    # 如果有 info (基本面)，加進報告
    pe_info = ""
    if info:
        pe_info = f"\n**3. 基本面補充**\n* **本益比:** {info.get('trailingPE', 'N/A')}\n* **殖利率:** {info.get('dividendYield', 0)*100:.2f}%"

    report = f"""
    ### 🤖 Sniper AI 診斷: {ticker}
    **1. 趨勢:** {trend} (現價 {last_close:.1f})
    **2. 策略:** **{action}** ({reason})
    {pe_info}
    """
    return report

# --- 6. 側邊欄 ---
with st.sidebar:
    st.title("🎯 Sniper 戰情室")
    if st.button("🔄 刷新庫存清單"):
        st.cache_data.clear()
        st.rerun()
        
    ticker_list = get_positions()
    
    if ticker_list:
        selected_ticker = st.selectbox("📂 選擇庫存", ticker_list)
    else:
        st.warning("無庫存，測試模式")
        selected_ticker = st.text_input("輸入代號", "2330")

# --- 7. 主畫面 (按需加載邏輯) ---
if selected_ticker:
    
    # 初始化 Session State (用來記憶按鈕狀態)
    if 'current_ticker' not in st.session_state:
        st.session_state.current_ticker = selected_ticker
        st.session_state.show_fundamentals = False
        st.session_state.show_ai = False
    
    # 如果切換了股票，重置所有狀態
    if st.session_state.current_ticker != selected_ticker:
        st.session_state.current_ticker = selected_ticker
        st.session_state.show_fundamentals = False
        st.session_state.show_ai = False
        st.session_state.info_data = None # 清空舊資料

    # 1. 先抓最基本的 K 線 (輕量)
    df = get_price_history(selected_ticker)
    
    if df is None:
        st.error("無法讀取股價資料，請稍後再試。")
    else:
        # Header 資訊
        st.header(f"📊 {selected_ticker} 技術看板")
        last_close = df['Close'].iloc[-1]
        change = last_close - df['Close'].iloc[-2]
        pct = (change / df['Close'].iloc[-2]) * 100
        
        c1, c2, c3 = st.columns(3)
        c1.metric("現價", f"{last_close:.1f}", f"{pct:.2f}%")
        c2.metric("成交量", f"{int(df['Volume'].iloc[-1]/1000)} 張")
        c3.metric("RSI (14)", f"{df['RSI_14'].iloc[-1]:.1f}")

        st.markdown("---")

        # 分頁區
        tab1, tab2, tab3 = st.tabs(["📈 K線圖 (預設)", "🤖 AI 診斷 (需請求)", "📋 基本面 (需請求)"])

        # Tab 1: K線圖 (預設顯示)
        with tab1:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='orange'), name='月線'), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='量'), row=2, col=1)
            fig.update_layout(height=500, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        # Tab 2: AI 報告 (按鈕觸發)
        with tab2:
            st.write("AI 運算需要消耗資源，請點擊下方按鈕啟動：")
            
            # 如果已經按過，就直接顯示，不用重跑
            if st.session_state.show_ai:
                # 這裡我們傳入 info=None (如果還沒抓基本面) 或是 session 裡的 info
                current_info = st.session_state.get('info_data', None)
                st.markdown(generate_ai_report(selected_ticker, df, current_info))
            else:
                if st.button("🚀 啟動 AI 運算"):
                    st.session_state.show_ai = True
                    st.rerun() # 重新執行以顯示結果

        # Tab 3: 基本面 (按鈕觸發 - 這是最容易被鎖的部分)
        with tab3:
            st.write("基本面數據 (本益比、殖利率) 需要向 Yahoo 發送額外請求：")
            
            if st.session_state.get('info_data'):
                # 顯示資料
                info = st.session_state.info_data
                col_a, col_b = st.columns(2)
                with col_a:
                    st.dataframe(pd.DataFrame({
                        "項目": ["本益比", "EPS", "殖利率", "Beta"],
                        "數值": [
                            info.get('trailingPE', 'N/A'),
                            info.get('trailingEps', 'N/A'),
                            f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else "N/A",
                            info.get('beta', 'N/A')
                        ]
                    }))
                with col_b:
                    st.info(info.get('longBusinessSummary', '無公司簡介'))
            else:
                if st.button("📥 下載基本面數據"):
                    with st.spinner('正在連線 Yahoo 資料庫...'):
                        # 這裡才真的去抓最容易被擋的 info
                        info_data = get_fundamental_info(selected_ticker)
                        st.session_state.info_data = info_data
                        st.session_state.show_fundamentals = True
                        st.rerun()
