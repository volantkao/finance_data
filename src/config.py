"""
COT 數據抓取器配置文件
"""

import os
from pathlib import Path

# 專案根目錄
BASE_DIR = Path(__file__).parent.parent

# API 端點（使用 resource 格式，不需要認證）
DISAGGREGATED_API = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
TFF_API = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

# CFTC App Token (可選，但建議使用以避免限流)
APP_TOKEN = os.getenv("CFTC_APP_TOKEN", "")

# 商品配置
COMMODITIES = {
    "GOLD": {
        "api_endpoint": DISAGGREGATED_API,
        "api_type": "disaggregated",
        "filter_field": "commodity_name",
        "filter_value": "GOLD",
        # NEW: two fixes for the same root cause - CFTC's disaggregated report
        # returns MULTIPLE rows per report_date for GOLD: (1) different contracts
        # sharing commodity_name=GOLD (main 100oz COMEX vs Micro Gold etc), and
        # (2) a 'FutOnly' row AND a 'Combined' (futures+options) row for the same
        # contract/date (see the futonly_or_combined field in the raw API response).
        # Without filtering both, drop_duplicates(keep='first') non-deterministically
        # keeps whichever row the API happened to return first that week, causing OI
        # to swing wildly between weeks (e.g. ~380k vs ~50-80k). Pin both explicitly.
        "contract_market_name": "GOLD",
        "futonly_or_combined": "FutOnly",
        "long_field": "m_money_positions_long_all",
        "short_field": "m_money_positions_short_all",
        "output_file": BASE_DIR / "data" / "gold_cot_data.csv",
        "description": "黃金 - Managed Money 部位"
    },
    "SILVER": {
        "api_endpoint": DISAGGREGATED_API,
        "api_type": "disaggregated",
        "filter_field": "commodity_name",
        "filter_value": "SILVER",
        # See note on GOLD above - same disambiguation applied here.
        "contract_market_name": "SILVER",
        "futonly_or_combined": "FutOnly",
        "long_field": "m_money_positions_long_all",
        "short_field": "m_money_positions_short_all",
        "output_file": BASE_DIR / "data" / "silver_cot_data.csv",
        "description": "白銀 - Managed Money 部位"
    },
    "SP500": {
        "api_endpoint": TFF_API,
        "api_type": "tff",
        "filter_field": "contract_market_name",
        "filter_value": "E-MINI S&P 500",
        "long_field": "asset_mgr_positions_long",
        "short_field": "asset_mgr_positions_short",
        "output_file": BASE_DIR / "data" / "sp500_cot_data.csv",
        "description": "S&P 500 E-mini - Asset Manager 部位"
    }
}

# API 請求配置
REQUEST_TIMEOUT = 30  # 秒
MAX_RETRIES = 3
RETRY_DELAY = 5  # 秒
PAGE_SIZE = 5000  # 每次請求的最大記錄數

# 數據欄位映射
COMMON_FIELDS = {
    "report_date_as_yyyy_mm_dd": "report_date",
    "open_interest_all": "open_interest"
}
