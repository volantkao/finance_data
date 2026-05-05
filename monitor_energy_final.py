import requests
import pandas as pd
from datetime import datetime
import os
import re
from io import StringIO

def fetch_barchart_data():
    """
    從 Barchart 抓取 Gasoil 與 Eurobob 數據
    """
    # 這裡我們使用一個更健壯的 headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    results = {"date": datetime.now().strftime("%Y-%m-%d")}
    
    # Gasoil Low Sulphur (LF) - 抓取主力合約
    try:
        url_lf = "https://www.barchart.com/futures/quotes/LFM26/overview" # 2026年6月合約
        resp = requests.get(url_lf, headers=headers, timeout=15)
        if resp.status_code == 200:
            price_match = re.search(r'"lastPrice":"([\d,.]+)"', resp.text)
            if price_match:
                results["ice_gasoil"] = float(price_match.group(1).replace(',', ''))
    except Exception as e:
        print(f"Error fetching Gasoil: {e}")

    # Eurobob Oxy (J7) - 抓取主力合約
    try:
        url_j7 = "https://www.barchart.com/futures/quotes/J7HK26/overview" # 2026年5月合約
        resp = requests.get(url_j7, headers=headers, timeout=15)
        if resp.status_code == 200:
            price_match = re.search(r'"lastPrice":"([\d,.]+)"', resp.text)
            if price_match:
                results["eurobob_oxy"] = float(price_match.group(1).replace(',', ''))
    except Exception as e:
        print(f"Error fetching Eurobob: {e}")
        
    return results

def update_csv(data, filename="energy_monitor.csv"):
    if not data or len(data) <= 1:
        return
    
    df_new = pd.DataFrame([data])
    
    if os.path.exists(filename):
        df_old = pd.read_csv(filename)
        df_old['date'] = df_old['date'].astype(str)
        
        if data['date'] in df_old['date'].values:
            idx = df_old.index[df_old['date'] == data['date']].tolist()[0]
            for key in data:
                if key != 'date':
                    df_old.at[idx, key] = data[key]
            df_old.to_csv(filename, index=False)
        else:
            df_combined = pd.concat([df_old, df_new], ignore_index=True)
            df_combined.to_csv(filename, index=False)
    else:
        df_new.to_csv(filename, index=False)

if __name__ == "__main__":
    print("Fetching Energy Data...")
    data = fetch_barchart_data()
    print(f"Fetched: {data}")
    update_csv(data)
    print("Done.")
