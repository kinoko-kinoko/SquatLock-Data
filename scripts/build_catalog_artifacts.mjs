name: Manus merge (all countries → root catalogs via PR)

on:
  push:
    paths:
      - 'data/manus/**/*.json'
      - 'data/manus/*.json'
      - 'catalog_*.json'
  workflow_dispatch: {}

permissions:
  contents: write
  pull-requests: write
  pages: write

jobs:
  merge:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.x'

      - name: List files to pass into Python
        id: list_files
        shell: bash
        run: |
          set -e
          # manus 配下の json をすべて拾う（ネスト/フラット両対応）
          mapfile -t FILES < <(find data/manus -type f -name '*.json' | sort)
          # GITHUB_OUTPUT にだけ流す（files.txt は作らない）
          {
            echo 'files<<EOF'
            printf '%s\n' "${FILES[@]}"
            echo 'EOF'
          } >> "$GITHUB_OUTPUT"

      - name: Build merged catalogs (root/catalog_<cc>.json)
        id: build
        shell: bash
        env:
          MANUS_FILE_LIST: ${{ steps.list_files.outputs.files }}
        run: |
          set -euo pipefail

          python <<'PY'
          import json, os, re
          from pathlib import Path
          from collections import defaultdict
          root = Path('.')
          flist = (os.getenv('MANUS_FILE_LIST') or '').splitlines()
          files = [Path(p) for p in flist if p.strip()]
          if not files:
              with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as g:
                  g.write('changed<<EOF\n\nEOF\n')
              raise SystemExit(0)

          RE_CC_FILE = re.compile(r'(?:^|/)manus_([a-z]{2})_\d{8}\.json$', re.I)

          def as_list(v):
              if v is None: return []
              if isinstance(v, list): return v
              return [v]

          def dedup_keep_order(seq):
              s, out = set(), []
              for x in seq:
                  if x not in s:
                      s.add(x); out.append(x)
              return out

          def load_json(path: Path):
              with path.open('r', encoding='utf-8') as f:
                  return json.load(f)

          def load_catalog_list(path: Path):
              if not path.exists(): return [], 1
              try:
                  data = load_json(path)
              except Exception:
                  return [], 1
              if isinstance(data, dict) and 'apps' in data:
                  ver = int(data.get('version', 1))
                  apps = data.get('apps') or []
                  if not isinstance(apps, list): apps = []
                  return apps, ver
              elif isinstance(data, list):
                  return data, 1
              else:
                  return [], 1

          def dump_catalog(path: Path, apps, version: int = 1):
              tmp = path.with_suffix(path.suffix + '.tmp')
              with tmp.open('w', encoding='utf-8') as f:
                  json.dump({'version': version, 'apps': apps}, f, ensure_ascii=False, indent=2)
                  f.write('\n')
              tmp.replace(path)

          incoming = defaultdict(list)
          for p in files:
              s = str(p).replace('\\', '/')
              m = RE_CC_FILE.search(s)
              if m:
                  cc = m.group(1).lower()
              else:
                  parts = Path(s).parts
                  try:
                      i = parts.index('manus')
                      cc = parts[i+1].lower() if len(parts) > i+1 and len(parts[i+1]) == 2 else None
                  except ValueError:
                      cc = None
              if not cc: continue

              try:
                  data = load_json(p)
              except Exception as e:
                  print(f"[warn] skip {p}: {e}")
                  continue

              if isinstance(data, dict) and 'apps' in data:
                  items = data.get('apps') or []
              elif isinstance(data, dict):
                  items = [data]
              elif isinstance(data, list):
                  items = data
              else:
                  items = []

              normed = []
              for it in items:
                  if not isinstance(it, dict): continue
                  it = it.copy()
                  _id = it.get('id') or it.get('name')
                  if not _id: continue
                  it['id'] = str(_id).strip()
                  it['name'] = str(it.get('name') or it['id']).strip()
                  it['symbol'] = it.get('symbol') or 'app.fill'
                  def clean_list(key):
                      return [x.strip() for x in as_list(it.get(key)) if isinstance(x, str) and x.strip()]
                  it['schemes']        = dedup_keep_order(clean_list('schemes'))
                  it['universalLinks'] = dedup_keep_order(clean_list('universalLinks'))
                  it['webHosts']       = dedup_keep_order(clean_list('webHosts'))
                  it['aliases']        = dedup_keep_order(clean_list('aliases'))
                  it['categories']     = dedup_keep_order(clean_list('categories'))

                  src = it.get('source') or {}
                  if not isinstance(src, dict): src = {}
                  src['country'] = src.get('country') or cc.upper()
                  via = as_list(src.get('via')); via.append('manus')
                  src['via'] = dedup_keep_order(via)
                  it['source'] = src

                  normed.append(it)

              if normed:
                  incoming[cc].extend(normed)

          changed_cc = []
          for cc, new_items in incoming.items():
              out_path = root / f"catalog_{cc}.json"
              existing, ver = load_catalog_list(out_path)
              by_id = {it['id']: it for it in existing if isinstance(it, dict) and it.get('id')}
              for it in new_items:
                  _id = it['id']
                  if _id in by_id:
                      cur = by_id[_id].copy()
                      for k in ('name', 'symbol'):
                          if it.get(k): cur[k] = it[k]
                      def uni(k):
                          cur[k] = sorted(set(as_list(cur.get(k)) + as_list(it.get(k))))
                      for k in ('schemes','universalLinks','webHosts','aliases','categories'):
                          uni(k)
                      cur_src = cur.get('source') or {}
                      it_src  = it.get('source') or {}
                      new_src = {
                          'country': cur_src.get('country') or it_src.get('country'),
                          'via': sorted(set(as_list(cur_src.get('via')) + as_list(it_src.get('via'))))
                      }
                      cur['source'] = new_src
                      by_id[_id] = cur
                  else:
                      by_id[_id] = it
              merged = sorted(by_id.values(), key=lambda x: x.get('id',''))
              dump_catalog(out_path, merged, version=ver)
              changed_cc.append(cc)

          outval = "\n".join(sorted(set(changed_cc)))
          with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as g:
              g.write(f"changed<<EOF\n{outval}\nEOF\n")
          PY

      - name: Commit changes on branch
        id: commit
        if: steps.build.outputs.changed != ''
        shell: bash
        run: |
          set -euo pipefail
          # 念のため不要ファイルを削除
          rm -f files.txt || true

          TS="$(date +'%Y%m%d-%H%M%S')"
          BR="chore/manus/${TS}"

          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          git checkout -b "$BR"
          git add catalog_*.json || true

          # 変更が無ければスキップ
          if git diff --cached --quiet; then
            echo "No catalog changes; skip commit."
            echo "branch=" >> "$GITHUB_OUTPUT"
            exit 0
          fi

          CHANGED="${{ steps.build.outputs.changed }}"
          SUMMARY="$(echo "$CHANGED" | tr '\n' ' ')"
          git commit -m "chore(manus): merge drops into catalogs (${TS}) [${SUMMARY}]"
          git push -u origin "$BR"

          echo "branch=$BR" >> "$GITHUB_OUTPUT"

      - name: Open PR (label:manus, catalog; comment:squash)
        if: steps.commit.outputs.branch != ''
        uses: actions/github-script@v7
        with:
          github-token: ${{ github.token }}
          script: |
            const branch = '${{ steps.commit.outputs.branch }}';
            const owner = context.repo.owner;
            const repo  = context.repo.repo;
            const changed = `${{ steps.build.outputs.changed }}`.split('\n').filter(Boolean);
            const title = `chore(manus): merge drops into catalogs (${new Date().toISOString().slice(0,10)})`;
            const body  = [
              'Manus の出力を各国カタログへ自動マージしました。',
              '',
              `更新対象: ${changed.length ? changed.join(', ') : '-'}`,
              '',
              '— 置き場: `data/manus/**/manus_<cc>_YYYYMMDD.json`（フラットでもOK）',
              '— 既存項目にも安全に統合（配列はユニオン、`source.via` に `manus` 付与）',
              '',
              '🟢 マージ方法: **Squash and merge** を選んでください（履歴が日付単位でまとまります）'
            ].join('\n');
            await github.rest.pulls.create({ owner, repo, head: branch, base: 'main', title, body });

  publish_artifacts:
    runs-on: ubuntu-latest
    needs: [merge]
    permissions:
      contents: write
      pages: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Build catalog artifacts (search_index + apps/{id}.json)
        run: node scripts/build_catalog_artifacts.mjs

      - name: Publish to gh-pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: dist
          publish_branch: gh-pages
          keep_files: false
          commit_message: "chore: publish catalog artifacts"
