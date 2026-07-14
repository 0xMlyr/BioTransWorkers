#!/usr/bin/env python3
"""
MiMo v2.5 — 全量词典页 OCR + 结构化提取
依次处理 LLMOCR 下全部 26 张图片，每张图携带 promote.txt 系统提示词，
汇总所有词条输出到 aafc_glossary.json，支持断点续传。
"""

import os
import sys
import json
import time
import base64
import requests
from datetime import datetime, timezone

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ==================== Configuration ====================
API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
API_KEY = "sk-cgwsr29n31ok3xu7go72teh66v2oxkw7321wfyhtailofy7u"
MODEL = "mimo-v2.5"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(SCRIPT_DIR, "smallpdf-convert-20260714-232145")
PROMPT_FILE = os.path.join(SCRIPT_DIR, "promote.txt")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "aafc_glossary.json")
CHECKPOINT_FILE = os.path.join(SCRIPT_DIR, "aafc_checkpoint.json")

MAX_COMPLETION_TOKENS = 8192
TEMPERATURE = 0.01
SAVE_EVERY = 3
REQUEST_TIMEOUT = 300
MAX_RETRIES = 2

# ==================== Helpers ====================

def load_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed": {}, "failed": {}}

def save_checkpoint(cp):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)

def parse_json_content(raw):
    content = raw.strip()
    if content.startswith("```"):
        parts = content.split("\n", 1)
        content = parts[1] if len(parts) > 1 else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None

# ==================== API Call ====================

def ocr_page(image_path, system_prompt):
    image_b64 = encode_image(image_path)
    headers = {
        "api-key": API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "请提取该页所有词条的结构化信息，按提示词要求输出 JSON 数组。",
                    },
                ],
            },
        ],
        "temperature": TEMPERATURE,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "thinking": {"type": "disabled"},
    }

    t0 = time.time()
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    elapsed = time.time() - t0

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:500], "elapsed": elapsed}

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    return {
        "elapsed": elapsed,
        "usage": usage,
        "raw": content,
    }

# ==================== Validation ====================

def validate_entries(entries, page_name):
    """Validate bbox format and column consistency. Returns list of warnings."""
    warnings = []
    for i, e in enumerate(entries):
        bbox = e.get("figure_bbox_approx")
        if bbox and isinstance(bbox, list) and len(bbox) == 4:
            for j, v in enumerate(bbox):
                if v > 1.01:
                    warnings.append(
                        f"[{page_name}] entry {i+1} '{e.get('term','?')}': "
                        f"bbox[{j}]={v} > 1.0, possibly not a ratio"
                    )
        col = e.get("column", "")
        if bbox and isinstance(bbox, list) and len(bbox) == 4:
            x_center = (bbox[0] + bbox[2]) / 2
            if col == "left" and x_center > 0.55:
                warnings.append(
                    f"[{page_name}] entry {i+1} '{e.get('term','?')}': "
                    f"column='left' but bbox center x={x_center:.2f} is in right half"
                )
            elif col == "right" and x_center < 0.45:
                warnings.append(
                    f"[{page_name}] entry {i+1} '{e.get('term','?')}': "
                    f"column='right' but bbox center x={x_center:.2f} is in left half"
                )
    return warnings

# ==================== Main ====================

