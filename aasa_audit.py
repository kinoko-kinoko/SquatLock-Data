#!/usr/bin/env python3
# aasa_audit.py
import json, re, sys, urllib.parse, urllib.request, ssl
from pathlib import Path
from collections import defaultdict

# --- Simple glob matcher for AASA path patterns ---
# AASA supports "*", "?" wildcards and "!" for negation patterns.
def glob_match(pattern, path):
    neg = pattern.startswith("!")
    pat = pattern[1:] if neg else pattern
    # Ensure leading slash matching like Apple's docs
    if not pat.startswith("/"):
        pat = "/" + pat
    # Convert to regex
    pat = re.escape(pat).replace(r"\*", ".*").replace(r"\?", ".")
    regex = re.compile("^" + pat + "$")
    ok = bool(regex.match(path))
    return (not ok) if neg else ok

def aasa_fetch(domain):
    urls = [
        f"https://{domain}/.well-known/apple-app-site-association",
        f"https://{domain}/apple-app-site-association",
    ]
    ctx = ssl.create_default_context()
    for u in urls:
        try:
            with urllib.request.urlopen(u, context=ctx, timeout=8) as r:
                raw = r.read()
                # Some servers send AASA without content-type; parse as JSON
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    # Some sites may return JSON without UTF-8 BOM, try latin-1 fallback
                    try:
                        return json.loads(raw.decode("latin-1"))
                    except Exception:
                        return None
        except Exception:
            continue
    return None

def load_catalog(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # support both wrapped and plain array formats
    apps = data["apps"] if isinstance(data, dict) and "apps" in data else data
    return apps

def normalize_host(url):
    u = urllib.parse.urlparse(url)
    host = (u.netloc or u.path).lower()
    return host.replace("www.", "")

def path_of(url):
    u = urllib.parse.urlparse(url)
    return u.path if u.path else "/"

def audit_ul_file(catalog_path):
    apps = load_catalog(catalog_path)
    results = []
    aasa_cache = {}

    for app in apps:
        uls = app.get("universalLinks") or []
        for ul in uls:
            host = normalize_host(ul)
            p = path_of(ul)
            if not host:
                results.append((app.get("id"), app.get("name"), ul, "INVALID_HOST", "", ""))
                continue
            if host not in aasa_cache:
                aasa_cache[host] = aasa_fetch(host)
            aasa = aasa_cache[host]
            if not aasa or "applinks" not in aasa or "details" not in aasa["applinks"]:
                results.append((app.get("id"), app.get("name"), ul, "NO_AASA", host, ""))
                continue

            # Flatten all paths across details entries
            patterns = []
            for det in aasa["applinks"]["details"]:
                for pat in det.get("paths", []):
                    patterns.append(pat)

            if not patterns:
                results.append((app.get("id"), app.get("name"), ul, "NO_PATHS", host, ""))
                continue

            # AASA evaluation: allow if at least one positive pattern matches AND no negation excludes it.
            allowed = False
            negations = [pat for pat in patterns if pat.startswith("!")]
            positives = [pat for pat in patterns if not pat.startswith("!")]

            pos_ok = any(glob_match(pat, p) for pat in positives) if positives else False
            neg_hit = any(glob_match(pat, p) for pat in negations) if negations else False
            allowed = pos_ok and not neg_hit

            results.append((app.get("id"), app.get("name"), ul, "OK" if allowed else "NG", host, ";".join(patterns[:10])))

    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: aasa_audit.py catalog_global.json [catalog_jp.json ...]")
        sys.exit(1)
    all_results = []
    for path in sys.argv[1:]:
        res = audit_ul_file(path)
        print(f"# {path}")
        print("app_id,app_name,url,status,host,sample_patterns")
        for row in res:
            print(",".join('"' + (str(col).replace('"','""')) + '"' for col in row))
        all_results.extend(res)

if __name__ == "__main__":
    main()