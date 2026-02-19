import asyncio
from playwright.async_api import async_playwright
import json
import time
import os
from datetime import datetime

async def fetch_macromicro_data():
    async with async_playwright() as p:
        # 啟動瀏覽器，設定常見的 User-Agent 和視窗大小
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        url = "https://www.macromicro.me/collections/20933/global-stock-market/115048/world-stock-market-correction-probability-indicators"
        print(f"[{datetime.now()}] 正在訪問: {url}")
        
        try:
            # 導航至頁面並等待 DOM 載入
            await page.goto(url, wait_until="load", timeout=60000)
            
            # 等待 JavaScript 執行與 Highcharts 初始化
            # 這裡使用固定等待時間以確保動態內容載入完成
            await asyncio.sleep(10)
            
            # 透過 JavaScript 評估從 Highcharts 實例中擷取數據
            data = await page.evaluate("""
                () => {
                    if (typeof Highcharts === 'undefined') return null;
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
            
            if data:
                # 處理並格式化擷取到的數據
                result = {
                    "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "charts": []
                }
                
                for chart in data:
                    chart_info = {"title": chart['title'], "indicators": []}
                    for s in chart['series']:
                        if s['lastX']:
                            date_str = time.strftime('%Y-%m-%d', time.gmtime(s['lastX'] / 1000.0))
                            chart_info["indicators"].append({
                                "name": s['name'],
                                "value": round(s['lastData'], 4) if s['lastData'] is not None else None,
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
    
    # 從檔案載入現有數據
    history = []
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            # 處理空檔案或無效的 JSON 檔案
            history = []
            
    # 追加新的數據記錄
    history.append(data)
    
    # 僅保留最新的 100 筆記錄以管理檔案大小
    if len(history) > 100:
        history = history[-100:]
        
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"資料已儲存至 {filename}")

async def main():
    data = await fetch_macromicro_data()
    if data:
        save_data(data)
        # 同時將最新數據儲存到獨立檔案，方便快速查看
        with open("latest.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    asyncio.run(main())
