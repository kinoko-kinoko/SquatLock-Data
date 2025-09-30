import json
import os
import re
from pathlib import Path
from collections import defaultdict

# --- Setup ---
ROOT = Path('.')
MANUS_DIR = ROOT / 'data' / 'manus'
CATALOGS_DIR = ROOT / 'catalogs'

# --- Helper Functions ---
def as_list(v):
    if v is None: return []
    if isinstance(v, list): return v
    return [v]

def dedup_keep_order(seq):
    s, out = set(), []
    for x in seq:
        if x not in s:
            s.add(x)
            out.append(x)
    return out

def load_json(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)

def load_catalog_list(path: Path):
    if not path.exists(): return [], 1
    try:
        data = load_json(path)
        if isinstance(data, list):
            return data, 1 # Assuming version 1 for simple lists
        # Handle the case where the catalog is a dictionary with an 'apps' key
        if isinstance(data, dict) and 'apps' in data:
            apps = data.get('apps') or []
            return (apps, data.get('version', 1)) if isinstance(apps, list) else ([], 1)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read or parse catalog file at {path}: {e}")
    return [], 1


def dump_catalog(path: Path, apps, version: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    # The output format is a simple list of apps, not a versioned dictionary.
    with path.open('w', encoding='utf-8') as f:
        json.dump(apps, f, ensure_ascii=False, indent=2)
        f.write('\n')

# --- Main Logic ---
def main():
    # 1. Find unprocessed files
    all_files = MANUS_DIR.glob('**/*.json')
    files_to_process = sorted([p for p in all_files if '_processed' not in p.parts])

    if not files_to_process:
        print("No new manus files to process.")
        with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a', encoding='utf-8') as g:
            g.write('changed=false\n')
            g.write('changed_countries=\n')
        return

    print(f"Found {len(files_to_process)} new files to process.")
    
    # 2. Group new files by country code
    incoming_data = defaultdict(list)
    processed_files_map = defaultdict(list)
    RE_CC_FILE = re.compile(r'manus_([a-z]{2})_\d{8}\.json$', re.I)

    for p in files_to_process:
        s = str(p)
        m = RE_CC_FILE.search(s)
        cc = None
        if m:
            cc = m.group(1).lower()
        else:
            try:
                # Fallback: find country code from directory structure like `manus/jp/...`
                i = p.parts.index('manus')
                if len(p.parts) > i + 1 and len(p.parts[i+1]) == 2:
                    cc = p.parts[i+1].lower()
            except (ValueError, IndexError):
                pass

        if not cc:
            print(f"[warn] Could not determine country code for {p}. Skipping.")
            continue

        try:
            data = load_json(p)
        except Exception as e:
            print(f"[warn] Failed to load JSON from {p}: {e}. Skipping.")
            continue

        items = data.get('apps', []) if isinstance(data, dict) else data if isinstance(data, list) else [data] if isinstance(data, dict) else []

        # 3. Normalize each app item
        normed_items = []
        for it in items:
            if not isinstance(it, dict): continue
            it_copy = it.copy()
            _id = it_copy.get('id') or it_copy.get('name')
            if not _id: continue

            it_copy['id'] = str(_id).strip()
            it_copy['name'] = str(it_copy.get('name') or it_copy['id']).strip()

            for key, default in [('schemes', []), ('universalLinks', []), ('webHosts', []), ('aliases', []), ('categories', [])]:
                it_copy[key] = dedup_keep_order([str(x).strip() for x in as_list(it_copy.get(key)) if str(x).strip()])

            src = it_copy.get('source') or {}
            if not isinstance(src, dict): src = {}
            src['country'] = src.get('country') or cc.upper()
            via = as_list(src.get('via')); via.append('manus')
            src['via'] = dedup_keep_order(via)
            it_copy['source'] = src
            normed_items.append(it_copy)

        if normed_items:
            incoming_data[cc].extend(normed_items)
            processed_files_map[cc].append(p)

    # 4. Merge data into main catalogs
    changed_countries = []
    for cc, new_items in incoming_data.items():
        out_path = CATALOGS_DIR / f"catalog_{cc}.json"
        existing_apps, ver = load_catalog_list(out_path)
        apps_by_id = {app['id']: app for app in existing_apps if isinstance(app, dict) and app.get('id')}

        for item in new_items:
            item_id = item['id']
            if item_id in apps_by_id: # Merge with existing
                current_app = apps_by_id[item_id]
                for key in ('name', 'symbol'):
                    if item.get(key): current_app[key] = item[key]
                for key in ('schemes', 'universalLinks', 'webHosts', 'aliases', 'categories'):
                    current_app[key] = sorted(list(set((current_app.get(key) or []) + (item.get(key) or []))))

                cur_src = current_app.get('source', {})
                it_src = item.get('source', {})
                cur_src['via'] = sorted(list(set(as_list(cur_src.get('via')) + as_list(it_src.get('via')))))
                current_app['source'] = cur_src
            else: # Add new
                apps_by_id[item_id] = item

        if new_items:
            merged_apps = sorted(list(apps_by_id.values()), key=lambda x: x['id'])
            dump_catalog(out_path, merged_apps, version=ver)
            changed_countries.append(cc)
            print(f"Updated catalog for {cc} at {out_path} with {len(new_items)} new/updated items.")

            # 5. Move processed files for this country
            for p in processed_files_map[cc]:
                processed_dir = p.parent / '_processed'
                processed_dir.mkdir(parents=True, exist_ok=True)
                try:
                    p.rename(processed_dir / p.name)
                    print(f"Moved {p.name} to {processed_dir}")
                except Exception as e:
                    print(f"[error] Failed to move {p}: {e}")

    # 6. Output result to GitHub Actions
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a', encoding='utf-8') as g:
        if changed_countries:
            changed_countries_str = ",".join(sorted(list(set(changed_countries))))
            g.write('changed=true\n')
            g.write(f'changed_countries={changed_countries_str}\n')
        else:
            g.write('changed=false\n')
            g.write('changed_countries=\n')

if __name__ == "__main__":
    main()