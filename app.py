import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import json

# --- 1. 頁面設定 ---
st.set_page_config(page_title="Sniper 戰情室", page_icon="🎯", layout="wide")

# CSS 美化
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    div[data-testid="metric-container"] { background-color: #262730; border: 1px solid #464B5C; padding: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet (增強容錯版) ---
@st.cache_data(ttl=60)
def get_positions():
    try:
        # 1. 讀取 Secrets 字串
        raw_json_str = st.secrets["G_SHEET_KEY"]
        
        # 2. 🔥 關鍵修正：清洗隱形控制字元
        # 很多時候複製貼上會把 \n 變成真正的換行，或者帶有 tab
        # 我們用 strict=False 讓 JSON 解析器放寬標準
        key_dict = json.loads(raw_json_str, strict=False)
        
        # 3. 再次檢查 private_key (雙重保險)
        # 確保私鑰格式正確，將多餘的脫逸字元修復
        if 'private_key' in key_dict:
             key_dict['private_key'] = key_dict['private_key'].replace('\\n', '\n')

        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)
        
        # 連線 Sheet
        sheet = client.open_by_url(st.secrets["SHEET_URL"]).worksheet('Sniper')
        
        # 讀取資料
        data = sheet.get_all_values()
        df = pd.DataFrame(data[1:], columns=data[0])
        
        # 過濾 "In Position"
        # ⚠️ 注意：如果你現在 Sheet 裡沒有 "In Position" 的股票
        # 下面這行會回傳空清單，導致你看到 "目前無庫存"
        # 為了測試，你可以暫時把過濾註解掉，看能不能印出所有股票
        # in_position_df = df[df['狀態'] == 'In Position'] 
        
        # --- 暫時改成回傳全部 (方便你確認連線成功) ---
        return df['代號'].astype(str).tolist() 
        
    except Exception as e:
        # 這裡會印出更詳細的錯誤，方便我們除錯
        st.error(f"Google Sheet 連線錯誤詳細資訊: {str(e)}")
        return []

# --- 3. 抓取股價資料 ---
def get_stock_data(ticker):
    stock = yf.Ticker(ticker + ".TW")
    df = stock.history(period="6mo")
    return df, stock.info

# --- 4. 側邊欄 ---
with st.sidebar:
    st.title("🔫 Sniper 戰情中心")
    ticker_list = get_positions()
    
    if ticker_list:
        selected_ticker = st.selectbox("📂 庫存監控", ticker_list)
    else:
        st.warning("目前無庫存 (In Position)")
        selected_ticker = st.text_input("或輸入代號查詢", "2330")

# --- 5. 主畫面 ---
if selected_ticker:
    st.header(f"📊 {selected_ticker} 分析儀表板")
    
    try:
        df, info = get_stock_data(selected_ticker)
        
        if df.empty:
            st.error("查無資料，請確認代號")
        else:
            # 指標區
            last_close = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            change = last_close - prev_close
            pct = (change / prev_close) * 100
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現價", f"{last_close:.1f}", f"{pct:.2f}%")
            c2.metric("成交量", f"{int(df['Volume'].iloc[-1]/1000)} 張")
            c3.metric("最高", f"{df['High'].iloc[-1]:.1f}")
            c4.metric("最低", f"{df['Low'].iloc[-1]:.1f}")

            # K線圖
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            df['MA20'] = df['Close'].rolling(window=20).mean()
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange'), name='月線'), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='量'), row=2, col=1)
            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
    except Exception as e:

        st.error(f"發生錯誤: {e}")
