// scripts/build_catalog_artifacts.mjs
// Node.js v18+ / v20
// catalog_*.json（国別）から検索用 index と apps/{id}.json 群を生成し、gh-pages に公開する dist/ を作ります。
// 変更点: search_index.json の各 entry に "path" を追加（例: "apps/cb/e6/facebook.json"）

import fs from "fs";
import path from "path";
import crypto from "crypto";

const ROOT = process.cwd();

// catalog_*.json は catalogs/ 配下から探す
const DATA_DIRS = [path.join(ROOT, "catalogs")];

const DIST_DIR = path.join(ROOT, "dist");
const APPS_DIR = path.join(DIST_DIR, "apps");

// ---------------- Utilities ----------------
const readJSON = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const sha1 = (s) => crypto.createHash("sha1").update(s).digest("hex");

// 軽量正規化
const nfkc = (s) => String(s ?? "").normalize("NFKC");
const norm = (s) =>
  nfkc(s)
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();

// 日本語の軽量正規化（中黒・ダッシュ類・長音・~・_ を除去、全角空白→半角）
const jpLite = (s) => {
  const t = norm(s);
  return t
    // 中黒: ・(U+30FB), ･(U+FF65)
    .replace(/[\u30FB\uFF65]/gu, "")
    // ダッシュ類（\p{Pd} = Dash_Punctuation）+ 数学用マイナス U+2212 + 長音 U+30FC + ~ と _
    .replace(/[\p{Pd}\u2212\u2012\u2013\u2014\u2015\u30FC~_]/gu, "")
    // 全角スペースを通常スペースに
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

// id から apps パスを作る（相対パス）
const pathForId = (id) => {
  const h = sha1(id);
  const p = `apps/${h.slice(0, 2)}/${h.slice(2, 4)}/${encodeURIComponent(id)}.json`;
  return p;
};

// ---------------- Load catalogs ----------------
const CATALOGS_DIR = path.join(ROOT, "catalogs");
let catalogFiles = [];

if (!fs.existsSync(CATALOGS_DIR)) {
  console.error(`Error: The 'catalogs' directory was not found.`);
  process.exit(1);
}

try {
  catalogFiles = fs.readdirSync(CATALOGS_DIR)
    .filter(f => /^catalog_.*\.json$/i.test(f))
    .map(f => path.join(CATALOGS_DIR, f));
} catch (e) {
  console.error(`Error reading the 'catalogs' directory:`, e);
  process.exit(1);
}

// For debugging: show which files were found
console.log(`Found catalog files to process:`, catalogFiles);

if (catalogFiles.length === 0) {
  console.error("No catalog_*.json found under /data or repo root");
  process.exit(1);
}

const readCatalogArray = (p) => {
  const data = readJSON(p);
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object" && Array.isArray(data.apps)) return data.apps;
  return [];
};

// id -> merged app object
const byId = new Map();
let totalItems = 0;

for (const p of catalogFiles) {
  const items = readCatalogArray(p);
  totalItems += items.length;

  for (const app of items) {
    if (!app || typeof app !== "object") continue;
    const id = app.id;
    if (!id) continue;

    const cur = byId.get(id) ?? {};

    // 配列系はユニオン＋軽量正規化で重複排除
    const mergeStrArray = (a, b) => uniqStr([...(a || []), ...(b || [])]);

    const merged = {
      ...cur,
      ...app, // プリミティブは後勝ち
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

// ---------------- Build search_index.json ----------------
// 各 entry に "path"（相対パス）を追加
const entries = [];
for (const [id, app] of byId.entries()) {
  entries.push({
    id,
    name_norm: jpLite(app.name || id),
    aliases_norm: uniqStr(asList(app.aliases)).map(jpLite),
    path: pathForId(id), // ★ 追加: 直接 fetch に使える相対パス
  });
}

const indexObj = {
  generatedAt: new Date().toISOString(),
  version: sha1(JSON.stringify(entries).slice(0, 1_000_000)),
  entries,
};

// ---------------- Emit apps/{id}.json ----------------
fs.rmSync(DIST_DIR, { recursive: true, force: true });
fs.mkdirSync(APPS_DIR, { recursive: true });

for (const [id, app] of byId.entries()) {
  const rel = pathForId(id);
  const outPath = path.join(DIST_DIR, rel); // dist/apps/xx/yy/<id>.json
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(app, null, 2));
}

// ---------------- Emit search_index.json ----------------
fs.writeFileSync(
  path.join(DIST_DIR, "search_index.json"),
  JSON.stringify(indexObj, null, 2)
);

console.log(
  `Done. Wrote ${entries.length} index entries and ${byId.size} app files under ${path.relative(
    ROOT,
    DIST_DIR
  )}`
);
