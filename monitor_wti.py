import csv
import os
import requests
import time
from datetime import datetime

# WTI 原油數據監控程式 (V5 - 1-Year Spread 版)
# 對齊財經 M 平方 (MM) 的邏輯：一年後價格 (1-Year Out) 減去 近期價格 (Front Month)
CSV_FILENAME = "wti_monitor_data.csv"

def fetch_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            data = response.json()
            # 獲取最新價格
            result = data['chart']['result'][0]['meta']
            return result['regularMarketPrice']
    except Exception as e:
        print(f"  抓取 {symbol} 失敗: {e}")
        return None
    return None

def get_contract_symbol(month_offset=0):
    """
    計算 WTI 合約代碼。
    month_offset=0: 近期合約 (Front Month)
    month_offset=12: 一年後合約 (1-Year Out)
    """
    symbols = "FGHJKMNQUVXZ"
    now = datetime.now()
    
    # WTI 期貨通常領先一個月，當前 3 月對應的是 4 月 (J)
    # 計算目標月份與年份
    total_months = now.month + month_offset
    target_month_idx = (total_months) % 12 
    target_year = now.year + (total_months // 12)
    
    symbol_char = symbols[target_month_idx]
    year_suffix = str(target_year)[2:]
    
    return f"CL{symbol_char}{year_suffix}.NYM"

def main():
    print(f"[{datetime.now()}] 正在從 Yahoo Finance 獲取 WTI 數據 (1-Year Spread)...")
    
    # 1. 獲取近期價格 (使用連續合約 CL=F 作為基準最穩定)
    price_front = fetch_price("CL=F")
    
    # 2. 獲取一年後的合約價格 (1-Year Out)
    symbol_year_out = get_contract_symbol(month_offset=12)
    price_year_out = fetch_price(symbol_year_out)
    
    # 如果一年後合約抓不到，嘗試抓取相鄰月份 (有時某些月份流動性較差)
    if price_year_out is None:
        print(f"  {symbol_year_out} 抓取失敗，嘗試相鄰合約...")
        symbol_year_out = get_contract_symbol(month_offset=11) # 11個月後
        price_year_out = fetch_price(symbol_year_out)

    if price_front and price_year_out:
        # 計算價差：遠期 - 近期 (L)
        # 根據 MM 的數據，目前遠期低於近期 (Backwardation)，所以值會是負的 (例如 -15)
        spread = round(price_year_out - price_front, 2)
        
        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "price": round(price_front, 2),
            "spread": spread,
            "year_out_symbol": symbol_year_out
        }
        
        print(f"  近期價格 (Front): {result['price']}")
        print(f"  遠期價格 ({result['year_out_symbol']}): {price_year_out}")
        print(f"  計算價差 (L): {result['spread']}")
        
        # 儲存數據
        file_exists = os.path.isfile(CSV_FILENAME)
        existing_dates = set()
        if file_exists:
            try:
                with open(CSV_FILENAME, mode='r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get('Date'): existing_dates.add(row['Date'])
            except: pass
            
        if result['date'] in existing_dates:
            print(f"[{datetime.now()}] {result['date']} 的數據已存在，跳過儲存。")
            return

        with open(CSV_FILENAME, mode='a', newline='', encoding='utf-8-sig') as f:
            fieldnames = ['Date', 'WTI_Intramarket_Spread(L)', 'NYMEX_WTI_Futures(R)']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists or os.path.getsize(CSV_FILENAME) == 0:
                writer.writeheader()
            writer.writerow({
                'Date': result['date'],
                'WTI_Intramarket_Spread(L)': result['spread'],
                'NYMEX_WTI_Futures(R)': result['price']
            })
        print(f"[{datetime.now()}] 數據已成功儲存至 {CSV_FILENAME}")
    else:
        print(f"[{datetime.now()}] 抓取失敗。")

if __name__ == "__main__":
    main()
