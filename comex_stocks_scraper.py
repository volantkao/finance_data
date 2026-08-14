"""
COMEX 倉儲庫存抓取器

從 CME 官方每日報告抓取 Registered / Eligible / Combined Total 庫存量，
用於判斷是否有實物擠壓跡象（跟選擇權gamma squeeze是不同機制，但同樣是
判斷黃金/白銀市場壓力的重要指標）。

資料來源（固定網址，每天更新內容）：
    Gold:   https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls
    Silver: https://www.cmegroup.com/delivery_reports/Silver_stocks.xls

解析邏輯：
    這兩份報告是舊版 .xls（CDFV2/OLE2 二進位格式，需要 xlrd 引擎讀取），
    結構是先列出每個depository的明細，最後有四行加總：
        TOTAL REGISTERED / TOTAL PLEDGED / TOTAL ELIGIBLE / COMBINED TOTAL
    本腳本抓的就是這四行的 "TOTAL TODAY" 欄位（今日收盤庫存量）。
    已驗證 COMBINED TOTAL = TOTAL REGISTERED + TOTAL ELIGIBLE
    （Pledged 是 Registered 底下的子集合，不重複累加）。

    報告日期從表頭 "Report Date: M/D/YYYY" 文字解析。

輸出：comex_gold_stocks.csv / comex_silver_stocks.csv
    欄位：report_date, registered, pledged, eligible, combined_total

用法：
    pip install requests pandas xlrd
    python comex_stocks_scraper.py
"""

import re
import os
import logging
from io import BytesIO
from datetime import datetime

import requests
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

METALS = {
    "gold": {
        "url": "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls",
        "output_file": "comex_gold_stocks.csv",
    },
    "silver": {
        "url": "https://www.cmegroup.com/delivery_reports/Silver_stocks.xls",
        "output_file": "comex_silver_stocks.csv",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# TOTAL TODAY 欄位的欄位索引（col0=depository/label名稱, col2=PREV TOTAL, col7=TOTAL TODAY）
COL_LABEL = 0
COL_TOTAL_TODAY = 7

TARGET_LABELS = {
    "TOTAL REGISTERED": "registered",
    "TOTAL PLEDGED": "pledged",
    "TOTAL ELIGIBLE": "eligible",
    "COMBINED TOTAL": "combined_total",
}


def parse_report_date(df_raw: pd.DataFrame) -> str:
    """
    從表格內容裡找出 "Report Date: M/D/YYYY" 這種文字並解析成 YYYY-MM-DD

    Args:
        df_raw: 完整原始表格（header=None讀入）

    Returns:
        str: YYYY-MM-DD 格式的日期字串

    Raises:
        ValueError: 找不到報告日期時拋出，避免寫入錯誤/空白的日期
    """
    for _, row in df_raw.iterrows():
        for cell in row:
            if isinstance(cell, str) and "Report Date" in cell:
                match = re.search(r"Report Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})", cell)
                if match:
                    month, day, year = match.groups()
                    return f"{year}-{int(month):02d}-{int(day):02d}"
    raise ValueError("在報告裡找不到 'Report Date:' 文字，表格結構可能變了")


def parse_totals(df_raw: pd.DataFrame) -> dict:
    """
    從表格裡找出 TOTAL REGISTERED / TOTAL PLEDGED / TOTAL ELIGIBLE / COMBINED TOTAL 四行

    Args:
        df_raw: 完整原始表格（header=None讀入）

    Returns:
        dict: {"registered": float, "pledged": float or None,
               "eligible": float, "combined_total": float}
    """
    results = {}
    for _, row in df_raw.iterrows():
        label = row[COL_LABEL]
        if not isinstance(label, str):
            continue
        label_clean = label.strip().upper()
        if label_clean in TARGET_LABELS:
            key = TARGET_LABELS[label_clean]
            value = row[COL_TOTAL_TODAY]
            results[key] = float(value) if pd.notna(value) else None

    missing = set(["registered", "eligible", "combined_total"]) - set(results.keys())
    if missing:
        raise ValueError(f"表格裡缺少必要的加總列: {missing}，結構可能變了，需要人工檢查")

    # 校驗：COMBINED TOTAL 應該等於 registered + eligible（已知邏輯，異常代表格式變了）
    expected = results["registered"] + results["eligible"]
    actual = results["combined_total"]
    if abs(expected - actual) > 1:  # 容許極小的浮點數誤差
        logger.warning(
            f"⚠️ COMBINED TOTAL({actual}) != registered+eligible({expected})，"
            f"報告結構可能有變化，請人工確認"
        )

    return results


def fetch_and_parse(metal: str) -> dict:
    """
    下載並解析單一金屬的 COMEX 倉儲報告

    Returns:
        dict: {"report_date": str, "registered": float, "pledged": float,
               "eligible": float, "combined_total": float}
    """
    config = METALS[metal]
    logger.info(f"下載 {metal} 報告: {config['url']}")

    resp = requests.get(config["url"], headers=HEADERS, timeout=30)
    resp.raise_for_status()

    df_raw = pd.read_excel(
        BytesIO(resp.content),
        sheet_name="Daily Metal Stocks Report",
        header=None,
        engine="xlrd",
    )

    report_date = parse_report_date(df_raw)
    totals = parse_totals(df_raw)
    totals["report_date"] = report_date

    logger.info(f"✅ {metal} {report_date}: "
                f"registered={totals['registered']:.0f}, "
                f"eligible={totals['eligible']:.0f}, "
                f"combined_total={totals['combined_total']:.0f}")

    return totals


def update_csv(metal: str, data: dict):
    """
    把單日資料更新/追加到對應的 CSV
    """
    config = METALS[metal]
    output_file = config["output_file"]

    columns = ["report_date", "registered", "pledged", "eligible", "combined_total"]

    if os.path.exists(output_file):
        df = pd.read_csv(output_file)
    else:
        df = pd.DataFrame(columns=columns)

    report_date = data["report_date"]

    if report_date in df["report_date"].values:
        logger.info(f"ℹ️ {metal} {report_date} 已存在，更新數值")
        for col in columns[1:]:
            df.loc[df["report_date"] == report_date, col] = data.get(col)
    else:
        logger.info(f"➕ 新增 {metal} {report_date}")
        new_row = {col: data.get(col) for col in columns}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    df = df.sort_values("report_date")

    try:
        df.to_csv(output_file, index=False)
        logger.info(f"💾 已儲存至 {output_file}")
    except Exception as e:
        logger.error(f"❌ 儲存 {output_file} 失敗: {e}")
        raise


def main():
    failed = []
    for metal in METALS:
        try:
            data = fetch_and_parse(metal)
            update_csv(metal, data)
        except Exception as e:
            logger.error(f"❌ 處理 {metal} 失敗: {e}", exc_info=True)
            failed.append(metal)

    if failed:
        logger.error(f"失敗: {failed}")
        raise SystemExit(1)
    logger.info("全部完成")


if __name__ == "__main__":
    main()
