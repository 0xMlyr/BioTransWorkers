#!/usr/bin/env python3
"""
AC自动机构建脚本（ackey驱动版）
以 glossary/BioTermbase/ackey_0715.txt 为权威词形清单，
构建 Aho-Corasick 自动机，序列化为 ac_trie.json 供 Cloudflare Worker 使用。

ackey_0715.txt = 以下 7 数据源的非重复并集：
  hao_core + my_term + engine_test + hao.obo synonym + hao_dsv4 INFLECT + aafc glossary

用法:
    cd glossary/automaton
    python build_ac.py
"""

import json
import os
import re
from collections import deque, defaultdict
from datetime import datetime, timezone

# ── 路径配置 ──────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)  # glossary/
ACKEY_PATH = os.path.join(ROOT, "BioTermbase", "ackey_0715.txt")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "ac_trie.json")


# ── Step 1: 从 ackey 构建大小写映射 ──────────────────────
def build_case_map(ackey_path: str) -> dict[str, str]:
    """
    从 ackey_0715.txt 读取所有词形, 构建 {小写: 原始大小写} 映射。
    同一小写出现多种大小写时, 优先保留非全小写变体 (如 T2 优于 t2)。

    返回: (case_map, stats)
      case_map: {lowercase: preferred_case_form}
      stats: {total_lines, case_collisions, collision_pairs}
    """
    case_map: dict[str, str] = {}
    collision_pairs: list[tuple[str, str]] = []  # (kept, discarded) 对
    total = 0

    with open(ackey_path, "r", encoding="utf-8") as f:
        for line in f:
            term = line.strip()
            if not term:
                continue
            total += 1
            lower = term.lower()

            if lower not in case_map:
                case_map[lower] = term
            else:
                existing = case_map[lower]
                # 优先保留非全小写变体
                if existing == existing.lower() and term != term.lower():
                    collision_pairs.append((term, existing))  # new 替换 old
                    case_map[lower] = term
                elif existing != existing.lower() and term == term.lower():
                    collision_pairs.append((existing, term))  # old 保留, new 丢弃
                else:
                    # 两个都不是/都是全小写 → 保留先到的
                    collision_pairs.append((existing, term))

    stats = {
        "total_lines": total,
        "unique_lowercase": len(case_map),
        "case_collisions": len(collision_pairs),
        "collision_pairs": collision_pairs,
    }
    print(f"[LOAD] {os.path.basename(ackey_path)}: {total} lines → {len(case_map)} unique (lowercased)")
    print(f"[LOAD] Case collisions (same lowercase, different case): {len(collision_pairs)}")
    return case_map, stats


def analyze_term_shapes(case_map: dict[str, str]) -> dict:
    """词形特征统计"""
    short = 0          # ≤2 chars
    with_digits = 0    # contains 0-9
    non_ascii = 0      # non-ASCII characters
    multi_word = 0     # contains space
    starts_punct = 0   # starts with non-alnum
    mixed_case = 0     # mixed upper/lower

    for term in case_map.values():
        if len(term) <= 2:
            short += 1
        if re.search(r'\d', term):
            with_digits += 1
        if not all(ord(ch) < 128 for ch in term):
            non_ascii += 1
        if ' ' in term:
            multi_word += 1
        if term and not term[0].isalnum():
            starts_punct += 1
        if term != term.lower() and term != term.upper():
            mixed_case += 1

    return {
        "short_le2": short,
        "with_digits": with_digits,
        "non_ascii": non_ascii,
        "multi_word": multi_word,
        "starts_punct": starts_punct,
        "mixed_case": mixed_case,
    }


# ── Step 3: 构建AC自动机 ──────────────────────────────────
class ACTrieNode:
    __slots__ = ("children", "fail", "output")

    def __init__(self):
        self.children: dict[str, int] = {}
        self.fail: int = 0
        self.output: list[str] = []


def build_trie(case_map: dict[str, str]) -> list[ACTrieNode]:
    nodes: list[ACTrieNode] = [ACTrieNode()]
    terms = sorted(case_map.keys())

    for lower_term in terms:
        state = 0
        for ch in lower_term:
            if ch not in nodes[state].children:
                nodes[state].children[ch] = len(nodes)
                nodes.append(ACTrieNode())
            state = nodes[state].children[ch]
        nodes[state].output.append(case_map[lower_term])

    print(f"[TRIE] Inserted {len(terms)} terms, {len(nodes)} nodes created")

    # 统计 children 分布
    child_counts = [len(n.children) for n in nodes]
    max_children = max(child_counts) if child_counts else 0
    avg_children = sum(child_counts) / len(child_counts) if child_counts else 0
    print(f"[TRIE] Children per node: max={max_children}, avg={avg_children:.1f}")

    return nodes


