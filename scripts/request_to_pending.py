#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert intake CSV -> pending/requests/*.json
- Accepts multilingual headers
- Verbose logs for created/skip reasons
Usage:
  python scripts/request_to_pending.py pending/requests/inbox.csv
"""

import csv
import json
import os
import re
import sys
from datetime import datetime

# ---- Config ----
OUT_DIR = "pending/requests"
DEFAULT_COUNTRY = "US"

APP_NAME_KEYS = [
    "app_name", "name",
    "アプリ名", "App Name", "App Name (アプリ名)"
]
COUNTRY_KEYS = [
    "country",
    "国", "Country", "Country (国)"
]

CATEGORIES_FALLBACK = ["game"]  # 最低限のデフォルト


def slugify(s: str) -> str:
    s = s.strip()
    # 半角化に頼らず安全なスラグに寄せる
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-zA-Z0-9\-\_]", "", s)
    return s.lower() or "app"

def pick(d: dict, keys: list[str]) -> str | None:
    for k in keys:
        if k in d and d[k]:
            return d[k].strip()
    return None

def ensure_outdir():
    os.makedirs(OUT_DIR, exist_ok=True)

def make_json(app_name: str, country: str) -> dict:
    # ごく簡易の推測（最低限の雛形）
    host_guess = None
    # 既知の超メジャーは軽く寄せる（無ければ None のままでもOK）
    known_hosts = {
        "minecraft": "minecraft.net",
        "youtube": "youtube.com",
        "instagram": "instagram.com",
        "tiktok": "tiktok.com",
        "x": "x.com",
        "twitter": "twitter.com",
        "netflix": "netflix.com",
    }
    key = app_name.lower()
    for k, host in known_hosts.items():
        if k in key:
            host_guess = host
            break

    universal_links = [f"https://{host_guess}/"] if host_guess else []
    web_hosts = [host_guess] if host_guess else []

    return {
        "id": slugify(app_name),
        "name": app_name,
        "symbol": "app.fill",
        "schemes": [],                 # ← あなたが後で追記
        "universalLinks": universal_links,
        "webHosts": web_hosts,
        "aliases": [app_name],
        "categories": CATEGORIES_FALLBACK,
        "source": {"country": country or DEFAULT_COUNTRY, "via": "intake"}
    }

def main():
    if len(sys.argv) < 2:
        print("ERROR: CSV path required", file=sys.stderr)
        sys.exit(2)

    csv_path = sys.argv[1]
    if not os.path.isfile(csv_path):
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(2)

    ensure_outdir()

    created = 0
    skipped = 0

    # BOM・区切りの揺れに強めに
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        print(f"[intake] CSV: {csv_path}")
        print(f"[intake] Headers: {headers}")

        for idx, row in enumerate(reader, start=2):  # 2=ヘッダの次の行番号
            raw = {k: (row.get(k) or "").strip() for k in row.keys()}
            app_name = pick(raw, APP_NAME_KEYS)
            country = pick(raw, COUNTRY_KEYS) or DEFAULT_COUNTRY

            if not app_name:
                print(f"[skip] row {idx}: empty app_name → {raw}")
                skipped += 1
                continue

            out_name = f"{slugify(app_name)}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
            out_path = os.path.join(OUT_DIR, out_name)

            # 同名スラグが短時間に連続で来た場合の衝突回避
            n = 1
            base = out_name
            while os.path.exists(out_path):
                out_name = base.replace(".json", f"_{n}.json")
                out_path = os.path.join(OUT_DIR, out_name)
                n += 1

            payload = make_json(app_name, country)
            with open(out_path, "w", encoding="utf-8") as wf:
                json.dump(payload, wf, ensure_ascii=False, indent=2)

            print(f"[create] {out_path}  name='{app_name}' country='{country}'")
            created += 1

    print(f"created: {created}")
    print(f"skipped: {skipped}")
    # 正常終了コード
    sys.exit(0)

if __name__ == "__main__":
    main()
