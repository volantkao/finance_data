import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import os
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
# 🕵️‍♂️ Barchart 萬用爬蟲
# ==========================================
def fetch_barchart_data(symbol, label):
    url = f"https://www.barchart.com/stocks/quotes/{symbol}/performance"
    print(f"\n🕵️ [{label}] 正在前往 Barchart 抓取 {symbol} ...")
    
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        driver.get(url)
        print("   👀 等待頁面載入 (8秒)...")
        time.sleep(8) 
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
        time.sleep(2)
        
        page_text = driver.find_element("tag name", "body").text
        
        pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)')
        matches = pattern.findall(page_text)
        
        data = []
        for match in matches:
            try:
                # 這裡抓到的還是字串
                date_str = match[0] # mm/dd/yy
                last_val = float(match[4].replace(',', ''))
                
                # 為了避免時區問題，先存字串，建立 DataFrame 後再一次轉
                data.append({'Date': date_str, label: last_val})
            except: continue
            
        if len(data) >= 1:
            df = pd.DataFrame(data).drop_duplicates(subset=['Date'])
            
            # 【關鍵修正】強制將 Date 欄位轉為 datetime 物件
            df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y')
            
            df.set_index('Date', inplace=True)
            df.sort_index(inplace=True)
            
            # 確保索引也是 datetime 類型
            df.index = pd.to_datetime(df.index)
            
            print(f"   ✅ 成功抓取 {len(df)} 筆。最新: {df.index[-1].date()} = {df[label].iloc[-1]}")
            return df
        else:
            print("   ❌ 抓取失敗 (Regex 未匹配到數據)")
            return None

    except Exception as e:
        print(f"   ❌ 發生錯誤: {e}")
        return None
    finally:
        driver.quit()

# ==========================================
# 💾 資料庫更新
# ==========================================
def update_database(new_data_dict):
    print(f"\n💾 正在更新歷史資料庫: {HISTORY_FILE} ...")
    
    # 1. 讀取舊資料
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            # 讀取時務必轉為 datetime，否則 index 無法對齊
            history_df['Date'] = pd.to_datetime(history_df['Date'])
            history_df.set_index('Date', inplace=True)
        except:
            history_df = pd.DataFrame()
    else:
        history_df = pd.DataFrame()

    # 2. 合併新數據
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

    # 確保 daily_snapshot 索引也是 datetime
    daily_snapshot.index = pd.to_datetime(daily_snapshot.index)

    # 這裡現在安全了，因為 index 已經是 datetime 物件
    print(f"   📥 本次抓取範圍: {daily_snapshot.index.min().date()} ~ {daily_snapshot.index.max().date()}")

    # 3. 更新
    if history_df.empty:
        history_df = daily_snapshot
    else:
        history_df = daily_snapshot.combine_first(history_df)

    # 4. 存檔
    history_df.sort_index(inplace=True)
    history_df.to_csv(HISTORY_FILE) # 存成 CSV 時會自動變回標準日期字串
    print(f"   ✅ 更新完成！目前資料庫共有 {len(history_df)} 筆交易日數據。")
    print("   📊 最新 3 筆數據預覽:")
    print(history_df.tail(3))

# ==========================================
# 🚀 主程式
# ==========================================
if __name__ == "__main__":
    print("🚀 啟動每日廣度數據收割機 v4 (Final)...")
    
    collected_data = {}
    
    for label, symbol in SYMBOLS.items():
        df = fetch_barchart_data(symbol, label)
        collected_data[label] = df
        time.sleep(3) 
        
    update_database(collected_data)
    
    print("\n🎉 任務結束。")