import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import os
import time

def get_cboe_daily_pcr(date: datetime):
    """
    從 CBOE 網站抓取指定日期的每日 PCR 數據。
    """
    date_str = date.strftime("%Y-%m-%d")
    url = f"https://www.cboe.com/markets/us/options/market-statistics/daily/?date={date_str}"
    
    # 使用更真實的瀏覽器頭部
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.cboe.com/markets/us/options/market-statistics/daily/',
    }
    
    try:
        # 添加延遲以避免被封
        time.sleep(1)
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 403:
            print(f"403 錯誤: {date_str}。可能需要 GitHub Actions 運行環境或更強的偽裝。")
            return None
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"請求失敗 ({date_str}): {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    pcr_values = {}
    
    # 解析邏輯與之前相同...
    ratio_table = None
    for table in soup.find_all('table'):
        if "TOTAL PUT/CALL RATIO" in table.text:
            ratio_table = table
            break
            
    if ratio_table:
        for row in ratio_table.find_all('tr'):
            cols = row.find_all(['td', 'th'])
            if len(cols) >= 2:
                name = cols[0].text.strip()
                value = cols[1].text.strip()
                try:
                    if "EQUITY PUT/CALL RATIO" in name:
                        pcr_values['Equity PCR'] = float(value)
                    elif "INDEX PUT/CALL RATIO" in name:
                        pcr_values['Index PCR'] = float(value)
                except ValueError:
                    continue

    # Open Interest
    for table in soup.find_all('table'):
        table_text = table.text
        if "EQUITY OPTIONS" in table_text and "OPEN INTEREST" in table_text:
            for row in table.find_all('tr'):
                if "OPEN INTEREST" in row.text:
                    cols = row.find_all('td')
                    if len(cols) >= 3:
                        try:
                            call_oi = int(cols[1].text.strip().replace(',', ''))
                            put_oi = int(cols[2].text.strip().replace(',', ''))
                            if call_oi > 0: pcr_values['Equity OI PCR'] = round(put_oi / call_oi, 2)
                        except ValueError: continue
        elif "INDEX OPTIONS" in table_text and "OPEN INTEREST" in table_text:
            for row in table.find_all('tr'):
                if "OPEN INTEREST" in row.text:
                    cols = row.find_all('td')
                    if len(cols) >= 3:
                        try:
                            call_oi = int(cols[1].text.strip().replace(',', ''))
                            put_oi = int(cols[2].text.strip().replace(',', ''))
                            if call_oi > 0: pcr_values['Index OI PCR'] = round(put_oi / call_oi, 2)
                        except ValueError: continue

    return pcr_values

def main():
    history_file = 'cboe_pcr_history.csv'
    
    if os.path.exists(history_file):
        df_history = pd.read_csv(history_file)
        df_history['Date'] = pd.to_datetime(df_history['Date'])
    else:
        df_history = pd.DataFrame(columns=['Date', 'Equity PCR', 'Index PCR', 'Equity OI PCR', 'Index OI PCR'])
        df_history['Date'] = pd.to_datetime(df_history['Date'])

    today = datetime.now()
    new_data = []
    
    # 檢查最近 10 天
    for i in range(1, 11):
        target_date = today - timedelta(days=i)
        target_date_str = target_date.strftime('%Y-%m-%d')
        
        if not df_history.empty and target_date_str in df_history['Date'].dt.strftime('%Y-%m-%d').values:
            # 如果已有數據且不是空值，跳過
            row = df_history[df_history['Date'].dt.strftime('%Y-%m-%d') == target_date_str]
            if not row.isnull().values.any():
                continue
            
        print(f"正在抓取 {target_date_str}...")
        pcr_data = get_cboe_daily_pcr(target_date)
        
        if pcr_data and 'Equity PCR' in pcr_data:
            pcr_data['Date'] = target_date_str
            new_data.append(pcr_data)
            print(f"成功抓取 {target_date_str}")
        else:
            print(f"{target_date_str} 無法獲取數據")

    if new_data:
        df_new = pd.DataFrame(new_data)
        df_new['Date'] = pd.to_datetime(df_new['Date'])
        df_combined = pd.concat([df_history, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=['Date'], keep='last')
        df_combined = df_combined.sort_values('Date', ascending=False)
        df_combined = df_combined.head(1000)
        df_combined.to_csv(history_file, index=False)
        print(f"已更新歷史數據。")
    else:
        print("沒有新數據。")

if __name__ == "__main__":
    main()
