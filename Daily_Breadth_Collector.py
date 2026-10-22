import os
import re
import sys
import time
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ==========================================
# 🔧 設定區
# ==========================================
HISTORY_FILE = 'nyse_history.csv'
SYMBOLS = {
    'NH': '$MAHN',
    'NL': '$MALN',
    'Adv': '$ADVN',
    'Dec': '$DECN',
}

RETRIES = 3               # 每個代號最多嘗試次數
PAGE_LOAD_TIMEOUT = 40    # 頁面載入上限(秒)
SCRIPT_TIMEOUT = 20       # JS 執行上限(秒)
COMMAND_TIMEOUT = 60      # chromedriver 單一指令上限(秒)，預設是 120
WAIT_FOR_DATA = 30        # 等表格出現的上限(秒)

# 支援 mm/dd/yy、mm/dd/yyyy、yyyy-mm-dd
PATTERN = re.compile(
    r'(\d{2}/\d{2}/\d{2,4}|\d{4}-\d{2}-\d{2})'
    r'\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)'
)


# ==========================================
# 🌐 Driver 管理
# ==========================================
def make_driver():
    o = Options()
    # GitHub Actions 一律 headless；本機也可以設 HEADLESS=1
    if os.environ.get('CI') == 'true' or os.environ.get('HEADLESS') == '1':
        o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--disable-gpu")
    o.add_argument("--window-size=1920,1080")
    o.add_argument("--disable-blink-features=AutomationControlled")
    o.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    # 不載圖片，減少負擔
    o.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
    # DOM 好了就繼續，不等廣告/追蹤腳本
    o.page_load_strategy = 'eager'

    # Selenium 4.6+ 內建 Selenium Manager，不需要 webdriver_manager
    try:
        driver = webdriver.Chrome(options=o)
    except Exception as e:
        print(f"   ⚠️ Selenium Manager 啟動失敗 ({type(e).__name__})，改用 webdriver_manager")
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=o)

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    # 縮短 chromedriver 指令逾時 (120s -> 60s)；不同 selenium 版本屬性不同，失敗就略過
    try:
        driver.command_executor._client_config.timeout = COMMAND_TIMEOUT
    except Exception:
        pass
    return driver


def safe_quit(driver):
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass


# ==========================================
# 🧮 日期解析
# ==========================================
def parse_date(s):
    if '-' in s:
        fmt = "%Y-%m-%d"
    elif len(s) == 10:
        fmt = "%m/%d/%Y"
    else:
        fmt = "%m/%d/%y"
    return pd.to_datetime(s, format=fmt)


# ==========================================
# 🕵️ Barchart 爬蟲
# ==========================================
def scrape_once(driver, symbol, label):
    """用既有 driver 抓一次，成功回傳 DataFrame，失敗丟例外。"""
    url = f"https://www.barchart.com/stocks/quotes/{symbol}/performance"
    try:
        driver.get(url)
    except TimeoutException:
        # 頁面還在載廣告：停止載入，直接用現有 DOM
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass

    # 輪詢直到表格出現，取代固定 sleep(8)
    matches = []
    deadline = time.time() + WAIT_FOR_DATA
    scrolled = False
    while time.time() < deadline:
        text = driver.find_element(By.TAG_NAME, "body").text
        matches = PATTERN.findall(text)
        if matches:
            break
        if not scrolled:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
            except Exception:
                pass
            scrolled = True
        time.sleep(1.5)

    if not matches:
        raise RuntimeError("Regex 未匹配到數據")

    rows = {}
    for m in matches:
        try:
            rows[parse_date(m[0])] = float(m[4].replace(',', ''))  # 第5欄 = Last
        except Exception:
            continue

    if not rows:
        raise RuntimeError("數據解析後為空")

    df = pd.DataFrame({label: rows}).sort_index()
    df.index.name = 'Date'
    return df


