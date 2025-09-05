#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AASA audit helper:
- 複数の catalog_*.json を受け取り、universalLinks を AASA で監査
- JSON を事前バリデーション（行番号つきエラー）
- 実行時エラーはトレースバックを出力
- CSV は stdout に出力（GitHub Actions 側で /tmp/ul_report.csv にリダイレクト）
- 1つの CSV に統合し、ファイル境界は "# ./filename" コメント行で示す

出力カラム:
  app_id, app_name, region, url, status, host, sample_patterns
status 例:
  OK            : UL 到達OK（HTTP 2xx/3xx）
  NO_AASA       : AASA が見つからない
  NO_PATHS      : AASA はあるが paths が無い
  URL_FAIL_xxx  : UL がHTTP的に失敗（xxxはHTTPコードまたはerror）
"""

import sys
import json
import csv
import os
import traceback
from typing import Any, Dict, List, Optional, Tuple
import requests
from urllib.parse import urlparse

# --------- HTTP 共通設定 ----------
UA = "SquatLock-AASA-Audit/1.0 (+https://github.com/kinoko-kinoko/SquatLock-Data)"
TIMEOUT = 7
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

# --------- JSON ローダ（行番号付きバリデーション） ----------
def load_catalog(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON invalid in {path}: line {e.lineno}, col {e.colno} → {e.msg}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"[ERROR] file not found: {path}", file=sys.stderr)
        sys.exit(1)

    # 形式: 1) [ {id,name,...}, ... ]  または  2) {"apps":[...]}
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict) and "apps" in data and isinstance(data["apps"], list):
        arr = data["apps"]
    else:
        print(f"[WARN] {path}: unknown catalog shape, skip.", file=sys.stderr)
        arr = []

    # 最低限の型チェック
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(arr, 1):
        if not isinstance(item, dict):
            print(f"[WARN] {path} #{i}: not an object, skip.", file=sys.stderr)
            continue
        out.append(item)
    return out

# --------- AASA 取得 ----------
def fetch_aasa(host: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    試行順:
      https://{host}/.well-known/apple-app-site-association
      https://{host}/apple-app-site-association
      （失敗時は http にもフォールバック）
    戻り値: (aasa_json or None, reason)
      reason は "OK" or "NO_AASA" or "HTTP_xxx" など
    """
    paths = [
        f"https://{host}/.well-known/apple-app-site-association",
        f"https://{host}/apple-app-site-association",
        f"http://{host}/.well-known/apple-app-site-association",
        f"http://{host}/apple-app-site-association",
    ]
    for url in paths:
        try:
            r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                # JSON or バイナリJSON（ほぼJSON）
                try:
                    return r.json(), "OK"
                except Exception:
                    # JSONじゃない場合もある（署名付きなど）→ 文字列として解析試行
                    try:
                        return json.loads(r.text), "OK"
                    except Exception:
                        return None, "NO_AASA"
            # 404等は 続行
        except requests.RequestException:
            continue
    return None, "NO_AASA"

# --------- AASA から paths サンプル抽出 ----------
def extract_paths_from_aasa(aasa: Dict[str, Any]) -> List[str]:
    # 仕様上は applinks.details[].paths に入ることが多い
    details = (
        aasa.get("applinks", {}).get("details")
        if isinstance(aasa, dict) else None
    )
    samples: List[str] = []
    if isinstance(details, list):
        for d in details:
            if not isinstance(d, dict):
                continue
            paths = d.get("paths")
            if isinstance(paths, list):
                for p in paths:
                    if isinstance(p, str):
                        samples.append(p)
    return samples

# --------- URL 到達チェック ----------
def check_url(url: str) -> Tuple[bool, str]:
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if 200 <= r.status_code < 400:
            return True, f"{r.status_code}"
        return False, f"HTTP_{r.status_code}"
    except requests.RequestException as e:
        return False, f"ERR_{type(e).__name__}"

# --------- 監査メイン ----------
def audit_universal_link(app: Dict[str, Any], region: str, url: str) -> Tuple[str, str, str]:
    """
    戻り値: (status, host, sample_patterns)
    """
    parsed = urlparse(url)
    host = parsed.netloc or ""
    if not host:
        return ("URL_FAIL_NOHOST", "", "")

    aasa, reason = fetch_aasa(host)
    samples: List[str] = []
    if aasa:
        samples = extract_paths_from_aasa(aasa)

    ok, url_result = check_url(url)

    if ok:
        status = "OK"
    else:
        if aasa is None and reason == "NO_AASA":
            status = "NO_AASA"
        elif aasa is not None and not samples:
            status = "NO_PATHS"
        else:
            status = f"URL_FAIL_{url_result}"

    sample_str = ";".join(samples[:50])  # 長すぎる場合は適当に打ち切り
    return status, host, sample_str

def guess_region_from_filename(path: str) -> str:
    base = os.path.basename(path)
    if base.startswith("catalog_") and base.endswith(".json"):
        return base[len("catalog_"):-len(".json")]
    return "unknown"

# --------- エントリ ----------
def main():
    try:
        files = sys.argv[1:]
        if not files:
            print("[ERROR] No catalog files specified", file=sys.stderr)
            sys.exit(1)

        writer = csv.writer(sys.stdout)
        header_written = False

        for path in files:
            apps = load_catalog(path)
            region = guess_region_from_filename(path)

            # ファイル境界をコメントで示す（GitHub上での目印）
            print(f"# ./{os.path.basename(path)}", flush=True)

            if not header_written:
                writer.writerow(["app_id", "app_name", "region", "url", "status", "host", "sample_patterns"])
                header_written = True

            for app in apps:
                app_id = str(app.get("id", "") or "")
                app_name = str(app.get("name", "") or "")

                uls = app.get("universalLinks") or app.get("universallinks") or []
                if not isinstance(uls, list):
                    uls = []

                if not uls:
                    # ULなしなら1行も出さない（カタログによってはスキップでOK）
                    continue

                for url in uls:
                    if not isinstance(url, str) or not url.strip():
                        continue
                    status, host, sample = audit_universal_link(app, region, url.strip())
                    writer.writerow([app_id, app_name, region, url.strip(), status, host, sample])

    except Exception:
        # 予期しないエラーはトレースバックを出して失敗終了
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
