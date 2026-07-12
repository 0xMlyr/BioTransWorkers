#!/usr/bin/env python3
"""
DeepSeek V4 Flash API 连通性与术语翻译测试
"""

import os
import sys
import json
import time
import requests

# Windows GBK 编码兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ==================== 配置 ====================
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = ""
MODEL = "deepseek-v4-pro"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "promote.txt")


def read_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


# ==================== 测试用例 ====================
TEST_CASES = [
    ("propodeum", "The first abdominal tergum that is fused with the metapleuron."),
    ("mesopleuron", "The pleuron that is located in the mesothorax."),
    ("mandible", "The appendage that is located on the ventral surface of the head, is used for biting and cutting, and is paired."),
    ("abdominal sternum 9", "The sternum that is located on abdominal segment 9."),
    ("fore wing venation", "The pattern of veins on the fore wing."),
    ("epicnemial carina", "The carina that extends across the mesepisternum."),
]


def call_api(system_prompt, user_content, temperature=0.01):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "top_p": 0.1,
        "max_tokens": 250,
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    start = time.time()
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    elapsed = round((time.time() - start) * 1000)
    resp.raise_for_status()
    data = resp.json()
    return data, elapsed


def parse_response(content):
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    result = {"zh": "", "phonetic": "", "inflect": ""}
    for line in lines:
        if line.startswith("ZH:"):
            result["zh"] = line[3:]
        elif line.startswith("PHONETIC:"):
            result["phonetic"] = line[9:]
        elif line.startswith("INFLECT:"):
            result["inflect"] = line[8:]
    return result


def main():
    print("=" * 70)
    print("DeepSeek V4 Pro API 测试")
    print("=" * 70)
    print(f"Endpoint:  {API_URL}")
    print(f"Model:     {MODEL}")
    print(f"Key prefix: {API_KEY[:10]}...")
    print()

    # ── Test 1: 基础连通性 ──
    system_prompt = read_prompt()
    print(f"System prompt 长度: {len(system_prompt)} chars")
    print()

    print("--- Test 1: 基础连通性 ---")
    try:
        data, elapsed = call_api(
            "You are a helpful assistant.",
            "Say exactly: API_OK",
            temperature=0.0,
        )
        model_actual = data.get("model", "?")
        content = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        print(f"  Model:      {model_actual}")
        print(f"  Response:   {content}")
        print(f"  Latency:    {elapsed} ms")
        print(f"  Tokens:     prompt={usage.get('prompt_tokens')}, "
              f"completion={usage.get('completion_tokens')}, "
              f"total={usage.get('total_tokens')}")
        print(f"  [PASS] 连通性正常")
    except Exception as e:
        print(f"  [FAIL] {e}")
        return

    print()

    # ── Test 2: 术语翻译 (含prompt) ──
    print("--- Test 2: 术语翻译 ---")
    results = []
    for name, definition in TEST_CASES:
        user_content = f"NAME:{name}\nDEF:{definition}"
        try:
            data, elapsed = call_api(system_prompt, user_content)
            raw = data["choices"][0]["message"]["content"].strip()
            parsed = parse_response(raw)
            usage = data.get("usage", {})
            results.append((name, parsed, elapsed, usage))
            print(f"  [{elapsed}ms] {name}")
            print(f"    ZH:       {parsed['zh'][:50]}")
            print(f"    PHONETIC: {parsed['phonetic'][:30]}")
            print(f"    INFLECT:  {parsed['inflect'][:40]}")
            print(f"    tokens:   in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
        time.sleep(0.3)

    print()

    # ── Summary ──
    print("--- 总结 ---")
    zh_filled = sum(1 for _, r, _, _ in results if r["zh"] and r["zh"] != "[待译]" and r["zh"] != "[无标准译词]")
    phonetic_filled = sum(1 for _, r, _, _ in results if r["phonetic"])
    inflect_filled = sum(1 for _, r, _, _ in results if r["inflect"])
    print(f"  测试用例:    {len(TEST_CASES)}")
    print(f"  ZH 产出:     {zh_filled}/{len(TEST_CASES)}")
    print(f"  PHONETIC 产出: {phonetic_filled}/{len(TEST_CASES)}")
    print(f"  INFLECT 产出:  {inflect_filled}/{len(TEST_CASES)}")

    latencies = [elapsed for _, _, elapsed, _ in results]
    if latencies:
        print(f"  平均延迟:    {sum(latencies) // len(latencies)} ms")
        print(f"  最快/最慢:   {min(latencies)} ms / {max(latencies)} ms")

    total_prompt = sum(u.get("prompt_tokens", 0) for _, _, _, u in results)
    total_completion = sum(u.get("completion_tokens", 0) for _, _, _, u in results)
    print(f"  总token:     prompt={total_prompt}, completion={total_completion}")
    print()
    print("测试完成。模型可用，可以开始批量翻译。")


if __name__ == "__main__":
    main()
