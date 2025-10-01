import json
import os
import sys

# Constants
INPUT_DIR = "data/manus"
OUTPUT_DIR = "catalogs"
ALL_APPS_FILE = os.path.join(INPUT_DIR, "all.json")


def main():
    """
    Merges individual country application lists with the main application list
    and outputs merged catalogs.
    """
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    try:
        with open(ALL_APPS_FILE, "r") as f:
            all_apps = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading all.json: {e}", file=sys.stderr)
        sys.exit(1)

    all_apps_set = {app["id"] for app in all_apps["applications"]}
    any_catalog_changed = False
    changed_countries = []

    for country in sorted(os.listdir(INPUT_DIR)):
        if not country.endswith(".json") or country == "all.json":
            continue

        country_code = os.path.splitext(country)[0].upper()
        output_filename = os.path.join(
            OUTPUT_DIR, f"catalog_{country_code.lower()}.json"
        )
        country_file_path = os.path.join(INPUT_DIR, country)

        try:
            with open(country_file_path, "r") as f:
                country_apps = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error reading {country_file_path}: {e}", file=sys.stderr)
            continue

        country_app_ids = {app["id"] for app in country_apps.get("applications", [])}
        merged_app_ids = all_apps_set.union(country_app_ids)
        
        merged_catalog = {
            "applications": [{"id": app_id} for app_id in sorted(list(merged_app_ids))]
        }

        # Check if the catalog has changed before writing
        needs_update = True
        if os.path.exists(output_filename):
            try:
                with open(output_filename, "r") as f:
                    existing_catalog = json.load(f)
                if existing_catalog == merged_catalog:
                    needs_update = False
            except (FileNotFoundError, json.JSONDecodeError):
                pass  # File is unreadable or doesn't exist, so we need to write it

        if needs_update:
            any_catalog_changed = True
            changed_countries.append(country_code)
            with open(output_filename, "w") as f:
                json.dump(merged_catalog, f, indent=2)
            print(f"Generated catalog for {country_code} at {output_filename}")
        else:
            print(f"Catalog for {country_code} is already up to date.")

    # Set GitHub Actions output
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            print(f"changed={str(any_catalog_changed).lower()}", file=f)
            print(f"changed_countries={' '.join(changed_countries)}", file=f)
    
    print(f"changed={str(any_catalog_changed).lower()}")
    print(f"changed_countries={' '.join(changed_countries)}")


if __name__ == "__main__":
    main()
