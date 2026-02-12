"""
CFTC API 客戶端
用於從 CFTC Public Reporting Environment 獲取 COT 數據
"""

import requests
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

from config import APP_TOKEN, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY, PAGE_SIZE

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CFTCAPIClient:
    """CFTC API 客戶端類"""
    
    def __init__(self, app_token: Optional[str] = None):
        """
        初始化 API 客戶端
        
        Args:
            app_token: CFTC App Token (可選)
        """
        self.app_token = app_token or APP_TOKEN
        self.session = requests.Session()
        if self.app_token:
            self.session.headers.update({'X-App-Token': self.app_token})
    
    def fetch_data(
        self,
        api_endpoint: str,
        filter_field: str,
        filter_value: str,
        start_date: Optional[str] = None,
        limit: int = PAGE_SIZE
    ) -> List[Dict]:
        """
        從 CFTC API 獲取數據（使用 GET 方法和 SoQL 查詢參數）
        
        Args:
            api_endpoint: API 端點 URL
            filter_field: 篩選欄位名稱
            filter_value: 篩選值
            start_date: 起始日期 (YYYY-MM-DD)，如果為 None 則獲取最新數據
            limit: 返回記錄數限制
            
        Returns:
            包含 COT 數據的字典列表
        """
        # 構建 SoQL WHERE 子句
        where_clause = f"{filter_field} = '{filter_value}'"
        if start_date:
            where_clause += f" AND report_date_as_yyyy_mm_dd >= '{start_date}'"
        
        # 使用 GET 方法和查詢參數
        params = {
            '$where': where_clause,
            '$order': 'report_date_as_yyyy_mm_dd DESC',
            '$limit': limit
        }
        
        if self.app_token:
            params['$$app_token'] = self.app_token
        
        logger.info(f"正在獲取數據: {filter_value}")
        logger.debug(f"WHERE 子句: {where_clause}")
        
        for attempt in range(MAX_RETRIES):
            try:
                # 使用 GET 方法
                response = self.session.get(
                    api_endpoint,
                    params=params,
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                
                data = response.json()
                
                # 檢查是否有數據
                if not data:
                    logger.warning(f"未找到 {filter_value} 的數據")
                    return []
                
                logger.info(f"成功獲取 {len(data)} 筆 {filter_value} 數據")
                return data
                
            except requests.exceptions.RequestException as e:
                logger.error(f"API 請求失敗 (嘗試 {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    logger.info(f"等待 {RETRY_DELAY} 秒後重試...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"達到最大重試次數，放棄獲取 {filter_value} 數據")
                    raise
        
        return []
    
    def get_latest_report_date(
        self,
        api_endpoint: str,
        filter_field: str,
        filter_value: str
    ) -> Optional[str]:
        """
        獲取最新報告日期
        
        Args:
            api_endpoint: API 端點 URL
            filter_field: 篩選欄位名稱
            filter_value: 篩選值
            
        Returns:
            最新報告日期 (YYYY-MM-DD) 或 None
        """
        data = self.fetch_data(
            api_endpoint=api_endpoint,
            filter_field=filter_field,
            filter_value=filter_value,
            limit=1
        )
        
        if data and len(data) > 0:
            # 提取日期
            date_str = data[0].get('report_date_as_yyyy_mm_dd')
            if date_str:
                # 轉換為 YYYY-MM-DD 格式
                try:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    return dt.strftime('%Y-%m-%d')
                except (ValueError, AttributeError):
                    return date_str.split('T')[0] if 'T' in date_str else date_str
        
        return None
    
    def close(self):
        """關閉 session"""
        self.session.close()