def build_failure_links(nodes: list[ACTrieNode]) -> list[ACTrieNode]:
    queue: deque[int] = deque()

    for ch, child_idx in nodes[0].children.items():
        nodes[child_idx].fail = 0
        queue.append(child_idx)

    while queue:
        current = queue.popleft()
        for ch, child_idx in nodes[current].children.items():
            queue.append(child_idx)

            fail_state = nodes[current].fail
            while fail_state != 0 and ch not in nodes[fail_state].children:
                fail_state = nodes[fail_state].fail

            if ch in nodes[fail_state].children and nodes[fail_state].children[ch] != child_idx:
                nodes[child_idx].fail = nodes[fail_state].children[ch]
            else:
                nodes[child_idx].fail = 0

            fail_output = nodes[nodes[child_idx].fail].output
            if fail_output:
                nodes[child_idx].output = nodes[child_idx].output + fail_output

    # 统计 fail 分布
    fail_nonzero = sum(1 for n in nodes if n.fail != 0)
    print(f"[FAIL] Failure links built for {len(nodes)} nodes ({fail_nonzero} non-zero, {len(nodes) - fail_nonzero} root-direct)")
    return nodes


# ── Step 5: 序列化 ────────────────────────────────────────
def serialize(nodes: list[ACTrieNode], term_count: int) -> dict:
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


# ── Step 6: 验证（含单词边界过滤，匹配 term-handler.js acMatch 行为）──
def verify(trie_data: dict, test_cases: list[tuple[str, list[str]]]):
    trie = trie_data["trie"]
    passed = 0
    failed = 0

    for text, expected in test_cases:
        # ── 原始 AC 匹配 ──
        state = 0
        raw_matches = []
        lower = text.lower()
        for i, ch in enumerate(lower):
            while state != 0 and ch not in trie[state]["children"]:
                state = trie[state]["fail"]
            state = trie[state]["children"].get(ch, 0)
            for term in trie[state]["output"]:
                raw_matches.append({"term": term, "start": i - len(term) + 1, "end": i + 1})

        # ── 单词边界过滤（与 term-handler.js acMatch 完全一致）──
        with_boundaries = []
        for m in raw_matches:
            if m["start"] > 0 and re.match(r'\w', text[m["start"] - 1]):
                continue
            if m["end"] < len(text) and re.match(r'\w', text[m["end"]]):
                continue
            with_boundaries.append(m)

        # ── 排序 + 贪心去重叠 ──
        with_boundaries.sort(
            key=lambda m: (m["start"], -(m["end"] - m["start"]))
        )
        final = []
        last_end = 0
        for m in with_boundaries:
            if m["start"] >= last_end:
                final.append(m["term"])
                last_end = m["end"]

        found_unique = sorted(set(final))
        expected_sorted = sorted(set(expected))

        if found_unique == expected_sorted:
            passed += 1
            print(f"  [PASS] \"{text}\" -> {found_unique}")
        else:
            failed += 1
            print(f"  [FAIL] \"{text}\"")
            print(f"         expected: {expected_sorted}")
            print(f"         got:      {found_unique}")

    print(f"\n[VERIFY] {passed} passed, {failed} failed out of {len(test_cases)} cases")


