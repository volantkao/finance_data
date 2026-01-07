import requests
import json
import os
import pandas as pd
import numpy as np
import urllib3
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FRED_API_KEY = os.environ.get("FRED_API_KEY")
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
}

# ===================================================================
# 資料獲取模組
# ===================================================================

def get_fred_latest(series_id):
    if not FRED_API_KEY: return None, None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=10).json()
        obs = r.get('observations', [])[0]
        return float(obs['value']), obs['date']
    except: return None, None

def get_fred_history(series_id, days=1825):
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
        volumes = result['indicators']['quote'][0].get('volume', [])
        timestamps = result['timestamp']
        clean = []
        for i in range(len(closes)):
            if closes[i] is not None:
                dt = datetime.fromtimestamp(timestamps[i]).strftime('%Y-%m-%d')
                vol = volumes[i] if volumes and i < len(volumes) and volumes[i] is not None else 0
                clean.append({'date': dt, 'price': float(closes[i]), 'volume': float(vol)})
        return clean
    except: return []

def get_jgb_10y_realtime():
    try:
        url = "https://www.cnbc.com/quotes/JP10Y"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        val = soup.select_one('.QuoteStrip-lastPrice')
        if val: return float(val.text.strip().replace('%', ''))
    except: pass
    val, _ = get_fred_latest("IRLTLT01JPM156N")
    return val if val else 2.05

def get_srf_usage():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = "https://markets.newyorkfed.org/api/rp/results/search.json"
        params = {"startDate": start_date, "endDate": today, "format": "json"}
        response = requests.get(url, headers=HEADERS, params=params, timeout=15, verify=False)
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
# 計算核心
# ===================================================================

def calculate_zscore(series):
    if len(series) < 2: return 0
    return (series.iloc[-1] - series.mean()) / series.std()

def calculate_slope(prices):
    if not prices or len(prices) < 2: return 0.0
    n = len(prices); x = list(range(n)); y = prices
    sum_x = sum(x); sum_y = sum(y); sum_xy = sum(i * j for i, j in zip(x, y)); sum_xx = sum(i * i for i in x)
    den = (n * sum_xx - sum_x * sum_x)
    if den == 0: return 0.0
    slope = (n * sum_xy - sum_x * sum_y) / den
    return slope

# 1. Vuln Z-Score [修復：完整邏輯回歸]
def calculate_z_score(jp_10y_now):
    print("\n--- Calculating Vuln Z-Score ---")
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
        
        # Snapshot calculation
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
            
            app_params = {"m2": latest_m2, "jgb_10y": jp_10y_now, "mean": mean, "std": std}
            return z, today_r, mean, std, latest_s, latest_m2, app_params
            
    except Exception as e:
        print(f"Vuln Calc Error: {e}")
        return None
    return None

# 2. Vol Stress
def get_vol_stress_params():
    try:
        hist = get_yahoo_history("JPY=X", "1y")
        if not hist: return None
        df = pd.DataFrame(hist)
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        df['ret'] = df['price'].pct_change()
        df['hv'] = df['ret'].rolling(window=10).std() * np.sqrt(252) * 100
        df['slope'] = df['hv'].diff()
        df = df.dropna()
        if len(df) < 20: return None
        return {
            "hv_mean": round(df['hv'].mean(), 4),
            "hv_std": round(df['hv'].std(), 4),
            "slope_mean": round(df['slope'].mean(), 4),
            "slope_std": round(df['slope'].std(), 4),
            "yesterday_hv": round(df['hv'].iloc[-1], 4)
        }
    except: return None

