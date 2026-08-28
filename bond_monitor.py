import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import json
import os

# 取得當前腳本所在的絕對資料夾路徑，確保跨平台相容性
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_data_table(soup):
    """
    TradingView's bond grid renders TWO <table> elements for the same visual
    widget: a sticky-header table that has <thead> but NO <tbody> (a decoy for
    layout purposes), followed by the real table that has both <thead> and a
    populated <tbody>. Naively taking "the next table after the heading" grabs
    the decoy, whose missing tbody causes an AttributeError deep in the parsing
    logic. This walks the candidate tables in document order and returns the
    first one that actually has data rows and looks like the YTW grid.
    """
    heading = (soup.find('h1', string='Corporate debt securities')
               or soup.find('h2', string='Corporate debt securities'))
    candidates = heading.find_all_next('table') if heading else soup.find_all('table')
    for t in candidates:
        tbody = t.find('tbody')
        if tbody and tbody.find_all('tr') and 'YTW' in t.get_text():
            return t
    return None


def get_bond_yield(url, target_maturity_year, company_name, instrument_type=None):
    debug_dir = os.path.join(BASE_DIR, "debug_html")
    os.makedirs(debug_dir, exist_ok=True) # Ensure debug directory exists
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36)'
        }

        response = requests.get(url, headers=headers, timeout=120) # Increase timeout to 120 seconds
        response.raise_for_status()  # Raise an exception for HTTP errors

        soup = BeautifulSoup(response.text, 'html.parser')

        table = find_data_table(soup)

        if not table:
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, f"{company_name}_bond_page.html"), "w", encoding='utf-8') as f:
                f.write(response.text)
            return None

        # Extract headers to find the index of 'YTW %' and 'Maturity date'
        headers_row = table.find("thead").find("tr") if table.find("thead") else table.find("tr")
        if not headers_row:
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, f"{company_name}_bond_page.html"), "w", encoding='utf-8') as f:
                f.write(response.text)
            return None

        headers = [cell.get_text().replace("\xa0", " ").strip() for cell in headers_row.find_all(["th", "td"])]
        try:
            ytw_index = headers.index("YTW %")
            maturity_index = headers.index("Maturity date")
        except ValueError:
            return None

        bond_yields = []
        rows = table.find('tbody').find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) > max(ytw_index, maturity_index):
                maturity_date_str = cells[maturity_index].get_text().replace("\xa0", " ").strip()
                ytw_raw = cells[ytw_index].get_text().replace("\xa0", " ").strip()

                # Convertible notes routinely show "—" (no YTW published) because
                # price reflects conversion value, not a straight discount yield.
                # Skip these rows instead of letting float() throw.
                if not ytw_raw or ytw_raw in ("—", "-", "N/A"):
                    continue

                try:
                    maturity_date = datetime.datetime.strptime(maturity_date_str, '%Y-%m-%d').date()
                    if target_maturity_year - 5 <= maturity_date.year <= target_maturity_year + 5:
                        bond_yields.append(float(ytw_raw.replace("%", "")))
                except ValueError:
                    # Handle cases where maturity date or yield cannot be parsed
                    continue

        if bond_yields:
            return sum(bond_yields) / len(bond_yields) # Return the average yield
        else:
            if instrument_type == "convertible":
                print(f"{company_name}: no YTW published (convertible note) — recording as N/A, not a scraper failure")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        os.makedirs(debug_dir, exist_ok=True)
        if 'response' in locals() and response.text:
            with open(os.path.join(debug_dir, f"{company_name}_bond_page_fetch_error.html"), "w", encoding='utf-8') as f:
                f.write(response.text)
        else:
            with open(os.path.join(debug_dir, f"{company_name}_bond_page_fetch_error.log"), "w", encoding='utf-8') as f:
                f.write(str(e))
        return None
    except Exception as e:
        print(f"Error parsing {url}: {e}")
        os.makedirs(debug_dir, exist_ok=True)
        if 'response' in locals() and response.text:
            with open(os.path.join(debug_dir, f"{company_name}_bond_page_parse_error.html"), "w", encoding='utf-8') as f:
                f.write(response.text)
        else:
            with open(os.path.join(debug_dir, f"{company_name}_bond_page_parse_error.log"), "w", encoding='utf-8') as f:
                f.write(str(e))
        return None

