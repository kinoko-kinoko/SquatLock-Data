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
          # 出力（改行を含むので heredoc 形式で安全に書く）
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
          # （Python スクリプト部分は前回のままなので省略）
          PY

      - name: Commit changes on branch
        id: commit
        if: steps.build.outputs.changed != ''
        shell: bash
        run: |
          set -euo pipefail
          TS="$(date +'%Y%m%d-%H%M%S')"
          BR="chore/manus/${TS}"

          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          git checkout -b "$BR"
          git add catalog_*.json

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

            const pr = await github.rest.pulls.create({
              owner, repo,
              head: branch,
              base: 'main',
              title, body
            });

            try {
              await github.rest.issues.addLabels({
                owner, repo,
                issue_number: pr.data.number,
                labels: ['catalog','manus']
              });
            } catch (e) {}

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
