import sys, json, csv, os, requests

def audit_catalog(file_path):
    country = os.path.basename(file_path).replace("catalog_", "").replace(".json", "")
    with open(file_path, encoding="utf-8") as f:
        catalog = json.load(f)
    results = []
    for app in catalog:
        app_id = app.get("id")
        name = app.get("name")
        schemes = app.get("schemes", [])
        uls = app.get("universalLinks", [])
        status = "NO_SCHEME" if not schemes else "UNKNOWN"
        # ここで実際の canOpenURL / AASA 判定を呼ぶ（既存処理を流用）
        results.append({
            "country": country,
            "id": app_id,
            "name": name,
            "schemes": ";".join(schemes),
            "universalLinks": ";".join(uls),
            "status": status
        })
    return results

def main():
    files = sys.argv[1:]
    all_results = []
    for f in files:
        all_results.extend(audit_catalog(f))

    with open("ul_report.csv", "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["country", "id", "name", "schemes", "universalLinks", "status"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

if __name__ == "__main__":
    main()
