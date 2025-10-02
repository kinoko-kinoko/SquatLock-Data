import json
import hashlib
import os
import re
from datetime import datetime, timezone

# 検索用の正規化処理
def normalize_for_search(text):
    # 小文字化
    s = text.lower()
    # カタカナをひらがなに変換
    s = "".join([chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in s])
    # 記号、空白、長音記号を除去
    s = re.sub(r'[\s\W_ー]+', '', s)
    return s

def main():
    input_base_dir = 'data/manus'
    output_base_dir = 'dist'

    output_indexes_dir = os.path.join(output_base_dir, 'indexes')
    output_catalogs_dir = os.path.join(output_base_dir, 'catalogs')
    os.makedirs(output_indexes_dir, exist_ok=True)
    os.makedirs(output_catalogs_dir, exist_ok=True)

    commit_hash = os.environ.get('GITHUB_SHA', 'unknown')

    # Iterate over country directories (e.g., 'jp', 'us')
    for country_code in os.listdir(input_base_dir):
        country_dir = os.path.join(input_base_dir, country_code)
        if not os.path.isdir(country_dir):
            continue

        print(f'Processing directory {country_dir}...')

        # Merge all JSON files in the country directory
        merged_apps = {}
        for filename in sorted(os.listdir(country_dir)):
            if not filename.endswith('.json'):
                continue

            file_path = os.path.join(country_dir, filename)
            print(f'  - Reading {filename}')
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Handle both list and dict formats
                apps_list = data.get('applications', []) if isinstance(data, dict) else data

                for app in apps_list:
                    if isinstance(app, dict) and 'id' in app:
                        # Store the full app object, overwriting duplicates
                        merged_apps[app['id']] = app
            except (json.JSONDecodeError, IOError) as e:
                print(f'    - Warning: Could not read or parse {filename}. Error: {e}')
                continue

        if not merged_apps:
            print(f'No applications found for {country_code}. Skipping.')
            continue

        # Sort applications by ID for consistent output
        final_catalog = sorted(merged_apps.values(), key=lambda x: x['id'])

        # --- Generate and write the catalog file ---
        output_catalog_path = os.path.join(output_catalogs_dir, f'catalog_{country_code}.json')
        with open(output_catalog_path, 'w', encoding='utf-8') as f:
            json.dump(final_catalog, f, ensure_ascii=False, indent=2)
        print(f'Generated {output_catalog_path} with {len(final_catalog)} applications.')

        # --- Generate and write the search index file ---
        entries = []
        for app in final_catalog:
            app_id = app.get('id')
            if not app_id:
                continue

            sha1_hash = hashlib.sha1(app_id.encode('utf-8')).hexdigest()
            path = f"apps/{sha1_hash[:2]}/{sha1_hash[2:4]}/{app_id}.json"

            entry = {
                'id': app_id,
                'name_norm': normalize_for_search(app.get('name', '')),
                'aliases_norm': [normalize_for_search(alias) for alias in app.get('aliases', [])],
                'path': path
            }
            entries.append(entry)

        search_index = {
            'generatedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'version': commit_hash,
            'entries': entries
        }

        output_index_path = os.path.join(output_indexes_dir, f'search_index_{country_code}.json')
        with open(output_index_path, 'w', encoding='utf-8') as f:
            json.dump(search_index, f, ensure_ascii=False, indent=2)
        print(f'Generated {output_index_path} with {len(entries)} entries.')

if __name__ == '__main__':
    main()