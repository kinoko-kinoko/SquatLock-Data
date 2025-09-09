#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CSV(Archive) → pending/requests/*.json を生成（差分のみ可）

- 入力: Google Sheets から落とした CSV
  * A列: タイムスタンプ (例: 2025/09/09 15:57:39)
  * B列: ユーザー入力のアプリ名（複数可。カンマ/読点/スラッシュ等で区切りに対応）
  * 以降の列は使わなくてもOK

- 同一アプリ判定:
  1) known_apps.json にある別名 → 正規 id へマッピング
  2) 無ければ簡易正規化（小文字化/記号除去）で slug を作成

- 重要: --since-ts オプションで「前回以降の行だけ」処理
"""

from __future__ import annotations
import csv
import json
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime

# ========= 設定 =========

KNOWN_APPS_PATH = Path("known_apps.json")   # 任意。存在すれば読み込む
OUT_DIR = Path("pending/requests")

# シートの列インデックス（0始まり）
COL_TS = 0     # A: タイムスタンプ
COL_APP = 1    # B: アプリ名入力欄

# 区切り（ユーザーが1度に複数アプリを入れてくる場合）
SPLIT_PATTERN = re.compile(r"[,\u3001\uFF0C\uFF0F/、／]")

# ========= ユーティリティ =========

def parse_ts(s: str) -> datetime | None:
    s = s.strip()
    if not s:
        return None
    # Googleフォームの標準 "YYYY/MM/DD HH:MM:SS" 想定
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

def normalize_name(name: str) -> str:
    s = name.strip().lower()
    # 記号・スペースを除去
    s = re.sub(r"[\s\-\_\.\+\(\)\[\]\{\}\'\"\!\?★☆™®©:;＠@#]", "", s)
    return s

def slugify(name: str) -> str:
    s = normalize_name(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s:
        s = "app"
    return s

def load_known_apps() -> dict:
    if KNOWN_APPS_PATH.exists():
        try:
            with KNOWN_APPS_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
                # 期待フォーマット:
                # {
                #   "minecraft": {
                #       "aliases": ["マインクラフト","我的世界","마인크래프트","mc"],
                #       "symbol": "gamecontroller.fill",
                #       "universalLinks": ["https://minecraft.net/"],
                #       "webHosts": ["minecraft.net","www.minecraft.net"],
                #       "categories": ["game"]
                #   },
                #   ...
                # }
                return data
        except Exception as e:
            print(f"[warn] failed to read known_apps.json: {e}", file=sys.stderr)
    return {}

def pick_id_and_meta(name: str, known: dict) -> tuple[str, dict]:
    """
    入力名から 正規id と 既知メタデータ を返す。
    - 完全一致/別名一致 で known_apps を優先
    - 無ければ slugify
    """
    normalized = normalize_name(name)
    # 完全一致または alias一致
    for app_id, meta in known.items():
        if normalize_name(app_id) == normalized:
            return app_id, meta
        for a in meta.get("aliases", []):
            if normalize_name(a) == normalized:
                return app_id, meta
    # 既知ではない → slugify
    return slugify(name), {}

# ========= 生成 =========

def build_record(app_id: str, display_name: str, meta: dict, source_country: str | None = None) -> dict:
    aliases = list(dict.fromkeys([display_name] + meta.get("aliases", [])))  # 重複排除
    rec = {
        "id": app_id,
        "name": display_name,
        "symbol": meta.get("symbol", "app.fill"),
        "schemes": meta.get("schemes", []),
        "universalLinks": meta.get("universalLinks", []),
        "webHosts": meta.get("webHosts", []),
        "aliases": aliases,
        "categories": meta.get("categories", []),
        "source": {
            "country": source_country or "Global",
            "via": "intake",
        },
    }
    return rec

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="Archive CSV path")
    ap.add_argument("--since-ts", default="", help="process only rows newer than this timestamp")
    args = ap.parse_args()

    csv_path = Path(args.csv_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    since_ts_dt = parse_ts(args.since_ts) if args.since_ts else None
    print(f"[info] since-ts: {args.since_ts or '(none)'}")

    known = load_known_apps()

    # 1回の実行でまとめた結果（id → record）
    merged: dict[str, dict] = {}

    with csv_path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        headers = next(r, [])

        for row in r:
            if not row:
                continue

            # 差分フィルタ: A列タイムスタンプ
            ts_raw = (row[COL_TS] if len(row) > COL_TS else "").strip()
            ts_dt = parse_ts(ts_raw)
            if since_ts_dt and ts_dt and ts_dt <= since_ts_dt:
                # 前回分まで → スキップ
                continue

            # アプリ名列
            app_raw = (row[COL_APP] if len(row) > COL_APP else "").strip()
            if not app_raw:
                continue

            # 複数入力の分割
            names = [s.strip() for s in SPLIT_PATTERN.split(app_raw) if s.strip()]
            for name in names:
                app_id, meta = pick_id_and_meta(name, known)
                # 代表表示名は known があれば metaの name / 無ければそのまま
                display = meta.get("name", name)

                if app_id not in merged:
                    merged[app_id] = build_record(app_id, display, meta, source_country="Global")
                else:
                    # すでに存在 → aliasに追加（重複排除）
                    al = merged[app_id].get("aliases", [])
                    if name not in al:
                        al.append(name)
                        merged[app_id]["aliases"] = al

    # 出力
    for app_id, rec in merged.items():
        out_path = OUT_DIR / f"{app_id}.json"
        with out_path.open("w", encoding="utf-8") as wf:
            json.dump(rec, wf, ensure_ascii=False, indent=2)
        print("[write]", out_path)

if __name__ == "__main__":
    main()
