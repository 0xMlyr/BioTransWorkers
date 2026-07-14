#!/usr/bin/env python3
"""
将 aafc_glossary.json 转换为 Cloudflare KV 导入格式 aafc_glossary_for_kv.json
"""

import os
import sys
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(SCRIPT_DIR, "aafc_glossary.json")
TARGET_FILE = os.path.join(SCRIPT_DIR, "aafc_glossary_for_kv.json")

METADATA = {
    "source": "ISBN 0-660-14933-8 aafc_hym_of_the_world 1894",
    "ver": "1.0.0",
    "date": "20260715",
}


def main():
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        source = json.load(f)

    entries = source.get("entries", [])
    print(f"Input:  {len(entries)} entries from {SOURCE_FILE}")

    output = []
    for entry in entries:
        term = entry.get("term", "")
        if not term:
            continue

        detailed = {}
        for field in ("variants", "definition", "source_page"):
            val = entry.get(field)
            if val is not None and val != "":
                detailed[field] = val

        output.append({
            "key": term,
            "value": {
                "data": [
                    {
                        "metadata": dict(METADATA),
                        "detailed": detailed,
                    }
                ]
            },
        })

    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Output: {len(output)} entries -> {TARGET_FILE}")
    print(f"Metadata: source={METADATA['source']}, date={METADATA['date']}")


if __name__ == "__main__":
    main()
