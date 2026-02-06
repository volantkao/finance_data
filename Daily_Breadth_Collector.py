import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import os
import sys
from datetime import datetime

# ==========================================
# 🔧 設定區
# ==========================================
HISTORY_FILE = 'nyse_history.csv'
SYMBOLS = {
    'NH': '$MAHN',   
    'NL': '$MALN',   
    'Adv': '$ADVN',  
    'Dec': '$DECN'   
}

# ==========================================
# 🕵️‍♂️ Barchart 萬用爬蟲 (格式修復版)
# ==========================================
def fetch_barchart_data(symbol, label):
    url = f"https://www.barchart.com/stocks/quotes/{symbol}/performance"
    print(f"\n🕵️ [{label}] 正在前往 Barchart 抓取 {symbol} ...")
    
    chrome_options = Options()
    
    # 根據環境判斷是否使用 Headless
    # 如果是在 GitHub Actions (CI=true) 或者 Linux 環境，強制使用 Headless
    is_ci = os.environ.get('CI') == 'true'
    if is_ci:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
    else:
        # 在 PC 上執行時，保持視窗開啟以觀察狀況 (也可以設為 headless)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

    chrome_options.add_argument("--disable-blink-features=AutomationControlled") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"   ❌ Driver 啟動失敗: {e}")
        return None
    
    try:
        driver.get(url)
        print("   👀 等待頁面載入 (8秒)...")
        time.sleep(8) 
        
        # 嘗試捲動
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
        time.sleep(2)
        
        page_text = driver.find_element("tag name", "body").text
        
        # Regex: 抓取日期 + 數值
        # 支援 mm/dd/yy (02/05/26) 和 yyyy-mm-dd (2026-02-05)
        pattern = re.compile(r'(\d{2,4}[-/]\d{2}[-/]\d{2,4})\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)')
        matches = pattern.findall(page_text)
        
        data = []
        for match in matches:
            try:
                date_raw = match[0]
                # 這裡不再手動轉換日期格式，直接存原始字串
                # 讓後面的 pd.to_datetime 自己去猜
                
                # 第5個欄位是 Last (收盤值)
                last_val = float(match[4].replace(',', ''))
                
                data.append({'Date': date_raw, label: last_val})
            except: continue
            
        if len(data) >= 1:
            df = pd.DataFrame(data).drop_duplicates(subset=['Date'])
            
            # 【關鍵修正】: 移除 format 參數，讓 Pandas 自動推斷日期格式
            # 這能同時相容 "02/05/26" 和 "2026-02-05"
            df['Date'] = pd.to_datetime(df['Date'])
            
            df.set_index('Date', inplace=True)
            df.sort_index(inplace=True)
            
            print(f"   ✅ 成功抓取 {len(df)} 筆。最新: {df.index[-1].date()} = {df[label].iloc[-1]}")
            return df
        else:
            print("   ❌ 抓取失敗 (Regex 未匹配到數據)")
            return None

    except Exception as e:
        print(f"   ❌ 發生錯誤: {e}")
        return None
    finally:
        try:
            driver.quit()
        except: pass

# ==========================================
# 💾 資料庫更新
# ==========================================
def update_database(new_data_dict):
    print(f"\n💾 正在更新歷史資料庫: {HISTORY_FILE} ...")
    
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df['Date'] = pd.to_datetime(history_df['Date'])
            history_df.set_index('Date', inplace=True)
        except:
            history_df = pd.DataFrame()
    else:
        history_df = pd.DataFrame()

    daily_snapshot = pd.DataFrame()
    for label, df in new_data_dict.items():
        if df is not None:
            if daily_snapshot.empty:
                daily_snapshot = df
            else:
                daily_snapshot = daily_snapshot.join(df, how='outer')
    
    if daily_snapshot.empty:
        print("   ❌ 沒有新數據可供更新。")
        return

    # 確保索引型態一致
    daily_snapshot.index = pd.to_datetime(daily_snapshot.index)
    
    print(f"   📥 本次抓取範圍: {daily_snapshot.index.min().date()} ~ {daily_snapshot.index.max().date()}")

    if history_df.empty:
        history_df = daily_snapshot
    else:
        # 使用 combine_first 更新舊資料 (新資料優先)
        history_df = daily_snapshot.combine_first(history_df)

    history_df.sort_index(inplace=True)
    
    # 存檔格式：YYYY-MM-DD
    history_df.to_csv(HISTORY_FILE, date_format='%Y-%m-%d')
    print(f"   ✅ 更新完成！目前資料庫共有 {len(history_df)} 筆交易日數據。")
    print("   📊 最新 3 筆數據預覽:")
    print(history_df.tail(3))

# ==========================================
# 🚀 主程式
# ==========================================
if __name__ == "__main__":
    print("🚀 啟動每日廣度數據收割機 (格式修復版)...")
    
    collected_data = {}
    
    for label, symbol in SYMBOLS.items():
        df = fetch_barchart_data(symbol, label)
        collected_data[label] = df
        time.sleep(3) 
        
    update_database(collected_data)
    
    print("\n🎉 任務結束。")
