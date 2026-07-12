#!/usr/bin/env python3
"""
DeepSeek V4 Pro — 全量翻译 hao.txt (~2596 条术语)
支持断点续传：跳过已翻译的术语，可随时中断后恢复
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ==================== Configuration ====================
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = ""
MODEL = "deepseek-v4-pro"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "promote.txt")
SOURCE_FILE = os.path.join(SCRIPT_DIR, "hao.txt")
TARGET_FILE = os.path.join(SCRIPT_DIR, "hao_dsv4.txt")
SAVE_EVERY = 10

# ==================== File I/O ====================

def read_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def parse_all_terms(filepath):
    """Parse all terms from source file. Returns [{name, definition, start_line, already_done}, ...]"""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    terms = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("NAME:"):
            name = line[5:].strip()
            definition = ""
            if i + 1 < len(lines):
                d = lines[i + 1].strip()
                if d.startswith("DEF:"):
                    definition = d[4:].strip()
            zh_done = False
            if i + 2 < len(lines):
                zh_line = lines[i + 2].strip()
                if zh_line.startswith("ZH:") and len(zh_line) > 3:
                    zh_done = True
            terms.append({
                "name": name,
                "definition": definition,
                "start_line": i,
                "already_done": zh_done,
            })
            i += 6
        else:
            i += 1
    return terms

def load_target_lines():
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

    def translate(self, name, definition):
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

        t0 = time.time()
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        elapsed = (time.time() - t0) * 1000
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

        return result, usage, elapsed

def classify_tier(zh):
    if zh == "[待译]":
        return "无译"
    if not zh:
        return "空"
    if zh.startswith("("):
        return "存疑"
    if "|(" in zh:
        return "确定+存疑"
    return "确定"

# ==================== Main ====================

def main():
    start_ts = time.time()
    print("=" * 70)
    print(f"DeepSeek V4 Pro — 全量翻译 hao.txt")
    print("=" * 70)
    print(f"Model:     {MODEL}")
    print(f"Target:    {TARGET_FILE}")
    print(f"Save:      every {SAVE_EVERY} terms")
    print()

    prompt = read_prompt()
    print(f"[INIT] System prompt: {len(prompt)} chars")

    all_terms = parse_all_terms(SOURCE_FILE)
    done = sum(1 for t in all_terms if t["already_done"])
    pending = [t for t in all_terms if not t["already_done"]]
    total = len(all_terms)

    print(f"[INIT] Total: {total}  |  Done: {done}  |  Pending: {len(pending)}")

    if not pending:
        print("[INIT] All terms already translated. Nothing to do.")
        return

    print(f"       First pending: {pending[0]['name'][:65]}")
    print(f"       Last pending:  {pending[-1]['name'][:65]}")
    print()

    all_lines = load_target_lines()
    print(f"[INIT] Target file: {len(all_lines)} lines")
    print()

    translator = Translator(prompt)

    tiers = {"确定": 0, "存疑": 0, "确定+存疑": 0, "无译": 0, "空": 0}
    success = 0
    fail = 0

    for i, term in enumerate(pending):
        idx = i + 1
        name = term["name"]
        definition = term["definition"]

        # Progress header every 20 terms
        if idx % 20 == 1 or idx == 1:
            elapsed = time.time() - start_ts
            done_so_far = done + success
            rate = done_so_far / (elapsed / 60) if elapsed > 0 else 0
            remaining = len(pending) - i
            eta_min = remaining / rate if rate > 0 else 0
            print(f"--- {done_so_far}/{total} ({done_so_far*100//total}%)  "
                  f"ETA: {eta_min:.0f}m  rate: {rate:.1f}/min ---")

        try:
            result, usage, latency = translator.translate(name, definition)
        except Exception as e:
            fail += 1
            print(f"  [{idx:>4}] {name[:60]}  FAIL: {e}")
            continue

        zh = result["zh"]
        ph = result["phonetic"]
        infl = result["inflect"]
        tier = classify_tier(zh)
        tiers[tier] = tiers.get(tier, 0) + 1
        success += 1

        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)

        print(f"  [{idx:>4}] {name[:55]}  [{tier}] {zh[:30]}  ({latency:.0f}ms, {out_tok}tok)")

        # Write to target lines
        start = term["start_line"]
        if start + 2 < len(all_lines):
            all_lines[start + 2] = f"ZH:{zh}\n"
        if start + 3 < len(all_lines):
            all_lines[start + 3] = f"INFLECT:{infl}\n"
        if start + 4 < len(all_lines):
            all_lines[start + 4] = f"PHONETC:{ph}\n"

        # Periodic save
        if success % SAVE_EVERY == 0:
            save_lines(all_lines)

    # Final save
    save_lines(all_lines)

    # Summary
    elapsed_total = time.time() - start_ts

    print()
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Total:    {total}")
    print(f"  Done:     {done + success}")
    print(f"  This run: {success} success, {fail} failed")
    print(f"  Time:     {elapsed_total:.0f}s ({elapsed_total/60:.1f} min)")
    print(f"  Output:   {TARGET_FILE}")
    print()
    print("  Confidence tiers:")
    for tier in ["确定", "存疑", "确定+存疑", "无译", "空"]:
        if tiers[tier]:
            print(f"    {tier}: {tiers[tier]}")


if __name__ == "__main__":
    main()
