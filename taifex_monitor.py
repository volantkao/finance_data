import requests
import pandas as pd
import datetime
import os
import json
import re
from io import StringIO, BytesIO
from bs4 import BeautifulSoup

# 設定 CSV 檔案路徑
CSV_FILE = 'market_monitor.csv'

def get_tx_futures():
    """抓取台指期近月收盤價與 OI"""
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    try:
        response = requests.get(url)
        data = response.json()
        df = pd.DataFrame(data)
        tx_df = df[df['Contract'] == 'TX'].copy()
        tx_df = tx_df[tx_df['ContractMonth(Week)'].str.len() == 6]
        tx_df = tx_df.sort_values('ContractMonth(Week)')
        if tx_df.empty: return {'tx_price': None, 'tx_oi': None}
        latest_month = tx_df.iloc[0]
        return {
            'tx_price': float(latest_month['Last']) if latest_month['Last'] else None,
            'tx_oi': int(latest_month['OpenInterest']) if latest_month['OpenInterest'] else None
        }
    except Exception as e:
        print(f"Error fetching TX Futures: {e}")
        return {'tx_price': None, 'tx_oi': None}

def get_margin_balance():
    """抓取大盤融資餘額"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    try:
        response = requests.get(url)
        data = response.json()
        df = pd.DataFrame(data)
        def clean_val(val):
            if pd.isna(val) or val == '': return 0
            return float(str(val).replace(',', ''))
        total_balance = df['融資今日餘額'].apply(clean_val).sum()
        balance_billion = round(total_balance / 100000, 2)
        return balance_billion if balance_billion > 0 else None
    except Exception as e:
        print(f"Error fetching Margin Balance: {e}")
        return None

def get_anc_ratio():
    """從期交所 ODS 檔解析資產前四大期貨商的 ANC 比率平均值"""
    list_url = "https://www.taifex.com.tw/cht/8/fcmFinancial"
    try:
        resp = requests.get(list_url, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        ods_url = None
        # 尋找包含「專營期貨商簡明財務資料表」的連結
        for a in soup.find_all('a', href=True):
            if '專營期貨商簡明財務資料表' in a.get_text() and '.ods' in a['href']:
                href = a['href']
                if href.startswith('http'):
                    ods_url = href
                else:
                    # 處理相對路徑
                    if href.startswith('/'):
                        ods_url = "https://www.taifex.com.tw" + href
                    else:
                        ods_url = "https://www.taifex.com.tw/cht/8/" + href
                break
        
        if not ods_url:
            # 備用方案：若 BeautifulSoup 沒抓到，嘗試用正則表達式
            match = re.search(r'href="([^"]*專營期貨商簡明財務資料表[^"]*\.ods)"', resp.text)
            if match:
                href = match.group(1)
                ods_url = href if href.startswith('http') else "https://www.taifex.com.tw" + (href if href.startswith('/') else "/cht/8/" + href)

        if not ods_url:
            print("Could not find ODS URL.")
            return None
            
        print(f"Downloading ODS: {ods_url}")
        ods_resp = requests.get(ods_url, timeout=20)
        df = pd.read_excel(BytesIO(ods_resp.content), engine='odf', header=None)
        
        header_row_idx = None
        for idx, row in df.iterrows():
            if '期貨商名稱' in row.values:
                header_row_idx = idx
                break
        
        if header_row_idx is not None:
            brokers = df.iloc[header_row_idx].values[1:]
            asset_row_idx, anc_row_idx = None, None
            for idx, row in df.iterrows():
                row_val = str(row.values[0]).replace('\n', '').replace(' ', '')
                if '資產合計' == row_val: asset_row_idx = idx
                if 'ANC比率(%)' in row_val: anc_row_idx = idx
            
            if asset_row_idx is not None and anc_row_idx is not None:
                assets = df.iloc[asset_row_idx].values[1:]
                ancs = df.iloc[anc_row_idx].values[1:]
                data = []
                for b, a, anc in zip(brokers, assets, ancs):
                    if pd.isna(b) or '合計' in str(b) or '總計' in str(b): continue
                    try:
                        asset_val = float(str(a).replace(',', ''))
                        anc_val = float(str(anc).replace('%', '').replace(',', ''))
                        # 若 anc_val < 1 (如 0.40)，則 * 100 轉為百分比 (40.0)
                        if anc_val < 5: # 正常 ANC 都在 100% 以上，若小於 5 應該是小數點表示
                            anc_val = anc_val * 100
                        data.append({'Broker': b, 'Asset': asset_val, 'ANC': anc_val})
                    except: continue
                
                res_df = pd.DataFrame(data)
                top_4 = res_df.sort_values(by='Asset', ascending=False).head(4)
                print(f"Top 4: {top_4['Broker'].tolist()}")
                return round(top_4['ANC'].mean(), 2)
    except Exception as e:
        print(f"Error fetching ANC: {e}")
    return None

def get_cp_rate():
    """抓取 30天期 CP 利率"""
    url = "https://www.tbfa.org.tw/practice/table_main_01.html"
    try:
        response = requests.get(url, timeout=15)
        text = ""
        for encoding in ['utf-8', 'big5', 'cp950']:
            try:
                text = response.content.decode(encoding)
                if '30天期' in text: break
            except: continue
        dfs = pd.read_html(StringIO(text))
        for df in dfs:
            if df.shape[1] >= 3:
                latest_row = df.iloc[-1]
                for val in reversed(latest_row):
                    try:
                        clean_v = float(str(val).replace('%', ''))
                        if 0 < clean_v < 10: return clean_v
                    except: continue
    except Exception as e:
        print(f"Error fetching CP Rate: {e}")
    return None

def main():
    tz_offset = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz_offset)
    today = now.strftime('%Y-%m-%d')
    print(f"Starting monitor at {now.strftime('%Y-%m-%d %H:%M:%S')} (Taipei Time)")
    
    tx_data = get_tx_futures()
    margin_balance = get_margin_balance()
    cp_rate = get_cp_rate()
    anc_ratio = get_anc_ratio()
    
    new_data = {
        'Date': today,
        'TX_Price': tx_data['tx_price'],
        'TX_OI': tx_data['tx_oi'],
        'Margin_Balance_Billion': margin_balance,
        'ANC_Ratio_Avg_Top4': anc_ratio,
        'CP_Rate': cp_rate
    }
    print(f"Fetched data: {new_data}")
    
    df_new = pd.DataFrame([new_data])
    if os.path.exists(CSV_FILE):
        try:
            df_old = pd.read_csv(CSV_FILE)
            # 確保欄位一致
            for col in df_new.columns:
                if col not in df_old.columns: df_old[col] = None
            df_old = df_old[df_old['Date'] != today]
            df_final = pd.concat([df_old[df_new.columns], df_new], ignore_index=True)
        except: df_final = df_new
    else: df_final = df_new
    df_final.to_csv(CSV_FILE, index=False)
    print(f"Data saved to {CSV_FILE}")

if __name__ == "__main__":
    main()