def main():
    start_ts = time.time()

    images = sorted(
        [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    )
    if not images:
        print("[ERROR] No images found in", IMAGE_DIR)
        return

    print("=" * 70)
    print("MiMo v2.5 — 全量词典页 OCR + 结构化提取")
    print("=" * 70)
    print(f"Model:        {MODEL}")
    print(f"Images:       {len(images)}")
    print(f"Output:       {OUTPUT_FILE}")
    print(f"Checkpoint:   {CHECKPOINT_FILE}")
    print()

    prompt = load_prompt()
    print(f"[INIT] System prompt: {len(prompt)} chars")

    cp = load_checkpoint()
    processed = cp["processed"]
    failed = cp["failed"]
    pending = [img for img in images if img not in processed and img not in failed]

    print(f"[INIT] Total: {len(images)}  |  Done: {len(processed)}  |  "
          f"Failed: {len(failed)}  |  Pending: {len(pending)}")
    print()

    if not pending:
        print("[INIT] All pages processed. Writing final output ...")
        _write_final(processed, failed)
        return

    total_success = len(processed)
    total_fail = len(failed)
    all_warnings = []

    for i, img_name in enumerate(pending):
        idx = i + 1
        img_path = os.path.join(IMAGE_DIR, img_name)
        file_kb = os.path.getsize(img_path) / 1024

        # Progress header every 5 pages
        if idx % 5 == 1 or idx == 1:
            elapsed = time.time() - start_ts
            done_count = total_success
            rate = done_count / (elapsed / 60) if elapsed > 0 else 0
            eta = len(pending) / rate if rate > 0 else 0
            print(f"--- {done_count}/{len(images)} ({done_count*100//len(images)}%)  "
                  f"ETA: {eta:.0f}m  rate: {rate:.1f}/min ---")

        print(f"  [{idx:>3}/{len(pending)}] {img_name} ({file_kb:.0f}KB) ... ", end="", flush=True)

        # Attempt with retries
        page_result = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                page_result = ocr_page(img_path, prompt)
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    wait = (attempt + 1) * 10
                    print(f"retry in {wait}s ... ", end="", flush=True)
                    time.sleep(wait)
                else:
                    page_result = {"error": str(e), "elapsed": 0}

        elapsed = page_result["elapsed"]

        if "error" in page_result:
            total_fail += 1
            failed[img_name] = {"error": page_result["error"], "elapsed": elapsed}
            print(f"FAIL ({elapsed:.0f}s): {page_result['error']}")
            save_checkpoint(cp)
            continue

        entries = parse_json_content(page_result["raw"])
        if entries is None:
            total_fail += 1
            failed[img_name] = {"error": "JSON parse error"}
            print(f"FAIL ({elapsed:.0f}s): JSON parse error")
            save_checkpoint(cp)
            continue

        n = len(entries) if isinstance(entries, list) else 0
        total_success += 1
        usage = page_result["usage"]

        print(f"OK ({elapsed:.0f}s, "
              f"{usage.get('completion_tokens','?')} tok, {n} entries)")

        # Validate
        if isinstance(entries, list):
            warnings = validate_entries(entries, img_name)
            for w in warnings:
                print(f"        WARN: {w}")
            all_warnings.extend(warnings)

        processed[img_name] = {
            "entries": entries,
            "count": n,
            "elapsed": elapsed,
            "usage": usage,
        }

        if idx % SAVE_EVERY == 0:
            save_checkpoint(cp)
            _write_final(processed, failed)

    # Final save
    save_checkpoint(cp)
    _write_final(processed, failed)

    # Summary
    elapsed_total = time.time() - start_ts
    total_entries = sum(p["count"] for p in processed.values())

    print()
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Pages:     {len(images)}")
    print(f"  Success:   {total_success}")
    print(f"  Failed:    {total_fail}")
    print(f"  Entries:   {total_entries}")
    print(f"  Warnings:  {len(all_warnings)}")
    print(f"  Time:      {elapsed_total:.0f}s ({elapsed_total/60:.1f} min)")
    print(f"  Output:    {OUTPUT_FILE}")
    if failed:
        print(f"  Failed:    {', '.join(failed.keys())}")


def _write_final(processed, failed):
    """Build and write aafc_glossary.json"""
    all_entries = []
    for img_name in sorted(processed.keys()):
        page = processed[img_name]
        page_entries = page.get("entries", [])
        if isinstance(page_entries, list):
            for entry in page_entries:
                entry["source_page"] = img_name
                all_entries.append(entry)

    output = {
        "metadata": {
            "model": MODEL,
            "total_pages": len(processed) + len(failed),
            "success_pages": len(processed),
            "failed_pages": len(failed),
            "total_entries": len(all_entries),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        "failed_pages": {k: v.get("error", "unknown") for k, v in failed.items()},
        "entries": all_entries,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
