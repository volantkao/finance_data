"""
數據處理模組
用於處理和儲存 COT 數據
"""

import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import logging

from config import COMMON_FIELDS

logger = logging.getLogger(__name__)


class COTDataProcessor:
    """COT 數據處理器"""
    
    def __init__(self, commodity_config: Dict):
        """
        初始化數據處理器
        
        Args:
            commodity_config: 商品配置字典
        """
        self.config = commodity_config
        self.output_file = Path(commodity_config['output_file'])
        self.long_field = commodity_config['long_field']
        self.short_field = commodity_config['short_field']
    
    def process_data(self, raw_data: List[Dict]) -> pd.DataFrame:
        """
        處理原始 API 數據
        
        Args:
            raw_data: 從 API 獲取的原始數據列表
            
        Returns:
            處理後的 DataFrame
        """
        if not raw_data:
            logger.warning("沒有數據需要處理")
            return pd.DataFrame()
        
        # 轉換為 DataFrame
        df = pd.DataFrame(raw_data)
        
        # 提取所需欄位
        required_fields = {
            'report_date_as_yyyy_mm_dd': 'report_date',
            'open_interest_all': 'open_interest',
            self.long_field: 'long_positions',
            self.short_field: 'short_positions'
        }
        
        # 檢查欄位是否存在
        missing_fields = [f for f in required_fields.keys() if f not in df.columns]
        if missing_fields:
            logger.error(f"缺少必要欄位: {missing_fields}")
            logger.debug(f"可用欄位: {df.columns.tolist()}")
            raise ValueError(f"數據缺少必要欄位: {missing_fields}")
        
        # 選擇並重命名欄位
        df = df[list(required_fields.keys())].copy()
        df.rename(columns=required_fields, inplace=True)
        
        # 處理日期格式
        df['report_date'] = pd.to_datetime(df['report_date']).dt.strftime('%Y-%m-%d')
        
        # 轉換數值類型
        for col in ['open_interest', 'long_positions', 'short_positions']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 計算淨部位
        df['net_positions'] = df['long_positions'] - df['short_positions']
        
        # 按日期排序（最新在前）
        df.sort_values('report_date', ascending=False, inplace=True)
        
        # 移除重複日期（保留最新的）
        df.drop_duplicates(subset=['report_date'], keep='first', inplace=True)
        
        logger.info(f"處理完成，共 {len(df)} 筆記錄")
        
        return df
    
    def load_existing_data(self) -> pd.DataFrame:
        """
        載入現有的 CSV 數據
        
        Returns:
            現有數據的 DataFrame，如果文件不存在則返回空 DataFrame
        """
        if self.output_file.exists():
            try:
                df = pd.read_csv(self.output_file)
                logger.info(f"載入現有數據: {len(df)} 筆記錄")
                return df
            except Exception as e:
                logger.error(f"載入現有數據失敗: {e}")
                return pd.DataFrame()
        else:
            logger.info("未找到現有數據文件，將建立新文件")
            return pd.DataFrame()
    
    def merge_data(self, new_data: pd.DataFrame, existing_data: pd.DataFrame) -> pd.DataFrame:
        """
        合併新舊數據
        
        Args:
            new_data: 新數據 DataFrame
            existing_data: 現有數據 DataFrame
            
        Returns:
            合併後的 DataFrame
        """
        if existing_data.empty:
            return new_data
        
        if new_data.empty:
            return existing_data
        
        # 合併數據
        merged = pd.concat([new_data, existing_data], ignore_index=True)
        
        # 移除重複日期（保留新數據）
        merged.drop_duplicates(subset=['report_date'], keep='first', inplace=True)
        
        # 按日期排序（最新在前）
        merged.sort_values('report_date', ascending=False, inplace=True)
        
        logger.info(f"合併後共 {len(merged)} 筆記錄")
        
        return merged
    
    def save_data(self, df: pd.DataFrame) -> bool:
        """
        儲存數據到 CSV 文件
        
        Args:
            df: 要儲存的 DataFrame
            
        Returns:
            是否成功儲存
        """
        try:
            # 確保輸出目錄存在
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 儲存為 CSV
            df.to_csv(self.output_file, index=False)
            
            logger.info(f"數據已儲存至: {self.output_file}")
            return True
            
        except Exception as e:
            logger.error(f"儲存數據失敗: {e}")
            return False
    
    def get_latest_date(self) -> Optional[str]:
        """
        獲取現有數據中的最新日期
        
        Returns:
            最新日期 (YYYY-MM-DD) 或 None
        """
        existing_data = self.load_existing_data()
        
        if existing_data.empty:
            return None
        
        return existing_data['report_date'].max()
    
    def update(self, new_data: List[Dict]) -> bool:
        """
        更新數據（處理、合併、儲存）
        
        Args:
            new_data: 從 API 獲取的新數據
            
        Returns:
            是否成功更新
        """
        try:
            # 處理新數據
            processed_new = self.process_data(new_data)
            
            if processed_new.empty:
                logger.warning("沒有新數據需要更新")
                return False
            
            # 載入現有數據
            existing = self.load_existing_data()
            
            # 合併數據
            merged = self.merge_data(processed_new, existing)
            
            # 儲存數據
            return self.save_data(merged)
            
        except Exception as e:
            logger.error(f"更新數據時發生錯誤: {e}")
            return False