# 3. Spread History
def generate_spread_history_for_app(current_jp_val, days=150):
    try:
        us_data = get_yahoo_history("^TNX", "1y")
        if not us_data: return []
        df_us = pd.DataFrame(us_data).set_index("date")
        df_us.index = pd.to_datetime(df_us.index)
        jp_data = get_fred_history("IRLTLT01JPM156N", 400)
        if jp_data:
            df_jp = pd.DataFrame(jp_data).set_index("date")
            df_jp.index = pd.to_datetime(df_jp.index)
            today = pd.Timestamp.now().normalize()
            if current_jp_val is not None: df_jp.loc[today] = {'value': current_jp_val}
            df_jp = df_jp.resample('D').interpolate(method='linear')
        else:
            df_jp = pd.DataFrame(index=df_us.index)
            df_jp['value'] = current_jp_val if current_jp_val else 1.0
        df = df_us.join(df_jp, rsuffix='_jp')
        df['value'] = df['value'].ffill()
        df = df.dropna()
        df['spread'] = (df['price'] - df['value']).apply(lambda x: x if x > 0.1 else 0.1)
        recent = df.tail(days)
        result = []
        for dt, row in recent.iterrows(): result.append({"date": dt.strftime('%Y-%m-%d'), "spread": round(row['spread'], 4)})
        return result
    except: return []

# 4. Extra Params (STLFSI, MOVE)
def calculate_extra_metrics_params(window=60):
    print("\n--- Calculating Extra Metrics Params ---")
    stlfsi_params = {"current": 0, "mean": 0, "std": 1}
    move_params = {"current": 0, "mean": 0, "std": 1}
    try:
        s_data = get_fred_history("STLFSI4", 365*2)
        if s_data:
            df = pd.DataFrame(s_data).set_index("date")
            df.index = pd.to_datetime(df.index)
            df = df.resample('D').ffill()
            recent = df['value'].tail(window)
            stlfsi_params = {"current": round(recent.iloc[-1], 4), "mean": round(recent.mean(), 4), "std": round(recent.std(), 4)}
    except: pass
    try:
        m_data = get_yahoo_history("^MOVE", "1y")
        if m_data:
            df = pd.DataFrame(m_data).set_index("date")
            recent = df['price'].tail(window)
            move_params = {"current": round(recent.iloc[-1], 2), "mean": round(recent.mean(), 2), "std": round(recent.std(), 2)}
    except: pass
    return stlfsi_params, move_params

# 5. LVII Components
def calculate_lvii_components():
    print("\n--- Calculating Gray Rhino Ingredients ---")
    try:
        raw_sp500 = get_yahoo_history("SPY", "3y")
        raw_vix = get_yahoo_history("^VIX", "3y")
        raw_us10 = get_yahoo_history("^TNX", "3y")
        raw_jp10 = get_fred_history("IRLTLT01JPM156N", 1095)
        raw_stress = get_fred_history("STLFSI4", 1095)
        if not (raw_sp500 and raw_vix and raw_us10 and raw_jp10 and raw_stress): return None
        
        sp500 = pd.DataFrame(raw_sp500).set_index("date")
        vix = pd.DataFrame(raw_vix).set_index("date")
        us10 = pd.DataFrame(raw_us10).set_index("date")
        jp10 = pd.DataFrame(raw_jp10).set_index("date")
        stress = pd.DataFrame(raw_stress).set_index("date")
        for df in [sp500, vix, us10, jp10, stress]: df.index = pd.to_datetime(df.index)
        
        df = sp500.rename(columns={'price': 'price', 'volume': 'volume'})
        df = df.join(vix['price'], rsuffix='_vix').join(us10['price'], rsuffix='_us')
        jp10 = jp10.resample('D').ffill(); df = df.join(jp10['value'].rename('value_jp'))
        stress = stress.resample('D').ffill(); df = df.join(stress['value'].rename('value_stress'))
        df = df.ffill().dropna()
        if len(df) < 252: return None
        
        df['price_to_high'] = df['price'] / df['price'].rolling(252).max()
        df['rv'] = df['price'].pct_change().rolling(20).std() * np.sqrt(252) * 100
        pvd = calculate_zscore(df['price_to_high'].tail(756)) - calculate_zscore(df['rv'].tail(756))
        
        df['vol_spread'] = df['price_vix'] - df['rv']
        vpd = -1 * calculate_zscore(df['vol_spread'].tail(756))
        
        df['yield_spread'] = df['price_us'] - df['value_jp']
        csd = calculate_zscore(df['yield_spread'].tail(756)) + calculate_zscore(df['value_stress'].tail(756))
        
        df['ret_abs'] = df['price'].pct_change().abs()
        df['amihud'] = df['ret_abs'] / (df['price'] * df['volume']) * 1e9 
        df['amihud'] = df['amihud'].replace([np.inf, -np.inf], np.nan).fillna(0)
        lf = calculate_zscore(df['amihud'].tail(756))
        
        df['vix_slope'] = df['price_vix'].rolling(10).mean().diff()
        ttd = calculate_slope(df['vix_slope'].tail(10).tolist())
        
        return {"pvd": round(pvd, 2), "vpd": round(vpd, 2), "csd": round(csd, 2), "lf": round(lf, 2), "ttd_slope": round(ttd, 4)}
    except: return None

