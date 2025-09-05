#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AASA (apple-app-site-association) quick auditor.
- Input: one or more catalog_*.json (array of AppTemplate-like dicts)
- Output: CSV to stdout (app_id, app_name, url, status, host, sample_patterns)
- Features:
  * JSON pre-validation with error location
  * Per-file verbose header
  * Graceful network handling
  * Exit code 1 when arguments missing or JSON invalid
"""

import sys
import json
import csv
import os
import traceback
from typing import List, Dict, Any
import requests

TIMEOUT = 8  # seconds

def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)

def load_catalog(path: str) -> List[Dict[str, Any]]:
    """Load one catalog JSON (must be a list of dict)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as ex:
        eprint(f"[JSON ERROR] {path}: line {ex.lineno} col {ex.colno}: {ex.msg}")
        raise
    except FileNotFoundError:
        eprint(f"[FILE MISSING] {path}")
        raise

    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level must be an array (list)")

    # minimal field checks (soft)
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{i}]: each entry must be an object")
        # allow missing keys; we just coalesce later
    return data

def try_fetch_aasa(host: str) -> Dict[str, Any]:
    """
    Try to fetch AASA from typical paths.
    Returns dict with keys: ok(bool), status(str), patterns(str)
    """
    paths = [
        f"https://{host}/.well-known/apple-app-site-association",
        f"https://{host}/apple-app-site-association",
    ]
    headers = {"Accept": "application/json, */*"}
    for url in paths:
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT)
            if resp.status_code == 200 and resp.content:
                # Some AASA are JSON without content-type
                try:
                    j = resp.json()
                except json.JSONDecodeError:
                    # Some are JSON but served as plain text; try manual parse
                    try:
                        j = json.loads(resp.text)
                    except Exception:
                        return {"ok": False, "status": "200 but non-JSON", "patterns": ""}
                # Extract patterns roughly
                patterns = extract_patterns(j)
                return {"ok": True, "status": "OK", "patterns": patterns}
            elif resp.status_code in (301, 302, 307, 308):
                # follow handled by requests automatically; if here, no final JSON
                continue
            elif resp.status_code == 404:
                return {"ok": False, "status": "NO_PATHS", "patterns": ""}
            else:
                return {"ok": False, "status": f"HTTP_{resp.status_code}", "patterns": ""}
        except requests.exceptions.SSLError:
            return {"ok": False, "status": "SSL_ERROR", "patterns": ""}
        except requests.exceptions.Timeout:
            return {"ok": False, "status": "TIMEOUT", "patterns": ""}
        except Exception as ex:
            eprint(f"[AASA ERROR] host={host} url={url} ex={ex}")
            return {"ok": False, "status": "ERR", "patterns": ""}
    return {"ok": False, "status": "NO_AASA", "patterns": ""}

def extract_patterns(j: Dict[str, Any]) -> str:
    """
    Pull out allowed patterns for applinks. This is heuristic and safe.
    """
    try:
        details = j.get("applinks", {}).get("details", [])
        patterns = []
        for d in details:
            comps = d.get("components", [])
            if isinstance(comps, list):
                for c in comps:
                    if isinstance(c, dict):
                        path = c.get("/") or c.get("/*") or ""
                        if path:
                            patterns.append(path)
        return ";".join(patterns[:50])
    except Exception:
        return ""

def tokens_for_name(name: str) -> List[str]:
    """
    Produce some tokens (not used in this script but handy to have).
    """
    return [name.lower()]

def audit_catalog(data: List[Dict[str, Any]], writer: csv.writer, src_name: str):
    """
    Emit CSV rows for a catalog.
    """
    for it in data:
        app_id = (it.get("id") or "").strip()
        app_name = it.get("name") or ""
        # Prefer schemes first (we audit UL only, but they are part of context)
        uls = it.get("universalLinks") or []
        hosts = it.get("webHosts") or []
        # Coalesce: if uls present, derive hosts from them as fallback
        for u in uls:
            try:
                host = u.split("//", 1)[1].split("/", 1)[0]
                if host and host not in hosts:
                    hosts.append(host)
            except Exception:
                pass

        if not hosts:
            writer.writerow([app_id, app_name, "", "NO_HOST", "", ""])
            continue

        for h in hosts:
            res = try_fetch_aasa(h)
            # Choose a stable sample URL: first UL if any, else homepage
            sample_url = uls[0] if uls else f"https://{h}/"
            writer.writerow([
                app_id,
                app_name,
                sample_url,
                res["status"],
                h,
                res["patterns"]
            ])

def main():
    args = sys.argv[1:]
    if not args:
        eprint("Usage: aasa_audit.py catalog_*.json > ul_report.csv")
        sys.exit(1)

    writer = csv.writer(sys.stdout)
    # header
    writer.writerow(["app_id", "app_name", "url", "status", "host", "sample_patterns"])

    had_fatal = False

    for p in args:
        print(f"# {p}", file=sys.stderr)
        try:
            data = load_catalog(p)
        except Exception:
            had_fatal = True
            traceback.print_exc()
            continue

        try:
            audit_catalog(data, writer, os.path.basename(p))
        except Exception:
            had_fatal = True
            traceback.print_exc()
            continue

    sys.exit(1 if had_fatal else 0)

if __name__ == "__main__":
    main()
