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
# 🕵️‍♂️ Barchart 萬用爬蟲 (雲端修正版)
# ==========================================
def fetch_barchart_data(symbol, label):
    url = f"https://www.barchart.com/stocks/quotes/{symbol}/performance"
    print(f"\n🕵️ [{label}] 正在前往 Barchart 抓取 {symbol} ...")
    
    chrome_options = Options()
    
    # === 關鍵修正：雲端環境適配 ===
    # 1. 必備：無頭模式 (因為 GitHub Actions 沒有螢幕)
    chrome_options.add_argument("--headless=new") 
    
    # 2. 必備：Linux/Docker 環境防崩潰參數
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080") # 假裝有個大螢幕，避免 RWD 隱藏元素
    
    # 3. 偽裝：這是為了騙過 Barchart 的反爬蟲
    chrome_options.add_argument("--disable-blink-features=AutomationControlled") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        # 在 GitHub Actions 上，ChromeDriverManager 會自動下載正確的 Linux版 ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"   ❌ Driver 啟動失敗: {e}")
        return None
    
    try:
        driver.get(url)
        print("   👀 等待頁面載入 (10秒)...")
        time.sleep(10) # 雲端網路有時較慢，多等一下
        
        # 雲端環境嘗試捲動 (雖然是 headless，但送 JS 指令還是有效)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
        time.sleep(2)
        
        page_text = driver.find_element("tag name", "body").text
        
        # Regex 解析
        pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)')
        matches = pattern.findall(page_text)
        
        data = []
        for match in matches:
            try:
                date_dt = datetime.strptime(match[0], "%m/%d/%y")
                date_str = date_dt.strftime("%Y-%m-%d")
                last_val = float(match[4].replace(',', ''))
                data.append({'Date': date_str, label: last_val})
            except: continue
            
        if len(data) >= 1:
            df = pd.DataFrame(data).drop_duplicates(subset=['Date'])
            df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y') # 格式化日期
            df.set_index('Date', inplace=True)
            df.sort_index(inplace=True)
            df.index = pd.to_datetime(df.index)
            
            print(f"   ✅ 成功抓取 {len(df)} 筆。最新: {df.index[-1].date()} = {df[label].iloc[-1]}")
            return df
        else:
            print("   ❌ 抓取失敗 (Regex 未匹配到數據)")
            # Debug: 如果失敗，印出部分內容看看是不是被擋了
            print(f"   [Debug] 頁面開頭: {page_text[:200].replace(chr(10), ' ')}")
            return None

    except Exception as e:
        print(f"   ❌ 發生錯誤: {e}")
        return None
    finally:
        try:
            driver.quit()
        except: pass

# ==========================================
# 💾 資料庫更新 (無變動)
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

    daily_snapshot.index = pd.to_datetime(daily_snapshot.index)
    print(f"   📥 本次抓取範圍: {daily_snapshot.index.min().date()} ~ {daily_snapshot.index.max().date()}")

    if history_df.empty:
        history_df = daily_snapshot
    else:
        history_df = daily_snapshot.combine_first(history_df)

    history_df.sort_index(inplace=True)
    history_df.to_csv(HISTORY_FILE)
    print(f"   ✅ 更新完成！目前資料庫共有 {len(history_df)} 筆交易日數據。")
    print("   📊 最新 3 筆數據預覽:")
    print(history_df.tail(3))

# ==========================================
# 🚀 主程式
# ==========================================
if __name__ == "__main__":
    print("🚀 啟動每日廣度數據收割機 (GitHub Actions 版)...")
    
    collected_data = {}
    
    for label, symbol in SYMBOLS.items():
        df = fetch_barchart_data(symbol, label)
        collected_data[label] = df
        time.sleep(5) # 雲端稍微多休息一點
        
    update_database(collected_data)
    
    print("\n🎉 任務結束。")