def collect_all():
    """共用同一個 Chrome；任何失敗就砍掉重開，不在卡死的瀏覽器上繼續等。"""
    results = {}
    driver = None
    try:
        for label, symbol in SYMBOLS.items():
            print(f"\n🕵️ [{label}] 正在前往 Barchart 抓取 {symbol} ...")
            df = None
            for attempt in range(1, RETRIES + 1):
                t0 = time.time()
                try:
                    if driver is None:
                        driver = make_driver()
                    df = scrape_once(driver, symbol, label)
                    print(f"   ✅ 第{attempt}次成功 ({time.time() - t0:.0f}s)，共 {len(df)} 筆。"
                          f"最新: {df.index[-1].date()} = {df[label].iloc[-1]}")
                    break
                except Exception as e:
                    print(f"   ⚠️ 第{attempt}次失敗 ({time.time() - t0:.0f}s): "
                          f"{type(e).__name__}: {str(e)[:120]}")
                    safe_quit(driver)
                    driver = None
                    time.sleep(3)
            if df is None:
                print(f"   ❌ [{label}] 全部 {RETRIES} 次嘗試都失敗")
            results[label] = df
            time.sleep(2)
    finally:
        safe_quit(driver)
    return results


# ==========================================
# 💾 資料庫更新
# ==========================================
def update_database(new_data_dict):
    print(f"\n💾 正在更新歷史資料庫: {HISTORY_FILE} ...")

    history_df = pd.DataFrame()
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df['Date'] = pd.to_datetime(history_df['Date'])
            history_df.set_index('Date', inplace=True)
        except Exception as e:
            # 讀檔失敗時不能默默用空表覆蓋，否則整個歷史會被洗掉
            print(f"   ❌ 讀取歷史檔失敗: {e}")
            print("   ⛔ 中止更新，避免覆蓋既有資料。")
            sys.exit(1)

    frames = [df for df in new_data_dict.values() if df is not None]
    if not frames:
        print("   ❌ 沒有新數據可供更新。")
        return False

    daily_snapshot = frames[0]
    for df in frames[1:]:
        daily_snapshot = daily_snapshot.join(df, how='outer')
    daily_snapshot.index = pd.to_datetime(daily_snapshot.index)

    print(f"   📥 本次抓取範圍: {daily_snapshot.index.min().date()} ~ {daily_snapshot.index.max().date()}")

    if history_df.empty:
        history_df = daily_snapshot
    else:
        # 新資料優先；新資料缺的欄位保留舊值
        history_df = daily_snapshot.combine_first(history_df)

    history_df.sort_index(inplace=True)
    history_df.to_csv(HISTORY_FILE, date_format='%Y-%m-%d')
    print(f"   ✅ 更新完成！目前資料庫共有 {len(history_df)} 筆交易日數據。")
    print("   📊 最新 3 筆數據預覽:")
    print(history_df.tail(3))

    # 檢查最新一天四個欄位是否齊全
    missing = [c for c in SYMBOLS if c not in history_df.columns or pd.isna(history_df[c].iloc[-1])]
    if missing:
        print(f"   ⚠️ 最新一筆 ({history_df.index[-1].date()}) 缺少欄位: {missing}")
    return True


# ==========================================
# 🚀 主程式
# ==========================================
if __name__ == "__main__":
    start = time.time()
    print("🚀 啟動每日廣度數據收割機 (穩定版)...")
    print(f"   🕒 {datetime.now():%Y-%m-%d %H:%M:%S}")

    collected = collect_all()
    ok = update_database(collected)

    failed = [k for k, v in collected.items() if v is None]
    print(f"\n⏱️ 總耗時 {time.time() - start:.0f} 秒")
    if failed:
        print(f"⚠️ 以下代號本次未抓到: {failed}")
    print("🎉 任務結束。")

    # 全部失敗才讓 workflow 顯示紅燈；部分失敗仍正常結束，讓後續 commit 步驟照跑
    if not ok:
        sys.exit(1)
