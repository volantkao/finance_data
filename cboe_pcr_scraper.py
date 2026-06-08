
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import os

def get_cboe_daily_pcr(date: datetime):
    """
    從 CBOE 網站抓取指定日期的每日 PCR 數據。
    使用 BeautifulSoup 解析 HTML 表格。
    """
    date_str = date.strftime("%Y-%m-%d")
    url = f"https://www.cboe.com/markets/us/options/market-statistics/daily/?date={date_str}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"請求失敗: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    pcr_values = {}
    
    # 1. 抓取 Equity PCR 和 Index PCR (從 Ratios 表格)
    # 尋找包含 "TOTAL PUT/CALL RATIO" 的表格
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
                if "EQUITY PUT/CALL RATIO" in name:
                    pcr_values['Equity PCR'] = float(value)
                elif "INDEX PUT/CALL RATIO" in name:
                    pcr_values['Index PCR'] = float(value)

    # 2. 抓取 Open Interest (用於計算 OI PCR)
    # 尋找 EQUITY OPTIONS 表格
    equity_oi_table = None
    for table in soup.find_all('table'):
        if "EQUITY OPTIONS" in table.text and "OPEN INTEREST" in table.text:
            equity_oi_table = table
            break
            
    if equity_oi_table:
        # 在表格中尋找 OPEN INTEREST 行
        # 根據 CBOE 的 HTML 結構，通常是一個包含 call, put, total 的行
        # 我們需要找到包含 "OPEN INTEREST" 的 tr
        for row in equity_oi_table.find_all('tr'):
            if "OPEN INTEREST" in row.text:
                cols = row.find_all('td')
                # 通常結構是: [Name, Call, Put, Total]
                if len(cols) >= 3:
                    try:
                        call_oi = int(cols[1].text.strip().replace(',', ''))
                        put_oi = int(cols[2].text.strip().replace(',', ''))
                        if call_oi > 0:
                            pcr_values['Equity OI PCR'] = round(put_oi / call_oi, 2)
                    except ValueError:
                        continue

    # 尋找 INDEX OPTIONS 表格
    index_oi_table = None
    for table in soup.find_all('table'):
        if "INDEX OPTIONS" in table.text and "OPEN INTEREST" in table.text:
            index_oi_table = table
            break
            
    if index_oi_table:
        for row in index_oi_table.find_all('tr'):
            if "OPEN INTEREST" in row.text:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    try:
                        call_oi = int(cols[1].text.strip().replace(',', ''))
                        put_oi = int(cols[2].text.strip().replace(',', ''))
                        if call_oi > 0:
                            pcr_values['Index OI PCR'] = round(put_oi / call_oi, 2)
                    except ValueError:
                        continue

    return pcr_values

def main():
    today = datetime.now()
    output_dir = 'cboe_pcr_data'
    os.makedirs(output_dir, exist_ok=True)

    # 嘗試過去 7 天
    found = False
    for i in range(1, 8):
        target_date = today - timedelta(days=i)
        print(f"嘗試抓取 {target_date.strftime('%Y-%m-%d')} 的數據...")
        pcr_data = get_cboe_daily_pcr(target_date)
        
        if pcr_data and 'Equity PCR' in pcr_data:
            df = pd.DataFrame([pcr_data])
            df['Date'] = target_date.strftime('%Y-%m-%d')
            df.set_index('Date', inplace=True)
            
            output_file = os.path.join(output_dir, f'cboe_pcr_{target_date.strftime("%Y%m%d")}.csv')
            df.to_csv(output_file)
            print(f"數據已成功抓取並保存到 {output_file}")
            found = True
            break
        else:
            print(f"{target_date.strftime('%Y-%m-%d')} 沒有數據，嘗試前一天...")
            
    if not found:
        print("在過去 7 天內未找到任何 CBOE 數據。")

if __name__ == "__main__":
    main()
