// Node.js v18+ / v20 で動作（外部依存なし）
import fs from "fs";
import path from "path";
import crypto from "crypto";

const ROOT = process.cwd();
const DATA_DIR = path.join(ROOT, "data");
const DIST_DIR = path.join(ROOT, "dist");
const APPS_DIR = path.join(DIST_DIR, "apps");

// ===== ユーティリティ =====
const readJSON = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const sha1 = (s) => crypto.createHash("sha1").update(s).digest("hex");
const nfkc = (s) => s.normalize("NFKC");
const norm = (s) =>
  nfkc(String(s || ""))
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();

// （軽めの日本語ゆれ吸収：中黒/ハイフン類・長音の一部を削る）
// ※ クライアント側も同じ正規化で検索してください
const jpLite = (s) =>
  norm(s).replace(/[・･‐--—―ー〜~\-_\u30fc]/g, "").replace(/[　]/g, " ");

const uniqBy = (arr, keyFn) => {
  const seen = new Set();
  const out = [];
  for (const x of arr) {
    const k = keyFn(x);
    if (!seen.has(k)) {
      seen.add(k);
      out.push(x);
    }
  }
  return out;
};

const uniqStr = (arr) => {
  const seen = new Set();
  const out = [];
  for (const s of arr || []) {
    const k = jpLite(s);
    if (k && !seen.has(k)) {
      seen.add(k);
      out.push(s);
    }
  }
  return out;
};

// ===== 1) カタログ読込（国別すべて） =====
const catalogFiles = fs
  .readdirSync(DATA_DIR)
  .filter((f) => /^catalog_.*\.json$/i.test(f));

if (catalogFiles.length === 0) {
  console.error("No catalog_*.json found under /data");
  process.exit(1);
}

// id -> 統合オブジェクト（配列はユニオン）
const byId = new Map();

for (const file of catalogFiles) {
  const p = path.join(DATA_DIR, file);
  const arr = readJSON(p);
  for (const app of arr) {
    const id = app?.id;
    if (!id) continue;
    const cur = byId.get(id) || {};
    // 配列はユニオン・重複排除
    const mergeArr = (a, b) => uniqStr([...(a || []), ...(b || [])]);
    const merged = {
      ...cur,
      ...app, // プリミティブは後勝ち（基本同一想定）
      aliases: mergeArr(cur.aliases, app.aliases),
      variants: mergeArr(cur.variants, app.variants),
      schemes: mergeArr(cur.schemes, app.schemes),
      universalLinks: mergeArr(cur.universalLinks, app.universalLinks),
      webHosts: mergeArr(cur.webHosts, app.webHosts),
      categories: mergeArr(cur.categories, app.categories),
    };
    byId.set(id, merged);
  }
}

// ===== 2) search_index.json を構築 =====
const entries = [];
for (const [id, app] of byId.entries()) {
  const nameNorm = jpLite(app.name || id);
  const aliasNorms = uniqStr(app.aliases || []).map(jpLite);
  entries.push({ id, name_norm: nameNorm, aliases_norm: aliasNorms });
}
const indexObj = {
  generatedAt: new Date().toISOString(),
  version: sha1(JSON.stringify(entries).slice(0, 1_000_000)), // 軽量ハッシュ
  entries,
};

// ===== 3) apps/{id}.json を出力 =====
fs.rmSync(DIST_DIR, { recursive: true, force: true });
fs.mkdirSync(APPS_DIR, { recursive: true });

// ファイルパスは sha1 で2階層に分散 + idはURLエンコードで衝突回避
for (const [id, app] of byId.entries()) {
  const h = sha1(id);
  const p1 = h.slice(0, 2);
  const p2 = h.slice(2, 4);
  const dir = path.join(APPS_DIR, p1, p2);
  fs.mkdirSync(dir, { recursive: true });
  const fn = encodeURIComponent(id) + ".json";
  fs.writeFileSync(path.join(dir, fn), JSON.stringify(app, null, 2));
}

// ===== 4) search_index.json を保存 =====
fs.writeFileSync(
  path.join(DIST_DIR, "search_index.json"),
  JSON.stringify(indexObj, null, 2)
);

// 参考：TOP100は catalog_global.json からアプリ同梱用にビルド時取り込み
console.log(
  `Done. apps/* and search_index.json written to ${path.relative(
    ROOT,
    DIST_DIR
  )}`
);
