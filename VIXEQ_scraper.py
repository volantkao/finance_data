"""
VIX 家族指數抓取器 (取代原本 VIXEQ_scraper.py 的 Selenium 作法)

原本的 VIXEQ_scraper.py 用 Selenium + Google Finance 抓 VIXEQ 單一數值，
確認 Yahoo Finance 其實直接有這些 ticker，可以用 yfinance 一次抓齊，
不需要開瀏覽器：
    ^VIX    - CBOE Volatility Index (標準 VIX)
    ^VIX9D  - 9-day VIX
    ^VIX1D  - Cboe 1-Day Volatility Index (CBOE已停用VIX3D，這是現行的短天期替代指數)
    ^VIXEQ  - Cboe S&P 500 Constituent Volatility Index
    ^GVZ    - Cboe Gold ETF Volatility Index (黃金選擇權隱含波動率，gamma squeeze監控用)

輸出檔案：沿用原本的 vixeq-history.csv，欄位新增 VIX/VIX9D/VIX1D/GVZ，
但 Date、Close 兩個既有欄位維持不變（Close = VIXEQ 收盤值），
確保其他監控腳本讀取這個檔案不會壞掉。
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FILENAME = "vixeq-history.csv"

TICKERS = {
    "Close": "^VIXEQ",   # 沿用舊欄位名稱 Close = VIXEQ，避免破壞既有監控腳本
    "VIX": "^VIX",
    "VIX9D": "^VIX9D",
    "VIX1D": "^VIX1D",   # CBOE已停止維護VIX3D，Yahoo無資料；VIX1D是CBOE現行的1日波動率指數替代品
    "GVZ": "^GVZ",       # Cboe Gold ETF波動率指數，用於黃金gamma squeeze/擠壓監控對照
}
}


def fetch_vix_family():
    """
    透過 yfinance 抓取 VIX 家族指數的最新收盤值

    Returns:
        dict: {"Close": float, "VIX": float, "VIX9D": float, "VIX3D": float}
              抓取失敗的欄位值為 None
    """
    results = {}
    for col_name, ticker_symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="5d")  # 抓5天避免遇到假日/資料延遲抓不到
            if hist.empty:
                logger.warning(f"⚠️ {ticker_symbol} 沒有資料")
                results[col_name] = None
                continue
            price = round(float(hist['Close'].iloc[-1]), 2)
            results[col_name] = price
            logger.info(f"✅ {ticker_symbol} = {price}")
        except Exception as e:
            logger.error(f"❌ 抓取 {ticker_symbol} 失敗: {e}")
            results[col_name] = None
    return results


def update_csv(values: dict):
    """
    更新或新增今天的資料到 CSV

    Args:
        values: fetch_vix_family() 回傳的字典
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. 讀取或建立 DataFrame
    if os.path.exists(FILENAME):
        try:
            df = pd.read_csv(FILENAME)
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
        except Exception as e:
            logger.warning(f"⚠️ 讀取 CSV 失敗，建立新檔: {e}")
            df = pd.DataFrame(columns=["Date", "Close"])
    else:
        df = pd.DataFrame(columns=["Date", "Close"])

    # 2. 確保新欄位存在（既有資料沒有 VIX/VIX9D/VIX1D/GVZ 的部分會是 NaN，不影響舊資料）
    for col in ["VIX", "VIX9D", "VIX1D", "GVZ"]:
        if col not in df.columns:
            df[col] = None

    # 3. 檢查今天是否已有資料
    if today_str in df['Date'].values:
        logger.info(f"ℹ️ {today_str} 的資料已存在，更新數值...")
        for col, val in values.items():
            df.loc[df['Date'] == today_str, col] = val
    else:
        logger.info(f"➕ 新增資料: {today_str} = {values}")
        new_row = {"Date": today_str, **values}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    # 4. 排序並存檔
    df = df.sort_values(by="Date")
    try:
        df.to_csv(FILENAME, index=False)
        logger.info(f"💾 檔案已保存至 {FILENAME}")
    except Exception as e:
        logger.error(f"❌ 儲存 CSV 失敗: {e}")
        raise


if __name__ == "__main__":
    import sys
    values = fetch_vix_family()
    if values.get("Close") is not None:
        update_csv(values)
    else:
        logger.error("❌ 無法獲取 VIXEQ 價格，程式終止。")
        sys.exit(1)
