import requests
import pandas as pd
from datetime import datetime
import os
from bs4 import BeautifulSoup

# 設定檔案名稱
FILE_NAME = 'jp10y_history.csv'

def get_jgb_10y_realtime():
    """從 CNBC 爬取即時日本 10 年債殖利率"""
    try:
        url = "https://www.cnbc.com/quotes/JP10Y"
        # 偽裝成瀏覽器，避免被擋
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # CNBC 的 CSS Selector (如果失效可能需要微調)
        val_element = soup.select_one('.QuoteStrip-lastPrice')
        
        if val_element:
            # 移除 % 符號並轉浮點數
            return float(val_element.text.strip().replace('%', ''))
        return None
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def update_csv():
    # 1. 獲取今日數據
    yield_val = get_jgb_10y_realtime()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    if yield_val is None:
        print("❌ 抓取失敗，今日不更新。")
        return

    print(f"✅ 抓取成功: {today_str} -> {yield_val}%")

    # 2. 讀取現有 CSV (如果存在)
    if os.path.exists(FILE_NAME):
        df = pd.read_csv(FILE_NAME)
        # 檢查今天是否已經存過了 (避免重複執行導致重複數據)
        if today_str in df['Date'].values:
            print("⚠️ 今日數據已存在，更新數值...")
            df.loc[df['Date'] == today_str, 'JP10Y'] = yield_val
        else:
            new_row = pd.DataFrame([{'Date': today_str, 'JP10Y': yield_val}])
            df = pd.concat([df, new_row], ignore_index=True)
    else:
        # 如果檔案不存在，建立新的
        print("📁 建立新檔案...")
        df = pd.DataFrame([{'Date': today_str, 'JP10Y': yield_val}])

    # 3. 存回 CSV
    df.to_csv(FILE_NAME, index=False)
    print(f"💾 數據已寫入 {FILE_NAME}")

if __name__ == "__main__":
    update_csv()