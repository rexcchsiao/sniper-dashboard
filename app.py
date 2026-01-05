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
import twstock  # 👈 新增：用來查中文股名

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Sniper Pro V9 (Smart UI)",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 美化 (優化側邊欄列表樣式)
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    /* 優化指標卡片 */
    div[data-testid="metric-container"] { 
        background-color: #1E2129; 
        border: 1px solid #363B4C; 
        padding: 10px; 
        border-radius: 8px; 
    }
    /* 優化側邊欄 Radio Button */
    .stRadio > div {
        background-color: #262730;
        padding: 10px;
        border-radius: 8px;
    }
    .stRadio label {
        font-size: 16px;
        font-weight: bold;
        color: #E0E0E0;
        cursor: pointer;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 連線 Google Sheet (取得代號並查中文名) ---
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
                # 🔥 使用 twstock 查詢中文名稱
                try:
                    name = twstock.codes[code].name
                except:
                    name = code # 查不到就用代號
                results.append(f"{code} {name}")
                
        return results
    except Exception as e:
        st.error(f"Sheet 連線錯誤: {str(e)}")
        return []

# --- 3. 技術數據核心 ---
def get_technical_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        df = stock.history(period="1y")
        if df.empty: return None
        
        # 指標計算
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
        st.error(f"股價抓取失敗: {e}")
        return None

# --- 4. 基本面數據核心 (只抓表格，不依賴 info) ---
def get_company_info_safe(ticker):
    # 嘗試抓取，失敗回傳空字典
    try:
        return yf.Ticker(ticker + ".TW").info
    except:
        return {} 

def get_financial_data(ticker):
    try:
        stock = yf.Ticker(ticker + ".TW")
        return stock.income_stmt, stock.balance_sheet, stock.cashflow
    except:
        return None, None, None

# --- 5. AI 分析引擎 (注入中文名稱) ---
def generate_ai_analysis(mode, ticker_full_name, df=None, info=None, financials=None, api_key=None):
    if not api_key:
        return "⚠️ 請先設定 Gemini API Key 以啟用 AI 分析。"

    # 解析代號與名稱 (例如 "2412 中華電" -> "2412", "中華電")
    ticker_code = ticker_full_name.split(" ")[0]
    stock_name = ticker_full_name.split(" ")[1] if len(ticker_full_name.split(" ")) > 1 else ticker_code

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # 即使 info 是空的，我們用 stock_name 告訴 AI 它是誰
        info_summary = info.get('longBusinessSummary', 'Yahoo 資料暫缺') if info else 'Yahoo 資料暫缺'
        pe = info.get('trailingPE', 'N/A') if info else 'N/A'

        if mode == "technical":
            last = df.iloc[-1]
            rsi = last['RSI_14'] if 'RSI_14' in df.columns else 0
            mfi = last['MFI_14'] if 'MFI_14' in df.columns else 0
            bias = last['BIAS_20'] if 'BIAS_20' in df.columns else 0
            
            prompt = f"""
            你是一位量化交易員。請分析 {stock_name} ({ticker_code}) 的技術面：
            [數據] 收盤:{last['Close']:.1f}, RSI:{rsi:.1f}, MFI:{mfi:.1f}, 乖離率:{bias:.2f}%
            [任務] 1. 給出評分(1-10) 2. 判斷資金流向(MFI)與背離 3. 給出具體操作建議
            """
            
        elif mode == "fundamental":
            inc_str = financials[0].iloc[:, :2].to_markdown() if financials and financials[0] is not None else "無"
            bal_str = financials[1].iloc[:, :2].to_markdown() if financials and financials[1] is not None else "無"
            
            # 🔥 關鍵提示：告訴 AI 公司名稱，讓它運用內建知識庫補全背景
            prompt = f"""
            你是一位專業的基本面分析師。請分析台灣上市公司：**{stock_name} ({ticker_code})**。
            即使缺乏詳細簡介，請運用你豐富的知識庫來識別這家公司所在的產業與地位。
            
            [提供的最新財報數據]
            損益表 (Income Statement):
            {inc_str}
            
            資產負債表 (Balance Sheet):
            {bal_str}
            
            [參考指標] PE (本益比): {pe}
            
            [分析任務]
            1. **公司背景補全**：請簡述 {stock_name} 的主要業務與市場地位 (不需依賴提供的簡介)。
            2. **獲利能力診斷**：根據損益表數據，分析營收與獲利是成長還是衰退？毛利率變化如何？
            3. **財務體質評估**：根據資產負債表，評估負債狀況與現金流風險。
            4. **投資評級**：綜合以上給出評級 (買進/持有/賣出) 與理由。
            """

        with st.spinner(f'♊ Gemini 正在分析 {stock_name}...'):
            response = model.generate_content(prompt)
            return response.text

    except Exception as e:
        return f"❌ AI 連線失敗: {str(e)}"

# --- 6. 側邊欄 (UI 大改版) ---
with st.sidebar:
    st.title("🦅 Sniper Pro V9")
    
    # Refresh 按鈕置頂
    if st.button("🔄 刷新庫存清單", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("---")
    
    # API Key 區域
    if "GEMINI_API_KEY" in st.secrets:
        gemini_key = st.secrets["GEMINI_API_KEY"]
    else:
        gemini_key = st.text_input("Gemini API Key", type="password")
        if not gemini_key:
            st.warning("⚠️ 請輸入 Key 以啟用 AI")
    
    st.markdown("---")
    st.subheader("📂 庫存監控")
    
    # 取得清單 (格式: "2412 中華電")
    ticker_list = get_positions()
    
    if ticker_list:
        # 🔥 改用 Radio Button 列表顯示，更直觀
        selected_option = st.radio("請選擇股票：", ticker_list, label_visibility="collapsed")
        # 拆解出代號，例如 "2412"
        selected_ticker = selected_option.split(" ")[0]
        selected_ticker_name = selected_option # 完整名稱 "2412 中華電" 用於顯示
    else:
        st.warning("目前無庫存")
        # 測試用
        test_code = st.text_input("或輸入代號測試", "2330")
        selected_ticker = test_code
        try:
            test_name = twstock.codes[test_code].name
        except:
            test_name = test_code
        selected_ticker_name = f"{test_code} {test_name}"

# --- 7. 主畫面 ---
if selected_ticker:
    if 'data_fetched' not in st.session_state:
        st.session_state.data_fetched = False

    # 檢查是否切換了股票
    if st.session_state.get('current_ticker') != selected_ticker:
        st.session_state.data_fetched = False
        st.session_state.current_ticker = selected_ticker
        st.session_state.financials = None

    # 標題顯示中文
    st.header(f"📊 {selected_ticker_name} 戰情中心")
    
    if not st.session_state.data_fetched:
        with st.spinner('數據載入中...'):
            df = get_technical_data(selected_ticker)
            info = get_company_info_safe(selected_ticker) # 這裡失敗也沒關係
            
            if df is not None:
                st.session_state.df = df
                st.session_state.info = info
                st.session_state.data_fetched = True
            else:
                st.error("❌ 無法抓取股價資料")

    if st.session_state.data_fetched:
        df = st.session_state.df
        info = st.session_state.info
        last = df.iloc[-1]
        
        # 安全取值 helper
        def safe_get(col, fmt="{:.1f}"):
            if col in df.columns and not pd.isna(last[col]):
                return fmt.format(last[col])
            return "N/A"

        # 頂部儀表板
        c1, c2, c3, c4, c5 = st.columns(5)
        pct = ((last['Close'] - df['Close'].iloc[-2])/df['Close'].iloc[-2])*100
        
        c1.metric("現價", f"{last['Close']:.1f}", f"{pct:.2f}%")
        c2.metric("MFI 資金", safe_get('MFI_14'))
        c3.metric("乖離率", safe_get('BIAS_20', "{:.2f}%"))
        
        # 就算 info 沒抓到，至少顯示 N/A
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

        with tabs[2]:
            st.markdown("### 🤖 技術面診斷")
            if st.button("✨ 啟動技術分析", key="btn_tech"):
                # 傳入完整名稱 (含中文)
                report = generate_ai_analysis("technical", selected_ticker_name, df=df, info=info, api_key=gemini_key)
                st.markdown(report)

        with tabs[3]:
            st.markdown(f"### 💰 {selected_ticker_name} 財報體質診斷")
            st.info("💡 下載財報並分析 (AI 將自動補全公司背景)")
            if st.button("📥 下載財報", key="btn_fund"):
                if not st.session_state.financials:
                    with st.spinner("連線 Yahoo 財報資料庫..."):
                        inc, bal, cash = get_financial_data(selected_ticker)
                        st.session_state.financials = (inc, bal, cash)
                
                # 傳入完整名稱 (含中文)，讓 AI 知道是哪家公司
                report = generate_ai_analysis("fundamental", selected_ticker_name, info=info, financials=st.session_state.financials, api_key=gemini_key)
                st.markdown(report)
