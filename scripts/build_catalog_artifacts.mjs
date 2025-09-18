// scripts/build_catalog_artifacts.mjs
// Node.js v18+ / v20
// catalog_*.json（国別）から検索用 index と apps/{id}.json 群を生成し、dist/ に出力します。

import fs from "fs";
import path from "path";
import crypto from "crypto";

const ROOT = process.cwd();

// catalog_*.json は data/ 配下にも、リポジトリ直下にも置ける前提で両方探す
const DATA_DIRS = [path.join(ROOT, "data"), ROOT];

const DIST_DIR = path.join(ROOT, "dist");
const APPS_DIR = path.join(DIST_DIR, "apps");

// ---------------- Utilities ----------------
const readJSON = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const sha1 = (s) => crypto.createHash("sha1").update(s).digest("hex");

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

// 安全に配列化
const asList = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

// ---------------- Load catalogs ----------------
let catalogFiles = [];
for (const dir of DATA_DIRS) {
  if (!fs.existsSync(dir)) continue;
  const files = fs
    .readdirSync(dir)
    .filter((f) => /^catalog_.*\.json$/i.test(f))
    .map((f) => path.join(dir, f));
  catalogFiles = catalogFiles.concat(files);
}

if (catalogFiles.length === 0) {
  console.error("No catalog_*.json found under /data or repo root");
  process.exit(1);
}

// id -> merged app object
const byId = new Map();

for (const p of catalogFiles) {
  const arr = readJSON(p);
  if (!Array.isArray(arr)) continue;

  for (const app of arr) {
    if (!app || typeof app !== "object") continue;
    const id = app.id;
    if (!id) continue;

    const cur = byId.get(id) ?? {};

    // 配列系はユニオン＋軽量正規化で重複排除
    const mergeStrArray = (a, b) => uniqStr([...(a || []), ...(b || [])]);

    const merged = {
      ...cur,
      ...app, // プリミティブは後勝ち（基本同一想定）
      aliases: mergeStrArray(cur.aliases, app.aliases),
      variants: mergeStrArray(cur.variants, app.variants),
      schemes: mergeStrArray(cur.schemes, app.schemes),
      universalLinks: mergeStrArray(cur.universalLinks, app.universalLinks),
      webHosts: mergeStrArray(cur.webHosts, app.webHosts),
      categories: mergeStrArray(cur.categories, app.categories),
    };

    // name は念のため文字列化＆trim
    if (merged.name == null || merged.name === "") {
      merged.name = String(id);
    } else {
      merged.name = String(merged.name).trim();
    }

    byId.set(id, merged);
  }
}

// ---------------- Build search_index.json ----------------
const entries = [];
for (const [id, app] of byId.entries()) {
  const nameNorm = jpLite(app.name || id);
  const aliasNorms = uniqStr(asList(app.aliases)).map(jpLite);
  entries.push({ id, name_norm: nameNorm, aliases_norm: aliasNorms });
}

// version は entries の内容から計算（軽量化のため先頭一部をハッシュ）
const indexObj = {
  generatedAt: new Date().toISOString(),
  version: sha1(JSON.stringify(entries).slice(0, 1_000_000)),
  entries,
};

// ---------------- Emit apps/{id}.json ----------------
fs.rmSync(DIST_DIR, { recursive: true, force: true });
fs.mkdirSync(APPS_DIR, { recursive: true });

// シャーディング: sha1(id) の先頭2桁/次2桁で分散、ファイル名は encodeURIComponent(id).json
for (const [id, app] of byId.entries()) {
  const h = sha1(id);
  const dir = path.join(APPS_DIR, h.slice(0, 2), h.slice(2, 4));
  fs.mkdirSync(dir, { recursive: true });
  const fn = encodeURIComponent(id) + ".json";
  fs.writeFileSync(path.join(dir, fn), JSON.stringify(app, null, 2));
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
