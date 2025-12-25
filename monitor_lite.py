import requests
import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup

# ===================================================================
# 設定與參數 (GitHub Actions 會讀取環境變數)
# ===================================================================
FRED_API_KEY = os.environ.get("FRED_API_KEY")

# API URL
NYFED_API_BASE = "https://markets.newyorkfed.org/api/rp/results/search.json"

# ===================================================================
# 核心資料獲取函式
# ===================================================================

def get_fred_data(series_id):
    if not FRED_API_KEY: return None, None
    url = f"https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 1}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        obs = data.get("observations", [])
        if obs and obs[0]["value"] != ".": return float(obs[0]["value"]), obs[0]["date"]
        return None, None
    except: return None, None

def get_fred_history(series_id):
    if not FRED_API_KEY: return []
    url = f"https://api.stlouisfed.org/fred/series/observations"
    start_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "observation_start": start_date}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        clean_data = []
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                clean_data.append({"date": obs["date"], "value": float(obs["value"])})
        return clean_data
    except: return []

def get_yahoo_data(symbol):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        result = data.get("chart", {}).get("result", [])
        if not result: return None, None
        quote = result[0].get("indicators", {}).get("quote", [])[0]
        closes = quote.get("close", [])
        for i in range(len(closes)-1, -1, -1):
            if closes[i] is not None:
                return float(closes[i]), None
        return None, None
    except: return None, None

def get_yahoo_history(symbol, range_str="5y"):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        result = data.get("chart", {}).get("result", [])
        if not result: return []
        quote = result[0].get("indicators", {}).get("quote", [])[0]
        closes = quote.get("close", [])
        timestamps = result[0].get("timestamp", [])
        data_points = []
        for i in range(len(closes)):
            if closes[i] is not None:
                dt = datetime.fromtimestamp(timestamps[i]).strftime('%Y-%m-%d')
                data_points.append({"date": dt, "price": float(closes[i])})
        return data_points
    except: return []

def get_yahoo_history_prices_only(symbol, range_str="6mo"):
    data = get_yahoo_history(symbol, range_str)
    return [d['price'] for d in data]

def get_yahoo_realtime_data(symbol):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        meta = data['chart']['result'][0]['meta']
        return meta['regularMarketPrice'], meta['regularMarketTime']
    except: return None, None

# ===================================================================
# 核心計算模組
# ===================================================================

def get_us_3m_yield():
    val, _ = get_yahoo_data("^IRX")
    if val is not None: return val
    val, _ = get_fred_data("DTB3")
    return val if val else 3.5

def get_jgb_10y_realtime():
    try:
        url = "https://www.cnbc.com/quotes/JP10Y"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        val = soup.select_one('.QuoteStrip-lastPrice')
        if val: return float(val.text.strip().replace('%', ''))
    except: pass
    val, _ = get_fred_data("IRLTLT01JPM156N")
    return val if val else 1.5

def get_jp_3m_yield():
    val, _ = get_fred_data("IR3TIB01JPM156N")
    return val if val else 0.75

def get_next_cme_expiry():
    today = date.today()
    expiry_months = [3, 6, 9, 12]
    candidates = []
    for year in [today.year, today.year + 1]:
        for month in expiry_months:
            first_day = date(year, month, 1)
            first_wed = first_day + timedelta(days=(2 - first_day.weekday() + 7) % 7)
            expiry = first_wed + timedelta(days=14) - timedelta(days=2)
            candidates.append(expiry)
    for d in candidates:
        if d > today: return (d - today).days
    return 90

def calculate_xccy_basis():
    try:
        spot, spot_ts = get_yahoo_realtime_data("JPY=X")
        if not spot: return None, 0
        future, future_ts = get_yahoo_realtime_data("6J=F")
        if not future: return None, 0
        
        lag_min = abs(spot_ts - future_ts) / 60
        forward = 1 / future
        us_3m = get_us_3m_yield()
        jp_3m = get_jp_3m_yield()
        t = get_next_cme_expiry() / 360.0
        if t < 0.01: t = 0.25

        r_j_implied = ((forward / spot) * (1 + (us_3m/100) * t) - 1) / t
        basis = (r_j_implied - (jp_3m/100)) * 10000
        return basis, lag_min
    except: return None, 0

