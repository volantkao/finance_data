"""
futures_oi_monitor.py

整合監控：
1. CBOE 每日 Put/Call Ratio
2. 台灣期交所 (TAIFEX) 台指期貨 (TX) 未平倉量 -- 每日資料，官方免費 OpenAPI
3. CME E-mini S&P 500 (ES) 未平倉量      -- 週資料，來自 CFTC 免費 Socrata API (TFF Futures Only)
   注意：CME 官方本身沒有免費即時/每日 OI，這是目前個人能拿到的免費管道，
   資料是「每週五公布、內容為前一週二」的落後資料，不是即時。

三份資料分別存成三個 CSV：
- cboe_pcr_history.csv
- taifex_oi_history.csv
- cme_oi_history.csv

【本版新增】
- 每個資料來源都會印出 HTTP status / 回應長度 / 回應開頭，方便在 Actions log 看出是被擋、改版還是欄位變動
- TAIFEX / CFTC 加入簡單重試
- 任何一個來源失敗，所有 CSV 仍會各自更新，但程式結尾會 exit(1)，讓 GitHub Actions 變紅並寄通知
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os
import re
import json
import sys
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}


# ---------------------------------------------------------------------------
# 診斷與重試工具
# ---------------------------------------------------------------------------
def _debug_resp(tag, resp):
    """印出回應狀態，失敗時可從 Actions log 判斷原因（403 = 被擋、200 但內容怪 = 改版或 challenge 頁）。"""
    print(f"[{tag}] status={resp.status_code}, len={len(resp.text)}, "
          f"content-type={resp.headers.get('Content-Type')}")
    print(f"[{tag}] head={resp.text[:300]!r}")


def _get_with_retry(tag, url, retries=3, backoff=5, **kwargs):
    """GET + 重試。每次都印出診斷資訊；全部失敗回傳 None。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, **kwargs)
            _debug_resp(tag, resp)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_err = e
            print(f"[{tag}] 第 {attempt}/{retries} 次請求失敗: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    print(f"[{tag}] 重試後仍失敗: {last_err}")
    return None


# ---------------------------------------------------------------------------
# 1. CBOE Put/Call Ratio
# ---------------------------------------------------------------------------
def _extract_next_chunks(soup):
    """
    收集頁面中所有 self.__next_f.push([1, "..."]) 的字串內容，
    用 json.loads 正確還原跳脫字元後串接成一整段文字。
    資料可能被切在多個 push 區塊裡，所以必須全部串起來再找。
    """
    chunks = []
    for script in soup.find_all('script'):
        s = script.string
        if not s or 'self.__next_f.push' not in s:
            continue
        m = re.search(r'self\.__next_f\.push\((\[.*\])\)', s, re.S)
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str):
            chunks.append(arr[1])
    return "".join(chunks)


def _find_json_after_key(text, key, start=0):
    """在 text 中找 "key": 之後的 JSON 值，用 raw_decode 解析（能正確處理巢狀大括號）。"""
    marker = f'"{key}":'
    idx = text.find(marker, start)
    while idx != -1:
        pos = idx + len(marker)
        while pos < len(text) and text[pos] in ' \n\r\t':
            pos += 1
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, pos)
            return obj, idx
        except json.JSONDecodeError:
            idx = text.find(marker, idx + 1)
    return None, -1


def _resolve_rsc_ref(text, obj):
    """Next.js RSC 有時會把資料放在別處，這裡只留一個 "$1f" 之類的參照，需要解開。"""
    if isinstance(obj, str) and re.fullmatch(r'\$[0-9a-f]+', obj):
        m = re.search(rf'(?m)^{re.escape(obj[1:])}:', text)
        if m:
            try:
                resolved, _ = json.JSONDecoder().raw_decode(text, m.end())
                return resolved
            except json.JSONDecodeError:
                pass
    return obj


