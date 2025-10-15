# merge_dvc_json.py
import os
import json
import glob

INPUT_DIR = "dvc_json"
OUTPUT_FILE = "Full_STEM_DataBase.json"

def main():
    combined = []

    for path in sorted(glob.glob(os.path.join(INPUT_DIR, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️ Skipping {path}: {e}")
            continue

        if isinstance(data, list):
            combined.extend(data)
        elif isinstance(data, dict):
            # If your per-file JSON is an object, we just append it.
            # (Change to combined.extend(data["whatever"]) if you store arrays under a key.)
            combined.append(data)
        else:
            print(f"⚠️ {path} has unsupported top-level type: {type(data).__name__}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        json.dump(combined, out, ensure_ascii=False, indent=2)

    print(f"✅ Wrote {len(combined)} records to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()