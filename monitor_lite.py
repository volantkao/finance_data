import requests
import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup

# ===================================================================
# 設定與參數
# ===================================================================
FRED_API_KEY = os.environ.get("FRED_API_KEY")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# ===================================================================
# 資料獲取模組
# ===================================================================

def get_fred_latest(series_id):
    """抓取 FRED 最新的一筆數據 (單點)"""
    if not FRED_API_KEY: return None, None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=10).json()
        obs = r.get('observations', [])[0]
        return float(obs['value']), obs['date']
    except: return None, None

def get_fred_history(series_id, days=1825):
    """抓取 FRED 歷史數據 (序列)"""
    if not FRED_API_KEY: return []
    url = "https://api.stlouisfed.org/fred/series/observations"
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "observation_start": start_date}
    try:
        r = requests.get(url, params=params, timeout=15).json()
        clean = []
        for obs in r.get('observations', []):
            if obs['value'] != '.':
                clean.append({'date': obs['date'], 'value': float(obs['value'])})
        return clean
    except: return []

def get_yahoo_history(symbol, range_str="5y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15).json()
        result = r['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        timestamps = result['timestamp']
        clean = []
        for i in range(len(closes)):
            if closes[i] is not None:
                dt = datetime.fromtimestamp(timestamps[i]).strftime('%Y-%m-%d')
                clean.append({'date': dt, 'price': float(closes[i])})
        return clean
    except: return []

def get_jgb_10y_realtime():
    # 優先嘗試 CNBC
    try:
        url = "https://www.cnbc.com/quotes/JP10Y"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        val = soup.select_one('.QuoteStrip-lastPrice')
        if val: return float(val.text.strip().replace('%', ''))
    except: pass
    # 備案 FRED
    val, _ = get_fred_latest("IRLTLT01JPM156N")
    return val if val else 2.05

def get_srf_usage():
    """從紐約聯儲抓取 SRF (Standing Repo Facility) 使用量"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        url = "https://markets.newyorkfed.org/api/rp/results/search.json"
        params = {"startDate": start_date, "endDate": today, "format": "json"}
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        data = response.json()
        
        ops = []
        if "repo" in data and "operations" in data["repo"]: ops = data["repo"]["operations"]
        elif "repoOperations" in data:
            temp = data["repoOperations"]
            if isinstance(temp, dict) and "operations" in temp: ops = temp["operations"]
            elif isinstance(temp, list): ops = temp
            
        if not ops: return 0.0, ""
        repo_ops = [op for op in ops if op.get("operationType", "") == "Repo"]
        if not repo_ops: return 0.0, ""
        
        latest_op = max(repo_ops, key=lambda x: x.get("operationDate", "0000-00-00"))
        raw_amt = latest_op.get("totalAmtAccepted", 0)
        if isinstance(raw_amt, str): raw_amt = float(raw_amt.replace(",", ""))
        
        return float(raw_amt), latest_op.get("operationDate")
    except: return 0.0, ""

# ===================================================================
# 計算核心 (含原料生產)
# ===================================================================

def calculate_z_score(jp_10y_now):
    print("\n--- Calculating Vuln Z-Score & Params ---")
    stock_data = get_yahoo_history("^W5000", "5y")
    tnx_data = get_yahoo_history("^TNX", "5y")
    m2_data = get_fred_history("M2SL")
    jgb_data = get_fred_history("IRLTLT01JPM156N")
    
    if not stock_data or not tnx_data or not m2_data: return None

    try:
        df_stock = pd.DataFrame(stock_data).set_index("date")
        df_tnx = pd.DataFrame(tnx_data).set_index("date")
        df_m2 = pd.DataFrame(m2_data).set_index("date")
        df_jgb = pd.DataFrame(jgb_data).set_index("date")
        
        for df in [df_stock, df_tnx, df_m2, df_jgb]: df.index = pd.to_datetime(df.index)

        df_s_m = df_stock.resample('ME').last()
        df_t_m = df_tnx.resample('ME').last()
        df_s_m.index = df_s_m.index.to_period('M')
        df_t_m.index = df_t_m.index.to_period('M')
        df_m2.index = df_m2.index.to_period('M')
        df_jgb.index = df_jgb.index.to_period('M')
        
        df = df_s_m.join(df_t_m, lsuffix='_s', rsuffix='_t').join(df_m2, rsuffix='_m').join(df_jgb, rsuffix='_jgb')
        df['value'] = df['value'].ffill()
        df['value_jgb'] = df['value_jgb'].ffill()
        df = df.dropna()
        
        df['spread'] = (df['price_t'] - df['value_jgb']).apply(lambda x: x if x > 0.1 else 0.1)
        df['ratio'] = (df['price_s'] / df['value']) / df['spread']
        
        # Server-side calculation (Snapshot)
        latest_s = stock_data[-1]['price']
        latest_t = tnx_data[-1]['price']
        latest_m2 = m2_data[-1]['value']
        
        real_spread = latest_t - jp_10y_now
        if real_spread < 0.1: real_spread = 0.1
        today_r = (latest_s / latest_m2) / real_spread
        
        if len(df) >= 12:
            win = df['ratio'].tail(12)
            mean = win.mean()
            std = win.std()
            z = (today_r - mean) / std if std != 0 else 0
            
            # [App 原料]
            app_params = {
                "m2": latest_m2,
                "jgb_10y": jp_10y_now,
                "mean": mean,
                "std": std
            }
            return z, today_r, mean, std, latest_s, latest_m2, app_params
            
    except: return None
    return None

def get_vol_stress_params():
    """生產 Vol Stress 所需的統計參數 (HV Mean, Std)"""
    print("\n--- Generating Vol Stress Params ---")
    try:
        hist = get_yahoo_history("JPY=X", "1y")
        if not hist: return None
        
        df = pd.DataFrame(hist)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        
        df['ret'] = df['price'].pct_change()
        df['hv'] = df['ret'].rolling(window=10).std() * np.sqrt(252) * 100
        df['slope'] = df['hv'].diff()
        df = df.dropna()
        
        if len(df) < 20: return None
        
        params = {
            "hv_mean": round(df['hv'].mean(), 4),
            "hv_std": round(df['hv'].std(), 4),
            "slope_mean": round(df['slope'].mean(), 4),
            "slope_std": round(df['slope'].std(), 4),
            "yesterday_hv": round(df['hv'].iloc[-1], 4)
        }
        return params
    except: return None

def generate_spread_history_for_app(days=150):
    """
    [新增] 為 App 準備最近 N 天的美日利差歷史數據 (日線)
    App 拿到這個 List 後，只要自己抓個股歷史股價，相除即可算出 Z-Score
    """
    print(f"\n--- Generating Spread History ({days} days) ---")
    try:
        # 1. 抓 US 10Y (Yahoo ^TNX, Daily)
        us_data = get_yahoo_history("^TNX", "1y")
        if not us_data: return []
        
        # 2. 抓 JP 10Y (FRED Monthly -> Resample to Daily)
        # 因為 App 抓不到日債，我們用 FRED 數據填充
        jp_data = get_fred_history("IRLTLT01JPM156N", 400)
        
        df_us = pd.DataFrame(us_data).set_index("date")
        df_us.index = pd.to_datetime(df_us.index)
        
        if jp_data:
            df_jp = pd.DataFrame(jp_data).set_index("date")
            df_jp.index = pd.to_datetime(df_jp.index)
            # 月資料轉日資料 (Forward Fill)
            df_jp = df_jp.resample('D').ffill()
        else:
            # Fallback: 如果抓不到，假設 1.0% (避免壞掉)
            df_jp = pd.DataFrame(index=df_us.index)
            df_jp['value'] = 1.0

        # 3. 合併計算利差
        df = df_us.join(df_jp, rsuffix='_jp')
        df['value'] = df['value'].ffill() # 填補 JP 空值
        df = df.dropna()
        
        # Spread = US - JP
        df['spread'] = df['price'] - df['value']
        df['spread'] = df['spread'].apply(lambda x: x if x > 0.1 else 0.1) # 防呆
        
        # 4. 取最近 N 天並轉為 List
        recent = df.tail(days)
        result_list = []
        for dt, row in recent.iterrows():
            result_list.append({
                "date": dt.strftime('%Y-%m-%d'),
                "spread": round(row['spread'], 4)
            })
            
        print(f"✅ Generated {len(result_list)} spread points.")
        return result_list
        
    except Exception as e:
        print(f"❌ Error generating spread history: {e}")
        return []

# ===================================================================
# 主程式：產生 全功能 JSON
# ===================================================================

def generate_app_data():
    print("🚀 Starting Monitor Lite (Full Pack + Spread History)...")
    
    # 1. 基礎數據
    jp_10y_val = get_jgb_10y_realtime()
    sofr, sofr_date = get_fred_latest("SOFR")
    iorb, iorb_date = get_fred_latest("IORB")
    us_3m, _ = get_fred_latest("DTB3")
    jp_3m, _ = get_fred_latest("IR3TIB01JPM156N")
    
    # 2. 風險指標
    hy_oas, _ = get_fred_latest("BAMLH0A0HYM2")
    baa_spread, _ = get_fred_latest("BAA10Y")
    fin_stress, _ = get_fred_latest("STLFSI3")
    srf_amt, srf_dt = get_srf_usage()
    srf_billions = srf_amt / 1000000000 

    # 3. 計算 Z-Score (Server Snapshot)
    z_res = calculate_z_score(jp_10y_val)
    z_score = 0; mean_val = 0; std_val = 0; today_r = 0; w5000 = 0; m2 = 0; status = "Data Error"
    vuln_params = {}
    
    if z_res:
        z_score, today_r, mean_val, std_val, w5000, m2, vuln_params = z_res
        status = "Critical" if z_score > 2.0 else "Warning" if z_score > 1.0 else "Normal"

    # 4. 計算參數
    vol_params = get_vol_stress_params()
    # [新增] 產生 150 天利差歷史供 App 使用 (足夠算 120MA)
    spread_history = generate_spread_history_for_app(150)

    # 5. 打包 JSON
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        
        "market_data": {
            "jp_10y": round(jp_10y_val, 3) if jp_10y_val else 0.0,
            "us_3m": round(us_3m, 3) if us_3m else 0.0,
            "jp_3m": round(jp_3m, 3) if jp_3m else 0.0,
            "sofr": round(sofr, 2) if sofr else 0.0,
            "iorb": round(iorb, 2) if iorb else 0.0,
            "sofr_date": sofr_date if sofr_date else ""
        },
        
        "risk_indicators": {
            "high_yield_oas": round(hy_oas, 2) if hy_oas else 0.0,
            "baa_spread": round(baa_spread, 2) if baa_spread else 0.0,
            "financial_stress": round(fin_stress, 2) if fin_stress else 0.0,
            "srf_usage": round(srf_billions, 2),
            "srf_date": srf_dt if srf_dt else ""
        },

        "z_score": {
            "value": round(z_score, 2),
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "status": status,
            "details": {
                "w5000": round(w5000, 0),
                "m2": round(m2, 1),
                "ratio": round(today_r, 4)
            },
            "history_debug": [
                f"S:{w5000:.0f} | M2:{m2:.0f}",
                f"R:{today_r:.4f} (Mean:{mean_val:.2f})" if z_res else "Data Missing"
            ]
        },

        "client_side_params": {
            # 1. 泡沫壓力計 (App Live Calc)
            "market_vuln": {
                "m2_supply": vuln_params.get("m2", 0),
                "jgb_10y": vuln_params.get("jgb_10y", 1.5),
                "hist_mean": vuln_params.get("mean", 0),
                "hist_std": vuln_params.get("std", 1)
            },
            # 2. 恐慌偵測器 (App Live Calc)
            "vol_stress": {
                "hv_mean": vol_params.get("hv_mean", 0) if vol_params else 0,
                "hv_std": vol_params.get("hv_std", 1) if vol_params else 1,
                "slope_mean": vol_params.get("slope_mean", 0) if vol_params else 0,
                "slope_std": vol_params.get("slope_std", 1) if vol_params else 1,
                "yesterday_hv": vol_params.get("yesterday_hv", 0) if vol_params else 0
            },
            # 3. [新增] 120天美日利差歷史 (for Free User 股價評分)
            # App 邏輯: 
            #   1. 用戶查 "TSLA" -> App 抓 TSLA 150天收盤價
            #   2. App 對齊這份 spread_history (by date)
            #   3. 計算 Ratio = Stock_Price / Spread (每天算)
            #   4. 算出這串 Ratio 的 Z-Score (顯示給用戶)
            "spread_history_150d": spread_history
        }
    }

    with open("vip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    
    print("✅ vip_data.json generated with Spread History.")

if __name__ == "__main__":
    generate_app_data()
