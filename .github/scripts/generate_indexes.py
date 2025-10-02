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
    # 入力と出力のベースディレクトリ
    input_base_dir = 'data/manus'
    output_base_dir = 'dist'

    # 出力ディレクトリを作成
    output_indexes_dir = os.path.join(output_base_dir, 'indexes')
    os.makedirs(output_indexes_dir, exist_ok=True)

    # Gitのコミットハッシュを取得 (ワークフローから渡される)
    commit_hash = os.environ.get('GITHUB_SHA', 'unknown')

    # data/manus/<cc> を探索
    for country_code in os.listdir(input_base_dir):
        catalog_path = os.path.join(input_base_dir, country_code, f'catalog_{country_code}.json')
        if not os.path.isfile(catalog_path):
            continue

        print(f'Processing {catalog_path}...')

        with open(catalog_path, 'r', encoding='utf-8') as f:
            huge_catalog = json.load(f)

        entries = []
        for app in huge_catalog:
            app_id = app.get('id', '')
            if not app_id:
                continue

            # SHA1ハッシュからパスを生成
            sha1 = hashlib.sha1(app_id.encode('utf-8')).hexdigest()
            path = f"apps/{sha1[:2]}/{sha1[2:4]}/{app_id}.json"

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

        # indexファイルを書き出し
        output_index_path = os.path.join(output_indexes_dir, f'search_index_{country_code}.json')
        with open(output_index_path, 'w', encoding='utf-8') as f:
            json.dump(search_index, f, ensure_ascii=False, indent=2)
        print(f'Generated {output_index_path} with {len(entries)} entries.')

if __name__ == '__main__':
    main()