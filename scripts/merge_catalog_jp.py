#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, re, shutil, sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog_jp.json"
INBOX_DIR = ROOT / "data" / "manus" / "jp"
PROCESSED_DIR = INBOX_DIR / "_processed"
REPORT = ROOT / "reports" / "merge_jp_summary.txt"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
REPORT.parent.mkdir(parents=True, exist_ok=True)

def slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:64] or "app"

def ensure_list(x):
    if x is None: return []
    if isinstance(x, list): return x
    return [x]

def uniq(seq):
    out, seen = [], set()
    for x in seq:
        if isinstance(x, str): k = x.strip()
        else: k = x
        if not k: continue
        if k not in seen:
            out.append(k)
            seen.add(k)
    return out

def host_from_url(u: str) -> str:
    try:
        h = urlparse(u).netloc.lower().strip()
        return h.lstrip("www.") if h else ""
    except Exception:
        return ""

def normalize_app(app: dict) -> dict:
    a = dict(app or {})
    # fields
    a["id"] = (a.get("id") or "").strip()
    a["name"] = (a.get("name") or "").strip()
    a["symbol"] = (a.get("symbol") or "app.fill").strip()

    a["schemes"] = uniq([s.strip() for s in ensure_list(a.get("schemes")) if isinstance(s, str)])
    a["universalLinks"] = uniq([u.strip() for u in ensure_list(a.get("universalLinks")) if isinstance(u, str)])
    a["webHosts"] = uniq([h.strip().lower() for h in ensure_list(a.get("webHosts")) if isinstance(h, str)])

    # derive hosts from ULs
    ul_hosts = [host_from_url(u) for u in a["universalLinks"]]
    a["webHosts"] = uniq(a["webHosts"] + [h for h in ul_hosts if h])

    a["aliases"] = uniq([s.strip() for s in ensure_list(a.get("aliases")) if isinstance(s, str)])
    if a["name"] and a["name"] not in a["aliases"]:
        a["aliases"].append(a["name"])

    a["categories"] = uniq([c.strip().lower() for c in ensure_list(a.get("categories")) if isinstance(c, str)])

    src = dict(a.get("source") or {})
    src["via"] = "manus" if not src.get("via") else src.get("via")
    src["country"] = src.get("country") or "Japan (日本)"
    a["source"] = src

    if not a["id"]:
        a["id"] = slug(a["name"] or (a["webHosts"][0] if a["webHosts"] else "app"))

    return a

def load_json(path: Path):
    if not path.exists(): return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def index_apps(apps):
    by_id, by_name, by_alias, by_host = {}, {}, {}, {}
    for a in apps:
        aid = a.get("id"); 
        if aid: by_id[aid] = a
        nm = (a.get("name") or "").strip().lower()
        if nm: by_name.setdefault(nm, []).append(a)
        for al in a.get("aliases", []):
            al = (al or "").strip().lower()
            if al: by_alias.setdefault(al, []).append(a)
        for h in a.get("webHosts", []):
            h = (h or "").strip().lower()
            if h: by_host.setdefault(h, []).append(a)
    return by_id, by_name, by_alias, by_host

def find_match(a, idx):
    aid = a["id"]
    if aid and aid in idx[0]: 
        return idx[0][aid]
    nm = a["name"].lower()
    if nm in idx[1]: 
        return idx[1][nm][0]
    for al in a["aliases"]:
        key = al.lower()
        if key in idx[2]:
            return idx[2][key][0]
    for h in a["webHosts"]:
        key = h.lower()
        if key in idx[3]:
            return idx[3][key][0]
    return None

def merge_one(dst, src):
    # lists: union
    for k in ["schemes","universalLinks","webHosts","aliases","categories"]:
        dst[k] = uniq(ensure_list(dst.get(k)) + ensure_list(src.get(k)))
    # symbol: 既存優先
    if not dst.get("symbol"): dst["symbol"] = src.get("symbol") or "app.fill"
    # source: via に manus を記録
    dsrc = dict(dst.get("source") or {})
    ssrc = dict(src.get("source") or {})
    if dsrc.get("via") != "manus" and ssrc.get("via") == "manus":
        dsrc["via"] = "manus"
    if not dsrc.get("country") and ssrc.get("country"):
        dsrc["country"] = ssrc["country"]
    dst["source"] = dsrc
    # name 編集はしない（変えると破壊的）。異綴りは aliases に入るので十分。
    return dst

def process():
    changed = False
    summary = []
    base = load_json(CATALOG)
    base = [normalize_app(a) for a in base]
    idx = index_apps(base)

    inbox = sorted(INBOX_DIR.glob("*.json"))
    if not inbox:
        REPORT.write_text("No Manus files found.\n", encoding="utf-8")
        return

    added_cnt, merged_cnt = 0, 0

    for p in inbox:
        try:
            raw = load_json(p)
            # ファイルが { "apps": [...] } の形でも配列でも両対応
            apps = raw.get("apps") if isinstance(raw, dict) else raw
            for a in apps or []:
                na = normalize_app(a)
                m = find_match(na, idx)
                if m:
                    merge_one(m, na)
                    merged_cnt += 1
                else:
                    base.append(na)
                    # index にも反映
                    base[-1] = normalize_app(base[-1])
                    idx = index_apps(base)
                    added_cnt += 1
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            shutil.move(str(p), str(PROCESSED_DIR / f"{p.stem}.{ts}.json"))
        except Exception as e:
            summary.append(f"[ERROR] {p.name}: {e}")

    # id で安定ソート
    base.sort(key=lambda x: (x.get("id") or "").lower())
    save_json(CATALOG, base)
    changed = True

    summary.insert(0, f"Added: {added_cnt}, Merged: {merged_cnt}")
    REPORT.write_text("\n".join(summary) + "\n", encoding="utf-8")

if __name__ == "__main__":
    process()