def main():
    config_path = os.path.join(BASE_DIR, 'bond_monitor_config.json')
    output_dir = os.path.join(BASE_DIR, 'bond_data')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'corporate_bond_spreads.csv')

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    today = datetime.date.today().isoformat()
    data = {'Date': today}

    # Get US 10-Year Treasury Yield
    fred_api_key = "08e0dbd8e48817f94d092e363024c981"
    us10y_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={fred_api_key}&file_type=json&sort_order=desc&limit=1"
    try:
        response = requests.get(us10y_url)
        response.raise_for_status()
        fred_data = response.json()
        if fred_data and fred_data["observations"]:
            latest_observation = fred_data["observations"][0]
            us10y_yield = float(latest_observation["value"])
            data["US10Y_Yield"] = us10y_yield
        else:
            data["US10Y_Yield"] = None
            print(f"Could not retrieve US10Y yield from FRED API: {us10y_url}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching US10Y yield from {us10y_url}: {e}")
        data['US10Y_Yield'] = None
    except Exception as e:
        print(f"Error parsing US10Y yield from {us10y_url}: {e}")
        data['US10Y_Yield'] = None

    # Fetch Corporate Bond Yields
    for company, details in config['companies'].items():
        instrument_type = details.get('instrument_type')
        tradingview_url = f"https://www.tradingview.com/symbols/{details['tradingview_symbol']}/bonds/"
        bond_yield = get_bond_yield(tradingview_url, details['target_maturity_year'], company, instrument_type)

        if bond_yield is not None:
            data[f'{company}_Yield'] = bond_yield
            data[f'{company}_Spread'] = (
                bond_yield - data['US10Y_Yield'] if data['US10Y_Yield'] is not None else None
            )
        elif instrument_type == "convertible":
            # Known data limitation, not a scraper failure: TradingView does not
            # publish YTW for these convertible notes. Flag it explicitly so it
            # isn't mistaken for a broken fetch when the CSV is reviewed later.
            data[f'{company}_Yield'] = "N/A (convertible, no YTW)"
            data[f'{company}_Spread'] = None
        else:
            data[f'{company}_Yield'] = None
            data[f'{company}_Spread'] = None

    df_new = pd.DataFrame([data])

    if os.path.exists(output_file):
        existing_df = pd.read_csv(output_file)
        
        # 【核心修正】：Upsert (Update or Insert) 邏輯
        # 如果今天已經有資料，先刪除舊的，避免因為重複執行產生多筆相同日期的無效行
        existing_df = existing_df[existing_df['Date'] != today]
        
        # 合併最新資料
        df = pd.concat([existing_df, df_new], ignore_index=True)
        
        # 依照日期排序，確保時間序列乾淨
        df = df.sort_values(by='Date')
    else:
        df = df_new

    # 【防呆機制】：確保欄位排列整齊
    # 強制把 Date 放在第一列，US10Y 放第二列，現有 config 的公司放前面，被棄用的殭屍欄位放最後
    fixed_cols = ['Date', 'US10Y_Yield']
    active_company_cols = []
    for company in config['companies'].keys():
        active_company_cols.extend([f'{company}_Yield', f'{company}_Spread'])
    
    # 找出除了固定欄位和當前公司欄位以外的「歷史殘留欄位」(例如 Samsung)
    legacy_cols = [c for c in df.columns if c not in fixed_cols and c not in active_company_cols]
    
    # 重新排列 DataFrame，讓閱讀體驗正常化
    final_cols = fixed_cols + [c for c in active_company_cols if c in df.columns] + sorted(legacy_cols)
    df = df[final_cols]

    # 存檔
    df.to_csv(output_file, index=False)
    print(f"Data saved to {output_file}")

if __name__ == '__main__':
    main()
