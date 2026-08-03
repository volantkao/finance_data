import requests
import pandas as pd
import json
import os
import matplotlib.pyplot as plt
from datetime import datetime

# 中央銀行 API 網址 (全體銀行放款餘額統計表 - 借戶行業別 - 月)
# 包含「週轉金」用途的詳細數據
API_URL = "https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=EI87M01"

def fetch_data():
    print(f"Fetching data from {API_URL}...")
    response = requests.get(API_URL)
    response.raise_for_status()
    return response.json()

def process_data(json_data):
    structure = json_data['data']['structure']
    table1 = structure['Table1']  # 借戶行業/部門
    table2 = structure['Table2']  # 用途別 (計, 購置不動產, 購置動產, 企業投資, 週轉金)
    table3 = structure['Table3']  # 數值型態 (原始值, 年增率)
    
    data_sets = json_data['data']['dataSets']
    
    # 我們要提取的目標：合計 (Index 0) / 週轉金 (Index 4) / 原始值 (Index 0)
    # 根據索引公式：1 + (t1_idx * len(t2)*len(t3) + t2_idx * len(t3) + t3_idx)
    # 合計週轉金索引 = 1 + (0 * 5 * 2 + 4 * 2 + 0) = 9
    # 個人週轉金索引 = 1 + (17 * 5 * 2 + 4 * 2 + 0) = 179
    
    results = []
    for row in data_sets:
        date_str = row[0]  # 格式如 2026M05
        try:
            total_wc = float(row[9]) if row[9] != '-' else None
            indiv_wc = float(row[179]) if row[179] != '-' else None
            
            # 轉換日期格式為 YYYY-MM
            dt = datetime.strptime(date_str, "%YM%m")
            results.append({
                "Date": dt.strftime("%Y-%m"),
                "Total_Working_Capital_Mln": total_wc,
                "Individual_Working_Capital_Mln": indiv_wc
            })
        except (ValueError, IndexError):
            continue
            
    df = pd.DataFrame(results)
    df = df.dropna().sort_values("Date")
    return df

def save_and_plot(df):
    # 儲存 CSV
    df.to_csv("taiwan_working_capital_loans.csv", index=False)
    print("Data saved to taiwan_working_capital_loans.csv")
    
    # 繪製圖表
    plt.figure(figsize=(12, 6))
    plt.plot(df['Date'], df['Total_Working_Capital_Mln'] / 1000000, label='Total Working Capital (Trillion TWD)', marker='o')
    plt.plot(df['Date'], df['Individual_Working_Capital_Mln'] / 1000000, label='Individual Working Capital (Trillion TWD)', marker='s')
    
    plt.title('Taiwan Working Capital Loans Trend (Source: CBC API EI87M01)')
    plt.xlabel('Month')
    plt.ylabel('Amount (Trillion TWD)')
    plt.xticks(rotation=45)
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig("loan_trend.png")
    print("Trend chart saved to loan_trend.png")

if __name__ == "__main__":
    try:
        raw_data = fetch_data()
        df = process_data(raw_data)
        save_and_plot(df)
        
        # 顯示最新數據
        latest = df.iloc[-1]
        print(f"\nLatest Data ({latest['Date']}):")
        print(f"Total Working Capital: {latest['Total_Working_Capital_Mln']/1000000:.2f} Trillion TWD")
        print(f"Individual Working Capital: {latest['Individual_Working_Capital_Mln']/1000000:.2f} Trillion TWD")
        
    except Exception as e:
        print(f"Error: {e}")
