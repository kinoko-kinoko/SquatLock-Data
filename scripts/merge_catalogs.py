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
    except (FileNotFoundError, json.JSONDecodeError):
        all_apps = {"applications": []}
        print("Warning: all.json not found or is invalid. Starting with an empty list.", file=sys.stderr)

    all_apps_set = {app["id"] for app in all_apps.get("applications", [])}
    any_catalog_changed = False
    changed_countries = []

    # Iterate over country directories
    for country_code in sorted(os.listdir(INPUT_DIR)):
        country_dir = os.path.join(INPUT_DIR, country_code)
        if not os.path.isdir(country_dir):
            continue

        country_app_ids = set()
        # Find all json files in the country directory
        for filename in sorted(os.listdir(country_dir)):
            if not filename.endswith(".json"):
                continue

            file_path = os.path.join(country_dir, filename)
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                apps_list = []
                if isinstance(data, dict):
                    apps_list = data.get("applications", [])
                elif isinstance(data, list):
                    apps_list = data
                else:
                    print(f"Warning: Skipping {file_path} because it contains an unknown data structure.", file=sys.stderr)
                    continue

                if not isinstance(apps_list, list):
                    print(f"Warning: Skipping {file_path} because 'applications' key does not contain a list.", file=sys.stderr)
                    continue

                country_app_ids.update(
                    app["id"] for app in apps_list if isinstance(app, dict) and "id" in app
                )
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"Error reading {file_path}: {e}", file=sys.stderr)
                continue

        if not country_app_ids:
            print(f"No applications found for country {country_code}. Skipping.")
            continue

        # Merge with all_apps and create catalog
        merged_app_ids = all_apps_set.union(country_app_ids)
        merged_catalog = {
            "applications": [{"id": app_id} for app_id in sorted(list(merged_app_ids))]
        }

        output_filename = os.path.join(
            OUTPUT_DIR, f"catalog_{country_code.lower()}.json"
        )

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
            changed_countries.append(country_code.upper())
            with open(output_filename, "w") as f:
                json.dump(merged_catalog, f, indent=2)
            print(f"Generated catalog for {country_code.upper()} at {output_filename}")
        else:
            print(f"Catalog for {country_code.upper()} is already up to date.")

    # Set GitHub Actions output
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            print(f"changed={str(any_catalog_changed).lower()}", file=f)
            # Use comma separator for build_catalog_artifacts.mjs compatibility
            print(f"changed_countries={','.join(changed_countries)}", file=f)

    print(f"changed={str(any_catalog_changed).lower()}")
    print(f"changed_countries={','.join(changed_countries)}")


if __name__ == "__main__":
    main()
