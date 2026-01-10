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
    page_title="Sniper Mobile V16.4",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS Styling ---
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    
    /* Hide Default Menu/Footer for App-like feel */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    .block-container {
        padding-top: 1rem !important; 
        padding-bottom: 3rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }

    /* V13 Metric Grid */
    .metric-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 6px; }
    .metric-grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 10px; }
    .metric-card {
        background-color: #1E2129; border: 1px solid #363B4C; border-radius: 6px; 
        padding: 8px 4px; text-align: center; display: flex; flex-direction: column; 
        justify-content: center; align-items: center;
    }
    .metric-label { font-size: 12px; color: #B0B0B0; margin-bottom: 2px; }
    .metric-value { font-size: 18px; font-weight: 600; color: #FFFFFF; line-height: 1.2; }
    .metric-delta { font-size: 11px; margin-top: 2px; }
    .up-color { color: #00E676; }
    .down-color { color: #FF5252; }
    .no-color { color: #B0B0B0; }

    /* V16 Sniper Signals */
    .signal-box {
        padding: 10px; border-radius: 5px; margin-bottom: 5px;
        font-weight: bold; text-align: center; color: white; font-size: 13px;
    }
    .signal-green { background-color: #00C853; }
    .signal-red { background-color: #D50000; }
    .signal-gray { background-color: #424242; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 2px; overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; }
    .stTabs [data-baseweb="tab"] { height: 35px; padding: 0px 10px; font-size: 14px; flex: 1 0 auto; }
    
    label { font-size: 14px !important; color: #E0E0E0 !important; }
    div[data-testid="stSelectbox"] label { display: none; }
    div[data-testid="stButton"] button { height: 42px; margin-top: 0px; }
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
        # 1. Fetch History from YFinance (for indicators & chart)
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
                # Note: Twstock returns string, needs conversion
                real_price = float(realtime_data['realtime']['latest_trade_price'])
        except:
            pass

        # 5. Hybrid Merge
        latest_date = df.index[-1].date()
        today_date = datetime.datetime.now(tz).date()
        
        df_today = df[df.index.date == latest_date].copy()
        
        # Override the last close with real-time price if available
        if real_price:
            # Only update if the chart data is actually from today
            if latest_date == today_date:
                df_today.iloc[-1, df_today.columns.get_loc('Close')] = real_price
                # Update High/Low if real price exceeds bounds
                if real_price > df_today.iloc[-1]['High']: df_today.iloc[-1, df_today.columns.get_loc('High')] = real_price
                if real_price < df_today.iloc[-1]['Low']: df_today.iloc[-1, df_today.columns.get_loc('Low')] = real_price
            
        # Recalculate indicators with updated price
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
        model = genai.GenerativeModel('gemini-2.5-flash')

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

# 🔥🔥🔥 V16.6: AI Auto-Failover (優先用 2.5，失敗自動切換 1.5) 🔥🔥🔥
def generate_sniper_advice(ticker_name, ticker_code, price, open_price, prev_close, 
                           vol_ratio, shadow_ratio, body_pct, trend_pct, 
                           v16_status, entry_cost, api_key):
    if not api_key: return "⚠️ 請輸入 API Key"
    
    genai.configure(api_key=api_key)
    
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.datetime.now(tz)
    current_time_str = now.strftime('%H:%M')
    
    # 整理 V16 的檢測結果
    status_text = ""
    for k, v in v16_status.items():
        icon = "✅" if v else "❌"
        status_text += f"- {k}: {icon}\n"

    # [使用者持倉狀態]
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
    
    請給出充滿洞見的分析 (Markdown)：
    ### 🧠 老手觀點 ({current_time_str})
    **1. 盤面解讀**:
       * (請解讀主力意圖：這是真突破、假拉抬、還是洗盤？目前的上影線或量能代表什麼心理狀態？)
    **2. 操作建議 (自定義)**:
       * 🎯 決策: **[強力買進 / 嘗試單 / 觀望 / 續抱 / 減碼 / 出清]** (請依據你的經驗給出最適合的建議，可與 V16 訊號不同)
       * 💡 邏輯: (告訴我為什麼。例如：「雖然 V16 亮紅燈，但遇到前高壓力，建議觀望」或「V16 雖然量能不足，但型態完美，可嘗試佈局」)
    **3. 關鍵點位**:
       * 🛡️ 防守: (給出一個你認為最安全的防守價，不一定要照公式)
       * 🚀 目標: (若看好，短線壓力看哪裡)
    **4. 一句話點評**: (犀利、直接的總結)
    """

    # --- 核心修改：自動切換模型機制 ---
    try:
        # 第一優先：嘗試使用 Gemini 2.5 Flash (聰明但有次數限制)
        model_25 = genai.GenerativeModel('gemini-2.5-flash')
        response = model_25.generate_content(prompt)
        return f"⚡ **[Gemini 2.5]** 分析報告：\n\n{response.text}"
        
    except Exception as e_25:
        # 如果 2.5 失敗 (例如 429 Too Many Requests)，自動切換到 1.5
        error_msg = str(e_25)
        # 可以在這裡印出錯誤日誌方便除錯
        # print(f"Gemini 2.5 failed: {error_msg}, switching to 1.5...")
        
        try:
            # 第二優先：使用 Gemini 1.5 Flash (穩定且額度高)
            model_15 = genai.GenerativeModel('gemini-1.5-flash')
            response = model_15.generate_content(prompt)
            return f"🛡️ **[Gemini 1.5 備援]** 分析報告 (2.5 忙碌中)：\n\n{response.text}"
            
        except Exception as e_15:
            # 如果連 1.5 都掛了，才回報錯誤
            return f"❌ AI 系統暫時無法連線 (兩道防線皆失敗): {e_15}"

# --- 5. Main Logic (Mobile UI Optimized) ---

# Top Expander for Settings (Replaces Sidebar)
with st.expander("⚙️ 模式切換與設定 (點擊展開)", expanded=False):
    c_set1, c_set2 = st.columns([2, 1])
    
    with c_set1:
        app_mode = st.radio(
            "功能模式", 
            ["📊 庫存/分析 (V13)", "⚡ AI 短線狙擊 (V16)"], 
            horizontal=True,
            label_visibility="collapsed"
        )
    
    with c_set2:
        if "GEMINI_API_KEY" in st.secrets:
            gemini_key = st.secrets["GEMINI_API_KEY"]
            st.success("API Key 鎖定")
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
# Mode 1: Inventory/Analysis (V13)
# ==========================================
if app_mode == "📊 庫存/分析 (V13)":
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
            placeholder="📦 從庫存選擇 (點擊自動填入)",
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

        st.caption(f"📊 {final_ticker_name}")

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
            
            color_cls = "up-color" if change > 0 else "down-color" if change < 0 else "no-color"
            sign = "+" if change > 0 else ""
            
            mfi = safe_num('MFI_14')
            rsi = safe_num('RSI_14')
            bias = safe_num('BIAS_20')
            pe = info.get('trailingPE', '-') if info else '-'

            st.markdown(f"""
            <div class="metric-grid-3">
                <div class="metric-card">
                    <div class="metric-label">現價</div>
                    <div class="metric-value {color_cls}">{close:.0f}</div>
                    <div class="metric-delta {color_cls}">{sign}{pct:.2f}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">MFI (資金)</div>
                    <div class="metric-value">{mfi:.0f}</div>
                    <div class="metric-delta no-color">流量</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">RSI (強弱)</div>
                    <div class="metric-value">{rsi:.0f}</div>
                    <div class="metric-delta no-color">動能</div>
                </div>
            </div>
            <div class="metric-grid-2">
                <div class="metric-card">
                    <div class="metric-label">BIAS (乖離率)</div>
                    <div class="metric-value">{bias:.2f}%</div>
                    <div class="metric-delta">20日</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">PE (本益比)</div>
                    <div class="metric-value">{pe}</div>
                    <div class="metric-delta">估值</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            tabs = st.tabs(["K線", "指標"])

            with tabs[0]:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.03)
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(20).mean(), line=dict(color='orange', width=1), name='MA20'), row=1, col=1)
                if 'OBV' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], name='OBV', line=dict(color='cyan')), row=2, col=1)
                fig.update_layout(height=380, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=5,b=0), legend=dict(orientation="h", y=1, x=0, bgcolor='rgba(0,0,0,0)'))
                st.plotly_chart(fig, use_container_width=True)

            with tabs[1]:
                fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True)
                if 'MACDh_12_26_9' in df.columns: fig2.add_trace(go.Bar(x=df.index, y=df['MACDh_12_26_9'], marker_color='#29B6F6', name='MACD'), row=1, col=1)
                if 'STOCHk_9_3_3' in df.columns:
                    fig2.add_trace(go.Scatter(x=df.index, y=df['STOCHk_9_3_3'], line=dict(color='yellow', width=1), name='K'), row=2, col=1)
                    fig2.add_trace(go.Scatter(x=df.index, y=df['STOCHd_9_3_3'], line=dict(color='red', width=1), name='D'), row=2, col=1)
                fig2.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)

            st.markdown("---") 
            col_ai_btn, col_ai_res = st.columns([1, 4])
            with col_ai_btn:
                if st.button("🚀 AI 全面狙擊", use_container_width=True):
                    if st.session_state.financials is None:
                        with st.spinner("下載財報中..."):
                            inc, bal, cash = get_financial_data(final_ticker_code)
                            st.session_state.financials = (inc, bal, cash)
                    report = generate_sniper_report(final_ticker_name, df, info, st.session_state.financials, gemini_key)
                    st.session_state.sniper_report = report
                    st.rerun()

            if st.session_state.sniper_report:
                st.markdown(st.session_state.sniper_report)
                if st.button("🗑️ 清除報告", key="cls_rpt"):
                    st.session_state.sniper_report = None
                    st.rerun()