def get_latest_cboe_pcr():
    """從 CBOE 網站抓取最新的每日 PCR 數據。"""
    url = "https://www.cboe.com/markets/us/options/market-statistics/daily/"
    headers = dict(HEADERS, Referer=url)

    time.sleep(2)
    response = _get_with_retry("CBOE", url, retries=2, backoff=5, headers=headers, timeout=20)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    combined = _extract_next_chunks(soup)
    print(f"[CBOE] 串接後的 Next.js 內嵌資料長度: {len(combined)}")

    script_data = None
    opt_idx = -1
    search_from = 0
    while True:
        obj, idx = _find_json_after_key(combined, "optionsData", search_from)
        if idx == -1:
            break
        obj = _resolve_rsc_ref(combined, obj)
        if isinstance(obj, dict) and obj:
            script_data = obj
            opt_idx = idx
            break
        search_from = idx + 1

    # selectedDate：優先取 optionsData 之後最近的一個，找不到就取第一個
    actual_data_date_str = None
    date_matches = list(re.finditer(r'"selectedDate":\s*"([^"]*)"', combined))
    for dm in date_matches:
        if dm.start() >= opt_idx:
            actual_data_date_str = dm.group(1)
            break
    if actual_data_date_str is None and date_matches:
        actual_data_date_str = date_matches[0].group(1)

    if not script_data or not actual_data_date_str:
        print("[CBOE] 未找到最新數據。")
        print(f"[CBOE] optionsData 解析結果: {'成功' if script_data else '失敗'}；selectedDate: {actual_data_date_str}")
        pos = combined.find('optionsData')
        if pos != -1:
            print(f"[CBOE] optionsData 附近內容: {combined[max(0, pos - 100):pos + 700]!r}")
        else:
            pos = response.text.find('optionsData')
            print(f"[CBOE] (原始 HTML) optionsData 附近內容: {response.text[max(0, pos - 100):pos + 700]!r}")
        return None

    print(f"[CBOE] optionsData 頂層欄位: {list(script_data.keys())}")

    pcr_values = {}

    try:
        for ratio in script_data.get('ratios', []):
            name = str(ratio.get('name', ''))
            raw = ratio.get('value')
            value = float(raw) if raw not in (None, '') else None
            if "EQUITY PUT/CALL RATIO" in name:
                pcr_values['Equity PCR'] = value
            elif "INDEX PUT/CALL RATIO" in name:
                pcr_values['Index PCR'] = value
    except (TypeError, ValueError, AttributeError) as e:
        print(f"[CBOE] 解析 ratios 失敗: {e}")

    for section, col in (('EQUITY OPTIONS', 'Equity OI PCR'), ('INDEX OPTIONS', 'Index OI PCR')):
        for item in script_data.get(section, []) or []:
            if item.get('name') == 'OPEN INTEREST':
                call_oi = item.get('call', 0)
                put_oi = item.get('put', 0)
                if call_oi is not None and put_oi is not None and call_oi > 0:
                    pcr_values[col] = round(put_oi / call_oi, 2)
                break

    if not pcr_values:
        print("[CBOE] 抓到 optionsData 但裡面沒有預期的 PCR 欄位，欄位結構可能已改變。")
        for k, v in script_data.items():
            print(f"[CBOE]   {k}: {str(v)[:200]!r}")
        return None

    pcr_values['Date'] = actual_data_date_str
    return pcr_values


# ---------------------------------------------------------------------------
# 2. 台灣期交所 (TAIFEX) 台指期貨 (TX) 未平倉量
# ---------------------------------------------------------------------------
def get_latest_taifex_oi(contract="TX"):
    """
    從 TAIFEX 官方 OpenAPI 抓取「期貨每日交易行情」，
    篩選出指定契約（預設 TX = 台指期貨）並加總各月份的未沖銷契約數 (OpenInterest)。

    注意：openapi.taifex.com.tw 只提供「最新一個交易日」的資料，沒有歷史查詢功能，
    所以歷史走勢要靠這支腳本每天排程執行、自己累積。
    """
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"

    resp = _get_with_retry("TAIFEX", url, retries=3, backoff=5, headers=HEADERS, timeout=30)
    if resp is None:
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        print(f"[TAIFEX] JSON 解碼失敗: {e}")
        return None

    if not data:
        print("[TAIFEX] 未取得任何資料。")
        return None

    df = pd.DataFrame(data)

    if 'Contract' not in df.columns or 'OpenInterest' not in df.columns:
        print(f"[TAIFEX] 回傳欄位與預期不符，實際欄位: {list(df.columns)}")
        return None

    df_contract = df[df['Contract'].str.strip() == contract].copy()
    if df_contract.empty:
        print(f"[TAIFEX] 找不到契約代碼 {contract}，實際出現的代碼: {df['Contract'].unique()[:20]}")
        return None

    # OpenInterest 欄位是字串，且可能含逗號，先清理再轉數字
    df_contract['OpenInterest'] = (
        df_contract['OpenInterest'].astype(str).str.replace(',', '').replace('', '0')
    )
    df_contract['OpenInterest'] = pd.to_numeric(df_contract['OpenInterest'], errors='coerce').fillna(0)

    total_oi = int(df_contract['OpenInterest'].sum())
    date_str = str(df_contract['Date'].iloc[0]) if 'Date' in df_contract.columns else datetime.now().strftime("%Y%m%d")

    return {
        'Date': date_str,
        'Contract': contract,
        'TotalOpenInterest': total_oi,
    }


