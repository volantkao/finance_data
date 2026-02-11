import cot_reports as cot
import pandas as pd
import numpy as np
from datetime import datetime

def get_sp500_cot_data(years=[2023, 2024, 2025]):
    """
    獲取 S&P 500 E-mini 的 COT 數據 (TFF 報告)
    """
    all_data = []
    for year in years:
        try:
            df = cot.cot_year(year, cot_report_type='traders_in_financial_futures_fut')
            # 篩選 E-MINI S&P 500
            target = df[df['Market_and_Exchange_Names'] == 'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE'].copy()
            all_data.append(target)
        except Exception as e:
            print(f"無法獲取 {year} 數據: {e}")
    
    full_df = pd.concat(all_data).sort_values('As_of_Date_In_Form_YYMMDD')
    
    # 轉換日期
    full_df['date'] = pd.to_datetime(full_df['As_of_Date_In_Form_YYMMDD'].astype(str), format='%y%m%d')
    
    # 計算 Managed Money (這裡使用 Leveraged Funds 作為 MM 的對應) 淨倉位
    # Net = Long - Short
    full_df['mm_net'] = full_df['Lev_Money_Positions_Long_All'] - full_df['Lev_Money_Positions_Short_All']
    
    # 計算 Commercial (這裡使用 Dealer/Intermediary 作為對手方/Commercial 的對應) 淨倉位
    full_df['comm_net'] = full_df['Dealer_Positions_Long_All'] - full_df['Dealer_Positions_Short_All']
    
    # OI
    full_df['oi'] = full_df['Open_Interest_All']
    
    return full_df[['date', 'mm_net', 'comm_net', 'oi']]

def calculate_scores(df):
    """
    打分邏輯:
    1. MM Z-score > |2| -> +10
    2. Commercial 站反向 -> +5
    3. OI 下滑 (相較上週) -> +5
    """
    # 1. MM Z-score (使用 52 週滾動窗口)
    window = 52
    df['mm_mean'] = df['mm_net'].rolling(window=window).mean()
    df['mm_std'] = df['mm_net'].rolling(window=window).std()
    df['mm_zscore'] = (df['mm_net'] - df['mm_mean']) / df['mm_std']
    
    # 2. Commercial 分歧 (MM 淨多則 Comm 需淨空，或反之)
    # 邏輯：mm_net * comm_net < 0
    df['comm_divergence'] = (df['mm_net'] * df['comm_net'] < 0).astype(int)
    
    # 3. OI 變化 (本週 OI < 上週 OI)
    df['oi_change'] = df['oi'].diff()
    df['oi_down'] = (df['oi_change'] < 0).astype(int)
    
    # 打分
    df['score'] = 0
    df.loc[df['mm_zscore'].abs() > 2, 'score'] += 10
    df.loc[df['comm_divergence'] == 1, 'score'] += 5
    df.loc[df['oi_down'] == 1, 'score'] += 5
    
    return df

if __name__ == "__main__":
    print("正在抓取 COT 歷史數據並計算得分...")
    # 獲取最近三年的數據以計算 Z-score
    cot_df = get_sp500_cot_data(years=[2023, 2024, 2025, 2026])
    scored_df = calculate_scores(cot_df)
    
    # 顯示最新結果
    latest = scored_df.tail(10)
    print("\n最新 COT 打分結果 (Position Crowding):")
    print(latest[['date', 'mm_zscore', 'comm_divergence', 'oi_down', 'score']])
    
    # 儲存
    scored_df.to_csv("cot_crowding_scores.csv", index=False)
    print("\n數據已儲存至 cot_crowding_scores.csv")