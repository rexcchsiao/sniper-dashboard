import streamlit as st
import pandas as pd
import pandas_ta as ta  # 技術指標套件
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper 旗艦戰情室",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 美化 (深色卡片風)
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    div[data-testid="metric-container"] { 
        background-color: #262730; 
        border: 1px solid #464B5C; 
        padding: 10px; 
        border-radius: 5px; 
        transition: transform 0.2s;
    }
    div[data-testid="metric-container"]:hover {
        transform: scale(1.02);
        border-color: #00ADB5;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet (含 JSON 修復 & 過濾) ---
@st.cache_data(ttl=60) # 預設快取 60 秒
def get_positions(force_refresh=False):
    try:
        # 1. JSON 清洗邏輯
        raw_json_str = st.secrets["G_SHEET_KEY"]
        
        # 暴力修復換行符號 (防止 Invalid control character)
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
        
        # 🔍 關鍵過濾：只抓 "In Position"
        # 使用 strip() 去除空白，並轉大寫比對，增加容錯率
        df['狀態'] = df['狀態'].astype(str).str.strip()
        in_position_df = df[df['狀態'] == 'In Position']
        
        # 為了除錯：如果真的沒庫存，可以暫時回傳全部，但正式版建議只回傳庫存
        if in_position_df.empty:
            return [] # 真的沒庫存就回傳空
            # return df['代號'].astype(str).tolist() # (測試用：回傳全部)
            
        return in_position_df['代號'].astype(str).tolist()
        
    except Exception as e:
        st.error(f"連線錯誤: {str(e)}")
        return []

# --- 3. 抓取股價與計算指標 ---
def get_stock_data(ticker):
    stock = yf.Ticker(ticker + ".TW")
    df = stock.history(period="1y") # 抓一年份以計算長天期均線
    
    # 計算技術指標 (pandas_ta)
    df.ta.rsi(length=14, append=True)   # RSI
    df.ta.macd(append=True)             # MACD
    df.ta.bbands(length=20, std=2, append=True) # 布林通道
    
    # 計算 KD 值 (Stoch)
    k_d = df.ta.stoch(append=True)
    
    return df, stock.info

# --- 4. AI 投顧邏輯 (規則基礎) ---
def generate_ai_report(ticker, df, info):
    last_close = df['Close'].iloc[-1]
    rsi = df['RSI_14'].iloc[-1]
    
    # 判斷趨勢
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    trend = "多頭強勢 🔥" if last_close > ma20 else "回檔整理 ❄️"
    
    # 判斷策略
    action = "觀望"
    reason = "數據中性"
    if rsi > 70:
        action = "注意停利"
        reason = "RSI 過熱 (>70)，隨時可能拉回"
    elif rsi < 30:
        action = "超跌反彈"
        reason = "RSI 超賣 (<30)，有機會反彈"
    elif last_close > ma20 and df['Volume'].iloc[-1] > df['Volume'].iloc[-5:].mean():
        action = "續抱/加碼"
        reason = "站上月線且量增，攻擊訊號明確"

    report = f"""
    ### 🤖 Sniper AI 診斷報告：{ticker}
    
    **1. 趨勢判讀**
    * 目前股價 **{last_close}**，呈現 **{trend}** 格局。
    * **RSI 指標：** {rsi:.1f} ({reason})。
    
    **2. 籌碼與基本面**
    * **本益比 (PE)：** {info.get('trailingPE', 'N/A')} (同業比較：{ '偏低' if info.get('trailingPE', 0) < 15 else '合理/偏高' })
    * **殖利率：** {info.get('dividendYield', 0)*100:.2f}%
    
    **3. 操作建議**
    * **指令：** **{action}**
    * **理由：** {reason}。請嚴守停損，切勿凹單。
    """
    return report

# --- 5. 側邊欄與刷新機制 ---
with st.sidebar:
    st.title("🎯 Sniper 戰情室")
    
    # 🔥 刷新按鈕
    if st.button("🔄 刷新最新數據", use_container_width=True):
        st.cache_data.clear() # 清除快取
        st.rerun()            # 重新執行
    
    ticker_list = get_positions()
    
    if ticker_list:
        st.success(f"目前持有 {len(ticker_list)} 檔標的")
        selected_ticker = st.selectbox("📂 選擇庫存", ticker_list)
    else:
        st.warning("目前無庫存 (In Position)")
        st.info("系統正持續監控 Google Sheet...")
        selected_ticker = None

# --- 6. 主畫面儀表板 ---
if selected_ticker:
    try:
        df, info = get_stock_data(selected_ticker)
        
        # 頂部大數據
        st.header(f"📊 {selected_ticker} {info.get('longName', '')}")
        
        last_close = df['Close'].iloc[-1]
        change = last_close - df['Close'].iloc[-2]
        pct = (change / df['Close'].iloc[-2]) * 100
        color = "normal"
        if change > 0: color = "off" # Streamlit metric color logic

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現價", f"{last_close:.1f}", f"{change:.1f} ({pct:.2f}%)")
        c2.metric("成交量", f"{int(df['Volume'].iloc[-1]/1000)} 張")
        c3.metric("RSI (14)", f"{df['RSI_14'].iloc[-1]:.1f}")
        c4.metric("布林帶寬", f"{((df['BBU_20_2.0'].iloc[-1] - df['BBL_20_2.0'].iloc[-1])/df['BBM_20_2.0'].iloc[-1]*100):.1f}%")

        st.markdown("---")

        # 多頁籤功能區
        tab1, tab2, tab3, tab4 = st.tabs(["📈 K線/籌碼", "🤖 AI 投顧", "📋 基本面", "🌊 技術指標"])

        with tab1:
            # 互動式 K 線圖 + 月線 + 成交量
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='orange', width=1), name='月線'), row=1, col=1)
            # 布林通道
            fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', width=1, dash='dot'), name='上軌'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', width=1, dash='dot'), name='下軌'), row=1, col=1)
            
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=['red' if o < c else 'green' for o, c in zip(df['Open'], df['Close'])]), row=2, col=1)
            
            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            st.markdown(generate_ai_report(selected_ticker, df, info))
            st.info("💡 提示：此報告為基於技術指標的自動化分析，僅供輔助參考。")

        with tab3:
            col_a, col_b = st.columns(2)
            with col_a:
                st.write("**財務數據**")
                st.dataframe(pd.DataFrame({
                    "項目": ["市值", "本益比", "EPS", "殖利率", "Beta值"],
                    "數值": [
                        f"{info.get('marketCap', 0)/100000000:.1f} 億",
                        info.get('trailingPE', 'N/A'),
                        info.get('trailingEps', 'N/A'),
                        f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else "N/A",
                        info.get('beta', 'N/A')
                    ]
                }))
            with col_b:
                st.write("**公司簡介**")
                st.write(info.get('longBusinessSummary', '暫無資料'))

        with tab4:
            st.subheader("進階技術指標")
            # MACD 圖表
            fig_macd = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
            fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_12_26_9'], line=dict(color='#00ADB5'), name='MACD'), row=1, col=1)
            fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACDs_12_26_9'], line=dict(color='#FF2E63'), name='Signal'), row=1, col=1)
            fig_macd.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], name='Hist'), row=2, col=1)
            fig_macd.update_layout(height=400, template="plotly_dark", title_text="MACD")
            st.plotly_chart(fig_macd, use_container_width=True)

    except Exception as e:
        st.error(f"資料讀取失敗: {e}")