def calculate_carry_to_risk():
    try:
        us_10y, _ = get_yahoo_data("^TNX")
        if not us_10y: return 0, 0, 0, 0, 0
        jp_10y = get_jgb_10y_realtime()
        carry = us_10y - jp_10y
        
        hist = get_yahoo_history_prices_only("JPY=X", "3mo")
        vol = 0
        if len(hist) >= 20:
            vol = pd.Series(hist).pct_change().dropna().std() * np.sqrt(252) * 100
            
        ratio = carry / vol if vol != 0 else 0
        return us_10y, jp_10y, carry, vol, ratio
    except: return 0, 0, 0, 0, 0

def calculate_z_score(current_jp_yield):
    try:
        stock_data = get_yahoo_history("^W5000", "5y")
        tnx_data = get_yahoo_history("^TNX", "5y")
        m2_data = get_fred_history("M2SL")
        jgb_data = get_fred_history("IRLTLT01JPM156N")
        
        if not stock_data or not tnx_data or not m2_data: return None

        df_stock = pd.DataFrame(stock_data).set_index("date")
        df_tnx = pd.DataFrame(tnx_data).set_index("date")
        df_m2 = pd.DataFrame(m2_data).set_index("date")
        df_jgb = pd.DataFrame(jgb_data).set_index("date")
        
        for df in [df_stock, df_tnx, df_m2, df_jgb]:
            df.index = pd.to_datetime(df.index)

        # Resample Monthly
        df_s_m = df_stock.resample('ME').last()
        df_t_m = df_tnx.resample('ME').last()
        df_s_m.index = df_s_m.index.to_period('M')
        df_t_m.index = df_t_m.index.to_period('M')
        df_m2.index = df_m2.index.to_period('M')
        df_jgb.index = df_jgb.index.to_period('M')
        
        df = df_s_m.join(df_t_m, lsuffix='_s', rsuffix='_t').join(df_m2, rsuffix='_m').join(df_jgb, rsuffix='_j')
        df['value'] = df['value'].ffill()
        df['value_jgb'] = df['value_jgb'].ffill()
        df = df.dropna()
        
        # Calc History
        df['spread'] = (df['price_t'] - df['value_jgb']).apply(lambda x: x if x > 0.1 else 0.1)
        df['ratio'] = (df['price_s'] / df['value']) / df['spread']
        
        # Calc Today
        if current_jp_yield is not None:
            latest_s = df_stock['price'].iloc[-1]
            latest_t = df_tnx['price'].iloc[-1]
            latest_m2 = df['value'].iloc[-1]
            real_spread = latest_t - current_jp_yield
            if real_spread < 0.1: real_spread = 0.1
            today_r = (latest_s / latest_m2) / real_spread
            
            # Z-Score (n=12)
            if len(df) >= 12:
                win = df['ratio'].tail(12)
                mean = win.mean()
                std = win.std()
                z = (today_r - mean) / std if std != 0 else 0
                return z, today_r, mean, std, latest_s, latest_m2
                
        return None
    except: return None

# ===================================================================
# 主程式：產生 JSON
# ===================================================================

def generate_app_data():
    print("🚀 Starting Monitor Lite for GitHub Actions...")
    
    # 1. Carry Trade
    us_10y, jp_10y, carry, vol, carry_ratio = calculate_carry_to_risk()
    
    # 2. Basis
    basis_bps, lag_min = calculate_xccy_basis()
    
    # 3. Z-Score
    z_res = calculate_z_score(jp_10y)
    z_score = mean_val = std_val = w5000 = m2 = 0
    today_r = 0
    if z_res:
        z_score, today_r, mean_val, std_val, w5000, m2 = z_res

    # 4. JSON Payload
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "z_score": {
            "value": round(z_score, 2),
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "status": "Critical" if z_score > 2.0 else "Warning" if z_score > 1.0 else "Normal",
            "history_debug": [
                f"S:{w5000:.0f} | M2:{m2:.0f}",
                f"Spr:{(us_10y-jp_10y):.2f}% | R:{today_r:.4f}" if z_res else ""
            ]
        },
        "xccy_basis": {
            "value": round(basis_bps, 2) if basis_bps else 0.0,
            "lag_minutes": int(lag_min),
            "is_stale": lag_min > 60
        },
        "carry_trade": {
            "ratio": round(carry_ratio, 2),
            "us_10y": round(us_10y, 2),
            "jp_10y": round(jp_10y, 2)
        }
    }

    # Save to file
    with open("vip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    
    print("✅ vip_data.json generated successfully.")

if __name__ == "__main__":
    generate_app_data()
