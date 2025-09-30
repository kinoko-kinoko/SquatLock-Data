// scripts/build_catalog_artifacts.mjs
// Node.js v18+ / v20
// catalogs/catalog_*.json（国別）から検索用 index と apps/{id}.json 群を生成します。

import fs from "fs";
import path from "path";
import crypto from "crypto";

const ROOT = process.cwd();
const CATALOGS_DIR = path.join(ROOT, "catalogs");
const DIST_DIR = path.join(ROOT, "dist");
const APPS_DIR = path.join(DIST_DIR, "apps");

// --- ユーティリティ関数 ---
const readJSON = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const sha1 = (s) => crypto.createHash("sha1").update(s).digest("hex");
const nfkc = (s) => String(s ?? "").normalize("NFKC");
const norm = (s) => nfkc(s).toLowerCase().replace(/\s+/g, " ").trim();
const jpLite = (s) => {
  const t = norm(s);
  return t
    .replace(/[\u30FB\uFF65]/gu, "")
    .replace(/[\p{Pd}\u2212\u2012\u2013\u2014\u2015\u30FC~_]/gu, "")
    .replace(/[　]/g, " ");
};
const uniqByKey = (arr, keyFn) => {
  const seen = new Set();
  const out = [];
  for (const v of arr ?? []) {
    const k = keyFn(v);
    if (k && !seen.has(k)) {
      seen.add(k);
      out.push(v);
    }
  }
  return out;
};
const uniqStr = (arr) => uniqByKey(arr, (s) => jpLite(s));
const asList = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);
const pathForId = (id) => {
  const h = sha1(id);
  return `apps/${h.slice(0, 2)}/${h.slice(2, 4)}/${encodeURIComponent(id)}.json`;
};
const readCatalogArray = (p) => {
  try {
    const data = readJSON(p);
    if (Array.isArray(data)) {
      return data;
    }
    console.warn(`Warning: Catalog file is not a JSON Array, skipping. path=${p}`);
    return [];
  } catch (e) {
    console.error(`Error reading or parsing JSON file at ${p}:`, e);
    return [];
  }
};

// --- メイン処理 ---
async function main() {
  console.log("Starting build process for catalog artifacts...");

  // 1. カタログファイルを catalogs/ ディレクトリから読み込む
  if (!fs.existsSync(CATALOGS_DIR)) {
    console.error(`Error: The 'catalogs' directory was not found.`);
    process.exit(1);
  }
  let catalogFiles = [];
  try {
    catalogFiles = fs.readdirSync(CATALOGS_DIR)
      .filter(f => /^catalog_.*\.json$/i.test(f))
      .map(f => path.join(CATALOGS_DIR, f));
  } catch (e) {
    console.error(`Error reading the 'catalogs' directory:`, e);
    process.exit(1);
  }

  if (catalogFiles.length === 0) {
    console.error("Error: No 'catalog_*.json' files were found in the 'catalogs' directory.");
    process.exit(1);
  }
  console.log(`Found catalog files to process:`, catalogFiles);

  // 2. 全てのカタログをマージする
  const byId = new Map();
  let totalItems = 0;

  for (const p of catalogFiles) {
    const items = readCatalogArray(p);
    totalItems += items.length;
    for (const app of items) {
      if (!app || typeof app !== "object" || !app.id) continue;
      const id = app.id;
      const cur = byId.get(id) ?? {};
      const mergeStrArray = (a, b) => uniqStr([...(a || []), ...(b || [])]);
      const merged = {
        ...cur, ...app,
        aliases: mergeStrArray(cur.aliases, app.aliases),
        variants: mergeStrArray(cur.variants, app.variants),
        schemes: mergeStrArray(cur.schemes, app.schemes),
        universalLinks: mergeStrArray(cur.universalLinks, app.universalLinks),
        webHosts: mergeStrArray(cur.webHosts, app.webHosts),
        categories: mergeStrArray(cur.categories, app.categories),
      };
      merged.name = merged.name ? String(merged.name).trim() : String(id);
      byId.set(id, merged);
    }
  }
  console.log(`Merged ${byId.size} unique apps from ${totalItems} items.`);

  // 3. 検索インデックス (search_index.json) を作成する
  const entries = [];
  for (const [id, app] of byId.entries()) {
    entries.push({
      id,
      name_norm: jpLite(app.name || id),
      aliases_norm: uniqStr(asList(app.aliases)).map(jpLite),
      path: pathForId(id),
    });
  }

  const entriesString = JSON.stringify(entries);
  const indexObj = {
    generatedAt: new Date().toISOString(),
    version: sha1(entriesString.slice(0, 1_000_000)),
    entries,
  };

  // 4. dist/ ディレクトリを準備し、成果物を出力する
  fs.rmSync(DIST_DIR, { recursive: true, force: true });
  fs.mkdirSync(APPS_DIR, { recursive: true });

  // 4a. 個別のアプリファイル (apps/{id}.json) を出力
  for (const [id, app] of byId.entries()) {
    const rel = pathForId(id);
    const outPath = path.join(DIST_DIR, rel);
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, JSON.stringify(app, null, 2));
  }

  // 4b. 検索インデックスファイル (search_index.json) を出力
  fs.writeFileSync(
    path.join(DIST_DIR, "search_index.json"),
    JSON.stringify(indexObj, null, 2)
  );

  console.log(
    `✅ Done. Wrote ${entries.length} index entries and ${byId.size} app files under ${path.relative(ROOT, DIST_DIR)}`
  );
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
