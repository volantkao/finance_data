"""
COT 數據抓取器主程式
每日自動從 CFTC API 抓取黃金、白銀、S&P 500 的 COT 數據
"""

import sys
import logging
from datetime import datetime, timedelta

from config import COMMODITIES
from cftc_api import CFTCAPIClient
from data_processor import COTDataProcessor

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_and_update_commodity(commodity_name: str, config: dict, api_client: CFTCAPIClient) -> bool:
    """
    抓取並更新單一商品的 COT 數據
    
    Args:
        commodity_name: 商品名稱
        config: 商品配置
        api_client: API 客戶端
        
    Returns:
        是否成功更新
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"開始處理: {commodity_name} - {config['description']}")
    logger.info(f"{'='*60}")
    
    try:
        # 初始化數據處理器
        processor = COTDataProcessor(config)
        
        # 獲取現有數據的最新日期
        latest_date = processor.get_latest_date()
        
        if latest_date:
            logger.info(f"現有數據最新日期: {latest_date}")
            # 從最新日期的前一週開始抓取（確保不遺漏）
            start_date_obj = datetime.strptime(latest_date, '%Y-%m-%d') - timedelta(days=7)
            start_date = start_date_obj.strftime('%Y-%m-%d')
        else:
            logger.info("無現有數據，將抓取最近 52 週的數據")
            # 抓取最近一年的數據
            start_date_obj = datetime.now() - timedelta(days=1850)
            start_date = start_date_obj.strftime('%Y-%m-%d')
        
        # 從 API 獲取數據
        raw_data = api_client.fetch_data(
            api_endpoint=config['api_endpoint'],
            filter_field=config['filter_field'],
            filter_value=config['filter_value'],
            start_date=start_date
        )
        
        if not raw_data:
            logger.warning(f"{commodity_name} 沒有新數據")
            return False
        
        # 更新數據
        success = processor.update(raw_data)
        
        if success:
            logger.info(f"✓ {commodity_name} 數據更新成功")
        else:
            logger.error(f"✗ {commodity_name} 數據更新失敗")
        
        return success
        
    except Exception as e:
        logger.error(f"處理 {commodity_name} 時發生錯誤: {e}", exc_info=True)
        return False


def main():
    """主函數"""
    logger.info(f"\n{'#'*60}")
    logger.info(f"COT 數據抓取器啟動")
    logger.info(f"執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'#'*60}\n")
    
    # 初始化 API 客戶端
    api_client = CFTCAPIClient()
    
    # 記錄成功和失敗的商品
    success_count = 0
    failed_commodities = []
    
    try:
        # 處理每個商品
        for commodity_name, config in COMMODITIES.items():
            success = fetch_and_update_commodity(commodity_name, config, api_client)
            
            if success:
                success_count += 1
            else:
                failed_commodities.append(commodity_name)
        
        # 輸出總結
        logger.info(f"\n{'='*60}")
        logger.info(f"執行完成")
        logger.info(f"{'='*60}")
        logger.info(f"成功: {success_count}/{len(COMMODITIES)}")
        
        if failed_commodities:
            logger.warning(f"失敗: {', '.join(failed_commodities)}")
            sys.exit(1)  # 有失敗的商品時返回非零退出碼
        else:
            logger.info("所有商品數據更新成功！")
            sys.exit(0)
        
    except Exception as e:
        logger.error(f"程式執行時發生嚴重錯誤: {e}", exc_info=True)
        sys.exit(1)
    
    finally:
        # 關閉 API 客戶端
        api_client.close()


if __name__ == "__main__":
    main()
