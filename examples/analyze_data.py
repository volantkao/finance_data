"""
COT 數據分析範例
展示如何讀取和分析 COT 數據
"""

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# 設定中文字體（可選）
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 數據文件路徑
DATA_DIR = Path(__file__).parent.parent / "data"


def load_data(commodity: str) -> pd.DataFrame:
    """
    載入指定商品的 COT 數據
    
    Args:
        commodity: 商品名稱 ('gold', 'silver', 'sp500')
        
    Returns:
        DataFrame
    """
    file_path = DATA_DIR / f"{commodity}_cot_data.csv"
    df = pd.read_csv(file_path, parse_dates=['report_date'])
    df.sort_values('report_date', inplace=True)
    return df


def plot_net_positions(df: pd.DataFrame, title: str):
    """
    繪製淨部位趨勢圖
    
    Args:
        df: COT 數據 DataFrame
        title: 圖表標題
    """
    plt.figure(figsize=(14, 6))
    
    # 淨部位趨勢
    plt.subplot(1, 2, 1)
    plt.plot(df['report_date'], df['net_positions'], linewidth=2, color='blue')
    plt.axhline(y=0, color='red', linestyle='--', alpha=0.5)
    plt.xlabel('日期')
    plt.ylabel('淨部位（口數）')
    plt.title(f'{title} - 淨部位趨勢')
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    
    # 多空單對比
    plt.subplot(1, 2, 2)
    plt.plot(df['report_date'], df['long_positions'], label='多單', linewidth=2, color='green')
    plt.plot(df['report_date'], df['short_positions'], label='空單', linewidth=2, color='red')
    plt.xlabel('日期')
    plt.ylabel('口數')
    plt.title(f'{title} - 多空單對比')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    plt.show()


def analyze_commodity(commodity: str, name: str):
    """
    分析單一商品的 COT 數據
    
    Args:
        commodity: 商品代碼
        name: 商品名稱
    """
    print(f"\n{'='*60}")
    print(f"{name} COT 數據分析")
    print(f"{'='*60}")
    
    # 載入數據
    df = load_data(commodity)
    
    # 基本統計
    print(f"\n數據範圍: {df['report_date'].min().date()} 至 {df['report_date'].max().date()}")
    print(f"總記錄數: {len(df)} 筆")
    
    # 最新數據
    latest = df.iloc[-1]
    print(f"\n最新報告日期: {latest['report_date'].date()}")
    print(f"未平倉量: {latest['open_interest']:,.0f} 口")
    print(f"多單口數: {latest['long_positions']:,.0f} 口")
    print(f"空單口數: {latest['short_positions']:,.0f} 口")
    print(f"淨部位: {latest['net_positions']:,.0f} 口")
    
    # 淨部位統計
    print(f"\n淨部位統計:")
    print(f"  平均值: {df['net_positions'].mean():,.0f} 口")
    print(f"  標準差: {df['net_positions'].std():,.0f} 口")
    print(f"  最大值: {df['net_positions'].max():,.0f} 口 ({df.loc[df['net_positions'].idxmax(), 'report_date'].date()})")
    print(f"  最小值: {df['net_positions'].min():,.0f} 口 ({df.loc[df['net_positions'].idxmin(), 'report_date'].date()})")
    
    # 近期變化
    if len(df) >= 2:
        prev = df.iloc[-2]
        change = latest['net_positions'] - prev['net_positions']
        print(f"\n週變化:")
        print(f"  淨部位變化: {change:+,.0f} 口 ({change/prev['net_positions']*100:+.2f}%)")
        print(f"  未平倉量變化: {latest['open_interest'] - prev['open_interest']:+,.0f} 口")
    
    # 繪製圖表
    plot_net_positions(df, name)


def compare_commodities():
    """
    比較三種商品的淨部位趨勢
    """
    print(f"\n{'='*60}")
    print("商品淨部位比較")
    print(f"{'='*60}")
    
    commodities = {
        'gold': '黃金',
        'silver': '白銀',
        'sp500': 'S&P 500'
    }
    
    plt.figure(figsize=(14, 8))
    
    for i, (code, name) in enumerate(commodities.items(), 1):
        df = load_data(code)
        
        # 標準化淨部位（轉換為百分比）
        df['net_pct'] = (df['net_positions'] / df['open_interest']) * 100
        
        plt.subplot(3, 1, i)
        plt.plot(df['report_date'], df['net_pct'], linewidth=2)
        plt.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        plt.ylabel('淨部位 (%)')
        plt.title(f'{name} - 淨部位佔未平倉量百分比')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
    
    plt.tight_layout()
    plt.show()


def main():
    """主函數"""
    print("COT 數據分析工具")
    print("="*60)
    
    # 分析各商品
    analyze_commodity('gold', '黃金')
    analyze_commodity('silver', '白銀')
    analyze_commodity('sp500', 'S&P 500 E-mini')
    
    # 比較分析
    compare_commodities()
    
    print(f"\n{'='*60}")
    print("分析完成！")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