# ---------------------------------------------------------------------------
# 3. CME E-mini S&P 500 (ES) 未平倉量 -- 透過 CFTC TFF (Futures Only) 免費週資料
# ---------------------------------------------------------------------------
def get_latest_cme_oi(cftc_contract_market_code="13874A"):
    """
    從 CFTC 公開 Socrata API 抓取 Traders in Financial Futures (TFF) - Futures Only
    報告中，指定契約（預設 13874A = E-mini S&P 500）的最新一筆未平倉量。

    注意：這是「每週」資料（每週五公布、內容為前一週二的部位），
    不是 CME 官方的每日/即時 OI；CME 官方即時/完整歷史 OI 是付費服務。
    """
    url = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
    params = {
        "$where": f"cftc_contract_market_code='{cftc_contract_market_code}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": 1,
    }

    resp = _get_with_retry("CME/CFTC", url, retries=3, backoff=5,
                           params=params, headers=HEADERS, timeout=30)
    if resp is None:
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        print(f"[CME/CFTC] JSON 解碼失敗: {e}")
        return None

    if not data:
        print(f"[CME/CFTC] 找不到契約代碼 {cftc_contract_market_code} 的資料。")
        return None

    row = data[0]
    return {
        'Date': row.get('report_date_as_yyyy_mm_dd', '').split('T')[0],
        'Contract': row.get('market_and_exchange_names', cftc_contract_market_code),
        'OpenInterestAll': row.get('open_interest_all'),
    }


# ---------------------------------------------------------------------------
# 通用：讀取既有 CSV -> 合併新資料 -> 去重 -> 存回
# ---------------------------------------------------------------------------
def _update_history_csv(history_file, latest_row, columns, date_col='Date'):
    """成功更新回傳 True；沒有新資料回傳 False。"""
    if latest_row is None:
        print(f"未取得新數據，略過更新 {history_file}。")
        return False

    if os.path.exists(history_file):
        df_history = pd.read_csv(history_file, dtype={date_col: str})
    else:
        df_history = pd.DataFrame(columns=columns)

    df_latest = pd.DataFrame([latest_row])

    df_combined = pd.concat([df_history, df_latest], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=[date_col], keep='last')
    df_combined = df_combined.sort_values(date_col, ascending=False)
    df_combined = df_combined.head(1000)

    df_combined.to_csv(history_file, index=False)
    print(f"數據已更新至 {history_file}，共 {len(df_combined)} 條記錄，最新日期 {latest_row.get('Date')}。")
    return True


def main():
    failures = []

    print("=== 1/3 抓取 CBOE Put/Call Ratio ===")
    cboe_data = get_latest_cboe_pcr()
    if not _update_history_csv(
        'cboe_pcr_history.csv',
        cboe_data,
        columns=['Date', 'Equity PCR', 'Index PCR', 'Equity OI PCR', 'Index OI PCR'],
    ):
        failures.append("CBOE")

    print("\n=== 2/3 抓取台指期 (TX) 未平倉量 ===")
    taifex_data = get_latest_taifex_oi(contract="TX")
    if not _update_history_csv(
        'taifex_oi_history.csv',
        taifex_data,
        columns=['Date', 'Contract', 'TotalOpenInterest'],
    ):
        failures.append("TAIFEX")

    print("\n=== 3/3 抓取 CME E-mini S&P 500 未平倉量 (CFTC 週資料) ===")
    cme_data = get_latest_cme_oi(cftc_contract_market_code="13874A")
    if not _update_history_csv(
        'cme_oi_history.csv',
        cme_data,
        columns=['Date', 'Contract', 'OpenInterestAll'],
    ):
        failures.append("CME/CFTC")

    print("\n=== 結果 ===")
    if failures:
        print(f"以下資料來源抓取失敗: {', '.join(failures)}")
        sys.exit(1)  # 讓 GitHub Actions 顯示紅叉並寄通知
    print("三個資料來源皆成功。")


if __name__ == "__main__":
    main()
