import asyncio
import csv
import json
import os
import time
from datetime import datetime
from playwright.async_api import async_playwright

# 設定目標網址
TARGET_URL = "https://www.macromicro.me/collections/19/mm-oil-price/4379/wti-intramarket-spread"
CSV_FILENAME = "wti_monitor_data.csv"

async def fetch_wti_data():
    async with async_playwright() as p:
        # 啟動瀏覽器
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        print(f"[{datetime.now()}] 正在訪問: {TARGET_URL}")
        
        try:
            # 導航至頁面並等待載入
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            
            # 等待 Highcharts 載入數據，通常需要一點時間
            print(f"[{datetime.now()}] 等待數據載入中...")
            await asyncio.sleep(15)
            
            # 透過 JavaScript 評估從 Highcharts 實例中擷取數據
            # 目標：WTI原油遠近期價差(L) 與 NYMEX-WTI西德州原油期貨(R)
            data = await page.evaluate("""
                () => {
                    if (typeof Highcharts === 'undefined' || !Highcharts.charts) return null;
                    const charts = Highcharts.charts.filter(c => c !== undefined);
                    if (charts.length > 0) {
                        return charts.map(chart => ({
                            title: chart.title ? chart.title.textStr : 'No Title',
                            series: chart.series.map(s => ({
                                name: s.name,
                                lastData: s.data.length > 0 ? s.data[s.data.length - 1].y : null,
                                lastX: s.data.length > 0 ? s.data[s.data.length - 1].x : null
                            }))
                        }));
                    }
                    return null;
                }
            """)
            
            if not data:
                print(f"[{datetime.now()}] 擷取失敗: 找不到 Highcharts 數據。可能是被 Cloudflare 阻擋或頁面未完全載入。")
                return None

            # 解析數據
            parsed_results = []
            # 我們尋找包含 WTI 的圖表
            for chart in data:
                entry = {"date": None, "spread": None, "price": None}
                found_wti = False
                for s in chart['series']:
                    if "WTI" in s['name'] or "價差" in s['name']:
                        found_wti = True
                        # 轉換時間戳
                        if s['lastX'] and not entry["date"]:
                            entry["date"] = time.strftime('%Y-%m-%d', time.gmtime(s['lastX'] / 1000.0))
                        
                        # 根據名稱分配數值，並四捨五入到小數點後兩位
                        if "價差" in s['name']:
                            entry["spread"] = round(s['lastData'], 4) if s['lastData'] is not None else None
                        elif "期貨" in s['name'] or "NYMEX-WTI" in s['name']:
                            entry["price"] = round(s['lastData'], 2) if s['lastData'] is not None else None
                
                if found_wti and entry["date"]:
                    parsed_results.append(entry)

            if parsed_results:
                # 通常我們只取最新的一筆（或是合併多個圖表的結果）
                # 在這個特定網頁，通常只有一個主要的圖表
                final_data = parsed_results[0]
                print(f"[{datetime.now()}] 成功擷取數據: {final_data}")
                return final_data
            else:
                print(f"[{datetime.now()}] 找不到符合條件的序列數據。")
                return None
                
        except Exception as e:
            print(f"[{datetime.now()}] 發生錯誤: {e}")
            return None
        finally:
            await browser.close()

def save_to_csv(new_data, filename=CSV_FILENAME):
    if not new_data or not new_data.get("date"):
        return
    
    file_exists = os.path.isfile(filename)
    
    # 讀取現有數據以避免重複
    existing_dates = set()
    if file_exists:
        with open(filename, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row['Date'])
    
    if new_data['date'] in existing_dates:
        print(f"[{datetime.now()}] 日期 {new_data['date']} 的數據已存在，跳過儲存。")
        return

    # 寫入 CSV
    with open(filename, mode='a', newline='', encoding='utf-8-sig') as f:
        fieldnames = ['Date', 'WTI_Intramarket_Spread(L)', 'NYMEX_WTI_Futures(R)']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow({
            'Date': new_data['date'],
            'WTI_Intramarket_Spread(L)': new_data['spread'],
            'NYMEX_WTI_Futures(R)': new_data['price']
        })
    
    print(f"[{datetime.now()}] 數據已成功追加至 {filename}")

async def main():
    data = await fetch_wti_data()
    if data:
        save_to_csv(data)
    else:
        print(f"[{datetime.now()}] 未能獲取數據，請檢查網路狀況或網頁結構是否變動。")

if __name__ == "__main__":
    asyncio.run(main())
