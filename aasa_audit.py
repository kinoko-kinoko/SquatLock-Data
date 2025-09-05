#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AASA / Universal Link 監査ツール
- 入力: catalog_*.json を複数（配列のアプリ定義）
- 出力: CSV (app_id, app_name, url, status, host, sample_patterns)
強化点:
  1) JSON の事前バリデーション（構文エラー時に行/列を表示）
  2) スキーマバリデーション（最低限の必須キー/型をチェック、欠けは警告の上スキップ）
  3) 例外時は詳細トレースバックを標準エラーに出力
"""

import csv
import json
import sys
import os
import ssl
import urllib.request
import urllib.error
import traceback
import logging
from typing import Dict, Any, List, Tuple, Optional

# ------- ログ設定 -------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("aasa_audit")

# ------- AASA 取得 -------

def fetch_aasa(host: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """AASA を 2 箇所（/.well-known と /）から順に取得してパース"""
    paths = [
        f"https://{host}/.well-known/apple-app-site-association",
        f"https://{host}/apple-app-site-association",
    ]
    ctx = ssl.create_default_context()
    for url in paths:
        try:
            with urllib.request.urlopen(url, context=ctx, timeout=10) as resp:
                data = resp.read()
                # AASA は JSON or UTF-8テキスト(JSON)
                try:
                    aasa = json.loads(data.decode("utf-8"))
                except Exception:
                    # 場合によっては application/json 以外で来ることがあるので再挑戦
                    try:
                        aasa = json.loads(data.decode("utf-8", errors="ignore"))
                    except Exception:
                        continue
                return ("OK", aasa)
        except urllib.error.HTTPError as e:
            # 404 などは継続
            logger.debug("HTTPError %s for %s", e.code, url)
        except Exception as e:
            logger.debug("Fetch error for %s: %s", url, e)
    return ("NG", None)

def summarize_aasa_paths(aasa: Dict[str, Any]) -> str:
    """CSV の sample_patterns 用に、許可パスのざっくり概要を作成"""
    try:
        details = []
        applinks = aasa.get("applinks", {})
        details_default = applinks.get("details", []) or []
        for d in details_default:
            appids = d.get("appIDs") or d.get("appids") or []
            components = d.get("components") or []
            paths = d.get("paths") or []
            if components:
                # components を簡略化
                sample = ";".join(
                    [str(c.get(""/**/"" , c)) if isinstance(c, dict) else str(c) for c in components]
                )
                details.append(sample)
            elif paths:
                details.append(";".join(paths))
            elif appids:
                details.append(";".join(appids))
        return (";".join(details))[:2000]  # 長すぎると CSV が重いので丸め
    except Exception:
        return ""

# ------- カタログ読み込み & バリデーション -------

REQUIRED_FIELDS = {
    "id": str,
    "name": str,
    "symbol": str,
    "schemes": list,          # 0本でもOK（空配列）
    "universalLinks": list,   # 同上
    "webHosts": list,         # 同上
    "aliases": list,          # 同上
    "categories": list,       # 同上
}

def load_one_catalog(path: str) -> List[Dict[str, Any]]:
    """1ファイル読み込み + 構文/型チェック。壊れていたら場所を表示して例外。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        data = json.loads(content)
    except json.JSONDecodeError as e:
        # 行列を明示
        raise RuntimeError(f"JSON syntax error in {path}: line {e.lineno}, column {e.colno}: {e.msg}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to read {path}: {e}") from e

    if not isinstance(data, list):
        raise RuntimeError(f"{path}: root must be a JSON array")

    valid: List[Dict[str, Any]] = []
    for i, app in enumerate(data, start=1):
        if not isinstance(app, dict):
            logger.warning("%s: #%d entry is not an object, skipped", path, i)
            continue
        ok = True
        for k, typ in REQUIRED_FIELDS.items():
            if k not in app:
                logger.warning("%s: #%d missing key '%s' -> skipped", path, i, k)
                ok = False
                break
            if not isinstance(app[k], typ):
                logger.warning("%s: #%d '%s' must be %s -> skipped", path, i, k, typ.__name__)
                ok = False
                break
        if ok:
            valid.append(app)
    return valid

def load_catalogs(paths: List[str]) -> List[Dict[str, Any]]:
    """複数ファイルを結合（id 重複は後勝ちで上書き）"""
    bag: Dict[str, Dict[str, Any]] = {}
    for p in paths:
        try:
            apps = load_one_catalog(p)
            for a in apps:
                bag[a["id"]] = a
            logger.info("loaded %s apps from %s (after validation)", len(apps), p)
        except Exception as e:
            logger.error("%s", e)
            # 続行（壊れたファイルがあっても他は見たい）
            logger.debug("traceback:\n%s", traceback.format_exc())
    merged = list(bag.values())
    logger.info("total merged apps: %d", len(merged))
    return merged

# ------- 監査（スキーム優先・なければ UL） -------

def pick_open_url(app: Dict[str, Any]) -> Tuple[str, str]:
    """
    アプリ 1 件に対し、まず URLスキームを、なければ UL を 1 本返す。
    戻り値: (url, host)  host は UL のホスト or スキームのホスト相当（CSV用）
    """
    schemes: List[str] = app.get("schemes") or []
    uls: List[str] = app.get("universalLinks") or []
    hosts: List[str] = app.get("webHosts") or []

    if schemes:
        u = schemes[0]
        return (u, (hosts[0] if hosts else ""))

    if uls:
        u = uls[0]
        try:
            host = u.split("//", 1)[1].split("/", 1)[0]
        except Exception:
            host = hosts[0] if hosts else ""
        return (u, host)

    # 何もない場合は空を返す（CSVには NG として記録）
    return ("", (hosts[0] if hosts else ""))

# ------- メイン（CSV 出力） -------

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: aasa_audit.py <catalog1.json> [catalog2.json ...]", file=sys.stderr)
        return 2

    # 例外はキャッチして詳細トレースバックを出す
    try:
        catalogs = [p for p in argv[1:] if os.path.exists(p)]
        if not catalogs:
            print("No existing catalog files supplied.", file=sys.stderr)
            return 2

        apps = load_catalogs(catalogs)

        writer = csv.writer(sys.stdout)
        writer.writerow(["app_id", "app_name", "url", "status", "host", "sample_patterns"])

        for app in apps:
            url, host = pick_open_url(app)
            app_id = app.get("id", "")
            app_name = app.get("name", "")
            if url.startswith("http"):   # UL
                status, aasa = fetch_aasa(host) if host else ("NG", None)
                sample = summarize_aasa_paths(aasa) if aasa else ""
                writer.writerow([app_id, app_name, url, status, host, sample])
            elif url:                    # スキーム
                # スキームは canOpenURL を CI では検証できないので “OK(未検証)” 相当で記録
                writer.writerow([app_id, app_name, url, "SCHEME_ONLY", host, ""])
            else:
                writer.writerow([app_id, app_name, "", "NO_URL", host, ""])

        return 0

    except Exception as e:
        # 失敗時は詳細トレースバックを出力し、非0で終了
        logger.error("Fatal error: %s", e)
        logger.error("traceback:\n%s", traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv))
