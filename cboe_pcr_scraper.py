import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os
import re
import json
import time

def get_latest_cboe_pcr():
    """
    從 CBOE 網站抓取最新的每日 PCR 數據。
    """
    url = "https://www.cboe.com/markets/us/options/market-statistics/daily/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.cboe.com/markets/us/options/market-statistics/daily/',
        'Connection': 'keep-alive',
    }
    
    try:
        time.sleep(2)
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"請求最新數據失敗: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    
    script_data = None
    actual_data_date_str = None

    for script in soup.find_all('script'):
        if script.string and 'self.__next_f.push' in script.string:
            match = re.search(r'self\.__next_f\.push\(\[1,\"(.*)\"\]\)', script.string)
            if match:
                json_str_escaped = match.group(1)
                json_str = json_str_escaped.replace('\\\"', '"').replace('\\\\n', '\\n')
                try:
                    data_match = re.search(r'"optionsData":(\{.*?\}),"selectedDate":"(.*?)"', json_str)
                    if data_match:
                        options_data_str = data_match.group(1)
                        actual_data_date_str = data_match.group(2)
                        script_data = json.loads(options_data_str)
                        break
                except json.JSONDecodeError as e:
                    print(f"JSON 解碼失敗: {e}")
                    continue

    if not script_data or not actual_data_date_str:
        print("未找到最新數據。")
        return None

    pcr_values = {}
    
    # 提取 Ratios
    if 'ratios' in script_data:
        for ratio in script_data['ratios']:
            name = ratio['name']
            value = float(ratio['value']) if ratio['value'] else None
            if "EQUITY PUT/CALL RATIO" in name: pcr_values['Equity PCR'] = value
            elif "INDEX PUT/CALL RATIO" in name: pcr_values['Index PCR'] = value

    # 提取 Open Interest PCR
    if 'EQUITY OPTIONS' in script_data:
        for item in script_data['EQUITY OPTIONS']:
            if item['name'] == 'OPEN INTEREST':
                call_oi = item.get('call', 0)
                put_oi = item.get('put', 0)
                if call_oi is not None and put_oi is not None and call_oi > 0:
                    pcr_values['Equity OI PCR'] = round(put_oi / call_oi, 2)
                break

    if 'INDEX OPTIONS' in script_data:
        for item in script_data['INDEX OPTIONS']:
            if item['name'] == 'OPEN INTEREST':
                call_oi = item.get('call', 0)
                put_oi = item.get('put', 0)
                if call_oi is not None and put_oi is not None and call_oi > 0:
                    pcr_values['Index OI PCR'] = round(put_oi / call_oi, 2)
                break

    pcr_values['Date'] = actual_data_date_str
    return pcr_values

def main():
    history_file = 'cboe_pcr_history.csv'
    
    # 讀取現有的歷史數據
    if os.path.exists(history_file):
        df_history = pd.read_csv(history_file)
        df_history['Date'] = pd.to_datetime(df_history['Date'])
    else:
        df_history = pd.DataFrame(columns=['Date', 'Equity PCR', 'Index PCR', 'Equity OI PCR', 'Index OI PCR'])
        df_history['Date'] = pd.to_datetime(df_history['Date'])

    # 抓取最新數據
    print("正在抓取最新數據...")
    latest_pcr_data = get_latest_cboe_pcr()
    
    if latest_pcr_data:
        df_latest = pd.DataFrame([latest_pcr_data])
        df_latest['Date'] = pd.to_datetime(df_latest['Date'])
        
        # 合併最新數據
        df_combined = pd.concat([df_history, df_latest], ignore_index=True)
        # 根據日期去重，保留最後一次抓取的數據
        df_combined = df_combined.drop_duplicates(subset=['Date'], keep='last')
        # 按照日期降序排序
        df_combined = df_combined.sort_values('Date', ascending=False)
        
        # 限制只保留最近 1000 條記錄（或根據需要調整）
        df_combined = df_combined.head(1000)
        
        df_combined.to_csv(history_file, index=False)
        print(f"數據已更新至 {history_file}，共 {len(df_combined)} 條記錄。")
    else:
        print("未獲取到新數據。")

if __name__ == "__main__":
    main()
