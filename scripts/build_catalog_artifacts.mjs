// scripts/build_catalog_artifacts.mjs
// Node.js v20+
// Generates country-specific search indexes and app detail files.
// - Indexes are created at: indexes/search_index_{cc}.json
// - App details are created at: apps/{hash}/{hash}/{id}.json

import fs from "fs";
import path from "path";
import crypto from "crypto";

const ROOT = process.cwd();
const CATALOGS_DIR = path.join(ROOT, "catalogs");
const INDEXES_DIR = path.join(ROOT, "indexes");
const APPS_DIR = path.join(ROOT, "apps");

// --- Utility Functions ---
const readJSON = (p) => {
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf8"));
};
const writeJSON = (p, data) => {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 2) + "\n");
};
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
const asList = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

// Generates the relative path for an app detail file based on its ID.
const getAppDetailPath = (id) => {
  const h = sha1(id);
  return path.join("apps", h.slice(0, 2), h.slice(2, 4), `${encodeURIComponent(id)}.json`);
};

// --- Main Logic ---
async function main() {
  console.log("Starting build process for catalog artifacts...");

  // 1. Get the list of changed countries from the environment variable.
  const changedCountriesStr = process.env.CHANGED_COUNTRIES || "";
  if (!changedCountriesStr) {
    console.log("No changed countries specified. Exiting.");
    return;
  }
  // Handle both space- and comma-separated country codes, and filter out empty strings.
  const changedCountries = changedCountriesStr.trim().split(/[\s,]+/).filter(Boolean);
  console.log(`Processing catalogs for countries: ${changedCountries.join(", ")}`);

  // 2. Ensure base directories exist.
  fs.mkdirSync(INDEXES_DIR, { recursive: true });
  fs.mkdirSync(APPS_DIR, { recursive: true });

  // 3. Process each changed country.
  for (const cc of changedCountries) {
    console.log(`\n--- Building index for country: ${cc} ---`);

    // 4. Load the source catalog for the country.
    const lcc = cc.toLowerCase();
    const catalogPath = path.join(CATALOGS_DIR, `catalog_${lcc}.json`);
    const catalog = readJSON(catalogPath);
    if (!catalog || !Array.isArray(catalog.applications)) {
      console.warn(`Warning: Catalog for country '${cc}' not found or invalid. Skipping.`);
      continue;
    }
    const apps = catalog.applications;

    // 5. Load the existing index for the country, if it exists, to merge into it.
    const indexPath = path.join(INDEXES_DIR, `search_index_${lcc}.json`);
    const existingIndex = readJSON(indexPath);
    const indexEntriesById = new Map(
      (existingIndex?.entries ?? []).map((entry) => [entry.id, entry])
    );
    console.log(`Found ${indexEntriesById.size} existing entries in index for '${cc}'.`);

    // 6. Process each app in the catalog.
    for (const app of apps) {
      if (!app?.id) continue;

      // 6a. Generate app detail file if it doesn't exist.
      const appDetailPath = getAppDetailPath(app.id);
      const appDetailFullPath = path.join(ROOT, appDetailPath);
      if (!fs.existsSync(appDetailFullPath)) {
        console.log(`Creating new app detail file: ${appDetailPath}`);
        writeJSON(appDetailFullPath, app);
      }

      // 6b. Create or update the entry for the search index.
      const indexEntry = {
        id: app.id,
        name_norm: jpLite(app.name || app.id),
        aliases_norm: asList(app.aliases).map(jpLite),
        path: appDetailPath,
      };
      indexEntriesById.set(app.id, indexEntry);
    }

    // 7. Create and write the new index file for the country.
    const finalEntries = Array.from(indexEntriesById.values()).sort((a, b) =>
      a.id.localeCompare(b.id)
    );

    const indexFileContent = {
      generatedAt: new Date().toISOString(),
      version: sha1(JSON.stringify(finalEntries)),
      entries: finalEntries,
    };

    console.log(`Writing index for '${cc}' with ${finalEntries.length} entries to: ${indexPath}`);
    writeJSON(indexPath, indexFileContent);
  }

  console.log("\n✅ Done. All specified countries have been processed.");
}

main().catch((e) => {
  console.error("An unexpected error occurred:", e);
  process.exit(1);
});