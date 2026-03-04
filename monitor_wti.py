import asyncio
import csv
import json
import os
import time
import random
from datetime import datetime
from playwright.async_api import async_playwright

# 設定目標網址
TARGET_URL = "https://www.macromicro.me/collections/19/mm-oil-price/4379/wti-intramarket-spread"
CSV_FILENAME = "wti_monitor_data.csv"

async def fetch_wti_data_once(p):
    # 啟動瀏覽器
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox", 
            "--disable-setuid-sandbox", 
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"
        ]
    )
    
    # 模擬更真實的瀏覽器指紋
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={'width': 1920, 'height': 1080},
        extra_http_headers={
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Referer": "https://www.google.com/"
        }
    )
    
    # 隱藏自動化特徵
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-TW', 'zh'] });
    """)
    
    page = await context.new_page()
    page.set_default_timeout(60000)
    
    print(f"[{datetime.now()}] 正在訪問: {TARGET_URL}")
    
    try:
        # 隨機延遲
        await asyncio.sleep(random.uniform(3, 7))
        
        # 導航，不等待任何條件，手動處理
        try:
            await page.goto(TARGET_URL, timeout=60000)
        except Exception as e:
            print(f"[{datetime.now()}] 導航發生異常 (可能正在載入): {e}")

        # 給予充足時間讓 Cloudflare 驗證與圖表載入
        print(f"[{datetime.now()}] 等待頁面穩定與圖表加載 (30秒)...")
        for i in range(6):
            await asyncio.sleep(5)
            title = await page.title()
            print(f"[{datetime.now()}] 當前標題: {title}")
            if "WTI" in title:
                break
        
        # 模擬一些人為滾動
        await page.mouse.wheel(0, 300)
        await asyncio.sleep(2)
        
        # 嘗試多種選擇器
        found = False
        selectors = [".chart-container", ".highcharts-container", ".m-chart"]
        for sel in selectors:
            if await page.query_selector(sel):
                print(f"[{datetime.now()}] 找到圖表容器: {sel}")
                found = True
                break
        
        if not found:
            content = await page.content()
            print(f"[{datetime.now()}] 警告：未偵測到圖表容器。內容長度: {len(content)}")
            await page.screenshot(path=f"debug_failed_{int(time.time())}.png")
            # 如果標題是 "Just a moment..." 則確定被阻擋
            if "Just a moment" in await page.title():
                print(f"[{datetime.now()}] 確認被 Cloudflare 阻擋。")
            return None
        
        # 擷取數據
        data = await page.evaluate("""
            () => {
                if (typeof Highcharts === 'undefined' || !Highcharts.charts) return null;
                const charts = Highcharts.charts.filter(c => c !== undefined && c.series);
                return charts.map(chart => ({
                    title: chart.title ? chart.title.textStr : 'No Title',
                    series: chart.series.map(s => ({
                        name: s.name,
                        lastData: s.data && s.data.length > 0 ? s.data[s.data.length - 1].y : null,
                        lastX: s.data && s.data.length > 0 ? s.data[s.data.length - 1].x : null
                    }))
                }));
            }
        """)
        
        if not data:
            print(f"[{datetime.now()}] 擷取失敗: 找不到 Highcharts 數據物件。")
            return None

        parsed_results = []
        for chart in data:
            entry = {"date": None, "spread": None, "price": None}
            found_target = False
            for s in chart['series']:
                name = s['name']
                if "WTI" in name or "價差" in name or "NYMEX" in name:
                    found_target = True
                    if s['lastX'] and not entry["date"]:
                        entry["date"] = time.strftime('%Y-%m-%d', time.gmtime(s['lastX'] / 1000.0))
                    if "價差" in name:
                        entry["spread"] = round(s['lastData'], 4) if s['lastData'] is not None else None
                    elif "期貨" in name or "NYMEX" in name:
                        entry["price"] = round(s['lastData'], 2) if s['lastData'] is not None else None
            if found_target and entry["date"]:
                parsed_results.append(entry)

        if parsed_results:
            best_entry = max(parsed_results, key=lambda x: (x['date'], (x['spread'] is not None) + (x['price'] is not None)))
            print(f"[{datetime.now()}] 成功擷取數據: {best_entry}")
            return best_entry
        return None
            
    except Exception as e:
        print(f"[{datetime.now()}] 發生錯誤: {e}")
        return None
    finally:
        await browser.close()

async def fetch_wti_data_with_retry(retries=3):
    async with async_playwright() as p:
        for i in range(retries):
            print(f"[{datetime.now()}] 嘗試第 {i+1} 次抓取...")
            result = await fetch_wti_data_once(p)
            if result:
                return result
            if i < retries - 1:
                wait_time = random.uniform(20, 40)
                print(f"[{datetime.now()}] 抓取失敗，等待 {wait_time:.1f} 秒後重試...")
                await asyncio.sleep(wait_time)
        return None

def save_to_csv(new_data, filename=CSV_FILENAME):
    if not new_data or not new_data.get("date"):
        return
    file_exists = os.path.isfile(filename)
    existing_dates = set()
    if file_exists:
        try:
            with open(filename, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Date'):
                        existing_dates.add(row['Date'])
        except Exception:
            pass
    if new_data['date'] in existing_dates:
        print(f"[{datetime.now()}] 日期 {new_data['date']} 的數據已存在，跳過儲存。")
        return
    with open(filename, mode='a', newline='', encoding='utf-8-sig') as f:
        fieldnames = ['Date', 'WTI_Intramarket_Spread(L)', 'NYMEX_WTI_Futures(R)']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists or os.path.getsize(filename) == 0:
            writer.writeheader()
        writer.writerow({
            'Date': new_data['date'],
            'WTI_Intramarket_Spread(L)': new_data['spread'],
            'NYMEX_WTI_Futures(R)': new_data['price']
        })
    print(f"[{datetime.now()}] 數據已成功追加至 {filename}")

async def main():
    data = await fetch_wti_data_with_retry(retries=3)
    if data:
        save_to_csv(data)
    else:
        print(f"[{datetime.now()}] 經過多次嘗試後仍未能獲取數據。")

if __name__ == "__main__":
    asyncio.run(main())
