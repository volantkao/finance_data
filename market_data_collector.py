import yfinance as yf
import pandas as pd
import requests
from io import StringIO
import os

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

def main():
    print("正在抓取 GEX 歷史數據...")
    gex_df = get_gex_history()
    
    print("正在抓取期貨基差數據...")
    basis_df = get_futures_basis_history()
    
    if gex_df is not None:
        # 合併數據
        merged_df = pd.merge(gex_df, basis_df, on='date', how='outer').sort_values('date')
        
        # 儲存到本地 CSV
        output_file = "market_history.csv"
        merged_df.to_csv(output_file, index=False)
        print(f"數據已儲存至 {output_file}")
        print(merged_df.tail(10))
    else:
        print("任務失敗")

if __name__ == "__main__":
    main()