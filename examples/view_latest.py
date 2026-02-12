"""
快速查看最新 COT 數據
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

# 數據文件路徑
DATA_DIR = Path(__file__).parent.parent / "data"


def view_latest():
    """顯示所有商品的最新 COT 數據"""
    
    commodities = {
        'gold_cot_data.csv': '黃金 (GOLD)',
        'silver_cot_data.csv': '白銀 (SILVER)',
        'sp500_cot_data.csv': 'S&P 500 E-mini'
    }
    
    print("\n" + "="*80)
    print(f"COT 數據快速查看 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80 + "\n")
    
    for file, name in commodities.items():
        file_path = DATA_DIR / file
        
        if not file_path.exists():
            print(f"❌ {name}: 數據文件不存在")
            continue
        
        try:
            df = pd.read_csv(file_path)
            df['report_date'] = pd.to_datetime(df['report_date'])
            df.sort_values('report_date', ascending=False, inplace=True)
            
            latest = df.iloc[0]
            
            print(f"📊 {name}")
            print(f"   報告日期: {latest['report_date'].strftime('%Y-%m-%d')}")
            print(f"   未平倉量: {latest['open_interest']:>15,} 口")
            print(f"   多單口數: {latest['long_positions']:>15,} 口")
            print(f"   空單口數: {latest['short_positions']:>15,} 口")
            print(f"   淨部位:   {latest['net_positions']:>15,} 口")
            
            # 計算淨部位佔比
            net_pct = (latest['net_positions'] / latest['open_interest']) * 100
            print(f"   淨部位佔比: {net_pct:>13.2f} %")
            
            # 如果有歷史數據，顯示變化
            if len(df) >= 2:
                prev = df.iloc[1]
                change = latest['net_positions'] - prev['net_positions']
                change_pct = (change / prev['net_positions'] * 100) if prev['net_positions'] != 0 else 0
                
                arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                print(f"   週變化:   {arrow} {change:+,} 口 ({change_pct:+.2f}%)")
            
            print()
            
        except Exception as e:
            print(f"❌ {name}: 讀取數據時發生錯誤 - {e}\n")
    
    print("="*80 + "\n")


if __name__ == "__main__":
    view_latest()