# ==========================================
# Mode 2: AI Sniper (V16 Hybrid Realtime)
# ==========================================
elif app_mode == "⚡ AI 短線狙擊 (V16)":
    
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()
    if time.time() - st.session_state.last_refresh > 60:
        st.session_state.last_refresh = time.time()
        st.rerun()

    tz = pytz.timezone('Asia/Taipei')
    now_tw = datetime.datetime.now(tz)
    st.caption(f"⚡ V16.4 狙擊模式 | Auto: 60s | Last: {now_tw.strftime('%H:%M:%S')} (TW)")

    col_in1, col_in2 = st.columns([2, 1])
    with col_in1:
        sniper_input = st.text_input("🎯 狙擊目標 (Stock)", value=st.session_state.active_ticker, placeholder="輸入代號")
        if sniper_input != st.session_state.active_ticker:
            st.session_state.active_ticker = sniper_input

    with col_in2:
        entry_cost = st.number_input("💲 進場成本 (選填)", value=0.0, step=0.5, placeholder="成本")

    target_code = sniper_input.strip()

    if 'last_sniper_code' not in st.session_state:
        st.session_state.last_sniper_code = ""

    if st.session_state.last_sniper_code != target_code:
        st.session_state.v14_sniper_advice = None
        st.session_state.last_sniper_code = target_code

    try: target_name = twstock.codes[target_code].name
    except: target_name = target_code
    
    # Fetch Data (Hybrid: YF History + Twstock Realtime)
    df_1m, yesterday_vol, prev_close, real_price = get_intraday_sniper_data(target_code)
    
    # Data Validation
    is_data_valid = False
    if df_1m is not None and not df_1m.empty and prev_close is not None:
        latest_data_date = df_1m.index[-1].date()
        today_date = now_tw.date()
        
        # If Twstock returned a real price, use it
        if real_price:
            curr_price = real_price
            is_data_valid = True
        else:
            # Fallback to chart data
            curr_price = df_1m.iloc[-1]['Close']
            if latest_data_date == today_date:
                is_data_valid = True
            else:
                st.warning(f"⚠️ 圖表數據為 {latest_data_date}，且無法取得即時報價。")
                st.info("原因：非開盤時間或 API 延遲。")
    
    if df_1m is not None and not df_1m.empty and prev_close is not None:
        last_bar = df_1m.iloc[-1]
        if not real_price: curr_price = last_bar['Close']
        open_price = df_1m.iloc[0]['Open']
        
        # --- V16.3 Core Logic (Correct Calculation + Safe Filter) ---

        # 1. Base Metrics
        trend_pct = ((curr_price - prev_close) / prev_close) * 100 
        
        # [Fix] Abs calculation for display accuracy (handles Black Candle)
        body_delta = curr_price - open_price
        body_len = abs(body_delta)
        
        # Body Pct (Signed) for Qualification Filter
        body_pct = (body_delta / prev_close) * 100 
        
        # Upper Shadow (Logic: High - Max(Open, Close))
        # Note: If real_price > chart high, we assume real_price is new high
        current_high = max(last_bar['High'], curr_price)
        upper_shadow = current_high - max(open_price, curr_price)
        
        # [Fix] Use 0.01 to allow calculation for display, BUT Safety is ensured by cond_qualify
        shadow_ratio = (upper_shadow / body_len) if body_len > 0.01 else 99.9 
        
        cum_vol = last_bar['Cum_Vol']
        vol_ratio = (cum_vol / yesterday_vol) * 100 if yesterday_vol > 0 else 0

        # 2. Time & Volume Filters
        current_time = now_tw.time()
        
        t_0905 = datetime.time(9, 5)
        t_0915 = datetime.time(9, 15)
        t_1000 = datetime.time(10, 0)
        t_1030 = datetime.time(10, 30)

        cond_vol = False
        vol_msg = "量能不足"
        
        if current_time < t_0905:
            cond_vol = False
            vol_msg = "⛔ 09:05前避險"
        elif current_time < t_0915:
            cond_vol = vol_ratio >= 10
            vol_msg = f"> 10% ({vol_ratio:.1f}%)"
        elif current_time < t_1000:
            cond_vol = vol_ratio >= 20
            vol_msg = f"> 20% ({vol_ratio:.1f}%)"
        else:
            cond_vol = vol_ratio >= 30
            vol_msg = f"> 30% ({vol_ratio:.1f}%)"
            
        # 3. Qualification & Shadow Filter (Strict Logic)
        cond_qualify = (curr_price > open_price) and (2 <= trend_pct <= 8) and (body_pct >= 0.2)
        cond_shadow = shadow_ratio <= 0.5
        cond_time = current_time <= t_1030

        # 4. Final Signal
        final_signal = cond_qualify and cond_shadow and cond_vol and cond_time and is_data_valid

        # 5. Trailing Stop Logic (UI Display)
        cost_base = entry_cost if entry_cost > 0 else curr_price
        roi_pct = ((curr_price - cost_base) / cost_base) * 100
        
        trailing_msg = "Phase 1: 蓄力"
        trailing_sl = cost_base * 0.975 # Default Phase 1
        
        if roi_pct > 5: # Phase 3
            trailing_msg = "Phase 3: 🚀 鎖利"
            trailing_sl = curr_price * 0.975 # Trail 2.5%
        elif roi_pct > 2: # Phase 2
            trailing_msg = "Phase 2: 🛡️ 保本"
            trailing_sl = cost_base * 1.005 # Cost + 0.5%
        
        # --- UI Display ---
        
        c1, c2, c3, c4 = st.columns(4)
        def signal_html(text, is_pass, fail_color="signal-gray"):
            color = "signal-green" if is_pass else fail_color
            return f'<div class="signal-box {color}">{text}</div>'

        with c1: 
            p_text = f"資格審查<br>{trend_pct:.1f}% / 實{body_pct:.1f}%"
            st.markdown(signal_html(p_text, cond_qualify), unsafe_allow_html=True)
            
        with c2: 
            s_text = f"避雷針<br>R: {shadow_ratio:.1f}"
            st.markdown(signal_html(s_text, cond_shadow, "signal-red"), unsafe_allow_html=True)
            
        with c3: 
            st.markdown(signal_html(f"動態量能<br>{vol_msg}", cond_vol), unsafe_allow_html=True)
            
        with c4: 
            t_text = "時間窗口<br>OK" if cond_time else "⛔ 逾時"
            st.markdown(signal_html(t_text, cond_time, "signal-gray"), unsafe_allow_html=True)

        if not is_data_valid:
             st.error("⛔ 資料過時或無法取得即時報價，請稍後再試。")
        else:
            if final_signal: st.success(f"🎯 V16 訊號確認！狙擊 {target_name}")
            elif not cond_qualify: st.warning("⚠️ 資格不符：需 紅K + 漲幅2~8% + 實體>0.2%")
            elif not cond_shadow: st.warning("⚠️ 避雷針警報：上影線過長，賣壓沈重")
            elif not cond_vol: st.info(f"⏳ 等待補量：{vol_msg}")
            else: st.info("⏳ 監控中...")

        # Chart
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], vertical_spacing=0.02)
        fig.add_trace(go.Candlestick(x=df_1m.index, open=df_1m['Open'], high=df_1m['High'], low=df_1m['Low'], close=df_1m['Close'], name='Price'), row=1, col=1)
        
        if 'BBU_20_2.0' in df_1m.columns:
            fig.add_trace(go.Scatter(x=df_1m.index, y=df_1m['BBU_20_2.0'], line=dict(color='yellow', width=1), name='Upper'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_1m.index, y=df_1m['BBM_20_2.0'], line=dict(color='orange', width=1), name='MA20'), row=1, col=1)
        
        if entry_cost > 0:
            fig.add_hline(y=entry_cost, line_dash="dash", line_color="white", row=1, col=1, annotation_text="成本")
            fig.add_hline(y=trailing_sl, line_color="#FF00FF", row=1, col=1, annotation_text="停損/利")

        colors = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df_1m.iterrows()]
        fig.add_trace(go.Bar(x=df_1m.index, y=df_1m['Volume'], marker_color=colors, name='Vol'), row=2, col=1)
        fig.update_layout(height=400, template="plotly_dark", margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown(f"""
        <div class="metric-grid-2">
            <div class="metric-card"><div class="metric-label">策略階段</div><div class="metric-value up-color">{trailing_msg}</div></div>
            <div class="metric-card"><div class="metric-label">執行點位 (Stop)</div><div class="metric-value down-color">{trailing_sl:.1f}</div></div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        
        if 'v14_sniper_advice' not in st.session_state:
            st.session_state.v14_sniper_advice = None

        if st.button("🤖 呼叫 V16 狙擊顧問", use_container_width=True):
            with st.spinner("V16 邏輯運算中..."):
                v16_status = {
                    "資格審查 (Trend 2-8% + Body > 0.2%)": cond_qualify,
                    "避雷針濾網 (Shadow < 0.5 Body)": cond_shadow,
                    "動態量能 (分時門檻)": cond_vol,
                    "時間窗口 (09:05-10:30)": cond_time
                }
                
                advice = generate_sniper_advice(
                    target_name, target_code, 
                    curr_price, open_price, prev_close,
                    vol_ratio, shadow_ratio, body_pct, trend_pct,
                    v16_status, entry_cost, gemini_key
                )
                st.session_state.v14_sniper_advice = advice
        
        if st.session_state.v14_sniper_advice:
            st.markdown(st.session_state.v14_sniper_advice)

    else:
        st.warning("今日尚未開盤或無資料")
