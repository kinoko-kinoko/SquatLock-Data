#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
User request intake -> pending JSON generator (stable ID + alias merge + external known_apps)

- Input: CSV (default: requests/inbox.csv) with headers like:
    "app_name", "country"
  * 見出しは多言語/改行でもゆるく検出（英/日/中/韓）

- Output: pending/requests/<stable_id>.json
  * 同じアプリ（Minecraft / マインクラフト / 我的世界 / 마인크래프트 など）は
    1つのIDに統合し、aliases に多言語名を統合
  * 既存ファイルがあればマージ（配列はユニーク化）
  * schemes は空欄（後で保守者が追記）
  * universalLinks / webHosts / symbol / categories は known_apps から提案（不明なら空）

使い方:
    python3 scripts/request_to_pending.py [requests/inbox.csv]

CI想定:
    - リポジトリ root で実行
    - 生成/更新ファイル: pending/requests/*.json
"""

from __future__ import annotations
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from urllib.parse import urlparse

# -------------------------------
# 設定
# -------------------------------
INBOX_DEFAULT = "requests/inbox.csv"
OUT_DIR = Path("pending/requests")
KNOWN_APPS_JSON = Path("data/known_apps.json")  # 外部辞書（任意・無ければ内蔵のみ）

# -------------------------------
# 内蔵の最小 known apps（外部JSONがあればマージで上書き）
# -------------------------------
KNOWN_APPS: Dict[str, Dict[str, Any]] = {
    "minecraft": {
        "aliases": ["Minecraft", "マインクラフト", "我的世界", "마인크래프트", "MC"],
        "symbol": "gamecontroller.fill",
        "schemes": [],
        "universalLinks": ["https://www.minecraft.net/"],
        "webHosts": ["minecraft.net"],
        "categories": ["game"],
    },
    "discord": {
        "aliases": ["Discord", "ディスコード"],
        "symbol": "bubble.left.and.bubble.right.fill",
        "schemes": [],
        "universalLinks": ["https://discord.com/"],
        "webHosts": ["discord.com"],
        "categories": ["social"],
    },
    "youtube": {
        "aliases": ["YouTube", "ユーチューブ", "油管", "유튜브"],
        "symbol": "play.rectangle.fill",
        "schemes": [],
        "universalLinks": ["https://www.youtube.com/"],
        "webHosts": ["youtube.com", "youtu.be"],
        "categories": ["video"],
    },
    "instagram": {
        "aliases": ["Instagram", "インスタグラム", "照片墙", "인스타그램", "IG"],
        "symbol": "camera.fill",
        "schemes": [],
        "universalLinks": ["https://www.instagram.com/"],
        "webHosts": ["instagram.com"],
        "categories": ["social"],
    },
    "tiktok": {
        "aliases": ["TikTok", "ティックトック", "抖音", "틱톡"],
        "symbol": "music.note",
        "schemes": [],
        "universalLinks": ["https://www.tiktok.com/"],
        "webHosts": ["tiktok.com"],
        "categories": ["video"],
    },
    "suika-game": {
        "aliases": ["スイカゲーム", "Suika", "Suika Game", "Watermelon Game"],
        "symbol": "gamecontroller.fill",
        "schemes": [],
        "universalLinks": [],
        "webHosts": [],
        "categories": ["game"],
    },
}

# -------------------------------
# ユーティリティ
# -------------------------------

def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def norm_key(s: str) -> str:
    """多言語文字の差異を吸収するための正規化キー
       - NFKC正規化（全角→半角等）
       - 小文字化
       - 空白除去
       - 記号除去（英数・アンダースコアのみ温存）
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\w]", "", s)
    return s

def slugify_ascii(s: str) -> str:
    """ASCII slug: 非ASCII除去 → 記号をハイフンに → 多重ハイフン圧縮 → trim/lower"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.strip()
    s = re.sub(r"[^\x00-\x7F]", "", s)      # 非ASCII削除（中国語/日本語/韓国語は空になり得る）
    s = re.sub(r"[^A-Za-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-").lower()
    return s

def to_unique_list(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        t = (it or "").strip()
        if not t:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def host_from_url(url: str) -> Optional[str]:
    try:
        host = urlparse(url).netloc
        return host or None
    except Exception:
        return None

# -------------------------------
# known_apps.json を読み込んで KNOWN_APPS を拡張
# -------------------------------

def load_known_apps_from_json(path: Path) -> Dict[str, Dict[str, Any]]:
    """data/known_apps.json を読み込み、id -> info の辞書に整形（無ければ空）"""
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        out: Dict[str, Dict[str, Any]] = {}
        for item in obj.get("apps", []):
            cid = item.get("id")
            if not cid:
                continue
            out[cid] = {
                "aliases": item.get("aliases", []),
                "schemes": item.get("schemes", []),
                "universalLinks": item.get("universalLinks", []),
                "webHosts": item.get("webHosts", []),
                "symbol": item.get("symbol", "app.fill"),
                "categories": item.get("categories", []),
            }
        return out
    except Exception as e:
        eprint("[known_apps] failed to load:", e)
        return {}

# -------------------------------
# CSV 見出しの多言語対応（ゆるく検出）
# -------------------------------

def detect_header_indexes(header: List[str]) -> Tuple[int, int]:
    """
    header から app_name / country の列位置を推定して返す
    - 英語/日本語/中国語/韓国語・改行入りでもOK
    """
    def contains(h: str, *needles: str) -> bool:
        H = (h or "").replace("\n", " ").replace("\r", " ").strip().lower()
        return any(n in H for n in needles)

    idx_name = -1
    idx_country = -1
    for i, h in enumerate(header):
        if idx_name < 0 and contains(
            h,
            "app", "name", "アプリ", "アプリ名", "应用", "应用名", "應用", "應用名",
            "앱", "앱이름", "이름", "example",
        ):
            idx_name = i
        if idx_country < 0 and contains(
            h,
            "country", "国", "国家", "國家", "국가", "지역",
        ):
            idx_country = i

    # フォールバック（列数が少ないケース）
    if idx_name < 0 and len(header) >= 1:
        idx_name = 0
    if idx_country < 0 and len(header) >= 2:
        idx_country = 1

    if idx_name < 0 or idx_country < 0:
        raise ValueError("Required columns not found. Check CSV headers for app_name / country.")

    return idx_name, idx_country

# -------------------------------
# 安定ID決定 + 既知DBとの照合
# -------------------------------

def decide_stable_id(app_name: str, known_apps: Dict[str, Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    1) known_apps の aliases に合致したらその canonical ID を返す
    2) スラグ（ASCII）が取れなければ md5 から安定IDを生成
    """
    nk = norm_key(app_name)

    for canonical_id, info in known_apps.items():
        for alias in info.get("aliases", []):
            if norm_key(alias) == nk:
                return canonical_id, info

    # 未知アプリ → slug or md5
    slug = slugify_ascii(app_name)
    if not slug:
        slug = "app-" + hashlib.md5(app_name.encode("utf-8")).hexdigest()[:12]
    return slug, None

def suggest_from_known(canonical_id: str, app_name: str, known_apps: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    既知DBを基に雛形を作成。未知なら汎用雛形。
    name は表示用：既知なら aliases[0]、未知は今回名
    """
    info = known_apps.get(canonical_id, None)
    if info:
        base_name = info["aliases"][0] if info.get("aliases") else app_name
        ul = info.get("universalLinks", []) or []
        hosts = [h for h in (host_from_url(u) for u in ul) if h]
        return {
            "id": canonical_id,
            "name": base_name,
            "symbol": info.get("symbol", "app.fill"),
            "schemes": info.get("schemes", [])[:],
            "universalLinks": ul[:],
            "webHosts": to_unique_list((info.get("webHosts", []) or []) + hosts),
            "aliases": to_unique_list(info.get("aliases", []) + [app_name]),
            "categories": info.get("categories", []),
            "source": {"country": "Global", "via": "intake"},
        }
    else:
        return {
            "id": canonical_id,
            "name": app_name,
            "symbol": "app.fill",
            "schemes": [],
            "universalLinks": [],
            "webHosts": [],
            "aliases": [app_name],
            "categories": [],
            "source": {"country": "Global", "via": "intake"},
        }

def merge_into(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """
    既存JSONに incoming をマージ（配列は和集合、source.country は履歴化）
    """
    out = dict(existing)

    # 配列項目は和集合
    for key in ["schemes", "universalLinks", "webHosts", "aliases", "categories"]:
        out[key] = to_unique_list(list(out.get(key, [])) + list(incoming.get(key, [])))

    # name / symbol は既存優先（人手で整えた値を尊重）
    out.setdefault("name", incoming.get("name", ""))
    out.setdefault("symbol", incoming.get("symbol", "app.fill"))

    # source: country を履歴化（country_list）
    src = dict(out.get("source", {}))
    countries: List[str] = []
    if "country_list" in src and isinstance(src["country_list"], list):
        countries.extend([str(x) for x in src["country_list"]])
    elif "country" in src and src["country"] and src["country"] != "Global":
        countries.append(str(src["country"]))
    inc_country = incoming.get("source", {}).get("country")
    if inc_country and inc_country != "Global":
        countries.append(str(inc_country))
    countries = to_unique_list(countries)
    if countries:
        src["country_list"] = countries
    src.setdefault("country", "Global")  # 互換用
    src["via"] = "intake"
    out["source"] = src

    # id は既存優先
    out["id"] = existing.get("id", incoming.get("id"))

    return out

# -------------------------------
# CSV 読み込み & 生成
# -------------------------------

def load_rows(csv_path: Path) -> List[Tuple[str, str]]:
    """
    CSVを読み込み、(app_name, country) のタプル配列に正規化。
    見出しは多言語対応で緩く検出。
    """
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return []

    header = rows[0]
    idx_name, idx_country = detect_header_indexes(header)
    data: List[Tuple[str, str]] = []
    for r in rows[1:]:
        if not r:
            continue
        app_name = (r[idx_name] if idx_name < len(r) else "").strip()
        country = (r[idx_country] if idx_country < len(r) else "").strip() or "Global"
        if app_name:
            data.append((app_name, country))
    return data

def generate_or_update(json_dir: Path, app_name: str, country: str, known_apps: Dict[str, Dict[str, Any]]) -> Path:
    """
    app_name/country から安定IDを算出し、既存JSONをマージして保存。
    """
    canonical_id, _ = decide_stable_id(app_name, known_apps)
    out_path = json_dir / f"{canonical_id}.json"

    # 雛形作成（known → known優先）
    base = suggest_from_known(canonical_id, app_name, known_apps)
    # 入力名は必ず aliases に含める
    base["aliases"] = to_unique_list(base.get("aliases", []) + [app_name])
    # country（今回分）
    base["source"]["country"] = country

    # 既存マージ
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        merged = merge_into(existing, base)
    else:
        merged = base

    # universalLinks から webHosts を補完（足りないもののみ）
    extra_hosts = [h for h in (host_from_url(u) for u in merged.get("universalLinks", [])) if h]
    merged["webHosts"] = to_unique_list(list(merged.get("webHosts", [])) + extra_hosts)

    # 保存
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path

# -------------------------------
# メイン
# -------------------------------

def main(argv: List[str]) -> int:
    inbox = Path(argv[1]) if len(argv) >= 2 else Path(INBOX_DEFAULT)

    if not inbox.exists():
        eprint(f"[intake] CSV not found: {inbox}")
        return 0

    # 外部 known_apps を読み込み（あれば内蔵にマージ）
    external_known = load_known_apps_from_json(KNOWN_APPS_JSON)
    if external_known:
        for k, v in external_known.items():
            KNOWN_APPS[k] = v
        print(f"[known_apps] loaded external: {len(external_known)} entries")

    ensure_dir(OUT_DIR)

    rows = load_rows(inbox)
    if not rows:
        eprint("[intake] no data rows.")
        return 0

    created_or_updated = 0
    touched_files: List[str] = []

    print(f"[intake] CSV: {inbox}")
    print(f"[intake] rows: {len(rows)}")

    for app_name, country in rows:
        p = generate_or_update(OUT_DIR, app_name, country, KNOWN_APPS)
        touched_files.append(str(p))
        created_or_updated += 1
        print(f"[create] {p.name}  name='{app_name}'  country='{country}'")

    # 生成物一覧
    print("== files in pending/requests ==")
    total = 0
    for fp in sorted(OUT_DIR.glob("*.json")):
        print(" -", fp.name)
        total += 1
    print("total", total)

    print(f"created_or_updated: {created_or_updated}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
