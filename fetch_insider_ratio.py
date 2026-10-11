#!/usr/bin/env python3
"""抓取 GuruFocus「Insider Buy/Sell Ratio - USA Overall Market」,upsert 進同目錄 CSV。

CSV 格式與既有檔案一致: UTF-8 BOM、CRLF、日期為每月 1 號。
GuruFocus 當月值是「近 30 天」滾動計算,所以當月那一列每次執行都會被更新,月底自然定版。
"""
import argparse
import csv
import html as htmllib
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
import yaml

HEADER = ["Date", "Insider_Buy_Sell_Ratio"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 頁面三種資料來源,依可靠度由高到低嘗試(格式已用真實頁面 HTML 驗證):
# 1) 資料表: <td data-column="Date">2026-10-01</td> ... <td data-column="Value">0.35</td>(近 ~14 個月)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r'<td[^>]*data-column="([^"]*)"[^>]*>(.*?)</td>', re.S)
# 2) SEO 文字 / ld+json: "Insider Buy/Sell Ratio - USA Overall Market is 0.35 as of 2026-10-01."
SENTENCE_RE = re.compile(r"Overall Market is\s+(-?\d+(?:\.\d+)?)\s+as of\s+(\d{4}-\d{2}-\d{2})", re.I)
# 3) <title>: "Insider Buy/Sell Ratio - USA Overall Market: 0.35 (Oct 2026) — ..."
TITLE_RE = re.compile(r"Overall Market:\s*(-?\d+(?:\.\d+)?)\s*\(([A-Za-z]{3}) (\d{4})\)")
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
log = logging.getLogger("insider")


# ---------- 取得頁面 ----------
def _cookie(cfg):
    return os.environ.get(cfg.get("cookie_env") or "", "")


def fetch_requests(cfg):
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if _cookie(cfg):
        headers["Cookie"] = _cookie(cfg)
    r = requests.get(cfg["url"], headers=headers, timeout=cfg["timeout_sec"])
    if r.status_code != 200:
        log.warning("HTTP %s | server=%s | cf-mitigated=%s | body開頭=%r", r.status_code,
                    r.headers.get("server"), r.headers.get("cf-mitigated"), r.text[:120])
    r.raise_for_status()
    return r.text


def _page_has_data(html):
    return "data-column" in html or bool(SENTENCE_RE.search(html)) or bool(TITLE_RE.search(html))


def fetch_playwright(cfg):
    """用真實 Chromium 開頁面。headless: false 搭配 xvfb(workflow 內 xvfb-run)較不易被判為機器人。
    會等待 Cloudflare 驗證頁("Just a moment")過去,最久 wait_sec 秒。"""
    from playwright.sync_api import sync_playwright  # 延遲載入,requests 模式不需安裝
    wait_sec = cfg.get("wait_sec", 40)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=cfg.get("headless", True),
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=UA, locale="en-US", timezone_id="America/New_York",
            viewport={"width": 1366, "height": 900},
        )
        if _cookie(cfg):
            ctx.set_extra_http_headers({"Cookie": _cookie(cfg)})
        page = ctx.new_page()
        try:
            resp = page.goto(cfg["url"], timeout=cfg["timeout_sec"] * 1000, wait_until="domcontentloaded")
            log.info("goto status=%s", resp.status if resp else None)
            html = ""
            for _ in range(wait_sec):
                html = page.title() + "\n" + page.content()
                if _page_has_data(html):
                    return html
                page.wait_for_timeout(1000)
            raise RuntimeError(f"等待 {wait_sec}s 仍無資料(title={page.title()!r},"
                               f"疑似 Cloudflare 驗證/封鎖)")
        finally:
            browser.close()


