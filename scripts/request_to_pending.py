#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Form CSV → pending/requests/*.json 生成スクリプト（取りこぼしゼロ版）
- Known Apps に載っていれば補完（ID/aliases/ULなど）
- Known Apps に無くても「必ず」1件＝1 JSON を作成（スルー禁止）
- 未知名の ID は slug（ASCII正規化）／空なら name の SHA1 で app-xxxxxxxx を付与
- 1行に複数名が書かれていれば分割（, ・ 、 / | 改行 など）して個別に作成
- --since-ts でフィルタ可能（ワークフローがセット）。省略時は全件。
"""

from __future__ import annotations
import csv, json, sys, re, unicodedata, hashlib, argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

# === 入出力既定 ===
PENDING_DIR = Path("pending/requests")
KNOWN_JSON  = Path("scripts/known_apps.json")   # あれば使う（無ければ無視）
DEFAULT_SYMBOL = "app.fill"

# === CSV の推定ヘッダ ===
COL_TS   = "timestamp"   # A列（見出しは任意：実際はヘッダ自動検出）
COL_NAME = "app_name"    # アプリ名
COL_COUNTRY = "country"  # 国（任意）

# === 名称分割に使う区切り ===
SPLIT_RE = re.compile(r"[,\u3001\u30FB/|\n\r\t]+")

# ------------------------------------------------------------

def read_known() -> Dict[str, Any]:
    """known_apps.json を読み込み（存在しなければ空）"""
    if KNOWN_JSON.exists():
        with KNOWN_JSON.open(encoding="utf-8") as f:
            data = json.load(f)
        # キー（id）も alias として検索できるよう正規化索引を作る
        idx = {}
        for kid, app in data.items():
            name = app.get("name", "")
            aliases = set(app.get("aliases", []) or [])
            aliases.add(name)
            aliases.add(kid)
            for a in aliases:
                idx[normalize_key(a)] = kid
        return {"data": data, "index": idx}
    return {"data": {}, "index": {}}

def normalize_key(s: str) -> str:
    """照合用のゆるいキー（全角→半角/大小無視/空白と記号を削除）"""
    t = unicodedata.normalize("NFKC", s)
    t = t.lower()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", "", t)
    return t

def slugify(name: str) -> str:
    """ファイル名/未知ID用の slug（空になったらハッシュでユニーク化）"""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        s = f"app-{h}"
    return s

def tokenize_app_names(raw: str) -> List[str]:
    tokens = [t.strip() for t in SPLIT_RE.split(raw or "") if t.strip()]
    # 同じ行に同名が重複しても1回だけ
    seen, out = set(), []
    for t in tokens:
        k = normalize_key(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out

def guess_defaults(name: str) -> Dict[str, Any]:
    """未知アプリの最低限テンプレ（ここは必要に応じ拡張）"""
    sym = DEFAULT_SYMBOL
    # “game”っぽい語が入っていれば雰囲気カテゴリ
    cat = []
    if re.search(r"game|ゲーム|遊|玩", name, re.I):
        cat = ["game"]
        sym = "gamecontroller.fill"
    return {
        "symbol": sym,
        "schemes": [],
        "universalLinks": [],
        "webHosts": [],
        "categories": cat,
    }

def load_csv_rows(csv_path: Path, since_ts: Optional[str]) -> List[Dict[str, str]]:
    """CSVを読み込み、ヘッダ名を推定しつつ since_ts 以降だけ返す"""
    out = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        rows = list(r)
    if not rows:
        return out

    header = rows[0]
    body = rows[1:]

    # ヘッダ推定
    # A列：タイムスタンプ相当
    # B列：アプリ名
    # C列：国（あれば）
    # ヘッダに説明文が長い場合もあるので列位置で扱う
    i_ts = 0
    i_name = 1 if len(header) > 1 else 0
    i_country = 2 if len(header) > 2 else None

    for row in body:
        if not row or all(not c.strip() for c in row):
            continue
        ts = (row[i_ts] if i_ts is not None and i_ts < len(row) else "").strip()
        if since_ts and ts <= since_ts:
            continue
        name = (row[i_name] if i_name is not None and i_name < len(row) else "").strip()
        country = (row[i_country] if i_country is not None and i_country < len(row) else "").strip() if i_country is not None else ""
        if not name:
            # 名称空はスキップ（ただし“取りこぼしゼロ”の趣旨は「名前があるものは必ず拾う」）
            continue
        out.append({"timestamp": ts, "app_name": name, "country": country})
    return out

def compose_json_for_known(kid: str, known: Dict[str, Any], source_country: str, alias: str) -> Dict[str, Any]:
    base = known["data"][kid]
    data = {
        "id": base.get("id", kid),
        "name": base.get("name", alias),
        "symbol": base.get("symbol", DEFAULT_SYMBOL),
        "schemes": base.get("schemes", []) or [],
        "universalLinks": base.get("universalLinks", []) or [],
        "webHosts": base.get("webHosts", []) or [],
        "aliases": sorted(list(set((base.get("aliases") or []) + [alias]))),
        "categories": base.get("categories", []) or [],
        "source": {
            "country": source_country or "Global",
            "via": "intake"
        }
    }
    return data

def compose_json_for_unknown(name: str, source_country: str) -> Dict[str, Any]:
    d = guess_defaults(name)
    return {
        "id": slugify(name),
        "name": name,
        "symbol": d["symbol"],
        "schemes": d["schemes"],
        "universalLinks": d["universalLinks"],
        "webHosts": d["webHosts"],
        "aliases": [name],
        "categories": d["categories"],
        "source": {
            "country": source_country or "Global",
            "via": "intake"
        }
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=str, help="CSV (Archive シートをエクスポートしたもの)")
    ap.add_argument("--since-ts", type=str, default="", help="この時刻より新しい行だけ処理（オプション）")
    args = ap.parse_args()

    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    known = read_known()  # {"data": {...}, "index": {...}}
    rows  = load_csv_rows(Path(args.csv_path), args.since_ts or None)

    # 取りこぼしゼロ：行×token（候補名）で1ファイルずつ必ず作る
    created = 0
    for row in rows:
        raw = row["app_name"]
        country = row.get("country", "") or "Global"
        names = tokenize_app_names(raw)
        if not names:
            continue

        for nm in names:
            key = normalize_key(nm)
            kid = known["index"].get(key, "")
            if kid and kid in (known["data"] or {}):
                data = compose_json_for_known(kid, known, country, nm)
                file_id = data["id"] if data.get("id") else kid
            else:
                data = compose_json_for_unknown(nm, country)
                file_id = data["id"]

            # ファイル名衝突も避ける（同一IDが同じRunに二度来たら末尾に -2, -3 を付与）
            out_path = PENDING_DIR / f"{file_id}.json"
            suffix = 2
            while out_path.exists():
                out_path = PENDING_DIR / f"{file_id}-{suffix}.json"
                suffix += 1

            with out_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            created += 1

    print(f"[intake] created json files: {created}")

if __name__ == "__main__":
    main()
