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
# 資料獲取模組 (通用)
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

def get_fred_history(series_id):
    """抓取 FRED 歷史數據 (序列)"""
    if not FRED_API_KEY: return []
    url = "https://api.stlouisfed.org/fred/series/observations"
    start_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")
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
        closes = r['chart']['result'][0]['indicators']['quote'][0]['close']
        timestamps = r['chart']['result'][0]['timestamp']
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

# ===================================================================
# Z-Score 計算核心
# ===================================================================

def calculate_z_score(jp_10y_now):
    print("\n--- Starting Z-Score Calculation ---")
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
            return z, today_r, mean, std, latest_s, latest_m2
    except: return None
    return None

# ===================================================================
# 主程式：產生 全功能 JSON
# ===================================================================

def generate_app_data():
    print("🚀 Starting Monitor Lite (Full Pack Version)...")
    
    # 1. 基礎數據
    jp_10y_val = get_jgb_10y_realtime()
    
    # 2. 額外 FRED 數據 (幫 App 預先抓好)
    sofr, sofr_date = get_fred_latest("SOFR")
    iorb, iorb_date = get_fred_latest("IORB")
    us_3m, _ = get_fred_latest("DTB3")
    jp_3m, _ = get_fred_latest("IR3TIB01JPM156N")
    
    # 3. 計算 Z-Score
    z_res = calculate_z_score(jp_10y_val)
    z_score = 0; mean_val = 0; std_val = 0; today_r = 0; w5000 = 0; m2 = 0; status = "Data Error"
    
    if z_res:
        z_score, today_r, mean_val, std_val, w5000, m2 = z_res
        status = "Critical" if z_score > 2.0 else "Warning" if z_score > 1.0 else "Normal"

    # 4. 打包 JSON (包含所有原料)
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_data": {
            "jp_10y": round(jp_10y_val, 3) if jp_10y_val else 0.0,
            "us_3m": round(us_3m, 3) if us_3m else 0.0,   # 來自 FRED DTB3
            "jp_3m": round(jp_3m, 3) if jp_3m else 0.0,   # 來自 FRED IR3TIB...
            "sofr": round(sofr, 2) if sofr else 0.0,      # 來自 FRED SOFR
            "iorb": round(iorb, 2) if iorb else 0.0,      # 來自 FRED IORB
            "sofr_date": sofr_date if sofr_date else ""
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
        }
    }

    with open("vip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    
    print("✅ vip_data.json generated with FULL FRED DATA.")

if __name__ == "__main__":
    generate_app_data()
