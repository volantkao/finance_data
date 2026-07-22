import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import re
import os

# 取得當前腳本所在的絕對資料夾路徑，確保跨平台相容性
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

URL = "https://portal.silicondata.com/token-index-chart"


def get_token_index(url):
    """
    抓取 Silicon Data LLM Token Expenditure Index (SDLLMTK)
    回傳 (index_date, value) 或 (None, None)
    """
    debug_dir = os.path.join(BASE_DIR, "debug_html")
    os.makedirs(debug_dir, exist_ok=True)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text(separator=" ", strip=True)

        # 抓 "As of Jul 18, 2026" 這種日期字串
        date_match = re.search(r"As of\s+([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})", page_text)
        # 抓 "1.59USD per million tokens" 這種數字（中間可能無空格）
        value_match = re.search(r"([\d.]+)\s*USD per million tokens", page_text)

        if not date_match or not value_match:
            with open(os.path.join(debug_dir, "token_index_page.html"), "w", encoding='utf-8') as f:
                f.write(response.text)
            print("Could not find date or value on the page. Saved debug HTML.")
            return None, None

        index_date_str = date_match.group(1)
        index_date = datetime.datetime.strptime(index_date_str, "%b %d, %Y").date().isoformat()
        value = float(value_match.group(1))

        return index_date, value

    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        with open(os.path.join(debug_dir, "token_index_fetch_error.log"), "w", encoding='utf-8') as f:
            f.write(str(e))
        return None, None
    except Exception as e:
        print(f"Error parsing {url}: {e}")
        if 'response' in locals():
            with open(os.path.join(debug_dir, "token_index_parse_error.html"), "w", encoding='utf-8') as f:
                f.write(response.text)
        return None, None


def main():
    output_dir = os.path.join(BASE_DIR, 'token_index_data')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'llm_token_expenditure_index.csv')

    index_date, value = get_token_index(URL)

    if index_date is None:
        print("Failed to retrieve token index. Nothing written.")
        return

    run_date = datetime.date.today().isoformat()
    data = {
        'Date': index_date,       # 網站上標示的「As of」日期（指數實際對應的日期）
        'Value_USD_per_M_tokens': value,
        'Fetched_On': run_date,   # 這支程式實際跑的日期，方便debug
    }

    df_new = pd.DataFrame([data])

    if os.path.exists(output_file):
        existing_df = pd.read_csv(output_file)
        # Upsert：如果該 index_date 已經存在，先刪除舊資料再覆寫，避免重複
        existing_df = existing_df[existing_df['Date'] != index_date]
        df = pd.concat([existing_df, df_new], ignore_index=True)
        df = df.sort_values(by='Date')
    else:
        df = df_new

    df = df[['Date', 'Value_USD_per_M_tokens', 'Fetched_On']]
    df.to_csv(output_file, index=False)
    print(f"Data saved to {output_file} (index date: {index_date}, value: {value})")


if __name__ == '__main__':
    main()