# ===================================================================
# 主程式
# ===================================================================

def generate_app_data():
    print("🚀 Starting Monitor Lite (Full Pack + Stlfsi/Move Params)...")
    
    jp_10y_val = get_jgb_10y_realtime()
    sofr, sofr_date = get_fred_latest("SOFR")
    iorb, iorb_date = get_fred_latest("IORB")
    us_3m, _ = get_fred_latest("DTB3")
    jp_3m, _ = get_fred_latest("IR3TIB01JPM156N")
    hy_oas, _ = get_fred_latest("BAMLH0A0HYM2")
    baa_spread, _ = get_fred_latest("BAA10Y")
    fin_stress, _ = get_fred_latest("STLFSI4")
    srf_amt, srf_dt = get_srf_usage()
    srf_billions = srf_amt / 1000000000 

    # [修復] 這裡呼叫的是真的 calculate_z_score，不再是假貨
    z_res = calculate_z_score(jp_10y_val)
    z_score = 0; mean_val = 0; std_val = 0; today_r = 0; w5000 = 0; m2 = 0; status = "Data Error"
    vuln_params = {}
    if z_res:
        z_score, today_r, mean_val, std_val, w5000, m2, vuln_params = z_res
        status = "Critical" if z_score > 2.0 else "Warning" if z_score > 1.0 else "Normal"

    vol_params = get_vol_stress_params()
    spread_history = generate_spread_history_for_app(jp_10y_val, 150)
    stlfsi_p, move_p = calculate_extra_metrics_params(60)
    gray_rhino = calculate_lvii_components()

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
            "details": {"w5000": round(w5000, 0), "m2": round(m2, 1), "ratio": round(today_r, 4)},
            "history_debug": [f"S:{w5000:.0f} | M2:{m2:.0f}", f"R:{today_r:.4f} (Mean:{mean_val:.2f})" if z_res else "Data Missing"]
        },
        "client_side_params": {
            "market_vuln": {
                "m2_supply": vuln_params.get("m2", 0),
                "jgb_10y": vuln_params.get("jgb_10y", 1.5),
                "hist_mean": vuln_params.get("mean", 0),
                "hist_std": vuln_params.get("std", 1)
            },
            "vol_stress": {
                "hv_mean": vol_params.get("hv_mean", 0) if vol_params else 0,
                "hv_std": vol_params.get("hv_std", 1) if vol_params else 1,
                "slope_mean": vol_params.get("slope_mean", 0) if vol_params else 0,
                "slope_std": vol_params.get("slope_std", 1) if vol_params else 1,
                "yesterday_hv": vol_params.get("yesterday_hv", 0) if vol_params else 0
            },
            "spread_history_150d": spread_history,
            "gray_rhino_ingredients": gray_rhino if gray_rhino else {},
            "stlfsi_z_params": stlfsi_p,
            "move_z_params": move_p
        }
    }

    with open("vip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print("✅ vip_data.json generated.")

if __name__ == "__main__":
    generate_app_data()