#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
request_to_pending.py

- Googleフォーム → CSV から pending/requests/*.json を生成
- Known Apps に一致すればその ID を採用
- 一致しなくても **取りこぼし無し**で必ず PR に出す
- 表記ゆれ（例: どうぶつタワーバトル / 動物タワーバトル）を
  `.intake/alias_map.json` で同一 ID に自動集約し、既存 JSON にマージ更新する

使い方:
  python scripts/request_to_pending.py pending/inbox.csv [--since-ts "YYYY/MM/DD HH:MM:SS"]

想定ファイル:
  - data/known_apps.json        … 既知アプリ（無ければ空でOK）
  - .intake/alias_map.json      … 表記ゆれ → ID の対応表（自動で増える）
  - pending/requests/*.json     … 出力
"""

from __future__ import annotations
import csv
import json
import re
import sys
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import unicodedata
from datetime import datetime

# ===== パス定義 =====
PENDING_DIR        = Path("pending/requests")
KNOWN_APPS_PATH    = Path("data/known_apps.json")     # 無い場合は空扱いでOK
ALIAS_MAP_PATH     = Path(".intake/alias_map.json")   # 自動作成・更新
INTAKE_STATE_DIR   = Path(".intake")

# ===== CSV のヘッダ推定（多言語対応・改行・句読点に強く） =====
HDR_APP_KEYS     = ["app", "アプリ", "应用", "應用", "앱", "名稱", "名前", "名"]
HDR_COUNTRY_KEYS = ["country", "国", "国家", "나라"]

SPLIT_PAT = re.compile(r"[,\n/、／;；]+")  # 複数アプリの区切り

# ===== 正規化・ユーティリティ =====
def normalize_key(s: str) -> str:
    """ID/照合用の正規化キー: 全角→半角・小文字化・空白/記号除去"""
    if not s:
        return ""
    x = unicodedata.normalize("NFKC", s).strip().lower()
    # 空白/記号などは除外（漢字・かな等はそのまま残す）
    x = re.sub(r"[\s\-\_\.\(\)\[\]\{\}]+", "", x)
    x = re.sub(r"[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~]", "", x)
    return x

def ts_to_dt(s: str) -> Optional[datetime]:
    """タイムスタンプ文字列を可能な限り datetime に。失敗したら None"""
    s = s.strip()
    if not s:
        return None
    for fmt in [
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def slugify_ascii(name: str) -> str:
    """ラテン文字だけでスラッグ生成。全部非ASCIIなら短いハッシュにフォールバック"""
    base = unicodedata.normalize("NFKD", name)
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    if base:
        return base
    # どうしてもASCII出ないならハッシュ
    h = hashlib.sha1(normalize_key(name).encode("utf-8")).hexdigest()[:8]
    return f"app-{h}"

# ===== 既知アプリ読込（任意） =====
def load_known_apps() -> Dict[str, Any]:
    """
    既知アプリ JSON 形式例:
    [
      {
        "id": "minecraft",
        "name": "Minecraft",
        "aliases": ["マインクラフト","我的世界","마인크래프트","MC"],
        "symbol": "gamecontroller.fill",
        "schemes": [],
        "universalLinks": ["https://minecraft.net/"],
        "webHosts": ["minecraft.net","www.minecraft.net"],
        "categories": ["game"]
      },
      ...
    ]
    """
    if not KNOWN_APPS_PATH.exists():
        return {"data": {}, "index": {}}
    try:
        raw = json.loads(KNOWN_APPS_PATH.read_text(encoding="utf-8"))
        data = {}
        index = {}
        for ent in raw or []:
            app_id = ent.get("id") or slugify_ascii(ent.get("name") or "")
            ent["id"] = app_id
            data[app_id] = ent
            # 正規化キーへインデックス（name + aliases）
            names = [ent.get("name") or ""] + list(ent.get("aliases") or [])
            for nm in names:
                k = normalize_key(nm)
                if k:
                    index[k] = app_id
        return {"data": data, "index": index}
    except Exception:
        return {"data": {}, "index": {}}

# ===== alias_map 読み書き =====
def load_alias_map() -> Dict[str, str]:
    if ALIAS_MAP_PATH.exists():
        try:
            return json.loads(ALIAS_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_alias_map(m: Dict[str, str]) -> None:
    INTAKE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    ALIAS_MAP_PATH.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

# ===== 出力 JSON 生成 =====
def compose_json_for_known(app_id: str, known: Dict[str, Any], country: str, input_name: str) -> Dict[str, Any]:
    ent = (known["data"] or {}).get(app_id, {})
    out = {
        "id": app_id,
        "name": ent.get("name") or input_name,
        "symbol": ent.get("symbol") or "app.fill",
        "schemes": list(ent.get("schemes") or []),
        "universalLinks": list(ent.get("universalLinks") or []),
        "webHosts": list(ent.get("webHosts") or []),
        "aliases": list(ent.get("aliases") or []),
        "categories": list(ent.get("categories") or []),
        "source": {
            "country": country or "Global",
            "via": "intake",
        },
    }
    # aliases にオリジナル入力を足しておく
    if input_name and input_name not in out["aliases"]:
        out["aliases"].append(input_name)
    return out

def compose_json_for_unknown(name: str, country: str, forced_id: Optional[str] = None) -> Dict[str, Any]:
    app_id = forced_id or slugify_ascii(name)
    return {
        "id": app_id,
        "name": name,
        "symbol": "app.fill",
        "schemes": [],
        "universalLinks": [],
        "webHosts": [],
        "aliases": [name],
        "categories": [],
        "source": {
            "country": country or "Global",
            "via": "intake",
        },
    }

def union_list(existing: List[Any], incoming: List[Any]) -> List[Any]:
    s = []
    seen = set()
    for v in (existing or []) + (incoming or []):
        if v is None:
            continue
        if isinstance(v, str):
            key = v
        else:
            key = json.dumps(v, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        s.append(v)
    return s

def merge_json(existing: Dict[str, Any], incoming: Dict[str, Any], new_alias: str, country: str) -> Dict[str, Any]:
    out = dict(existing or {})
    out["id"] = existing.get("id") or incoming.get("id")
    out["name"] = existing.get("name") or incoming.get("name")
    out["symbol"] = existing.get("symbol") or incoming.get("symbol") or "app.fill"

    out["schemes"]        = union_list(existing.get("schemes"),        incoming.get("schemes"))
    out["universalLinks"] = union_list(existing.get("universalLinks"), incoming.get("universalLinks"))
    out["webHosts"]       = union_list(existing.get("webHosts"),       incoming.get("webHosts"))
    out["categories"]     = union_list(existing.get("categories"),     incoming.get("categories"))

    aliases = set(existing.get("aliases") or [])
    if new_alias:
        aliases.add(new_alias)
    # incoming 側の aliases も併合
    for a in incoming.get("aliases") or []:
        aliases.add(a)
    out["aliases"] = sorted(aliases)

    src = dict(existing.get("source") or {})
    # 既存 country を落とさず country_list に集約
    country_list = set(src.get("country_list") or [])
    if src.get("country"):
        country_list.add(src["country"])
    if country:
        country_list.add(country)
    src["country"] = src.get("country") or (country or "Global")
    src["via"] = "intake"
    if country_list:
        src["country_list"] = sorted(country_list)
    out["source"] = src

    return out

# ===== CSV ヘッダ検出 =====
def detect_columns(headers: List[str]) -> Tuple[int, int]:
    """(app_col_index, country_col_index or -1)"""
    def score(h: str, keys: List[str]) -> int:
        n = normalize_key(h)
        return 1 if any(k in n for k in keys) else 0

    app_idx = -1
    ctry_idx = -1
    best_app = -1
    best_ctry = -1
    for i, h in enumerate(headers):
        s_app  = score(h, HDR_APP_KEYS)
        s_ctry = score(h, HDR_COUNTRY_KEYS)
        if s_app > best_app:
            best_app, app_idx = s_app, i
        if s_ctry > best_ctry:
            best_ctry, ctry_idx = s_ctry, i
    # app は最低限必要
    if app_idx < 0:
        # 2列目(=B列)がアプリ名の事が多い
        app_idx = 1 if len(headers) > 1 else 0
    return app_idx, (ctry_idx if best_ctry > 0 else -1)

# ===== メイン =====
def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: request_to_pending.py <csv_path> [--since-ts 'YYYY/MM/DD HH:MM:SS']", file=sys.stderr)
        return 2

    csv_path = Path(argv[1])
    since_ts = None
    for i, a in enumerate(argv):
        if a == "--since-ts" and i + 1 < len(argv):
            since_ts = ts_to_dt(argv[i + 1])

    known = load_known_apps()
    alias_map = load_alias_map()

    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0

    with csv_path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        headers = next(r, [])
        # 先頭がタイムスタンプ & 一部シートでは先頭行がヘッダのケースのみ想定
        app_col, country_col = detect_columns(headers)

        for row in r:
            if not row or all((c or "").strip() == "" for c in row):
                continue

            # A列がタイムスタンプのケースが多い想定
            ts_raw = (row[0] if len(row) > 0 else "").strip()
            dt = ts_to_dt(ts_raw)
            if since_ts and dt and dt <= since_ts:
                # チェックポイント以前はスキップ
                continue

            app_raw = (row[app_col] if len(row) > app_col else "").strip()
            country = (row[country_col] if (country_col >= 0 and len(row) > country_col) else "").strip()

            if not app_raw:
                skipped += 1
                continue

            # 1行に複数のアプリ名が来ることがある（カンマ/改行/日本語読点など）
            names = [n.strip() for n in SPLIT_PAT.split(app_raw) if n.strip()]
            if not names:
                skipped += 1
                continue

            for nm in names:
                key = normalize_key(nm)
                if not key:
                    continue

                # 1) alias_map 優先（すでに同一IDに束ね済みか）
                mapped_id = alias_map.get(key, "")

                # 2) Known Apps にヒット？
                if not mapped_id:
                    kid = known["index"].get(key, "")
                    if kid and (known["data"].get(kid)):
                        data = compose_json_for_known(kid, known, country, nm)
                        mapped_id = data["id"] or kid
                    else:
                        # 未知 → 新規ID（ASCII slug or ハッシュ）
                        data = compose_json_for_unknown(nm, country)
                        mapped_id = data["id"]

                    # 新しいキー→ID を記録
                    alias_map[key] = mapped_id
                else:
                    # 既存IDに対しては “最小の雛形” を作って後段でマージ
                    data = compose_json_for_unknown(nm, country, forced_id=mapped_id)

                out_path = PENDING_DIR / f"{mapped_id}.json"
                if out_path.exists():
                    try:
                        existing = json.loads(out_path.read_text(encoding="utf-8"))
                    except Exception:
                        existing = {}
                    merged = merge_json(existing, data, new_alias=nm, country=country)
                    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
                else:
                    # 初回作成でも aliases に自分の表記を確実に入れておく（composeで済んでいる想定）
                    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    created += 1

    save_alias_map(alias_map)

    print(f"[intake] created={created}  skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
