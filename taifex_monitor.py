import requests
import pandas as pd
import datetime
import os
import json
import re
import sys
from io import StringIO, BytesIO
from bs4 import BeautifulSoup

# 設定 CSV 檔案路徑
CSV_FILE = 'market_monitor.csv'

def get_tx_futures():
    """抓取台指期近月收盤價與 OI"""
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        df = pd.DataFrame(data)
        tx_df = df[df['Contract'] == 'TX'].copy()
        tx_df = tx_df[tx_df['ContractMonth(Week)'].str.len() == 6]
        tx_df = tx_df.sort_values('ContractMonth(Week)')
        if tx_df.empty: 
            print("TX Futures data is empty.")
            return {'tx_price': None, 'tx_oi': None}
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
        response = requests.get(url, timeout=15)
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
    """從期交所 ODS 檔解析所有專營期貨商的 ANC 比率，回傳「前四大資產中最弱一家」與
    「全市場最弱一家」的最小值 (水桶最短板)，以及對應的 ANC=15% 紅線前剩餘保證金承載空間"""
    list_url = "https://www.taifex.com.tw/cht/8/fcmFinancial"
    try:
        resp = requests.get(list_url, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        ods_url = None
        for a in soup.find_all('a', href=True):
            if '專營期貨商簡明財務資料表' in a.get_text() and '.ods' in a['href']:
                href = a['href']
                if href.startswith('http'):
                    ods_url = href
                else:
                    ods_url = "https://www.taifex.com.tw" + (href if href.startswith('/') else "/cht/8/" + href)
                break
        
        if not ods_url:
            match = re.search(r'href="([^"]*專營期貨商簡明財務資料表[^"]*\.ods)"', resp.text)
            if match:
                href = match.group(1)
                ods_url = href if href.startswith('http') else "https://www.taifex.com.tw" + (href if href.startswith('/') else "/cht/8/" + href)

        if not ods_url:
            print("Could not find ODS URL for ANC Ratio.")
            return None

        # 🌟 從檔名解析資料所屬月份 (例如 ...202607.ods -> 2026-07)，
        # 之後才能精準對應「該月月底 TAIEX 收盤價」，不用用今天日期去猜
        data_period = None
        m = re.search(r'(20\d{2})(0[1-9]|1[0-2])\.(?:ods|xlsx|ODS|XLSX)', ods_url)
        if m:
            data_period = f"{m.group(1)}-{m.group(2)}"

        print(f"Downloading ODS from: {ods_url}")
        ods_resp = requests.get(ods_url, timeout=20)
        # 確保安裝了 odfpy
        try:
            df = pd.read_excel(BytesIO(ods_resp.content), engine='odf', header=None)
        except ImportError:
            print("Error: 'odfpy' library is required to read ODS files. Please install it using 'pip install odfpy'.")
            return None

        # 檔名解析失敗時的備援：從表內文字「115年7 月」反推 (民國年+1911=西元年)
        if not data_period:
            for idx in range(min(5, len(df))):
                cell = str(df.iloc[idx].values[0])
                m2 = re.search(r'(\d{2,3})年\s*(\d{1,2})\s*月', cell)
                if m2:
                    ad_year = int(m2.group(1)) + 1911
                    data_period = f"{ad_year}-{int(m2.group(2)):02d}"
                    break
            
        header_row_idx = None
        for idx, row in df.iterrows():
            if '期貨商名稱' in row.values:
                header_row_idx = idx
                break
        
        if header_row_idx is not None:
            brokers = df.iloc[header_row_idx].values[1:]
            asset_row_idx, anc_row_idx, capital_row_idx = None, None, None
            for idx, row in df.iterrows():
                row_val = str(row.values[0]).replace('\n', '').replace(' ', '')
                if '資產合計' == row_val: asset_row_idx = idx
                if 'ANC比率(%)' in row_val: anc_row_idx = idx
                if '調整後資本' == row_val: capital_row_idx = idx
            
            if asset_row_idx is not None and anc_row_idx is not None:
                assets = df.iloc[asset_row_idx].values[1:]
                ancs = df.iloc[anc_row_idx].values[1:]
                # 調整後資本 (ANC 的分子) 若找不到該列則整段補 None，headroom 計算會自動略過
                capitals = df.iloc[capital_row_idx].values[1:] if capital_row_idx is not None else [None] * len(ancs)
                data = []
                for b, a, anc, cap in zip(brokers, assets, ancs, capitals):
                    if pd.isna(b) or '合計' in str(b) or '總計' in str(b): continue
                    try:
                        asset_val = float(str(a).replace(',', ''))
                        anc_val = float(str(anc).replace('%', '').replace(',', ''))
                        if anc_val < 5: anc_val = anc_val * 100
                        cap_val = None
                        if cap is not None:
                            try: cap_val = float(str(cap).replace(',', ''))
                            except: cap_val = None
                        data.append({'Broker': b, 'Asset': asset_val, 'ANC': anc_val, 'AdjCapital': cap_val})
                    except: continue
                
                res_df = pd.DataFrame(data)
                if res_df.empty:
                    print("ANC data parsing resulted in empty DataFrame.")
                    return None
                top_4 = res_df.sort_values(by='Asset', ascending=False).head(4)
                print(f"Top 4 Brokers by Asset: {top_4['Broker'].tolist()}")

                # 🌟 修正：水桶「最短板」邏輯 -> 用 min，不是 mean
                # anc_min_top4：資產前四大期貨商中最弱的一家 (量體最大者的極限)
                # anc_min_all ：全市場所有專營期貨商中最弱的一家 (最先被迫停單者)
                anc_min_top4 = round(top_4['ANC'].min(), 2)
                anc_min_all = round(res_df['ANC'].min(), 2)

                # ==========================================
                # 🌟 ANC=15% 政策紅線前，還可以承載多少客戶保證金 (資金天花板)
                # 依規定 ANC比率 = 調整後淨資本 / 期貨交易人未沖銷部位所需之客戶保證金總額
                # 因此每家期貨商目前的保證金分母 = AdjCapital / (ANC% / 100)
                # 在 AdjCapital 不變的假設下，跌到 15% 前，分母(保證金承載量)還能再擴張多少
                # 這裡刻意用「加總」而非「最小值」-- 目的不同：Min 是抓誰先觸線，
                # Headroom 加總是抓全市場/前四大整體還有多少資金緩衝空間
                # ==========================================
                def headroom_100m(sub_df):
                    total = 0.0
                    valid = False
                    for _, r in sub_df.iterrows():
                        cap, anc = r['AdjCapital'], r['ANC']
                        if cap is None or pd.isna(cap) or anc is None or pd.isna(anc) or anc <= 0:
                            continue
                        current_margin_req = cap / (anc / 100)
                        max_margin_req_at_15 = cap / 0.15
                        total += (max_margin_req_at_15 - current_margin_req)
                        valid = True
                    return round(total / 1e8, 2) if valid else None  # 轉換為「億元」

                headroom_all = headroom_100m(res_df)
                headroom_top4 = headroom_100m(top_4)
                print(f"ANC 最小值: 前四大 {anc_min_top4}% / 全市場 {anc_min_all}%")
                print(f"ANC=15% 紅線前剩餘保證金承載空間: 全市場 {headroom_all} 億元 / 前四大 {headroom_top4} 億元")

                return {
                    'anc_min_top4': anc_min_top4,
                    'anc_min_all': anc_min_all,
                    'headroom_all_100m': headroom_all,
                    'headroom_top4_100m': headroom_top4,
                    'data_period': data_period,
                }
            else:
                print(f"Could not find rows: Asset={asset_row_idx}, ANC={anc_row_idx}")
    except Exception as e:
        print(f"Error fetching ANC Ratio: {e}")
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
    print(f"--- Market Monitor Started: {now.strftime('%Y-%m-%d %H:%M:%S')} (Taipei) ---")
    
    tx_data = get_tx_futures()
    margin_balance = get_margin_balance()
    cp_rate = get_cp_rate()
    anc_result = get_anc_ratio()

    # 相容處理：get_anc_ratio() 現在回傳 dict（若解析失敗則為 None）
    anc_min_top4 = anc_result.get('anc_min_top4') if anc_result else None
    anc_min_all = anc_result.get('anc_min_all') if anc_result else None
    headroom_all = anc_result.get('headroom_all_100m') if anc_result else None
    headroom_top4 = anc_result.get('headroom_top4_100m') if anc_result else None
    data_period = anc_result.get('data_period') if anc_result else None

    new_data = {
        'Date': today,
        'TX_Price': tx_data['tx_price'],
        'TX_OI': tx_data['tx_oi'],
        'Margin_Balance_Billion': margin_balance,
        'ANC_Ratio_Min_Top4': anc_min_top4,
        'ANC_Ratio_Min': anc_min_all,
        'ANC_Headroom_All_100M': headroom_all,
        'ANC_Headroom_Top4_100M': headroom_top4,
        'ANC_Data_Period': data_period,
        'CP_Rate': cp_rate
    }
    print(f"Final Data: {new_data}")
    
    df_new = pd.DataFrame([new_data])
    if os.path.exists(CSV_FILE):
        try:
            df_old = pd.read_csv(CSV_FILE)
            for col in df_new.columns:
                if col not in df_old.columns: df_old[col] = None
            df_old = df_old[df_old['Date'] != today]
            df_final = pd.concat([df_old[df_new.columns], df_new], ignore_index=True)
        except Exception as e:
            print(f"CSV Update Error: {e}")
            df_final = df_new
    else:
        df_final = df_new
        
    df_final.to_csv(CSV_FILE, index=False)
    print(f"Successfully saved to {CSV_FILE}")
    print("--- Monitor Finished ---")

if __name__ == "__main__":
    main()
