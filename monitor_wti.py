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
        # 啟動瀏覽器，加入額外參數以利在 GitHub Actions 執行
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        # 增加預設超時時間
        page.set_default_timeout(60000)
        
        print(f"[{datetime.now()}] 正在訪問: {TARGET_URL}")
        
        try:
            # 修改導航策略：不等待 networkidle，改為等待 domcontentloaded
            # 因為財經M平方常有廣告或追蹤腳本導致 networkidle 永遠無法達成
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 等待關鍵圖表容器出現
            print(f"[{datetime.now()}] 等待圖表容器加載...")
            try:
                # 財經M平方的圖表通常在 .chart-container 或類似元素中
                await page.wait_for_selector(".chart-container, .highcharts-container", timeout=30000)
            except:
                print(f"[{datetime.now()}] 警告：未偵測到標準圖表容器，繼續嘗試抓取數據。")
            
            # 固定等待時間確保 Highcharts 實例初始化並填入數據
            await asyncio.sleep(10)
            
            # 透過 JavaScript 評估從 Highcharts 實例中擷取數據
            data = await page.evaluate("""
                () => {
                    if (typeof Highcharts === 'undefined' || !Highcharts.charts) return null;
                    const charts = Highcharts.charts.filter(c => c !== undefined && c.series);
                    if (charts.length > 0) {
                        return charts.map(chart => ({
                            title: chart.title ? chart.title.textStr : 'No Title',
                            series: chart.series.map(s => ({
                                name: s.name,
                                lastData: s.data && s.data.length > 0 ? s.data[s.data.length - 1].y : null,
                                lastX: s.data && s.data.length > 0 ? s.data[s.data.length - 1].x : null
                            }))
                        }));
                    }
                    return null;
                }
            """)
            
            if not data:
                # 截圖存檔以便偵錯 (在 GitHub Actions 的 artifacts 中可以查看)
                await page.screenshot(path="debug_screenshot.png")
                print(f"[{datetime.now()}] 擷取失敗: 找不到 Highcharts 數據。已儲存 debug_screenshot.png。")
                return None

            # 解析數據
            parsed_results = []
            for chart in data:
                entry = {"date": None, "spread": None, "price": None}
                found_wti = False
                for s in chart['series']:
                    name = s['name']
                    # 財經M平方的 WTI 價差通常包含 "WTI" 與 "價差"
                    # 期貨價格通常包含 "WTI" 與 "期貨" 或 "NYMEX"
                    if "WTI" in name or "價差" in name or "NYMEX" in name:
                        found_wti = True
                        if s['lastX'] and not entry["date"]:
                            entry["date"] = time.strftime('%Y-%m-%d', time.gmtime(s['lastX'] / 1000.0))
                        
                        if "價差" in name:
                            entry["spread"] = round(s['lastData'], 4) if s['lastData'] is not None else None
                        elif "期貨" in name or "NYMEX" in name:
                            entry["price"] = round(s['lastData'], 2) if s['lastData'] is not None else None
                
                if found_wti and entry["date"]:
                    parsed_results.append(entry)

            if parsed_results:
                # 優先選擇同時有價差與價格的結果
                best_entry = max(parsed_results, key=lambda x: (x['spread'] is not None) + (x['price'] is not None))
                print(f"[{datetime.now()}] 成功擷取數據: {best_entry}")
                return best_entry
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
        try:
            with open(filename, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Date'):
                        existing_dates.add(row['Date'])
        except Exception as e:
            print(f"[{datetime.now()}] 讀取現有 CSV 時發生錯誤 (可能格式損壞): {e}")
    
    if new_data['date'] in existing_dates:
        print(f"[{datetime.now()}] 日期 {new_data['date']} 的數據已存在，跳過儲存。")
        return

    # 寫入 CSV
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
    data = await fetch_wti_data()
    if data:
        save_to_csv(data)
    else:
        print(f"[{datetime.now()}] 未能獲取數據。")

if __name__ == "__main__":
    asyncio.run(main())
