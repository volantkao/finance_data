#!/usr/bin/env python3
"""Daily monitor for U.S. Treasury TIC official holdings and primary-dealer net positions."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

TIC_URL = "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/slt_table5.txt"
PD_URL = "https://markets.newyorkfed.org/api/pd/get/PDPOSGST-TOT.json"
OUT = Path(os.getenv("OUTPUT_DIR", "data"))
OUT.mkdir(parents=True, exist_ok=True)
HISTORY = OUT / "observations.csv"
REPORT = OUT / "latest_report.md"


def get(url: str) -> bytes:
    """
    抓取指定 URL 的原始內容。失敗時（連線逾時、HTTP錯誤、來源網站掛掉等）
    印出清楚的錯誤訊息再往外拋，讓 main() 統一處理、GitHub Actions 能顯示
    有意義的失敗原因，而不是一段原始 traceback。
    """
    req = Request(url, headers={"User-Agent": "tic-dealer-monitor/1.0"})
    try:
        with urlopen(req, timeout=30) as r:
            return r.read()
    except Exception as e:
        raise RuntimeError(f"抓取失敗: {url} ({type(e).__name__}: {e})") from e


def parse_tic(raw: bytes) -> dict:
    try:
        rows = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter="\t"))
        header_i = next(i for i, row in enumerate(rows) if row and row[0] == "Country")
        header = rows[header_i]
        records = {}
        for row in rows[header_i + 1 :]:
            if not row or not row[0] or row[0].startswith("Notes:"):
                continue
            if row[0] in {
                "Of Which: Foreign Official",
                "Of Which: Foreign Official Treasury Bills",
                "Of Which: Foreign Official T-Bonds & Notes",
            }:
                for month, value in zip(header[1:], row[1:]):
                    if month and value:
                        records[(row[0], month)] = float(value)
        months = sorted({m for (_, m) in records})
        month = months[-1]
        return {
            "source": TIC_URL,
            "observation_date": month,
            "foreign_official_total_usd_bn": records[("Of Which: Foreign Official", month)],
            "foreign_official_bills_usd_bn": records[("Of Which: Foreign Official Treasury Bills", month)],
            "foreign_official_bonds_notes_usd_bn": records[("Of Which: Foreign Official T-Bonds & Notes", month)],
        }
    except (StopIteration, KeyError, IndexError, ValueError) as e:
        # 通常代表 Treasury 改了 slt_table5.txt 的格式（欄位名稱、分隔符號等），
        # 不是網路問題，需要人工去源頭確認新格式。
        raise RuntimeError(
            f"TIC 資料解析失敗，來源格式可能已變動，請人工檢查 {TIC_URL} "
            f"({type(e).__name__}: {e})"
        ) from e


def parse_pd(raw: bytes) -> dict:
    try:
        obj = json.loads(raw.decode("utf-8"))
        values = obj["pd"]["timeseries"]
        candidates = [x for x in values if x["keyid"] == "PDPOSGST-TOT"]
        row = max(candidates, key=lambda x: x["asofdate"])
        return {
            "source": PD_URL,
            "observation_date": row["asofdate"],
            "dealer_net_treasury_ex_tips_usd_mn": float(row["value"]),
            "dealer_net_treasury_ex_tips_usd_bn": float(row["value"]) / 1000.0,
            "dealer_series": row["keyid"],
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise RuntimeError(
            f"NY Fed dealer 部位資料解析失敗，API 回傳格式可能已變動，請人工檢查 {PD_URL} "
            f"({type(e).__name__}: {e})"
        ) from e


def previous() -> dict | None:
    if not HISTORY.exists():
        return None
    with HISTORY.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-1] if rows else None


def is_new_observation(old: dict | None, obs: dict) -> bool:
    """
    判斷這次抓到的資料，是否跟上一筆記錄的觀測值「實質不同」。

    比對邏輯不只看 observation_date，因為 TIC 資料常常會回頭修正
    之前月份的數字——如果只比對日期，同一個月份被修正過的新值會被
    誤判成「沒有新資料」而漏記。所以這裡把日期跟所有數值欄位都納入比對，
    任何一項不同就視為有新觀測（含修訂）。
    """
    if old is None:
        return True

    fields_to_compare = [
        ("tic_observation_date", obs["tic"]["observation_date"]),
        ("foreign_official_total_usd_bn", obs["tic"]["foreign_official_total_usd_bn"]),
        ("foreign_official_bills_usd_bn", obs["tic"]["foreign_official_bills_usd_bn"]),
        ("foreign_official_bonds_notes_usd_bn", obs["tic"]["foreign_official_bonds_notes_usd_bn"]),
        ("pd_observation_date", obs["pd"]["observation_date"]),
        ("dealer_net_treasury_ex_tips_usd_bn", obs["pd"]["dealer_net_treasury_ex_tips_usd_bn"]),
    ]
    for key, new_value in fields_to_compare:
        old_value = old.get(key)
        if key.endswith("_date") or key == "dealer_series":
            if str(old_value) != str(new_value):
                return True
        else:
            # 數值欄位用浮點數比較，容忍極小的字串轉換誤差，避免每次重跑都因為
            # 「1.0」vs「1」這種格式差異被誤判成有新資料
            try:
                if abs(float(old_value) - float(new_value)) > 1e-6:
                    return True
            except (TypeError, ValueError):
                return True  # 舊值缺失或格式異常，保守起見視為有變化，寫入一筆
    return False


def append_observation(obs: dict) -> None:
    fields = ["retrieved_at", "tic_observation_date", "foreign_official_total_usd_bn", "foreign_official_bills_usd_bn", "foreign_official_bonds_notes_usd_bn", "pd_observation_date", "dealer_net_treasury_ex_tips_usd_bn", "dealer_series"]
    exists = HISTORY.exists()
    with HISTORY.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow({
            "retrieved_at": obs["retrieved_at"],
            "tic_observation_date": obs["tic"]["observation_date"],
            "foreign_official_total_usd_bn": obs["tic"]["foreign_official_total_usd_bn"],
            "foreign_official_bills_usd_bn": obs["tic"]["foreign_official_bills_usd_bn"],
            "foreign_official_bonds_notes_usd_bn": obs["tic"]["foreign_official_bonds_notes_usd_bn"],
            "pd_observation_date": obs["pd"]["observation_date"],
            "dealer_net_treasury_ex_tips_usd_bn": obs["pd"]["dealer_net_treasury_ex_tips_usd_bn"],
            "dealer_series": obs["pd"]["dealer_series"],
        })


def main() -> None:
    try:
        tic_raw = get(TIC_URL)
        pd_raw = get(PD_URL)
        obs = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "tic": parse_tic(tic_raw), "pd": parse_pd(pd_raw)}
        obs["raw_sha256"] = {"tic": hashlib.sha256(tic_raw).hexdigest(), "pd": hashlib.sha256(pd_raw).hexdigest()}
    except RuntimeError as e:
        # get()/parse_tic()/parse_pd() 已經把錯誤訊息整理成人看得懂的句子，
        # 這裡直接印到 stderr 並以非零狀態結束，GitHub Actions 會標記這次執行失敗，
        # 且 log 裡看得到具體是哪個來源、哪個環節出問題，不用去挖原始 traceback。
        print(f"[錯誤] {e}", file=sys.stderr)
        sys.exit(1)

    old = previous()
    is_new = is_new_observation(old, obs)

    if is_new:
        append_observation(obs)
        write_note = "（新觀測值，已寫入 observations.csv）"
    else:
        write_note = "（跟上一筆記錄相同，本次未寫入 observations.csv，避免重複列）"

    deltas = {}
    if old:
        for key in ["foreign_official_total_usd_bn", "foreign_official_bills_usd_bn", "foreign_official_bonds_notes_usd_bn", "dealer_net_treasury_ex_tips_usd_bn"]:
            if key.startswith("dealer_"):
                now = obs["pd"][key]
            else:
                now = obs["tic"][key]
            deltas[key] = now - float(old[key])

    lines = ["# TIC / Primary Dealer Monitor", "", f"Retrieved: {obs['retrieved_at']} {write_note}", "", "| Series | Observation date | Latest (USD bn) | Change vs prior recorded (USD bn) |", "|---|---:|---:|---:|"]
    items = [
        ("Foreign official Treasury holdings", obs["tic"]["observation_date"], obs["tic"]["foreign_official_total_usd_bn"], deltas.get("foreign_official_total_usd_bn")),
        ("Foreign official Treasury bills", obs["tic"]["observation_date"], obs["tic"]["foreign_official_bills_usd_bn"], deltas.get("foreign_official_bills_usd_bn")),
        ("Foreign official T-bonds & notes", obs["tic"]["observation_date"], obs["tic"]["foreign_official_bonds_notes_usd_bn"], deltas.get("foreign_official_bonds_notes_usd_bn")),
        ("Dealer net Treasury position, ex-TIPS", obs["pd"]["observation_date"], obs["pd"]["dealer_net_treasury_ex_tips_usd_bn"], deltas.get("dealer_net_treasury_ex_tips_usd_bn")),
    ]
    for name, date, value, delta in items:
        lines.append(f"| {name} | {date} | {value:,.3f} | {'n/a' if delta is None else f'{delta:+,.3f}'} |")
    lines += ["", f"TIC source: [{TIC_URL}]({TIC_URL})", f"NY Fed source: [{PD_URL}]({PD_URL})", "", f"Raw TIC SHA-256: `{obs['raw_sha256']['tic']}`", f"Raw NY Fed SHA-256: `{obs['raw_sha256']['pd']}`"]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    webhook = os.getenv("ALERT_WEBHOOK_URL")
    threshold = float(os.getenv("ALERT_THRESHOLD_BN", "50"))
    alerts = [f"{k}: {v:+.3f} bn" for k, v in deltas.items() if abs(v) >= threshold]
    if alerts and webhook:
        try:
            payload = json.dumps({"content": "TIC/dealer monitor alert\n" + "\n".join(alerts)}).encode()
            req = Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=20):
                pass
        except Exception as e:
            # 警報通知失敗不該讓整個監控任務被標記失敗（資料已經抓到、報告已經寫好），
            # 只印警告，不 raise。
            print(f"[警告] 警報 webhook 發送失敗，但資料已正常更新: {e}", file=sys.stderr)

    print(REPORT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
