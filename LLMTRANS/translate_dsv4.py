#!/usr/bin/env python3
"""
DeepSeek V4 Pro 批量翻译 hao.txt 前50条术语
"""

import os
import sys
import time
import requests
from datetime import datetime

# Windows GBK encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ==================== Configuration ====================
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = ""
MODEL = "deepseek-v4-pro"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "promote.txt")
SOURCE_FILE = os.path.join(SCRIPT_DIR, "hao.txt")
TARGET_FILE = os.path.join(SCRIPT_DIR, "hao_dsv4_test.txt")

BATCH_COUNT = 50   # translate first 50 terms
SAVE_EVERY = 10    # save every N terms
MIN_INTERVAL = 1.0 # seconds between requests

# ==================== File I/O ====================

def read_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def parse_terms(filepath, count):
    """Parse first `count` terms from source file.
    Each term is a 6-line block: NAME, DEF, ZH, INFLECT, PHONETC, blank.
    Returns [{name, definition, start_line}, ...]"""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    terms = []
    i = 0
    while i < len(lines) and len(terms) < count:
        line = lines[i].strip()
        if line.startswith("NAME:"):
            name = line[5:].strip()
            definition = ""
            if i + 1 < len(lines):
                d = lines[i + 1].strip()
                if d.startswith("DEF:"):
                    definition = d[4:].strip()
            terms.append({
                "name": name,
                "definition": definition,
                "start_line": i,
            })
            i += 6
        else:
            i += 1
    return terms

def load_target_lines():
    """Load target file lines. If not exists, copy from source."""
    if not os.path.exists(TARGET_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        with open(TARGET_FILE, "w", encoding="utf-8") as f:
            f.write(content)
    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        return f.readlines()

def save_lines(lines):
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

# ==================== LLM API ====================

class Translator:
    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
        self.last_request = 0

    def _wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        self.last_request = time.time()

    def translate(self, name, definition):
        self._wait()

        user_content = f"NAME:{name}\nDEF:{definition}"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.01,
            "top_p": 0.1,
            "max_tokens": 250,
            "thinking": {"type": "disabled"},
            "stream": False,
        }

        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})

        result = {"zh": "", "phonetic": "", "inflect": ""}
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("ZH:"):
                result["zh"] = line[3:]
            elif line.startswith("PHONETIC:"):
                result["phonetic"] = line[9:]
            elif line.startswith("INFLECT:"):
                result["inflect"] = line[8:]

        return result, usage, content

# ==================== Main ====================

def main():
    print("=" * 70)
    print(f"DeepSeek V4 Pro — 批量翻译前 {BATCH_COUNT} 条术语")
    print("=" * 70)
    print(f"Model:     {MODEL}")
    print(f"Source:    {SOURCE_FILE}")
    print(f"Target:    {TARGET_FILE}")
    print(f"Save every {SAVE_EVERY} terms")
    print()

    # Load
    prompt = read_prompt()
    print(f"[INIT] System prompt: {len(prompt)} chars")

    terms = parse_terms(SOURCE_FILE, BATCH_COUNT)
    print(f"[INIT] Parsed {len(terms)} terms from hao.txt")
    print(f"       First: {terms[0]['name'][:60]}")
    print(f"       Last:  {terms[-1]['name'][:60]}")

    all_lines = load_target_lines()
    print(f"[INIT] Target file: {len(all_lines)} lines")
    print()

    translator = Translator(prompt)

    # Translate
    success = 0
    fail = 0
    batch = []
    start_time = time.time()

    for i, term in enumerate(terms):
        idx = i + 1
        name = term["name"]
        definition = term["definition"]

        print(f"[{idx:>3}/{BATCH_COUNT}] {name[:65]}", end=" ", flush=True)

        try:
            result, usage, raw = translator.translate(name, definition)
        except Exception as e:
            fail += 1
            print(f"FAIL: {e}")
            continue

        zh = result["zh"]
        ph = result["phonetic"]
        infl = result["inflect"]

        # Determine confidence tier
        if zh == "[待译]":
            tier = "无译"
        elif zh.startswith("("):
            tier = "存疑"
        elif "|(" in zh:
            tier = "确定+存疑"
        elif zh:
            tier = "确定"
        else:
            tier = "空"

        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cache_hit = usage.get("prompt_cache_hit_tokens", 0)
        cache_miss = usage.get("prompt_cache_miss_tokens", 0)

        cache_info = ""
        if cache_hit:
            cache_info = f" [cache hit:{cache_hit}]"

        print(f"[{tier}] {zh[:35]}{cache_info}  ({out_tok} tok)")

        # Update target lines (keep source NAME/DEF, fill ZH/INFLECT/PHONETC)
        start = term["start_line"]
        if start + 2 < len(all_lines):
            all_lines[start + 2] = f"ZH:{zh}\n"
        if start + 3 < len(all_lines):
            all_lines[start + 3] = f"INFLECT:{infl}\n"
        if start + 4 < len(all_lines):
            all_lines[start + 4] = f"PHONETC:{ph}\n"

        batch.append(term)
        success += 1

        # Periodic save
        if idx % SAVE_EVERY == 0 or idx == len(terms):
            save_lines(all_lines)
            elapsed = time.time() - start_time
            rate = idx / elapsed * 60 if elapsed > 0 else 0
            print(f"  [SAVE] {idx}/{BATCH_COUNT} saved ({elapsed:.0f}s, {rate:.1f} terms/min)")

    # Summary
    elapsed_total = time.time() - start_time
    print()
    print("=" * 70)
    print("Complete!")
    print(f"  Success: {success}")
    print(f"  Failed:  {fail}")
    print(f"  Time:    {elapsed_total:.0f}s ({elapsed_total/60:.1f} min)")
    print(f"  Output:  {TARGET_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
