#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
request_to_pending.py
- Googleフォーム等のCSVを pending/requests/*.json に変換
- ヘッダを多言語・部分一致で判別（Timestamp等は除外）
- --split-multi で「アプリ名」欄の複数入力を分割して複数JSON生成
"""

from __future__ import annotations
import csv
import json
import os
import re
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Optional

OUT_DIR = "pending/requests"
SPLIT_PATTERN = r"[,\u3001;\uFF0C/\u30FB\|]|[\r\n]+"  # , 、 ; ， / ・ | 改行

# ヘッダ検出用パターン
TS_EXCLUDE = re.compile(r"(timestamp|time\s*stamp|date\s*/?\s*time|日時|日付|タイムスタンプ)", re.I)
APP_INCLUDE = [
    re.compile(r"\bapp\b.*\bname\b", re.I),    # "App name"
    re.compile(r"app\s*title", re.I),
    re.compile(r"アプリ\s*名"),
    re.compile(r"アプリ", re.I),
]
COUNTRY_INCLUDE = [
    re.compile(r"\bcountry\b", re.I),
    re.compile(r"国", re.I),
]

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "app"

def guess_symbol(name: str) -> str:
    if re.search(r"(game|games|battle|royale|quest|clash|star|dragon|minecraft|pubg|cod|duty)", name, re.I):
        return "gamecontroller.fill"
    return "app.fill"

def guess_ul_and_host(name: str) -> Dict[str, List[str]]:
    nm = name.strip().lower()
    hosts: List[str] = []
    uls: List[str] = []
    table = {
        "minecraft": "minecraft.net",
        "youtube": "youtube.com",
        "instagram": "instagram.com",
        "twitter": "x.com",
        "x": "x.com",
        "tiktok": "tiktok.com",
        "discord": "discord.com",
        "netflix": "netflix.com",
        "spotify": "open.spotify.com",
        "line": "line.me",
        "whatsapp": "whatsapp.com",
    }
    for key, host in table.items():
        if key in nm:
            hosts.append(host)
    if hosts:
        uls = [f"https://{hosts[0]}/"]
    return {"universalLinks": uls, "webHosts": hosts}

def make_entry(app_name: str, country: str) -> Dict:
    sym = guess_symbol(app_name)
    guess = guess_ul_and_host(app_name)
    return {
        "id": slugify(app_name),
        "name": app_name.strip(),
        "symbol": sym,
        "schemes": [],  # ← 後で保守者が追記
        "universalLinks": guess["universalLinks"],
        "webHosts": guess["webHosts"],
        "aliases": [app_name.strip()],
        "categories": ["game"] if sym == "gamecontroller.fill" else [],
        "source": {"country": (country or "Global").strip(), "via": "intake"},
    }

def write_json(entry: Dict) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{entry['id']}_{ts}.json"
    out_path = os.path.join(OUT_DIR, filename)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    return out_path

def split_names(raw: str) -> List[str]:
    parts = [p.strip() for p in re.split(SPLIT_PATTERN, raw or "") if p.strip()]
    dedup, seen = [], set()
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            dedup.append(p)
    return dedup[:10]

def find_header(headers: List[str], includes: List[re.Pattern], exclude_ts: bool = False) -> Optional[str]:
    """
    ヘッダ一覧から、includeパターンにヒットする列名を返す。
    exclude_ts=True の場合は Timestamp系を除外。
    """
    for h in headers:
        h_norm = h.strip()
        if not h_norm:
            continue
        if exclude_ts and TS_EXCLUDE.search(h_norm):
            continue
        for inc in includes:
            if inc.search(h_norm):
                return h  # 元の大文字小文字を返す
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="CSV file like pending/requests/inbox.csv")
    ap.add_argument("--split-multi", action="store_true", help="アプリ名欄の複数記入を分割して複数JSONを生成")
    args = ap.parse_args()

    csv_path = args.csv_path
    if not os.path.exists(csv_path):
        print(f"[intake] CSV not found: {csv_path}")
        sys.exit(0)

    created = 0
    skipped = 0

    # BOM吸収
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers_orig = reader.fieldnames or []
        headers_lc = [h or "" for h in headers_orig]

        print(f"[intake] CSV: {csv_path}")
        print(f"[intake] Headers(raw): {headers_orig}")

        # ヘッダ検出
        app_key = find_header(headers_orig, APP_INCLUDE, exclude_ts=True)
        country_key = find_header(headers_orig, COUNTRY_INCLUDE, exclude_ts=False)

        if not app_key:
            print("[intake] ERROR: 'アプリ名 / App name' に該当する列名が見つかりません。フォームの質問文（列名）を確認してください。")
            print("         例: 'App name / アプリ名', 'アプリ名', 'App name' などが望ましいです。")
        else:
            print(f"[intake] detected app_name header: {app_key}")

        if not country_key:
            print("[intake] WARN: '国 / Country' 列が見つかりません。全件 'Global' として処理します。")
        else:
            print(f"[intake] detected country header: {country_key}")

        for idx, row in enumerate(reader, start=2):
            # 値取得
            raw_app = (row.get(app_key or "") or "").strip()
            raw_country = (row.get(country_key or "") or "Global").strip()

            if not raw_app:
                print(f"[skip] row {idx}: empty app_name (row={row})")
                skipped += 1
                continue

            names = [raw_app]
            if args.split_multi:
                names = split_names(raw_app)

            for nm in names:
                entry = make_entry(nm, raw_country)
                out = write_json(entry)
                print(f"[create] {out}  name='{nm}' country='{raw_country}'")
                created += 1

    print(f"created: {created}")
    print(f"skipped: {skipped}")

if __name__ == "__main__":
    main()
