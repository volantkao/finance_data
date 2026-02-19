import asyncio
from playwright.async_api import async_playwright
import json
import time
import os
from datetime import datetime

async def fetch_macromicro_data():
    async with async_playwright() as p:
        # Launch browser with a common user agent and viewport
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={\'width\': 1280, \'height\': 800}
        )
        page = await context.new_page()
        
        url = "https://www.macromicro.me/collections/20933/global-stock-market/115048/world-stock-market-correction-probability-indicators"
        print(f"[{datetime.now( )}] 正在訪問: {url}")
        
        try:
            # Navigate to the page and wait for the DOM to be loaded
            await page.goto(url, wait_until="load", timeout=60000)
            
            # Wait for JavaScript to execute and Highcharts to initialize
            # A fixed sleep is used here as a workaround for dynamic content loading
            await asyncio.sleep(10)
            
            # Extract data from Highcharts instances using JavaScript evaluation
            data = await page.evaluate("""
                () => {
                    if (typeof Highcharts === \'undefined\') return null;
                    const charts = Highcharts.charts.filter(c => c !== undefined);
                    if (charts.length > 0) {
                        return charts.map(chart => ({
                            title: chart.title ? chart.title.textStr : \'No Title\',
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
            
            if data:
                # Process and format the extracted data
                result = {
                    "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "charts": []
                }
                
                for chart in data:
                    chart_info = {"title": chart[\'title\'], "indicators": []}
                    for s in chart[\'series\']:
                        if s[\'lastX\']:
                            date_str = time.strftime(\'%Y-%m-%d\', time.gmtime(s[\'lastX\'] / 1000.0))
                            chart_info["indicators"].append({
                                "name": s[\'name\'],
                                "value": round(s[\'lastData\'], 4) if s[\'lastData\'] is not None else None,
                                "date": date_str
                            })
                    result["charts"].append(chart_info)
                
                print(f"[{datetime.now()}] 資料擷取成功")
                return result
            else:
                print(f"[{datetime.now()}] 擷取失敗: 找不到圖表數據")
                return None
                
        except Exception as e:
            print(f"[{datetime.now()}] 發生錯誤: {e}")
            return None
        finally:
            await browser.close()

def save_data(data, filename="history_data.json"):
    if not data:
        return
    
    # Load existing data from the file
    history = []
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            # Handle empty or invalid JSON file
            history = []
            
    # Append new data record
    history.append(data)
    
    # Keep only the last 100 records to manage file size
    if len(history) > 100:
        history = history[-100:]
        
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"資料已儲存至 {filename}")

async def main():
    data = await fetch_macromicro_data()
    if data:
        save_data(data)
        # Also save the latest data to a separate file for easy access
        with open("latest.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    asyncio.run(main())