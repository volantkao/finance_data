import requests
import pandas as pd
from datetime import datetime
import os
from io import StringIO

def fetch_saxo_data():
    url = "https://fxowebtools.saxobank.com/otc.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # 使用 pandas 讀取網頁中的所有表格
        tables = pd.read_html(StringIO(response.text))
        
        # 根據觀察，第一個表格通常是 ATM Volatilities，第二個是 Risk Reversal
        atm_vol_df = tables[0]
        risk_rev_df = tables[1]
        
        # 提取 USDJPY 數據
        usdjpy_1m_iv = None
        for index, row in atm_vol_df.iterrows():
            if any('USDJPY' in str(val) for val in row.values):
                # 提取純數字部分
                raw_val = str(row['1m'])
                usdjpy_1m_iv = raw_val.split(' ')[0]
                break
        
        usdjpy_1m_rr = None
        for index, row in risk_rev_df.iterrows():
            if any('USDJPY' in str(val) for val in row.values):
                # 提取純數字部分
                raw_val = str(row['1m'])
                usdjpy_1m_rr = raw_val.split(' ')[0]
                break
        
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "usdjpy_1m_iv": usdjpy_1m_iv,
            "usdjpy_1m_rr": usdjpy_1m_rr
        }
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def update_csv(data, filename="usdjpy_monitor.csv"):
    if data is None:
        return
    
    df_new = pd.DataFrame([data])
    
    if os.path.exists(filename):
        df_old = pd.read_csv(filename)
        # 確保日期列為字串
        df_old['date'] = df_old['date'].astype(str)
        
        if data['date'] in df_old['date'].values:
            # 如果數據已存在，更新它
            idx = df_old.index[df_old['date'] == data['date']].tolist()[0]
            df_old.at[idx, 'usdjpy_1m_iv'] = data['usdjpy_1m_iv']
            df_old.at[idx, 'usdjpy_1m_rr'] = data['usdjpy_1m_rr']
            df_old.to_csv(filename, index=False)
            print(f"Updated entry for {data['date']}.")
        else:
            # 否則添加新行
            df_combined = pd.concat([df_old, df_new], ignore_index=True)
            # 按日期排序
            df_combined['date'] = pd.to_datetime(df_combined['date'])
            df_combined = df_combined.sort_values('date').drop_duplicates('date')
            df_combined['date'] = df_combined['date'].dt.strftime('%Y-%m-%d')
            df_combined.to_csv(filename, index=False)
            print(f"Added new data for {data['date']}.")
    else:
        df_new.to_csv(filename, index=False)
        print(f"Created {filename} and added initial data.")

if __name__ == "__main__":
    print("Starting USDJPY Monitor...")
    data = fetch_saxo_data()
    if data:
        print(f"Fetched Data: {data}")
        update_csv(data)
    else:
        print("Failed to fetch data.")
