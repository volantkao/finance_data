
Carry-to-Risk (美日套息 CP 值)

Vulnerability Index (美股脆弱性)

LVII (灰犀牛 - CSD 子項)

import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta

# ==============================================================================
# LITE HISTORY GENERATOR (Standalone)
# 用途: 每天執行一次，生成過去 30 天的"安全"歷史數據供 App 繪圖
# 特性: 嚴格排除任何涉及 JGB (日本公債) 的指標，確保數據連續性
# ==============================================================================

def generate_safe_history():
    print("🚀 開始執行 Lite 歷史數據生成程序...")
    
    # 1. 定義要抓取的安全資產 (Safe Assets Only)
    tickers = {
        'SPY': 'SPY',         # 美股基準
        '^TWII': 'TWII',      # 台股基準
        'BIL': 'BIL',         # 資金壓力 (Funding Proxy)
        'XLF': 'XLF',         # 券商健康 (Dealer Proxy)
        'AUDJPY': 'AUDJPY=X', # 套息走勢 (Carry Trend) - 只看價格，不算 Ratio
        'USDJPY': 'JPY=X'     # 匯率參考
    }
    
    # 2. 設定時間窗口
    # 雖然只要 30 天輸出，但我們抓 180 天以確保 Z-Score 計算有足夠樣本
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)
    
    print(f"📥 下載數據中 ({start_date.strftime('%Y-%m-%d')} ~ Now)...")
    
    try:
        data = yf.download(list(tickers.values()), start=start_date, end=end_date, progress=True)
        
        # 處理 yfinance 多層索引問題
        if isinstance(data.columns, pd.MultiIndex):
            try:
                adj_close = data['Adj Close']
            except KeyError:
                adj_close = data['Close']
        else:
            adj_close = data['Close']
            
        # 重新命名欄位 (Ticker -> Readable Name)
        # 建立反向映射: {Code: Name}
        rename_map = {v: k for k, v in tickers.items()}
        # 過濾並改名
        valid_cols = [c for c in adj_close.columns if c in rename_map]
        df = adj_close[valid_cols].rename(columns=rename_map)
        
        # 填補空值 (避免假期造成的 NaN)
        df = df.ffill().bfill()
        
    except Exception as e:
        print(f"❌ 數據下載失敗: {e}")
        return

    print("⚙️ 計算核心指標 (Safe Metrics Only)...")
    
    # --- A. Funding Stress (資金壓力) ---
    # 邏輯: BIL 的價格穩定度 Z-Score
    # 視窗: 60天滾動
    bil_ret = df['BIL'].pct_change()
    bil_z = (bil_ret - bil_ret.rolling(60).mean()) / bil_ret.rolling(60).std()
    
    # --- B. Dealer Health (券商健康度) ---
    # 邏輯: XLF / SPY 相對強弱
    dealer_ratio = df['XLF'] / df['SPY']
    # 歸一化: 除以 60 日均線，變成 "偏離度 %"
    dealer_trend = (dealer_ratio - dealer_ratio.rolling(60).mean()) / dealer_ratio.rolling(60).mean() * 100
    
    # --- C. Carry Trend (套息走勢) ---
    # 邏輯: 僅提供 AUD/JPY 價格走勢 (不做複雜運算)
    carry_price = df['AUDJPY']
    
    # --- D. Market Price (大盤) ---
    spy_price = df['SPY']
    twii_price = df['^TWII']
    usdjpy_price = 1 / df['USDJPY'] # yfinance JPY=X 通常是 JPY/USD，需倒數變 USD/JPY (視情況調整)
    # 修正: Yahoo 的 JPY=X 報價通常是 150.x (即 USD/JPY)，如果是這樣就不用倒數
    # 檢查一下大致數值，如果 > 100 就是 USD/JPY
    if df['USDJPY'].iloc[-1] < 1.0:
        usdjpy_price = 1 / df['USDJPY']
    else:
        usdjpy_price = df['USDJPY']

    # 3. 組合最終數據表
    final_df = pd.DataFrame({
        'Funding_Z': bil_z,          # 資金壓力 (負越多越危險)
        'Dealer_Dev': dealer_trend,  # 券商信心 (正代表強勢)
        'Carry_Px': carry_price,     # 套息趨勢
        'SPY': spy_price,            # 美股
        'TWII': twii_price,          # 台股
        'USDJPY': usdjpy_price       # 匯率
    })
    
    # 4. 裁切最後 30 天 (Output Slicing)
    output_df = final_df.tail(30).copy()
    
    # 5. 輸出 JSON
    # 格式處理: 日期轉字串，數值保留 4 位小數
    output_df.index = output_df.index.strftime('%Y-%m-%d')
    output_df = output_df.round(4)
    
    # 轉成 List of Dictionaries 格式，方便 App 讀取
    # 格式範例: [{"Date": "2023-12-01", "SPY": 450.1, ...}, ...]
    json_data = output_df.reset_index().rename(columns={'index': 'Date'}).to_json(orient='records')
    
    filename = 'app_lite_history_30d.json'
    with open(filename, 'w') as f:
        f.write(json_data)
        
    print(f"\n✅ 成功生成: {filename}")
    print(f"   資料筆數: {len(output_df)} 天")
    print(f"   包含欄位: {list(output_df.columns)}")
    print("\n🔍 預覽最後一筆數據:")
    print(output_df.iloc[-1].to_dict())

if __name__ == "__main__":
    generate_safe_history()

輸出檔案說明 (app_lite_history_30d.json)
這隻程式跑完後，會產生一個乾淨的 JSON 檔，裡面包含 App 畫圖所需的所有數據。

欄位定義 (你可以直接貼給 App 開發者看)：

Date: 日期 (X軸)

SPY: 美股價格 (Y軸 - 價格線)

TWII: 台股價格 (Y軸 - 價格線)

USDJPY: 美元日圓匯率 (Y軸 - 價格線)

Carry_Px: 澳幣日圓價格 (Y軸 - 趨勢線) -> 用來代替 Carry-to-Risk，告訴用戶套息交易現在是賺錢還是賠錢。

Funding_Z: 資金壓力 Z-Score (Y軸 - 柱狀圖) -> 這是 CTM 的核心，數值 < -2.5 為危險。

Dealer_Dev: 券商信心乖離率 % (Y軸 - 柱狀圖) -> 正值代表券商願意承擔風險。