# ── Main ──────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("AC Automaton Builder (ackey-driven)")
    print(f"  Input:  {ACKEY_PATH}")
    print(f"  Output: {OUTPUT_PATH}")
    print("=" * 70)

    if not os.path.exists(ACKEY_PATH):
        print(f"[ERROR] ackey not found: {ACKEY_PATH}")
        return

    # ── 1. 从 ackey 构建大小写映射 ──
    print("\n--- Step 1: Build case map from ackey ---")
    case_map, ackey_stats = build_case_map(ACKEY_PATH)
    total = len(case_map)

    # ── 2. 词形特征统计 ──
    shape = analyze_term_shapes(case_map)
    print(f"[STAT] Short (<=2 chars):      {shape['short_le2']:>6,d}")
    print(f"[STAT] With digits:            {shape['with_digits']:>6,d}")
    print(f"[STAT] Non-ASCII:              {shape['non_ascii']:>6,d}")
    print(f"[STAT] Multi-word (space):     {shape['multi_word']:>6,d}")
    print(f"[STAT] Starts with punct:      {shape['starts_punct']:>6,d}")
    print(f"[STAT] Mixed case:             {shape['mixed_case']:>6,d}")

    # ── 3. 构建 Trie ──
    print("\n--- Step 3: Build Trie ---")
    nodes = build_trie(case_map)

    # ── 4. 构建 failure 指针 ──
    print("\n--- Step 4: Build failure links ---")
    nodes = build_failure_links(nodes)

    # 节点内多 output 统计
    multi_output = sum(1 for n in nodes if len(n.output) > 1)
    nodes_with_output = sum(1 for n in nodes if len(n.output) > 0)
    print(f"[STAT] Nodes with output:   {nodes_with_output:>6,d}")
    print(f"[STAT] Nodes with >=2 output:{multi_output:>6,d}")

    # ── 5. 序列化 ──
    print("\n--- Step 5: Serialize ---")
    trie_data = serialize(nodes, total)
    json_str = json.dumps(trie_data, ensure_ascii=False, separators=(",", ":"))
    file_size_kb = len(json_str) / 1024
    print(f"[SIZE] JSON size: {len(json_str):,} bytes ({file_size_kb:.1f} KB)")

    # ── 6. 验证 ──
    verify(trie_data, [
        ("The propodeum is lateral to the pleuron", ["propodeum", "pleuron"]),
        ("Median area of propodeum: evenly reticulate", ["area", "median", "propodeum", "reticulate"]),
        ("The Mesopleuron is located posterior", ["mesopleuron"]),
        ("fore wing venation of Chalcidoidea", ["fore wing venation", "Chalcidoidea"]),
        ("The abdomen is segmented", ["abdomen"]),
        ("No terms here", []),
        ("PROPODEUM and Propodeum and propodeum", ["propodeum"]),
        ("The whole organism displays polymorphism", ["whole organism"]),
        ("Several anatomical structures are visible", ["anatomical structures"]),
        ("The anatomically structural components vary", ["anatomically structural"]),
        ("Der Hinterleib ist segmentiert", ["der Hinterleib"]),
        ("T2 is larger than t2", ["T2"]),
        ("abdominal sternite 6 is anterior", ["Abdominal sternite 6"]),
    ])

    # ── 7. 写入文件 ──
    print(f"\n--- Step 7: Write output ---")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(json_str)

    # ── 8. 构建报告 ──
    print()
    print("=" * 70)
    print("BUILD SUMMARY")
    print("=" * 70)
    print(f"  Input lines (ackey):                             {ackey_stats['total_lines']:>6,d}")
    print(f"  Unique lowercase keys after dedup:               {total:>6,d}")
    print(f"  Case collisions (discarded lowercase variant):   {ackey_stats['case_collisions']:>6,d}")
    print(f"  ───────────────────────────────────────────────────────")
    print(f"  TOTAL UNIQUE TERMS IN TRIE:                      {total:>6,d}")
    print(f"  TOTAL NODES:                                     {len(nodes):>6,d}")
    print(f"  Children per node (max / avg):                   {max(len(n.children) for n in nodes):>3} / {sum(len(n.children) for n in nodes)/len(nodes):.1f}")
    print(f"  Nodes with output:                               {nodes_with_output:>6,d}")
    print(f"    of which multi-output (>=2):                   {multi_output:>6,d}")
    print(f"  OUTPUT FILE SIZE:                                {file_size_kb:>7.1f} KB")
    print(f"  OUTPUT PATH:                                     {OUTPUT_PATH}")
    print("=" * 70)

    # ── 词形特征 ──
    print(f"\n  Term shape breakdown ({total:,d} unique):")
    print(f"    <= 2 characters:        {shape['short_le2']:>6,d}")
    print(f"    Contains digits:        {shape['with_digits']:>6,d}")
    print(f"    Non-ASCII:              {shape['non_ascii']:>6,d}")
    print(f"    Multi-word (space):     {shape['multi_word']:>6,d}")
    print(f"    Starts with punct:      {shape['starts_punct']:>6,d}")
    print(f"    Mixed case:             {shape['mixed_case']:>6,d}")

    # ── 大小写碰撞详情 ──
    if ackey_stats['case_collisions'] > 0:
        print(f"\n  Case collision details ({ackey_stats['case_collisions']} pairs, kept vs discarded):")
        for kept, discarded in sorted(ackey_stats['collision_pairs'], key=lambda x: x[0].lower()):
            print(f"    kept={kept!r:40s}  discarded={discarded!r}")

    # ── 与旧版本对比 ──
    # acbuild_0714 数据 (来自历史记录)
    old_terms = 9022
    old_nodes = 64825

    term_delta = total - old_terms
    node_delta = len(nodes) - old_nodes
    old_size_mb = 3.5
    size_delta = file_size_kb - (old_size_mb * 1024)
    print(f"\n  Compared to build 2026-07-14 (ackey_0714, 9022 lines):")
    print(f"    Terms:  {old_terms:>6,d} → {total:>6,d}  (+{term_delta:+,d})")
    print(f"    Nodes:  {old_nodes:>6,d} → {len(nodes):>6,d}  ({node_delta:+d})")
    print(f"    Size:   {old_size_mb:.1f} MB → {file_size_kb / 1024:.1f} MB  ({size_delta / 1024:+.1f} MB)")

    print(f"\n[DONE] Written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
