import requests
import pandas as pd
from datetime import datetime
import os
import re

def fetch_barchart_price(symbol):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            price_match = re.search(r'"lastPrice":"([\d,.]+)"', resp.text)
            if price_match:
                return float(price_match.group(1).replace(',', ''))
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None

def update_csv(data, filename="energy_monitor.csv"):
    if not data or len(data) <= 1: return
    df_new = pd.DataFrame([data])
    if os.path.exists(filename):
        df_old = pd.read_csv(filename)
        df_old['date'] = df_old['date'].astype(str)
        if data['date'] in df_old['date'].values:
            idx = df_old.index[df_old['date'] == data['date']].tolist()[0]
            for key in data:
                if key != 'date' and data[key] is not None:
                    df_old.at[idx, key] = data[key]
            df_old.to_csv(filename, index=False)
        else:
            df_combined = pd.concat([df_old, df_new], ignore_index=True)
            df_combined.to_csv(filename, index=False)
    else:
        df_new.to_csv(filename, index=False)

if __name__ == "__main__":
    print("Fetching Energy Data...")
    results = {"date": datetime.now().strftime("%Y-%m-%d")}
    
    # Tickers
    # LFM26: Gasoil
    # J7HK26: Eurobob Oxy
    # RBM26: RBOB Gasoline
    
    results["ice_gasoil"] = fetch_barchart_price("LFM26")
    results["eurobob_oxy"] = fetch_barchart_price("J7HK26")
    results["rbob_gasoline"] = fetch_barchart_price("RBM26")
    
    print(f"Fetched: {results}")
    update_csv(results)
    print("Done.")
