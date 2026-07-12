#!/usr/bin/env python3
"""
AC自动机构建脚本
从 glossary/terms/ 下的三个数据源提取全部key，构建Aho-Corasick自动机，
序列化为 ac_trie.json 供 Cloudflare Worker 使用。

用法:
    cd glossary/automaton
    python build_ac.py
"""

import json
import os
import re
from collections import deque
from datetime import datetime, timezone

# ── 路径配置 ──────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TERMS_DIR = os.path.join(SCRIPT_DIR, "..", "terms")

SOURCES = [
    os.path.join(TERMS_DIR, "hao_core", "hao_for_kv.json"),
    os.path.join(TERMS_DIR, "my_trem_202604", "my_term_for_kv.json"),
    os.path.join(TERMS_DIR, "engine_test", "test_term.txt"),
]

OUTPUT_PATH = os.path.join(SCRIPT_DIR, "ac_trie.json")


# ── Step 1: 提取并去重所有key ─────────────────────────────
def extract_keys() -> list[str]:
    """
    从三个数据源提取所有英文术语key，去重并统一转小写。
    返回排序后的唯一key列表。
    """
    raw_keys: set[str] = set()

    for src_path in SOURCES:
        if not os.path.exists(src_path):
            print(f"[WARN] Source not found, skipping: {src_path}")
            continue

        if src_path.endswith(".json"):
            # JSON格式: [{"key": "term", "value": {...}}, ...]
            with open(src_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data:
                if "key" in entry and isinstance(entry["key"], str):
                    raw_keys.add(entry["key"])
            print(f"[LOAD] {os.path.basename(src_path)}: extracted {len(data)} entries")

        elif src_path.endswith(".txt"):
            # 纯文本格式: 每行一个英文术语
            with open(src_path, "r", encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    # 跳过空行和非英文行（含中文等）
                    if term and re.match(r'^[a-zA-Z\s\-]+$', term):
                        raw_keys.add(term)
            print(f"[LOAD] {os.path.basename(src_path)}: loaded text terms")

    # 统一转小写，去重
    normalized = sorted({k.lower() for k in raw_keys if k.strip()})
    print(f"[DONE] Total unique keys (lowercase): {len(normalized)}")
    return normalized


# ── Step 2: 构建AC自动机 ──────────────────────────────────
class ACTrieNode:
    """Trie节点"""
    __slots__ = ("children", "fail", "output")

    def __init__(self):
        self.children: dict[str, int] = {}
        self.fail: int = 0
        self.output: list[str] = []


def build_trie(terms: list[str]) -> list[ACTrieNode]:
    """
    从术语列表构建Trie树。
    每个节点存储children映射、failure指针、output列表。
    """
    nodes: list[ACTrieNode] = [ACTrieNode()]  # 根节点 index=0

    # 插入所有术语
    for term in terms:
        state = 0
        for ch in term:
            if ch not in nodes[state].children:
                nodes[state].children[ch] = len(nodes)
                nodes.append(ACTrieNode())
            state = nodes[state].children[ch]
        nodes[state].output.append(term)

    print(f"[TRIE] Inserted {len(terms)} terms, {len(nodes)} nodes created")
    return nodes


def build_failure_links(nodes: list[ACTrieNode]) -> list[ACTrieNode]:
    """
    BFS构建failure指针。
    failure指针指向：当前节点的最长真后缀所对应的Trie节点。
    """
    queue: deque[int] = deque()

    # 第一层子节点的fail指向根
    for ch, child_idx in nodes[0].children.items():
        nodes[child_idx].fail = 0
        queue.append(child_idx)

    # BFS构建
    while queue:
        current = queue.popleft()
        for ch, child_idx in nodes[current].children.items():
            queue.append(child_idx)

            # 沿fail链回退，找到可以走ch的祖先
            fail_state = nodes[current].fail
            while fail_state != 0 and ch not in nodes[fail_state].children:
                fail_state = nodes[fail_state].fail

            if ch in nodes[fail_state].children and nodes[fail_state].children[ch] != child_idx:
                nodes[child_idx].fail = nodes[fail_state].children[ch]
            else:
                nodes[child_idx].fail = 0

            # 合并output：failure指向的节点的output也要继承
            # （处理一个术语是另一个术语的后缀的情况）
            fail_output = nodes[nodes[child_idx].fail].output
            if fail_output:
                nodes[child_idx].output = nodes[child_idx].output + fail_output

    print(f"[FAIL] Failure links built for {len(nodes)} nodes")
    return nodes


# ── Step 3: 序列化 ────────────────────────────────────────
def serialize(nodes: list[ACTrieNode], term_count: int) -> dict:
    """
    将Trie序列化为JSON友好的格式。
    每个节点: {children: {char: index}, fail: index, output: [terms]}
    """
    trie = []
    for node in nodes:
        trie.append({
            "children": node.children,
            "fail": node.fail,
            "output": node.output,
        })

    return {
        "version": "1.0",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "term_count": term_count,
        "node_count": len(trie),
        "trie": trie,
    }


# ── Step 4: 验证 ──────────────────────────────────────────
def verify(trie_data: dict, test_cases: list[tuple[str, list[str]]]):
    """
    用测试用例验证自动机匹配结果。
    test_cases: [(input_text, expected_terms), ...]
    """
    trie = trie_data["trie"]
    passed = 0
    failed = 0

    for text, expected in test_cases:
        # AC匹配
        state = 0
        found = []
        lower = text.lower()
        for i, ch in enumerate(lower):
            while state != 0 and ch not in trie[state]["children"]:
                state = trie[state]["fail"]
            state = trie[state]["children"].get(ch, 0)
            for term in trie[state]["output"]:
                found.append(term)

        found_unique = sorted(set(found))
        expected_sorted = sorted(set(expected))

        if found_unique == expected_sorted:
            passed += 1
            print(f"  [PASS] \"{text}\" → {found_unique}")
        else:
            failed += 1
            print(f"  [FAIL] \"{text}\"")
            print(f"         expected: {expected_sorted}")
            print(f"         got:      {found_unique}")

    print(f"\n[VERIFY] {passed} passed, {failed} failed out of {len(test_cases)} cases")


# ── Main ──────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("AC Automaton Builder")
    print("=" * 60)

    # 1. 提取key
    print("\n--- Step 1: Extract keys ---")
    terms = extract_keys()
    if not terms:
        print("[ERROR] No terms found!")
        return

    # 2. 构建Trie
    print("\n--- Step 2: Build Trie ---")
    nodes = build_trie(terms)

    # 3. 构建failure指针
    print("\n--- Step 3: Build failure links ---")
    nodes = build_failure_links(nodes)

    # 4. 序列化
    print("\n--- Step 4: Serialize ---")
    trie_data = serialize(nodes, len(terms))
    json_str = json.dumps(trie_data, ensure_ascii=False, separators=(",", ":"))
    print(f"[SIZE] JSON size: {len(json_str):,} bytes ({len(json_str) / 1024:.1f} KB)")

    # 5. 验证
    print("\n--- Step 5: Verify ---")
    verify(trie_data, [
        ("The propodeum is lateral to the pleuron", ["propodeum", "pleuron"]),
        ("Median area of propodeum: evenly reticulate", ["area", "propodeum"]),
        ("The Mesopleuron is located posterior", ["mesopleuron"]),
        ("fore wing venation of Chalcidoidea", ["fore wing venation", "chalcidoidea"]),
        ("The abdomen is segmented", ["abdomen"]),
        ("No terms here", []),
        ("PROPODEUM and Propodeum and propodeum", ["propodeum"]),
    ])

    # 6. 写入文件
    print(f"\n--- Step 6: Write output ---")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(json_str)
    print(f"[DONE] Written to {OUTPUT_PATH}")
    print(f"[STATS] {trie_data['term_count']} terms, {trie_data['node_count']} nodes")


if __name__ == "__main__":
    main()
