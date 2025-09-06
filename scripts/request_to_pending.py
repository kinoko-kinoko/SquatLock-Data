#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv, json, os, re, sys, unicodedata
import urllib.parse, urllib.request

OUT_DIR = "pending/requests"
ITUNES_SEARCH = "https://itunes.apple.com/search?media=software&entity=software&limit=1&term={term}&country={country}"

GENRE_MAP = {
    "Games": ["game"],
    "Social Networking": ["social"],
    "Entertainment": ["video"],
    "Photo & Video": ["video"],
    "Music": ["music"],
    "Navigation": ["maps"],
    "Utilities": ["tool"],
    "News": ["news"]
}

def slugify(text: str) -> str:
    # ラテン化→小文字→英数以外をハイフン
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    if not t.strip(): t = text  # 日本語のみならそのままローマ字化なしで使う
    t = re.sub(r"[^\w]+", "-", t.lower()).strip("-")
    return t[:64] or "app"

def fetch_itunes(name: str, country: str) -> dict | None:
    q = urllib.parse.quote(name)
    url = ITUNES_SEARCH.format(term=q, country=country.lower())
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
            if data.get("resultCount", 0) > 0:
                return data["results"][0]
    except Exception:
        return None
    return None

def host_from(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return ""

def norm_ul(url: str) -> str:
    if not url: return ""
    u = url.strip()
    if not u: return ""
    u = re.sub(r"^http://", "https://", u)
    # ルートに寄せる（/pathが長い場合は切り戻す）
    p = urllib.parse.urlparse(u)
    return f"https://{p.netloc}/" if p.netloc else ""
    
def guess_categories(itunes: dict) -> list[str]:
    g = (itunes or {}).get("primaryGenreName") or ""
    return GENRE_MAP.get(g, [])

def make_entry(name: str, country: str) -> dict | None:
    it = fetch_itunes(name, country or "US")  # 国未指定→US
    entry_name = it.get("trackName") if it else name
    ul = ""
    host = ""
    # itunes の sellerUrl / websiteUrl / trackViewUrl からUL候補
    for key in ("sellerUrl", "websiteUrl"):
        v = (it or {}).get(key) or ""
        ul = norm_ul(v)
        if ul: break
    if not ul:
        # 最低限ホームに戻す（なければ空のまま）
        tv = (it or {}).get("trackViewUrl") or ""
        if tv and "apps.apple.com" in tv:
            ul = ""  # AppStoreはULにしない
    host = host_from(ul) if ul else ""
    cats = guess_categories(it)
    aliases = [name] if name != entry_name else []

    # id は slug（bundleIdが取れたらそれを優先スラグ化）
    base_id = (it or {}).get("bundleId") or entry_name
    idv = slugify(base_id)

    return {
        "id": idv,
        "name": entry_name,
        "symbol": "app.fill",
        "schemes": [],  # あなたがあとで追記
        "universalLinks": [ul] if ul else [],
        "webHosts": [host] if host else [],
        "aliases": aliases,
        "categories": cats,
        "meta": {
            "source": "user_request",
            "region_hint": [country.lower()] if country else [],
            "original_query": name
        }
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: request_to_pending.py requests/inbox.csv", file=sys.stderr)
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)
    created = 0
    with open(sys.argv[1], newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name: continue
            country = (row.get("country") or "US").strip()
            e = make_entry(name, country)
            if not e: continue
            fn = os.path.join(OUT_DIR, f"{e['id']}.json")
            with open(fn, "w", encoding="utf-8") as out:
                json.dump(e, out, ensure_ascii=False, indent=2)
            created += 1
            print(f"[pending] {fn}")
    print(f"created: {created}", file=sys.stderr)

if __name__ == "__main__":
    main()
