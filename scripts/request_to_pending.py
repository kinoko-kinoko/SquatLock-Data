#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
request_to_pending.py
- Googleフォームなどから集計した CSV を読み、 pending/requests/*.json を生成する。
- 既定: 1回答(1行)=1つのJSON
- --split-multi を付けると、アプリ名欄に複数記入（区切り: カンマ/セミコロン/改行/スラッシュ/日本語句読点 等）を分割し、
  1回答から複数の JSON を生成する。

CSV 期待ヘッダ:
  app_name, country
"""

from __future__ import annotations
import csv
import json
import os
import re
import sys
import argparse
from datetime import datetime
from typing import List, Dict

OUT_DIR = "pending/requests"
# 名前の分割に使う区切り文字（必要に応じて追加）
SPLIT_PATTERN = r"[,\u3001;\uFF0C/\u30FB\|]|[\r\n]+"  # , 、 ; ， / ・ | 改行

def slugify(s: str) -> str:
    s = s.strip().lower()
    # アルファベット/数字以外をハイフンに
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "app"

def guess_symbol(name: str) -> str:
    # 最低限: ゲームっぽい語が含まれていれば gamecontroller、なければ app.fill
    if re.search(r"(game|games|battle|royale|quest|clash|star|dragon|minecraft|pubg|cod|duty)", name, re.I):
        return "gamecontroller.fill"
    return "app.fill"

def guess_ul_and_host(name: str) -> Dict[str, List[str]]:
    # ざっくり推測（保守者が後で整える前提）
    nm = name.strip().lower()
    hosts: List[str] = []
    uls: List[str] = []

    # 簡易マップ（足しこみ可）
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

    # ホストが見つかったら https をひとつ作る。なければ空でOK
    if hosts:
        uls = [f"https://{hosts[0]}/"]
    return {"universalLinks": uls, "webHosts": hosts}

def make_entry(app_name: str, country: str) -> Dict:
    app = app_name.strip()
    sym = guess_symbol(app)
    guess = guess_ul_and_host(app)
    entry = {
        "id": slugify(app),
        "name": app_name.strip(),
        "symbol": sym,
        "schemes": [],                 # ← 保守者が後で追記
        "universalLinks": guess["universalLinks"],
        "webHosts": guess["webHosts"],
        "aliases": [app_name.strip()],
        "categories": ["game"] if sym == "gamecontroller.fill" else [],
        "source": {
            "country": country.strip(),
            "via": "intake"
        }
    }
    return entry

def write_json(entry: Dict) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{entry['id']}_{ts}.json"
    out_path = os.path.join(OUT_DIR, filename)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    return out_path

def split_names(raw: str) -> List[str]:
    # 区切り文字で分割し、空要素・重複を除去。安全のため最大10件に制限
    parts = [p.strip() for p in re.split(SPLIT_PATTERN, raw or "") if p.strip()]
    dedup = []
    seen = set()
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup[:10]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", help="CSV file like pending/requests/inbox.csv")
    parser.add_argument("--split-multi", action="store_true",
                        help="アプリ名欄の複数記入を分割して複数JSONを生成する")
    args = parser.parse_args()

    csv_path = args.csv_path
    if not os.path.exists(csv_path):
        print(f"[intake] CSV not found: {csv_path}")
        sys.exit(0)

    created = 0
    skipped = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames or []]
        print(f"[intake] CSV: {csv_path}")
        print(f"[intake] Headers: {headers}")

        # 緩くヘッダ許容
        name_key = "app_name" if "app_name" in headers else (headers[0] if headers else "app_name")
        country_key = "country" if "country" in headers else (headers[1] if len(headers) > 1 else "Global")

        for row in reader:
            raw_name = (row.get(name_key) or "").strip()
            country = (row.get(country_key) or "Global").strip()

            if not raw_name:
                skipped += 1
                continue

            names = [raw_name]
            if args.split_multi:
                names = split_names(raw_name)

            for nm in names:
                entry = make_entry(nm, country)
                path = write_json(entry)
                print(f"[create] {path:40s} name='{nm}' country='{country}'")
                created += 1

    print(f"created: {created}")
    print(f"skipped: {skipped}")

if __name__ == "__main__":
    main()
