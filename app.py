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
import pytz 
import google.generativeai as genai
import twstock
import time

# --- Optional: News Search Module ---
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH = True
except ImportError:
    HAS_SEARCH = False

# --- 1. Helper Functions ---
def get_yfinance_suffix(ticker):
    try:
        stock_info = twstock.codes.get(ticker)
        if stock_info:
            if stock_info.market == '上櫃':
                return ".TWO"
            else:
                return ".TW"
        return ".TW"
    except:
        return ".TW"

# --- 2. Page Config ---
st.set_page_config(
    page_title="Sniper V17 Royal",
    page_icon="👑",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 👑 CSS Styling (Royal Edition) ---
st.markdown("""
<style>
    /* 1. 全局背景：皇家深紫 */
    .stApp { 
        background-color: #130f26; 
        background-image: linear-gradient(180deg, #130f26 0%, #2a1b5e 100%);
        color: #FFFFFF;
    }
    
    /* 隱藏預設元件 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* 調整邊距，適配手機 */
    .block-container {
        padding-top: 1rem !important; 
        padding-bottom: 4rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }

    /* 2. Expander (設定選單) 美化 */
    div[data-testid="stExpander"] {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid #FFD700; /* 金邊 */
        border-radius: 12px;
    }
    div[data-testid="stExpander"] summary {
        color: #FFD700 !important;
        font-weight: bold;
    }

    /* 3. Hero Section (大數字) */
    .hero-container {
        background: rgba(45, 31, 88, 0.6);
        border-radius: 16px;
        padding: 15px;
        margin-bottom: 10px;
        border: 1px solid rgba(255, 215, 0, 0.3); /* 淡金邊 */
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        backdrop-filter: blur(10px);
    }
    .hero-title { font-size: 14px; color: #B0B0E0; letter-spacing: 1px; }
    .hero-price { font-size: 42px; font-weight: 800; color: #FFFFFF; line-height: 1.1; font-family: 'Roboto Mono', monospace; }
    .hero-delta-up { color: #00E676; font-weight: bold; font-size: 16px; }
    .hero-delta-down { color: #FF5252; font-weight: bold; font-size: 16px; }

    /* 4. 訊號卡片 (Grid) */
    .signal-box {
        padding: 12px 5px; 
        border-radius: 10px; 
        margin-bottom: 8px;
        font-weight: 600; 
        text-align: center; 
        color: white; 
        font-size: 13px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .signal-green { background: linear-gradient(135deg, #00C853 0%, #009624 100%); }
    .signal-red { background: linear-gradient(135deg, #FF5252 0%, #D50000 100%); }
    .signal-gray { background: linear-gradient(135deg, #424242 0%, #212121 100%); }
    .signal-gold { background: linear-gradient(135deg, #FFD700 0%, #FFA000 100%); color: #000; }

    /* 5. Input 欄位優化 */
    input[type="text"], input[type="password"], input[type="number"] {
        background-color: rgba(255,255,255,0.1) !important;
        color: white !important;
        border: 1px solid #5C4B8C !important;
        border-radius: 8px !important;
    }
    
    /* 6. AI 建議區塊 (金卡) */
    .ai-card {
        background: linear-gradient(180deg, rgba(60, 40, 100, 0.8) 0%, rgba(30, 20, 60, 0.9) 100%);
        border-left: 4px solid #FFD700;
        border-radius: 8px;
        padding: 15px;
        margin-top: 15px;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 5px; }
    .stTabs [data-baseweb="tab"] { 
        height: 40px; 
        background-color: rgba(255,255,255,0.05); 
        border-radius: 8px;
        color: #ddd;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFD700 !important;
        color: #000 !important;
        font-weight: bold;
    }

</style>
""", unsafe_allow_html=True)

# --- 3. Data Fetching Functions ---
@st.cache_data(ttl=60)
def get_positions():
    try:
        if "G_SHEET_KEY" not in st.secrets: return []
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
        
        results = []
        for code in df['代號'].astype(str).tolist():
            if code and code.strip(): 
                try: name = twstock.codes[code].name
                except: name = code
                results.append(f"{code} {name}")
        return results
    except Exception as e:
        return []

# V13: Daily Technical Data
def get_technical_data(ticker):
    try:
        suffix = get_yfinance_suffix(ticker)
        stock = yf.Ticker(ticker + suffix)
        df = stock.history(period="1y")
        
        if df.empty and suffix == ".TW":
            stock = yf.Ticker(ticker + ".TWO")
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

# V16: Intraday Sniper Data (Hybrid: YFinance History + Twstock Realtime)
def get_intraday_sniper_data(ticker):
    try:
        # 1. Fetch History from YFinance
        suffix = get_yfinance_suffix(ticker)
        stock = yf.Ticker(ticker + suffix)
        df = stock.history(period="5d", interval="1m")
        
        if df.empty and suffix == ".TW":
             stock = yf.Ticker(ticker + ".TWO")
             df = stock.history(period="5d", interval="1m")
        
        if df.empty: return None, None, None, None

        # 2. Fetch Base Info (Prev Close & Vol)
        daily = stock.history(period="5d", interval="1d")
        if len(daily) >= 2:
            yesterday_vol = daily['Volume'].iloc[-2]
            prev_close = daily['Close'].iloc[-2]
        elif len(daily) == 1:
            yesterday_vol = daily['Volume'].iloc[-1]
            prev_close = daily['Close'].iloc[-1]
        else:
            yesterday_vol = 1 
            prev_close = df['Close'].iloc[0]

        # 3. Timezone conversion
        tz = pytz.timezone('Asia/Taipei')
        df.index = df.index.tz_convert(tz)
        
        # 4. Fetch Realtime Price from Twstock
        real_price = None
        try:
            realtime_data = twstock.realtime.get(ticker)
            if realtime_data['success']:
                real_price = float(realtime_data['realtime']['latest_trade_price'])
        except:
            pass

        # 5. Hybrid Merge
        latest_date = df.index[-1].date()
        today_date = datetime.datetime.now(tz).date()
        
        df_today = df[df.index.date == latest_date].copy()
        
        if real_price:
            if latest_date == today_date:
                df_today.iloc[-1, df_today.columns.get_loc('Close')] = real_price
                if real_price > df_today.iloc[-1]['High']: df_today.iloc[-1, df_today.columns.get_loc('High')] = real_price
                if real_price < df_today.iloc[-1]['Low']: df_today.iloc[-1, df_today.columns.get_loc('Low')] = real_price
            
        df_today.ta.bbands(length=20, std=2, append=True)
        df_today['Cum_Vol'] = df_today['Volume'].cumsum()
        df_today['Vol_MA5'] = df_today['Volume'].rolling(window=5).mean()
        
        return df_today, yesterday_vol, prev_close, real_price

    except Exception as e:
        return None, None, None, None

def get_company_info_safe(ticker):
    try: 
        suffix = get_yfinance_suffix(ticker)
        info = yf.Ticker(ticker + suffix).info
        if not info or 'trailingPE' not in info:
             alt_suffix = ".TWO" if suffix == ".TW" else ".TW"
             alt_info = yf.Ticker(ticker + alt_suffix).info
             if alt_info and 'trailingPE' in alt_info:
                 return alt_info
        return info
    except: return {} 

def get_financial_data(ticker):
    try:
        suffix = get_yfinance_suffix(ticker)
        stock = yf.Ticker(ticker + suffix)
        if stock.income_stmt is None or stock.income_stmt.empty:
             alt_suffix = ".TWO" if suffix == ".TW" else ".TW"
             stock = yf.Ticker(ticker + alt_suffix)
        return stock.income_stmt, stock.balance_sheet, stock.cashflow
    except: return None, None, None

# --- 4. AI Engine ---
def get_news_summary(ticker_name):
    if not HAS_SEARCH:
        return "（系統提示：無法搜尋新聞，請確認已安裝 duckduckgo-search）"
    news_text = ""
    try:
        with DDGS() as ddgs:
            keywords = f"{ticker_name} 新聞"
            results = ddgs.text(keywords, region='wt-wt', safesearch='off', timelimit='w', max_results=3)
            if results:
                for res in results:
                    news_text += f"- {res['title']}: {res['body']}\n"
            else:
                news_text = "（本週無重大新聞）"
    except Exception as e:
        news_text = f"（新聞搜尋連線失敗: {str(e)}）"
    return news_text

def generate_sniper_report(ticker_full_name, df, info, financials, api_key):
    if not api_key: return "⚠️ 未設定 API Key"
    progress_bar = st.progress(0)
    status_text = st.empty()
    try:
        parts = ticker_full_name.split(" ")
        code = parts[0]
        name = parts[1] if len(parts) > 1 else code
        
        status_text.text(f"🔍 解析 {name} 基礎數據...")
        progress_bar.progress(10)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        macd_val = last['MACDh_12_26_9'] if 'MACDh_12_26_9' in df.columns else 0
        
        tech_data = f"""
        收盤: {last['Close']:.2f} (漲跌 {last['Close']-prev['Close']:.2f})
        MFI(14): {last.get('MFI_14', 0):.1f}
        MACD柱狀圖: {macd_val:.2f}
        """

        status_text.text("📊 分析財務報表...")
        progress_bar.progress(30)
        inc_str = "無資料"
        if financials and financials[0] is not None:
            inc_df = financials[0].iloc[:, :2] 
            inc_str = inc_df.to_markdown()

        status_text.text(f"🌐 搜索 {name} 新聞...")
        progress_bar.progress(60)
        news_content = get_news_summary(name)

        status_text.text("🤖 Gemini 戰略整合...")
        progress_bar.progress(80)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash') # Force 1.5 Flash for Quota

        prompt = f"""
        你現在是華爾街頂尖的對沖基金交易員，代號「Sniper」。
        請針對台股 {name} ({code}) 進行全方位掃描。
        
        【輸入數據】
        技術面：{tech_data}
        基本面：\n{inc_str}
        新聞：\n{news_content}
        PE: {info.get('trailingPE', 'N/A')}

        【任務指令】
        回覆格式必須嚴格遵守以下結構 (Markdown)：
        ### 🎯 狙擊報告: {name}
        **1. 戰情摘要**: (新聞與財報一句話總結)
        **2. 技術籌碼**: (趨勢與資金流向)
        ---
        ### 🔥 最終決策
        **1. 趨勢評分 (0-10)**: [分數]
        **2. 資金流向**: [流入/流出/觀望]
        **3. 操作點位**:
           * 🔴 壓力: [價格]
           * 🟢 支撐: [價格]
           * 💡 策略: [簡短建議]
        """
        response = model.generate_content(prompt)
        progress_bar.progress(100)
        status_text.text("✅ 完成！")
        time.sleep(1)
        progress_bar.empty()
        status_text.empty()
        return response.text
    except Exception as e:
        status_text.error(f"分析中斷: {str(e)}")
        return f"❌ 錯誤: {str(e)}"

# 🔥🔥🔥 V16.5: Unchained AI Expert Prompt 🔥🔥🔥
def generate_sniper_advice(ticker_name, ticker_code, price, open_price, prev_close, 
                           vol_ratio, shadow_ratio, body_pct, trend_pct, 
                           v16_status, entry_cost, api_key):
    if not api_key: return "⚠️ 請輸入 API Key"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tz)
    current_time_str = now.strftime('%H:%M')
    
    status_text = ""
    for k, v in v16_status.items():
        icon = "✅" if v else "❌"
        status_text += f"- {k}: {icon}\n"

    if entry_cost > 0:
        roi = ((price - entry_cost) / entry_cost) * 100
        position_status = f"🔴 持倉中 | 成本: {entry_cost} | 損益: {roi:.2f}%"
        mission = "部位管理顧問 (Position Manager)"
        focus = "請以資深操盤手的角度，審視目前持倉風險。不要死板遵守固定 % 數，而是依據走勢強弱判斷去留。"
    else:
        position_status = "⚪ 空手觀望 (Sniper Mode)"
        mission = "首席交易策略師 (Chief Strategist)"
        focus = "請以你的交易經驗判斷這是否為『勝率高』的機會。即便 V16 訊號全亮，若你覺得是主力誘多，請務必警告我；反之若訊號差一點但型態極佳，也可提出獨到見解。"

    prompt = f"""
    【角色】你是一名在台股市場打滾 20 年的「{mission}」。你看盡了主力的騙線手法，風格老練、直覺敏銳，不完全依賴僵化的指標，更看重「量價結構」與「市場心理」。
    
    【戰情資訊 - {ticker_name} ({ticker_code})】
    * 時間: {current_time_str}
    * 現價: {price} (漲幅 {trend_pct:.2f}%)
    * 昨收: {prev_close}
    * ⚠️ 【使用者狀態】: {position_status}
    
    【V16 系統自動檢測結果 (僅供參考)】
    {status_text}
    * K棒型態: 實體漲幅 {body_pct:.2f}% / 避雷針比例 {shadow_ratio:.2f} (一般標準 < 0.5)
    * 攻擊量能: 累積量為昨天的 {vol_ratio:.1f}%
    
    【你的任務】
    使用者已經看得到上面的紅綠燈號了，**不需要你複述規則**。
    {focus}
    
    請給出充滿洞見的分析 (Markdown)，請使用條列式重點，語氣專業果斷：
    ### 🧠 老手觀點 ({current_time_str})
    **1. 盤面解讀**:
       * (請解讀主力意圖：這是真突破、假拉抬、還是洗盤？)
    **2. 操作建議 (自定義)**:
       * 🎯 決策: **[強力買進 / 嘗試單 / 觀望 / 續抱 / 減碼 / 出清]** (請明確選一個)
       * 💡 邏輯: (告訴我為什麼)
    **3. 關鍵點位**:
       * 🛡️ 防守: (給出一個你認為最安全的防守價)
       * 🚀 目標: (短線壓力看哪裡)
    **4. 一句話點評**: (犀利、直接的總結)
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AI 思考中斷: {e}"

# --- 5. Main Logic (Royal UI) ---

# Top Expander for Settings (Styled)
with st.expander("⚙️ 皇家設定 (Settings)", expanded=False):
    c_set1, c_set2 = st.columns([2, 1])
    
    with c_set1:
        app_mode = st.radio(
            "Mode", 
            ["📊 庫存 (Inventory)", "⚡ 狙擊 (Sniper V17)"], 
            horizontal=True,
            label_visibility="collapsed"
        )
    
    with c_set2:
        if "GEMINI_API_KEY" in st.secrets:
            gemini_key = st.secrets["GEMINI_API_KEY"]
            st.success("API 鎖定")
        else:
            gemini_key = st.text_input("API Key", type="password", placeholder="Gemini Key")

if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = "2330"

def update_ticker_from_select():
    selection = st.session_state.inventory_select
    if selection:
        code = selection.split(" ")[0]
        st.session_state.active_ticker = code
        st.session_state.v14_sniper_advice = None
        st.session_state.last_sniper_code = code

# ==========================================
# Mode 1: Inventory/Analysis
# ==========================================
if app_mode == "📊 庫存 (Inventory)":
    c_nav_1, c_nav_2 = st.columns([1, 4], gap="small")
    with c_nav_1:
        if st.button("🔄", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with c_nav_2:
        ticker_list = get_positions()
        st.selectbox(
            "inventory", 
            ticker_list, 
            key="inventory_select",
            on_change=update_ticker_from_select,
            index=None,
            placeholder="📦 從庫存選擇",
            label_visibility="collapsed"
        )

    manual_input = st.text_input("search", value=st.session_state.active_ticker, label_visibility="collapsed")

    final_ticker_code = None
    final_ticker_name = None

    if manual_input:
        clean_code = manual_input.strip()
        final_ticker_code = clean_code
        
        if clean_code != st.session_state.active_ticker:
            st.session_state.active_ticker = clean_code
            st.session_state.v14_sniper_advice = None

        try: name = twstock.codes[clean_code].name
        except: name = clean_code
        final_ticker_name = f"{clean_code} {name}"
    else:
        final_ticker_code = "2330"
        final_ticker_name = "2330 台積電 (Demo)"

    if final_ticker_code:
        if 'current_ticker' not in st.session_state:
            st.session_state.current_ticker = ""
            st.session_state.sniper_report = None
            st.session_state.df = None
            st.session_state.info = None
            st.session_state.financials = None

        if st.session_state.current_ticker != final_ticker_code:
            st.session_state.current_ticker = final_ticker_code
            st.session_state.sniper_report = None
            st.session_state.df = None
            st.session_state.info = None
            st.session_state.financials = None
            
            with st.spinner('Loading Data...'):
                st.session_state.df = get_technical_data(final_ticker_code)
                st.session_state.info = get_company_info_safe(final_ticker_code)

        # Hero Style Title
        st.markdown(f"<div style='color:#FFD700; font-size:20px; font-weight:bold; margin-bottom:10px;'>📊 {final_ticker_name}</div>", unsafe_allow_html=True)

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
            
            color_cls = "hero-delta-up" if change > 0 else "hero-delta-down" if change < 0 else "no-color"
            sign = "+" if change > 0 else ""
            
            # 👑 New Hero Section for V13
            st.markdown(f"""
            <div class="hero-container">
                <div class="hero-title">CURRENT PRICE</div>
                <div class="hero-price">{close:,.0f}</div>
                <div class="{color_cls}">{sign}{change:.1f} ({sign}{pct:.2f}%)</div>
            </div>
            """, unsafe_allow_html=True)

            # ... Keep Metrics as fallback detailed info ...
            mfi = safe_num('MFI_14')
            rsi = safe_num('RSI_14')
            bias = safe_num('BIAS_20')
            pe = info.get('trailingPE', '-') if info else '-'

            st.markdown(f"""
            <div class="metric-grid-3">
                <div class="metric-card">
                    <div class="metric-label">MFI</div>
                    <div class="metric-value">{mfi:.0f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">RSI</div>
                    <div class="metric-value">{rsi:.0f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">乖離率</div>
                    <div class="metric-value">{bias:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            tabs = st.tabs(["K線", "指標"])

            with tabs[0]:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
                # 👑 Royal Chart Style
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K', increasing_line_color='#00E676', decreasing_line_color='#FF5252'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='#FFD700', width=1), name='MA20'), row=1, col=1)
                if 'OBV' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV', line=dict(color='#00E5FF')), row=2, col=1)
                
                # Update Layout for Royal Theme
                fig.update_layout(
                    height=380, 
                    template="plotly_dark", 
                    paper_bgcolor='rgba(0,0,0,0)', 
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis_rangeslider_visible=False, 
                    margin=dict(l=0,r=0,t=5,b=0), 
                    legend=dict(orientation="h", y=1, x=0, bgcolor='rgba(0,0,0,0)')
                )
                # 🔥 FIX SCROLL TRAP
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'staticPlot': False})

            with tabs[1]:
                fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True)
                if 'MACDh_12_26_9' in df.columns: fig2.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], marker_color='#29B6F6', name='MACD'), row=1, col=1)
                if 'STOCHk_9_3_3' in df.columns:
                    fig2.add_trace(go.Scatter(x=df.index, y=df['STOCHk_9_3_3'], line=dict(color='#FFD700', width=1), name='K'), row=2, col=1)
                    fig2.add_trace(go.Scatter(x=df.index, y=df['STOCHd_9_3_3'], line=dict(color='#FF5252', width=1), name='D'), row=2, col=1)
                fig2.update_layout(height=350, template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                st.plotly_chart(fig2, use_container_width=True, config={'scrollZoom': False})

            st.markdown("---") 
            col_ai_btn, col_ai_res = st.columns([1, 4])
            with col_ai_btn:
                if st.button("🚀 分析", use_container_width=True):
                    if st.session_state.financials is None:
                        with st.spinner("下載財報中..."):
                            inc, bal, cash = get_financial_data(final_ticker_code)
                            st.session_state.financials = (inc, bal, cash)
                    report = generate_sniper_report(final_ticker_name, df, info, st.session_state.financials, gemini_key)
                    st.session_state.sniper_report = report
                    st.rerun()

            if st.session_state.sniper_report:
                st.markdown(f"<div class='ai-card'>{st.session_state.sniper_report}</div>", unsafe_allow_html=True)
                if st.button("🗑️ 清除", key="cls_rpt"):
                    st.session_state.sniper_report = None
                    st.rerun()

# ==========================================
# Mode 2: AI Sniper (V17 Royal Edition)
# ==========================================
elif app_mode == "⚡ 狙擊 (Sniper V17)":
    
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()
    if time.time() - st.session_state.last_refresh > 60:
        st.session_state.last_refresh = time.time()
        st.rerun()

    tz = pytz.timezone('Asia/Taipei')
    now_tw = datetime.datetime.now(tz)
    
    # 👑 Royal Header
    st.markdown(f"""
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <span style="color:#FFD700; font-weight:bold; font-size:14px;">⚡ SNIPER V17</span>
        <span style="color:#888; font-size:12px;">{now_tw.strftime('%H:%M:%S')}</span>
    </div>
    """, unsafe_allow_html=True)

    col_in1, col_in2 = st.columns([2, 1])
    with col_in1:
        sniper_input = st.text_input("Stock Code", value=st.session_state.active_ticker, placeholder="代號", label_visibility="collapsed")
        if sniper_input != st.session_state.active_ticker:
            st.session_state.active_ticker = sniper_input

    with col_in2:
        entry_cost = st.number_input("Cost", value=0.0, step=0.5, placeholder="成本", label_visibility="collapsed")

    target_code = sniper_input.strip()

    if 'last_sniper_code' not in st.session_state:
        st.session_state.last_sniper_code = ""

    if st.session_state.last_sniper_code != target_code:
        st.session_state.v14_sniper_advice = None
        st.session_state.last_sniper_code = target_code

    try: target_name = twstock.codes[target_code].name
    except: target_name = target_code
    
    # Fetch Data
    df_1m, yesterday_vol, prev_close, real_price = get_intraday_sniper_data(target_code)
    
    # Data Validation
    is_data_valid = False
    if df_1m is not None and not df_1m.empty and prev_close is not None:
        latest_data_date = df_1m.index[-1].date()
        today_date = now_tw.date()
        
        if real_price:
            curr_price = real_price
            is_data_valid = True
        else:
            curr_price = df_1m.iloc[-1]['Close']
            if latest_data_date == today_date:
                is_data_valid = True
            else:
                st.warning(f"⚠️ 歷史數據: {latest_data_date}")
    
    if df_1m is not None and not df_1m.empty and prev_close is not None:
        last_bar = df_1m.iloc[-1]
        if not real_price: curr_price = last_bar['Close']
        open_price = df_1m.iloc[0]['Open']
        
        # --- V16.3 Logic ---
        trend_pct = ((curr_price - prev_close) / prev_close) * 100 
        body_delta = curr_price - open_price
        body_len = abs(body_delta)
        body_pct = (body_delta / prev_close) * 100 
        
        current_high = max(last_bar['High'], curr_price)
        upper_shadow = current_high - max(open_price, curr_price)
        shadow_ratio = (upper_shadow / body_len) if body_len > 0.01 else 99.9 
        
        cum_vol = last_bar['Cum_Vol']
        vol_ratio = (cum_vol / yesterday_vol) * 100 if yesterday_vol > 0 else 0

        current_time = now_tw.time()
        t_0905 = datetime.time(9, 5)
        t_0915 = datetime.time(9, 15)
        t_1000 = datetime.time(10, 0)
        t_1030 = datetime.time(10, 30)

        cond_vol = False
        vol_msg = "量縮"
        
        if current_time < t_0905:
            cond_vol = False
            vol_msg = "避險"
        elif current_time < t_0915:
            cond_vol = vol_ratio >= 10
            vol_msg = f"{vol_ratio:.0f}%"
        elif current_time < t_1000:
            cond_vol = vol_ratio >= 20
            vol_msg = f"{vol_ratio:.0f}%"
        else:
            cond_vol = vol_ratio >= 30
            vol_msg = f"{vol_ratio:.0f}%"
            
        cond_qualify = (curr_price > open_price) and (2 <= trend_pct <= 8) and (body_pct >= 0.2)
        cond_shadow = shadow_ratio <= 0.5
        cond_time = current_time <= t_1030
        final_signal = cond_qualify and cond_shadow and cond_vol and cond_time and is_data_valid

        cost_base = entry_cost if entry_cost > 0 else curr_price
        roi_pct = ((curr_price - cost_base) / cost_base) * 100
        
        trailing_msg = "蓄力"
        trailing_sl = cost_base * 0.975 
        
        if roi_pct > 5:
            trailing_msg = "鎖利"
            trailing_sl = curr_price * 0.975
        elif roi_pct > 2:
            trailing_msg = "保本"
            trailing_sl = cost_base * 1.005

        # 👑 HERO PRICE SECTION (Royal Style)
        color_cls = "hero-delta-up" if trend_pct > 0 else "hero-delta-down" if trend_pct < 0 else "no-color"
        sign = "+" if trend_pct > 0 else ""
        
        st.markdown(f"""
        <div class="hero-container">
            <div style="display:flex; justify-content:space-between;">
                <span class="hero-title">{target_name}</span>
                <span style="color:#FFD700; font-weight:bold;">VIP</span>
            </div>
            <div class="hero-price">{curr_price:,.1f}</div>
            <div class="{color_cls}">{sign}{trend_pct:.2f}% <span style="font-size:12px; color:#888; margin-left:10px;">Vol: {cum_vol/1000:.0f}K</span></div>
        </div>
        """, unsafe_allow_html=True)
        
        # --- UI Grid ---
        c1, c2, c3, c4 = st.columns(4)
        def signal_html(text, subtext, is_pass, fail_color="signal-gray"):
            color = "signal-green" if is_pass else fail_color
            return f'<div class="signal-box {color}">{text}<br><span style="font-size:10px; opacity:0.8;">{subtext}</span></div>'

        with c1: 
            st.markdown(signal_html("資格", f"{body_pct:.1f}%", cond_qualify), unsafe_allow_html=True)
        with c2: 
            st.markdown(signal_html("避雷", f"{shadow_ratio:.1f}", cond_shadow, "signal-red"), unsafe_allow_html=True)
        with c3: 
            st.markdown(signal_html("量能", vol_msg, cond_vol), unsafe_allow_html=True)
        with c4: 
            t_stat = "OK" if cond_time else "逾時"
            st.markdown(signal_html("時窗", t_stat, cond_time, "signal-gray"), unsafe_allow_html=True)

        if not is_data_valid:
             st.error("⛔ 資料過時或無法取得即時報價，請稍後再試。")
        else:
            if final_signal: 
                st.markdown(f'<div class="signal-box signal-gold">🎯 狙擊訊號確認</div>', unsafe_allow_html=True)
            elif not cond_qualify: st.warning("⚠️ 資格不符")
            elif not cond_shadow: st.warning("⚠️ 避雷針過長")
            elif not cond_vol: st.info(f"⏳ 等待補量")
            else: st.info("⏳ 監控中...")

        # Chart
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.02)
        fig.add_trace(go.Candlestick(x=df_1m.index, open=df_1m['Open'], high=df_1m['High'], low=df_1m['Low'], close=df_1m['Close'], name='Price', increasing_line_color='#00E676', decreasing_line_color='#FF5252'), row=1, col=1)
        
        if 'BBU_20_2.0' in df_1m.columns:
            fig.add_trace(go.Scatter(x=df_1m.index, y=df_1m['BBU_20_2.0'], line=dict(color='#FFD700', width=1), name='Upper'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_1m.index, y=df_1m['BBM_20_2.0'], line=dict(color='#FF9100', width=1), name='MA20'), row=1, col=1)
        
        if entry_cost > 0:
            fig.add_hline(y=entry_cost, line_dash="dash", line_color="white", row=1, col=1)
            fig.add_hline(y=trailing_sl, line_color="#FF00FF", row=1, col=1)

        colors = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df_1m.iterrows()]
        fig.add_trace(go.Bar(x=df_1m.index, y=df_1m['Volume'], marker_color=colors, name='Vol'), row=2, col=1)
        
        fig.update_layout(
            height=400, 
            template="plotly_dark", 
            paper_bgcolor='rgba(0,0,0,0)', 
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0,r=0,t=0,b=0), 
            xaxis_rangeslider_visible=False, 
            showlegend=False
        )
        # 🔥 FIX SCROLL TRAP
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'staticPlot': False})
        
        st.markdown(f"""
        <div class="metric-grid-2">
            <div class="metric-card"><div class="metric-label">策略</div><div class="metric-value up-color">{trailing_msg}</div></div>
            <div class="metric-card"><div class="metric-label">防守</div><div class="metric-value down-color">{trailing_sl:.1f}</div></div>
        </div>
        """, unsafe_allow_html=True)

        if 'v14_sniper_advice' not in st.session_state:
            st.session_state.v14_sniper_advice = None

        if st.button("🤖 呼叫顧問 (AI)", use_container_width=True):
            with st.spinner("V16 運算中..."):
                v16_status = {
                    "資格": cond_qualify,
                    "避雷": cond_shadow,
                    "量能": cond_vol,
                    "時窗": cond_time
                }
                
                advice = generate_sniper_advice(
                    target_name, target_code, 
                    curr_price, open_price, prev_close,
                    vol_ratio, shadow_ratio, body_pct, trend_pct,
                    v16_status, entry_cost, gemini_key
                )
                st.session_state.v14_sniper_advice = advice
        
        if st.session_state.v14_sniper_advice:
            st.markdown(f"<div class='ai-card'>{st.session_state.v14_sniper_advice}</div>", unsafe_allow_html=True)

    else:
        st.warning("今日尚未開盤或無資料")
