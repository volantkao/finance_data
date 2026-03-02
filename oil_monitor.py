import requests
import pandas as pd
import os
from datetime import datetime

def fetch_fred_data(series_id):
    """從 FRED 抓取數據"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    # 讀取 CSV
    from io import StringIO
    df = pd.read_csv(StringIO(response.text))
    
    # 處理 FRED 的 '.' 表示無數據的情況
    df = df.replace('.', pd.NA)
    df = df.dropna()
    
    df['observation_date'] = pd.to_datetime(df['observation_date'])
    df.set_index('observation_date', inplace=True)
    return df

def main():
    print(f"開始執行數據抓取任務: {datetime.now()}")
    
    try:
        # 1. 抓取 WTI 與 Brent 數據
        print("正在從 FRED 抓取 WTI 數據...")
        wti_df = fetch_fred_data("DCOILWTICO")
        
        print("正在從 FRED 抓取 Brent 數據...")
        brent_df = fetch_fred_data("DCOILBRENTEU")
        
        # 2. 合併數據並計算價差 (Brent - WTI)
        # 財經 M 平方的 WTI Intramarket Spread 通常是指遠近月價差
        # 這裡我們提供 Brent-WTI 價差作為 monitor 指標，並保留原始數據
        df = pd.merge(wti_df, brent_df, left_index=True, right_index=True, how='inner')
        
        # 處理可能的 '.' 或空值 (FRED 有時會用 '.' 表示無數據)
        df = df.replace('.', pd.NA).dropna()
        df = df.astype(float)
        
        df['Brent_WTI_Spread'] = df['DCOILBRENTEU'] - df['DCOILWTICO']
        
        # 3. 滾動更新 CSV
        output_file = 'oil_data.csv'
        
        if os.path.exists(output_file):
            print(f"發現現有檔案 {output_file}，進行滾動更新...")
            old_df = pd.read_csv(output_file)
            old_df['observation_date'] = pd.to_datetime(old_df['observation_date'])
            old_df.set_index('observation_date', inplace=True)
            
            # 合併新舊數據，以新數據覆蓋舊數據（如果有重疊），並按日期排序
            combined_df = df.combine_first(old_df).sort_index()
        else:
            print(f"建立新檔案 {output_file}...")
            combined_df = df.sort_index()
            
        # 4. 儲存結果
        combined_df.to_csv(output_file)
        print(f"成功更新 {output_file}，目前共有 {len(combined_df)} 筆數據。")
        print(f"最新數據日期: {combined_df.index[-1].strftime('%Y-%m-%d')}")
        print(f"最新 Brent-WTI 價差: {combined_df['Brent_WTI_Spread'].iloc[-1]:.2f}")

    except Exception as e:
        print(f"執行過程中發生錯誤: {e}")
        exit(1)

if __name__ == "__main__":
    main()
