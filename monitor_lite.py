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
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ===================================================================
# 資料獲取
# ===================================================================

def get_fred_history(series_id):
    if not FRED_API_KEY:
        print(f"❌ [FRED] API Key is missing! Cannot fetch {series_id}")
        return []
    
    url = f"https://api.stlouisfed.org/fred/series/observations"
    start_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "observation_start": start_date}
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        clean_data = []
        if "observations" not in data:
            print(f"❌ [FRED] Error fetching {series_id}: {data}")
            return []
            
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                clean_data.append({"date": obs["date"], "value": float(obs["value"])})
        print(f"✅ [FRED] Fetched {len(clean_data)} records for {series_id}")
        return clean_data
    except Exception as e:
        print(f"❌ [FRED] Exception for {series_id}: {e}")
        return []

def get_yahoo_history(symbol, range_str="5y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"❌ [Yahoo] Failed {symbol}: Status {response.status_code}")
            return []
            
        data = response.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            print(f"❌ [Yahoo] No data found for {symbol}")
            return []
            
        quote = result[0].get("indicators", {}).get("quote", [])[0]
        closes = quote.get("close", [])
        timestamps = result[0].get("timestamp", [])
        
        clean_data = []
        for i in range(len(closes)):
            if closes[i] is not None:
                dt = datetime.fromtimestamp(timestamps[i]).strftime('%Y-%m-%d')
                clean_data.append({"date": dt, "price": float(closes[i])})
                
        print(f"✅ [Yahoo] Fetched {len(clean_data)} records for {symbol}")
        return clean_data
    except Exception as e:
        print(f"❌ [Yahoo] Exception for {symbol}: {e}")
        return []

def get_jgb_10y_realtime():
    # 嘗試抓取日債，失敗回傳 None，後面會處理
    try:
        url = "https://www.cnbc.com/quotes/JP10Y"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        val = soup.select_one('.QuoteStrip-lastPrice')
        if val: return float(val.text.strip().replace('%', ''))
    except: pass
    
    # 備案：從 FRED 抓最新一筆
    try:
        hist = get_fred_history("IRLTLT01JPM156N")
        if hist: return hist[-1]['value']
    except: pass
    
    return 2.05 # 最後保底值

# ===================================================================
# 計算核心
# ===================================================================

def calculate_z_score(jp_10y_now):
    print("\n--- Starting Z-Score Calculation ---")
    
    stock_data = get_yahoo_history("^W5000", "5y")
    tnx_data = get_yahoo_history("^TNX", "5y")
    m2_data = get_fred_history("M2SL")
    jgb_data = get_fred_history("IRLTLT01JPM156N")
    
    if not stock_data or not tnx_data or not m2_data:
        print("❌ Critical Data Missing! Aborting.")
        return None

    try:
        df_stock = pd.DataFrame(stock_data).set_index("date")
        df_tnx = pd.DataFrame(tnx_data).set_index("date")
        df_m2 = pd.DataFrame(m2_data).set_index("date")
        df_jgb = pd.DataFrame(jgb_data).set_index("date")
        
        for df in [df_stock, df_tnx, df_m2, df_jgb]:
            df.index = pd.to_datetime(df.index)

        # Resample
        df_s_m = df_stock.resample('ME').last()
        df_t_m = df_tnx.resample('ME').last()
        df_s_m.index = df_s_m.index.to_period('M')
        df_t_m.index = df_t_m.index.to_period('M')
        df_m2.index = df_m2.index.to_period('M')
        df_jgb.index = df_jgb.index.to_period('M')
        
        df = df_s_m.join(df_t_m, lsuffix='_s', rsuffix='_t') \
                   .join(df_m2, rsuffix='_m') \
                   .join(df_jgb, rsuffix='_jgb')
                   
        df['value'] = df['value'].ffill()       # M2
        df['value_jgb'] = df['value_jgb'].ffill() # JGB
        df = df.dropna()
        
        # Calc History
        df['spread'] = (df['price_t'] - df['value_jgb']).apply(lambda x: x if x > 0.1 else 0.1)
        df['ratio'] = (df['price_s'] / df['value']) / df['spread']
        
        # Calc Today
        latest_s = stock_data[-1]['price']
        latest_t = tnx_data[-1]['price']
        latest_m2 = m2_data[-1]['value']
        
        real_spread = latest_t - jp_10y_now
        if real_spread < 0.1: real_spread = 0.1
        today_r = (latest_s / latest_m2) / real_spread
        
        # Z-Score (n=12)
        if len(df) >= 12:
            win = df['ratio'].tail(12)
            mean = win.mean()
            std = win.std()
            z = (today_r - mean) / std if std != 0 else 0
            
            print(f"✅ Calculation Success: Z={z:.2f}, R={today_r:.2f}, Mean={mean:.2f}")
            return z, today_r, mean, std, latest_s, latest_m2
            
    except Exception as e:
        print(f"❌ Calculation Error: {e}")
        return None
        
    return None

# ===================================================================
# 主程式：產生精簡版 JSON (含 JP10Y)
# ===================================================================

def generate_app_data():
    print("🚀 Starting Monitor Lite (Clean Version)...")
    
    # 1. 獲取即時日債 (App 抓不到，所以這裡幫它抓)
    jp_10y_val = get_jgb_10y_realtime()
    print(f"🇯🇵 JP 10Y Yield: {jp_10y_val}%")

    # 2. 計算 Z-Score (傳入日債)
    z_res = calculate_z_score(jp_10y_val)
    
    # 預設值
    z_score = 0.0
    mean_val = 0.0
    std_val = 0.0
    today_r = 0.0
    w5000 = 0.0
    m2 = 0.0
    status = "Data Error"

    if z_res:
        z_score, today_r, mean_val, std_val, w5000, m2 = z_res
        status = "Critical" if z_score > 2.0 else "Warning" if z_score > 1.0 else "Normal"
    else:
        print("⚠️ Z-Score calculation failed. Outputting zeros.")

    # 3. 產生 JSON (追加 jp_10y 欄位)
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "jp_10y": round(jp_10y_val, 3) if jp_10y_val else 0.0, # <--- 這是給 App 用的新欄位
        "z_score": {
            "value": round(z_score, 2),
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "status": status,
            "history_debug": [
                f"S:{w5000:.0f} | M2:{m2:.0f}",
                f"R:{today_r:.4f} (Mean:{mean_val:.2f})" if z_res else "Data Missing"
            ]
        }
    }

    # 寫入檔案
    with open("vip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    
    print("✅ vip_data.json generated (Lite Version).")

if __name__ == "__main__":
    generate_app_data()
