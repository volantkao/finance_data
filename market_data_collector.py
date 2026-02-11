import yfinance as yf
import pandas as pd
import requests
from io import StringIO
import os
from datetime import datetime

def get_gex_history():
    """
    從 SqueezeMetrics 獲取 SPX GEX 歷史數據 (免費公開源)
    """
    url = "https://squeezemetrics.com/monitor/static/DIX.csv"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        df = pd.read_csv(StringIO(response.text))
        df['date'] = pd.to_datetime(df['date'])
        return df[['date', 'gex']]
    else:
        print("無法獲取 GEX 數據")
        return None

def get_futures_basis_history(period="1y"):
    """
    計算期貨基差 (S&P 500 現貨 - E-mini 期貨)
    """
    # ^GSPC = S&P 500 Index, ES=F = E-mini S&P 500 Futures
    spot = yf.Ticker("^GSPC").history(period=period)['Close']
    futures = yf.Ticker("ES=F").history(period=period)['Close']
    
    df = pd.DataFrame({'spot': spot, 'futures': futures}).dropna()
    df['basis'] = df['spot'] - df['futures']
    df.index = pd.to_datetime(df.index).date
    df.reset_index(inplace=True)
    df.rename(columns={'index': 'date'}, inplace=True)
    df['date'] = pd.to_datetime(df['date'])
    return df[['date', 'basis']]

from cot_scoring import get_sp500_cot_data, calculate_scores

def main():
    print("正在抓取 GEX 歷史數據...")
    gex_df = get_gex_history()
    
    print("正在抓取期貨基差數據...")
    basis_df = get_futures_basis_history()

    print("正在抓取並計算 COT 擁擠度得分...")
    try:
        current_year = datetime.now().year
        cot_df = get_sp500_cot_data(years=list(range(current_year-3, current_year+1)))
        cot_scored = calculate_scores(cot_df)
        cot_final = cot_scored[['date', 'score']].rename(columns={'score': 'cot_crowding_score'})
    except Exception as e:
        print(f"COT 抓取失敗: {e}")
        cot_final = None
    
    # 合併所有數據
    if gex_df is not None:
        merged_df = pd.merge(gex_df, basis_df, on='date', how='outer')
        if cot_final is not None:
            merged_df = pd.merge(merged_df, cot_final, on='date', how='outer')
        
        merged_df = merged_df.sort_values('date')
        
        output_file = "market_history.csv"
        merged_df.to_csv(output_file, index=False)
        print(f"數據已儲存至 {output_file}")
        print(merged_df.tail(10))
    else:
        print("任務失敗")

if __name__ == "__main__":
    main()