def get_latest(cfg):
    fetcher = {"requests": fetch_requests, "playwright": fetch_playwright}[cfg["method"]]
    last_err = None
    for i in range(1, cfg["retries"] + 1):
        try:
            return parse_html(fetcher(cfg))
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("第 %d/%d 次失敗: %s", i, cfg["retries"], e)
            if i < cfg["retries"]:
                time.sleep(cfg["retry_wait_sec"])
    raise RuntimeError(f"抓取失敗: {last_err}")


def parse_html(html):
    """回傳 {'YYYY-MM-01': '0.35', ...}(至少含最新一個月)。"""
    out = {}
    for tr in ROW_RE.findall(html):  # 1) 資料表
        cells = {k: htmllib.unescape(re.sub(r"<[^>]+>", "", v)).strip() for k, v in CELL_RE.findall(tr)}
        if "Related Item" in cells or "YOY (%)" not in cells:
            continue  # 跳過頁面下方「相關指標」表(Canada、各產業等),它們也有 Date/Value 欄
        d, v = cells.get("Date", ""), cells.get("Value", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and re.fullmatch(r"-?\d+(\.\d+)?", v):
            out.setdefault(d[:7] + "-01", v)  # 同月份以先出現者為準
    if out:
        return out
    m = SENTENCE_RE.search(html)  # 2) 文字句
    if m:
        return {m.group(2)[:7] + "-01": m.group(1)}
    m = TITLE_RE.search(html)  # 3) title
    if m and m.group(2) in MONTHS:
        return {f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-01": m.group(1)}
    raise ValueError("頁面中找不到資料表 / 'is x.xx as of YYYY-MM-DD' / title 數值"
                     "(可能被擋、需登入,或頁面改版)")


# ---------- CSV ----------
def read_csv(path):
    rows = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows[r["Date"]] = r["Insider_Buy_Sell_Ratio"]
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(HEADER)
        for k in sorted(rows):
            w.writerow([k, rows[k]])


def shift_month(key, months):
    t = int(key[:4]) * 12 + (int(key[5:7]) - 1) + months
    return f"{t // 12:04d}-{t % 12 + 1:02d}-01"


# ---------- 主流程 ----------
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--dry-run", action="store_true", help="只顯示結果,不寫檔")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg_path = Path(args.config).resolve()
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    out = cfg_path.parent / cfg["output"]["csv_file"]
    val = cfg["validation"]

    fetched = get_latest(cfg["source"])
    latest = max(fetched)
    log.info("抓到 %d 個月份,最新: %s -> %s", len(fetched), latest, fetched[latest])

    bad = {k: v for k, v in fetched.items() if not (val["min_ratio"] <= float(v) <= val["max_ratio"])}
    if bad:
        log.error("數值超出合理範圍,不寫入: %s", bad)
        return 1

    rows = read_csv(out)
    if rows and val.get("reject_older_than_csv", True) and latest < max(rows):
        log.warning("頁面最新月份 %s 比 CSV 最新月份 %s 還舊,視為過期資料,略過", latest, max(rows))
        return 0

    # 缺的月份補上;既有月份只在「CSV 最新月份往前 revise_months 個月」內允許修正,更早的歷史不動
    revise_from = shift_month(max(rows), -val.get("revise_months", 3)) if rows else "0000-00-00"
    changed = False
    for k in sorted(fetched):
        new, old = f"{float(fetched[k]):.2f}", rows.get(k)
        if old is None:
            rows[k], changed = new, True
            log.info("%s: (新增) -> %s", k, new)
        elif float(old) != float(new):  # 數值比較,0.4 與 0.40 視為相同
            if k >= revise_from:
                rows[k], changed = new, True
                log.info("%s: %s -> %s", k, old, new)
            else:
                log.warning("%s 與既有資料不同(%s vs %s),超出可修正範圍,保持原值", k, old, new)

    if cfg["output"].get("normalize_decimals", False):
        norm = {k: f"{float(v):.2f}" for k, v in rows.items()}
        changed |= norm != rows
        rows = norm

    if not changed:
        log.info("無變動")
    elif not args.dry_run:
        write_csv(out, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
