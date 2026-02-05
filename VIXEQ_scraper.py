from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
from datetime import datetime
import os
import sys

# 設定檔案名稱 (請確保您的歷史檔案名稱與此一致，或在此修改)
FILENAME = "vixeq-history.csv"

def get_vixeq_selenium():
    print("🚀 啟動 Chrome 瀏覽器...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") # 新版無頭模式
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    # 反爬蟲設置
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 自動安裝與管理 ChromeDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    url = "https://www.google.com/finance/quote/VIXEQ:INDEXCBOE"
    
    try:
        print(f"🔗 前往: {url}")
        driver.get(url)
        
        # 等待價格元素加載 (Class 名稱可能會變，這是 Google Finance 的風險)
        # 您原本提供的 class 是 ".YMlKec.fxKbKc"
        wait = WebDriverWait(driver, 15)
        element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".YMlKec.fxKbKc")))
        
        price_text = element.text.replace(',', '')
        price = float(price_text)
        print(f"✅ 成功抓取價格: {price}")
        driver.quit()
        return price
    except Exception as e:
        print(f"❌ Selenium 抓取失敗: {e}")
        # 如果失敗，嘗試印出網頁源碼的前幾行或是標題，方便除錯
        try:
            print(f"網頁標題: {driver.title}")
        except: pass
        driver.quit()
        return None

def update_csv(price):
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. 讀取或建立 DataFrame
    if os.path.exists(FILENAME):
        try:
            df = pd.read_csv(FILENAME)
            # 嘗試統一日期格式，將舊有的 M/D/YYYY 轉為 YYYY-MM-DD
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
        except Exception as e:
            print(f"⚠️ 讀取 CSV 失敗，建立新檔: {e}")
            df = pd.DataFrame(columns=["Date", "Close"])
    else:
        df = pd.DataFrame(columns=["Date", "Close"])

    # 2. 檢查今天是否已經有資料 (避免重複執行導致重複數據)
    if today_str in df['Date'].values:
        print(f"ℹ️ {today_str} 的資料已存在，更新數值...")
        df.loc[df['Date'] == today_str, 'Close'] = price
    else:
        print(f"➕ 新增資料: {today_str} = {price}")
        new_row = pd.DataFrame([[today_str, price]], columns=["Date", "Close"])
        df = pd.concat([df, new_row], ignore_index=True)

    # 3. 排序並存檔
    df = df.sort_values(by="Date")
    df.to_csv(FILENAME, index=False)
    print(f"💾 檔案已保存至 {FILENAME}")

if __name__ == "__main__":
    price = get_vixeq_selenium()
    if price:
        update_csv(price)
    else:
        print("❌ 無法獲取價格，程式終止。")
        sys.exit(1) # 回傳錯誤代碼讓 GitHub Actions 知道失敗了