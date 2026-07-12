#!/usr/bin/env python3
"""
将 hao_dsv4.txt 转换为 _for_kv.json 格式

用法:
    cd glossary/terms/hao_expand_202607
    python build_kv.py
"""

import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, "hao_dsv4.txt")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "hao_expand_for_kv.json")

METADATA = {
    "source": "hao_core_expand_dsv4",
    "ver": "1.0.0",
    "date": "20260713",
}


def parse_entry(block: str) -> dict | None:
    """解析单个条目块，返回 {key, translation, phonetic} 或 None"""
    fields = {}
    for line in block.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(NAME|ZH|PHONETC):(.+)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip()

    name = fields.get("NAME")
    if not name:
        return None

    return {
        "key": name,
        "translation": fields.get("ZH", ""),
        "phonetic": fields.get("PHONETC", ""),
    }


def build_kv_json():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 按空行分割条目
    blocks = re.split(r"\n\s*\n", content.strip())

    entries = []
    seen_keys: set[str] = set()
    skipped = 0

    for block in blocks:
        parsed = parse_entry(block)
        if parsed is None:
            skipped += 1
            continue

        key = parsed["key"]
        if key in seen_keys:
            print(f"[WARN] Duplicate key skipped: {key}")
            skipped += 1
            continue
        seen_keys.add(key)

        entries.append({
            "key": key,
            "value": {
                "data": [
                    {
                        "metadata": METADATA,
                        "detailed": {
                            "translation": parsed["translation"],
                            "phonetic": parsed["phonetic"],
                        },
                    }
                ]
            },
        })

    # 写入 JSON（ensure_ascii=False 保留中文）
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"[DONE] Parsed {len(blocks)} blocks → {len(entries)} entries")
    print(f"[DONE] Skipped: {skipped}")
    print(f"[DONE] Written to: {OUTPUT_FILE}")

    # 统计
    has_trans = sum(1 for e in entries if e["value"]["data"][0]["detailed"]["translation"])
    has_daiyi = sum(
        1 for e in entries
        if e["value"]["data"][0]["detailed"]["translation"].startswith("[待译]")
    )
    has_phonetic = sum(1 for e in entries if e["value"]["data"][0]["detailed"]["phonetic"])
    print(f"[STATS] Total: {len(entries)}")
    print(f"[STATS] With translation: {has_trans}")
    print(f"[STATS] [待译]: {has_daiyi}")
    print(f"[STATS] With phonetic: {has_phonetic}")


if __name__ == "__main__":
    build_kv_json()
