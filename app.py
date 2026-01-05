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
import requests # 用來呼叫 OpenAI (如果有的話)

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper Pro 戰情室",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 美化 (仿專業看盤軟體)
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    /* 指標卡片優化 */
    div[data-testid="metric-container"] { 
        background-color: #1E2129; 
        border: 1px solid #363B4C; 
        padding: 15px; 
        border-radius: 8px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    /* Tab 樣式 */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        background-color: #262730;
        border-radius: 4px;
        padding: 0px 16px;
        color: #FAFAFA;
    }
    .stTabs [aria-selected="true"] {
        background-color: #00ADB5;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet (維持穩定版) ---
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

# --- 3. 數據核心 (含 MACD/KD) ---
def get_full_data(ticker):
    stock = yf.Ticker(ticker + ".TW")
    df = stock.history(period="1y")
    if df.empty: return None, None

    # --- 計算指標 ---
    # 1. MACD (12, 26, 9)
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    
    # 2. KD (9, 3) - Stochastic
    stoch = df.ta.stoch(k=9, d=3)
    df = pd.concat([df, stoch], axis=1)
    
    # 3. RSI (14)
    df.ta.rsi(length=14, append=True)
    
    # 4. 布林通道
    df.ta.bbands(length=20, std=2, append=True)
    
    # 5. OBV (能量潮) - 作為籌碼替代指標
    df.ta.obv(append=True)

    return df, stock.info

# --- 4. 真・AI 報告生成引擎 ---
def generate_pro_report(ticker, df, info, openai_key=None):
    # 準備數據摘要
    last_close = df['Close'].iloc[-1]
    change_pct = ((last_close - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
    rsi = df['RSI_14'].iloc[-1]
    macd_hist = df['MACDh_12_26_9'].iloc[-1]
    k_val = df['STOCHk_9_3_3'].iloc[-1]
    d_val = df['STOCHd_9_3_3'].iloc[-1]
    vol_ratio = df['Volume'].iloc[-1] / df['Volume'].iloc[-5:].mean()
    
    # A. 如果有 OpenAI Key -> 呼叫真 AI
    if openai_key:
        try:
            prompt = f"""
            你是一位專業的台股籌碼分析師。請根據以下數據，為股票代號 {ticker} 撰寫一份詳細的分析報告。
            語氣要專業、客觀，並模仿投顧報告的格式。
            
            [數據]
            - 收盤價: {last_close} (漲跌 {change_pct:.2f}%)
            - RSI(14): {rsi:.2f}
            - MACD柱狀體: {macd_hist:.2f} (正數為多頭，負數為空頭)
            - KD值: K={k_val:.2f}, D={d_val:.2f}
            - 量能比: {vol_ratio:.2f} (大於1代表量增)
            - 公司簡介: {info.get('longBusinessSummary', '無')}
            
            [報告結構]
            1. 🎯 AI 投資觀點 (一句話總結)
            2. 📈 技術面深度解析 (MACD, KD, RSI 綜合判斷)
            3. 💸 籌碼與量能分析 (解讀成交量變化隱含的主力動向)
            4. 🛡️ 操作建議 (進場、停損建議)
            """
            
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-3.5-turbo", # 或 gpt-4
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }
            res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content']
            else:
                return f"OpenAI 連線失敗: {res.text} (切換回專家系統模式)"
        except Exception as e:
            pass # 失敗就往下走，用專家系統

    # B. 專家系統模式 (Pseudo-AI) - 模仿截圖的詳細風格
    trend_str = "多頭排列" if last_close > df['Close'].rolling(20).mean().iloc[-1] else "弱勢整理"
    kd_signal = "黃金交叉" if k_val > d_val else "死亡交叉"
    macd_signal = "多方控盤" if macd_hist > 0 else "空方力道增強"
    vol_signal = "量能溫和放大，主力吸籌跡象" if vol_ratio > 1.2 else "量縮觀望，籌碼沉澱"
    
    report = f"""
    ### 🤖 AI 全方位診斷報告
    
    **好的，作為您的專屬 AI 分析師，我已針對 {ticker} 完成深度掃描。以下是截至 {datetime.date.today()} 的最新分析：**
    
    ---
    
    #### 1. 🎯 核心觀點
    目前股價位於 **{last_close}**，整體呈現 **{trend_str}** 格局。{vol_signal}。
    
    #### 2. 📈 技術指標詳細解讀
    * **MACD 動能：** 目前柱狀體為 **{macd_hist:.2f}**，顯示 **{macd_signal}**。若柱狀體持續翻紅，則波段攻擊力道可望延續。
    * **KD 隨機指標：** K值({k_val:.1f}) 與 D值({d_val:.1f}) 目前呈現 **{kd_signal}**。{ "留意短線過熱風險" if k_val > 80 else "位於低檔區，具反彈契機" if k_val < 20 else "處於中性區間，等待方向確認" }。
    * **RSI 相對強弱：** 數值為 **{rsi:.1f}**。{ "買盤力道強勁" if rsi > 60 else "賣壓沈重" if rsi < 40 else "多空拉鋸中" }。
    
    #### 3. 💸 籌碼與量能結構 (Volume Profile)
    * **量價關係：** 今日成交量為昨日的 **{vol_ratio:.1f} 倍**。
    * **主力動向解讀：** { "出現攻擊量，顯示主力有強烈作價意願。" if vol_ratio > 1.5 else "成交量萎縮，顯示市場籌碼惜售，主力可能正在洗盤。" if vol_ratio < 0.7 else "量價結構健康，換手積極。" }
    * **OBV 能量潮：** 累積能量{ "創新高，籌碼集中" if df['OBV'].iloc[-1] > df['OBV'].iloc[-5:].max() else "持平，等待表態" }。
    
    #### 4. 🛡️ AI 操作建議
    * **策略：** { "偏多操作 / 拉回找買點" if trend_str == "多頭排列" else "保守觀望 / 反彈減碼" }
    * **關鍵防守價：** 建議以月線 **{df['Close'].rolling(20).mean().iloc[-1]:.1f}** 作為多空分水嶺。
    
    *(註：本報告由 Sniper Expert System 生成，無 OpenAI Key 時自動啟用此模式)*
    """
    return report

# --- 5. 側邊欄 ---
with st.sidebar:
    st.title("🚀 Sniper Pro")
    if st.button("🔄 刷新數據"):
        st.cache_data.clear()
        st.rerun()
    
    # OpenAI Key 輸入框 (選填)
    openai_key = st.text_input("OpenAI API Key (選填)", type="password", help="填入可啟用真·AI生成報告，不填則使用專家系統")
    
    ticker_list = get_positions()
    if ticker_list:
        selected_ticker = st.selectbox("📂 庫存監控", ticker_list)
    else:
        st.warning("無庫存，測試模式")
        selected_ticker = st.text_input("輸入代號", "2330")

# --- 6. 主畫面 ---
if selected_ticker:
    # 狀態管理
    if 'data_fetched' not in st.session_state:
        st.session_state.data_fetched = False
        st.session_state.df = None
        st.session_state.info = None

    # 只在切換股票或按鈕時抓取
    if st.session_state.get('current_ticker') != selected_ticker:
        st.session_state.data_fetched = False
        st.session_state.current_ticker = selected_ticker

    # 頂部儀表板
    st.header(f"📊 {selected_ticker} 戰情中心")
    
    if not st.session_state.data_fetched:
        with st.spinner('正在載入全方位數據...'):
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
        
        # Metric Row
        last = df['Close'].iloc[-1]
        prev = df['Close'].iloc[-2]
        chg = last - prev
        pct = (chg/prev)*100
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現價", f"{last:.1f}", f"{pct:.2f}%")
        c2.metric("MACD", f"{df['MACDh_12_26_9'].iloc[-1]:.2f}", delta_color="normal")
        c3.metric("KD (K/D)", f"{df['STOCHk_9_3_3'].iloc[-1]:.0f} / {df['STOCHd_9_3_3'].iloc[-1]:.0f}")
        c4.metric("RSI", f"{df['RSI_14'].iloc[-1]:.1f}")

        st.markdown("---")
        
        # 仿截圖的多頁籤設計
        tabs = st.tabs(["📈 K線與籌碼", "🌊 MACD & KD", "🤖 AI 深度解讀", "📋 基本面數據"])

        # Tab 1: 主圖
        with tabs[0]:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
            # K線
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            # 均線
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='#FFA500', width=1), name='月線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(60).mean(), line=dict(color='#00FFFF', width=1), name='季線'), row=1, col=1)
            # 成交量
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='量', marker_color=['#FF5252' if o<c else '#00E676' for o,c in zip(df['Open'], df['Close'])]), row=2, col=1)
            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)

        # Tab 2: 指標
        with tabs[1]:
            col_macd, col_kd = st.columns(2)
            with col_macd:
                st.subheader("MACD 趨勢")
                fig_m = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                fig_m.add_trace(go.Scatter(x=df.index, y=df['MACD_12_26_9'], line=dict(color='#00ADB5'), name='DIF'), row=1, col=1)
                fig_m.add_trace(go.Scatter(x=df.index, y=df['MACDs_12_26_9'], line=dict(color='#FF2E63'), name='DEM'), row=1, col=1)
                fig_m.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], name='OSC'), row=2, col=1)
                fig_m.update_layout(height=400, template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_m, use_container_width=True)
            
            with col_kd:
                st.subheader("KD 隨機指標")
                fig_k = go.Figure()
                fig_k.add_trace(go.Scatter(x=df.index, y=df['STOCHk_9_3_3'], line=dict(color='#FFD700'), name='K'))
                fig_k.add_trace(go.Scatter(x=df.index, y=df['STOCHd_9_3_3'], line=dict(color='#B03060'), name='D'))
                fig_k.add_hline(y=80, line_dash="dot", line_color="gray")
                fig_k.add_hline(y=20, line_dash="dot", line_color="gray")
                fig_k.update_layout(height=400, template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_k, use_container_width=True)

        # Tab 3: AI 報告
        with tabs[2]:
            st.markdown("### 🧠 智能戰情分析")
            if st.button("⚡ 立即生成深度報告 (Live)"):
                with st.spinner("AI 正在分析大數據... (如使用 OpenAI Key 請稍候)"):
                    report = generate_pro_report(selected_ticker, df, info, openai_key)
                    st.markdown(report)
            else:
                st.info("點擊按鈕後，系統將整合技術面、籌碼面(量能)與基本面數據進行綜合診斷。")

        # Tab 4: 基本面
        with tabs[3]:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.dataframe(pd.DataFrame({
                    "指標": ["市值", "本益比(PE)", "每股盈餘(EPS)", "殖利率", "Beta", "52週高", "52週低"],
                    "數值": [
                        f"{info.get('marketCap',0)/1e8:.1f}億",
                        f"{info.get('trailingPE','N/A')}",
                        f"{info.get('trailingEps','N/A')}",
                        f"{info.get('dividendYield',0)*100:.2f}%" if info.get('dividendYield') else "N/A",
                        f"{info.get('beta','N/A')}",
                        f"{info.get('fiftyTwoWeekHigh','N/A')}",
                        f"{info.get('fiftyTwoWeekLow','N/A')}"
                    ]
                }), hide_index=True, use_container_width=True)
            with c2:
                st.markdown(f"**🏢 公司簡介**\n\n{info.get('longBusinessSummary', '無詳細資料')}")
