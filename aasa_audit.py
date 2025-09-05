#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AASA (Universal Links) quick auditor
- catalog JSON は次のどちらのトップレベルにも対応します:
    1) [{...}, {...}]                             # 配列
    2) {"version": N, "apps": [{...}, {...}], ...}# ラップ付き
- 主要キー: id, name, schemes, universalLinks, webHosts, aliases, categories
- 成果物: CSV を stdout に出力（ワークフロー側で /tmp などへリダイレクト）
"""

from __future__ import annotations
import sys, json, csv, os, traceback
from typing import List, Dict, Any, Iterable, Tuple
import requests

# --------- 設定 ---------
DEFAULT_TIMEOUT = 8.0
AASA_PATH = "/.well-known/apple-app-site-association"

# --------- ユーティリティ ---------
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def load_catalog(path: str) -> List[Dict[str, Any]]:
    """
    ファイルを読み、トップレベルが list ならそのまま、
    dict なら apps キーのリストを取り出す。
    それ以外はエラー。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as ex:
        raise ValueError(f"JSON load failed in {path}: {ex}")

    if isinstance(data, list):
        apps = data
    elif isinstance(data, dict):
        # よくある {"version":1,"apps":[...]} 形式を許容
        if "apps" in data and isinstance(data["apps"], list):
            apps = data["apps"]
        else:
            raise ValueError(f"{path}: top-level must be a list OR an object that has list 'apps'")
    else:
        raise ValueError(f"{path}: unsupported top-level type ({type(data).__name__})")

    # 最低限の正規化
    norm: List[Dict[str, Any]] = []
    for i, raw in enumerate(apps):
        if not isinstance(raw, dict):
            eprint(f"[WARN] skip non-dict item in {path} index {i}")
            continue
        app = {
            "id": raw.get("id") or "",
            "name": raw.get("name") or "",
            "schemes": list(raw.get("schemes") or []),
            "universalLinks": list(raw.get("universalLinks") or []),
            "webHosts": list(raw.get("webHosts") or []),
            "aliases": list(raw.get("aliases") or []),
            "categories": list(raw.get("categories") or []),
        }
        # id / name が空の場合はスキップ
        if not app["id"] or not app["name"]:
            eprint(f"[WARN] skip app without id/name in {path} index {i}")
            continue
        norm.append(app)
    return norm

def fetch_aasa(host: str) -> Tuple[bool, Dict[str, Any] | None, str]:
    """AASA を取得して JSON 解析。成功/失敗と理由を返す。"""
    url = f"https://{host}{AASA_PATH}"
    try:
        r = requests.get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return False, None, f"HTTP {r.status_code}"
        text = r.text.strip()
        if not text:
            return False, None, "empty"
        try:
            # AASA は JSON か（稀に）バイナリ plist のこともあるが、ここは JSON のみ判定
            data = json.loads(text)
            return True, data, "OK"
        except Exception as ex:
            return False, None, f"JSON error: {ex}"
    except Exception as ex:
        # ネットワーク・名前解決など
        return False, None, f"EXC: {ex}"

def pick_sample_paths(aasa: Dict[str, Any]) -> List[str]:
    """
    AASA JSON から applinks の paths を軽く要約して CSV に入れるためのサンプルに整形。
    """
    samples: List[str] = []
    details = aasa.get("applinks", {}).get("details", [])
    if not isinstance(details, list):
        return samples
    for d in details:
        if not isinstance(d, dict):
            continue
        paths = d.get("paths")
        if isinstance(paths, list) and paths:
            # 長すぎないように頭 6 個まで
            samples.append(";".join(str(p) for p in paths[:6]))
    return samples

# --------- メイン監査処理 ---------
def audit_catalog(apps: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    各アプリにつき、代表 UL をチェックして CSV 行データを返す。
    """
    rows: List[Dict[str, str]] = []
    for app in apps:
        app_id = app.get("id", "")
        app_name = app.get("name", "")
        uls: List[str] = list(app.get("universalLinks") or [])
        hosts: List[str] = list(app.get("webHosts") or [])

        # UL -> host 推定（https://host/… 形式から host を抜く）
        for ul in uls:
            host = ""
            try:
                if ul.startswith("https://"):
                    host = ul[len("https://"):].split("/", 1)[0]
                elif ul.startswith("http://"):
                    host = ul[len("http://"):].split("/", 1)[0]
            except Exception:
                host = ""
            if host and host not in hosts:
                hosts.append(host)

        status = "NO_UL"
        sample = ""
        host_used = ""

        # チェック対象 host を走査（多すぎると時間がかかるので最大 4）
        for h in hosts[:4]:
            ok, aasa, reason = fetch_aasa(h)
            if not ok:
                eprint(f"[AASA ERROR] host={h} url=https://{h}{AASA_PATH} -> {reason}")
                continue
            paths = pick_sample_paths(aasa)
            status = "OK" if paths else "OK_NO_PATHS"
            sample = paths[0] if paths else ""
            host_used = h
            break

        rows.append({
            "app_id": app_id,
            "app_name": app_name,
            "url": (uls[0] if uls else ""),
            "status": status,
            "host": host_used,
            "sample_patterns": sample
        })
    return rows

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        eprint("Usage: aasa_audit.py <catalog1.json> [catalog2.json ...]")
        return 2

    all_apps: List[Dict[str, Any]] = []
    for p in argv[1:]:
        try:
            apps = load_catalog(p)
            print(f"# {os.path.basename(p)}", file=sys.stderr)
            all_apps.extend(apps)
        except Exception as ex:
            # どのファイルで失敗したか行番号付きで出す
            eprint(f"Traceback (most recent call last):")
            eprint(traceback.format_exc())
            eprint(f"JSON invalid in {p}: {ex}")
            return 1

    # 重複 id を簡易的に除外（先勝ち）
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for a in all_apps:
        aid = a.get("id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        deduped.append(a)

    # 監査して CSV を標準出力へ
    writer = csv.writer(sys.stdout)
    writer.writerow(["app_id", "app_name", "url", "status", "host", "sample_patterns"])
    for row in audit_catalog(deduped):
        writer.writerow([row["app_id"], row["app_name"], row["url"], row["status"], row["host"], row["sample_patterns"]])

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
