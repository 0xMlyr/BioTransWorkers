#!/usr/bin/env python3
"""
AC自动机构建脚本（扩展版）
从 glossary/terms/ 下的五个数据源提取全部词形，构建Aho-Corasick自动机，
序列化为 ac_trie.json 供 Cloudflare Worker 使用。

新增数据源：
  - hao.obo          → 提取所有 synonym 行中的同义异名词形
  - hao_dsv4.txt     → 提取所有 INFLECT 行的词形变体（复数、形容词化等）

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

# 新增数据源
OBO_PATH = os.path.join(TERMS_DIR, "hao_core", "hao.obo")
DSV4_PATH = os.path.join(TERMS_DIR, "hao_expand_202607", "hao_dsv4.txt")

OUTPUT_PATH = os.path.join(SCRIPT_DIR, "ac_trie.json")


# ── Step 1: 从 OBO 提取 synonym ────────────────────────────
def extract_obo_synonyms(obo_path: str) -> list[str]:
    """
    从 hao.obo 解析所有 synonym 行，提取引号内的词形文本。
    OBO synonym 行格式:
        synonym: "text" [TYPE] [ref, ...]
        synonym: "der Hinterleib" [http://api.hymao.org/api/ref/78598]
    仅提取第一对双引号之间的文本。
    """
    synonyms: list[str] = []
    if not os.path.exists(obo_path):
        print(f"[WARN] OBO file not found, skipping: {obo_path}")
        return synonyms

    synonym_pattern = re.compile(r'^synonym:\s*"([^"]*)"')
    with open(obo_path, "r", encoding="utf-8") as f:
        for line in f:
            m = synonym_pattern.match(line)
            if m:
                text = m.group(1).strip()
                if text:
                    synonyms.append(text)

    print(f"[LOAD] {os.path.basename(obo_path)}: extracted {len(synonyms)} synonym forms")
    return synonyms


# ── Step 2: 从 DSV4 提取 INFLECT ──────────────────────────
def extract_dsv4_inflects(dsv4_path: str) -> list[str]:
    """
    从 hao_dsv4.txt 解析所有 INFLECT 行，提取词形变体。
    INFLECT 行格式:
        INFLECT:anatomical structures|anatomically structural
        INFLECT:scape
    以 "|" 分隔多个变体。
    """
    inflects: list[str] = []
    if not os.path.exists(dsv4_path):
        print(f"[WARN] DSV4 file not found, skipping: {dsv4_path}")
        return inflects

    with open(dsv4_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("INFLECT:"):
                continue
            raw = line.split(":", 1)[1].strip()
            if not raw:
                continue
            for form in raw.split("|"):
                form = form.strip()
                # 只接受至少含有一个英文字母的文本
                if form and re.search(r'[a-zA-Z]', form):
                    inflects.append(form)

    print(f"[LOAD] {os.path.basename(dsv4_path)}: extracted {len(inflects)} inflection forms")
    return inflects


# ── Step 3: 提取所有原始 key（保留原始大小写）─────────────
def extract_keys() -> dict[str, str]:
    """
    从三个基础数据源提取所有英文术语key，构建 {小写: 原始大小写} 映射。
    同一小写key出现多种大小写时，优先保留非全小写的变体。
    """
    case_map: dict[str, str] = {}

    for src_path in SOURCES:
        if not os.path.exists(src_path):
            print(f"[WARN] Source not found, skipping: {src_path}")
            continue

        if src_path.endswith(".json"):
            with open(src_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data:
                if "key" in entry and isinstance(entry["key"], str):
                    key = entry["key"]
                    lower = key.lower()
                    if lower not in case_map or (
                        case_map[lower] == case_map[lower].lower() and key != key.lower()
                    ):
                        case_map[lower] = key
            print(f"[LOAD] {os.path.basename(src_path)}: extracted {len(data)} entries")

        elif src_path.endswith(".txt"):
            with open(src_path, "r", encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term and re.match(r'^[a-zA-Z\s\-]+$', term):
                        lower = term.lower()
                        if lower not in case_map or (
                            case_map[lower] == case_map[lower].lower() and term != term.lower()
                        ):
                            case_map[lower] = term
            print(f"[LOAD] {os.path.basename(src_path)}: loaded text terms")

    return case_map


def merge_terms(case_map: dict[str, str], new_terms: list[str], source_label: str) -> dict[str, str]:
    """
    将新词形列表合并到 case_map 中。
    返回被合并入的 {key: count} 统计。
    """
    added = 0
    overwritten = 0
    skipped = 0

    for term in new_terms:
        lower = term.lower()
        if lower not in case_map:
            # 全新词形
            case_map[lower] = term
            added += 1
        elif case_map[lower] == case_map[lower].lower() and term != term.lower():
            # 已有全小写变体，新变体有大小写 → 取而代之
            case_map[lower] = term
            overwritten += 1
        else:
            # 已存在且大小写策略不允许覆盖
            skipped += 1

    print(f"[MERGE] {source_label}: +{added} new, {overwritten} case-overwrite, {skipped} skipped (already in map)")
    return case_map


# ── Step 4: 构建AC自动机 ──────────────────────────────────
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

    print(f"[FAIL] Failure links built for {len(nodes)} nodes")
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
    print("AC Automaton Builder (Extended — OBO synonyms + DSV4 inflections)")
    print("=" * 70)

    stats: dict[str, int] = {}

    # ── 1. 提取基础 key ──
    print("\n--- Step 1: Extract base keys ---")
    case_map = extract_keys()
    base_count = len(case_map)
    stats["base_keys"] = base_count
    print(f"[STAT] Base unique keys (hao_core + my_term + engine_test): {base_count}")

    if not case_map:
        print("[ERROR] No terms found in base sources!")
        return

    # ── 2. 提取 OBO synonym ──
    print("\n--- Step 2: Extract OBO synonyms ---")
    obo_synonyms = extract_obo_synonyms(OBO_PATH)
    stats["obo_synonym_raw"] = len(obo_synonyms)
    case_map_before_obo = len(case_map)
    merge_terms(case_map, obo_synonyms, "OBO synonyms")
    stats["after_obo"] = len(case_map)
    stats["obo_new"] = stats["after_obo"] - case_map_before_obo

    # ── 3. 提取 DSV4 INFLECT ──
    print("\n--- Step 3: Extract DSV4 INFLECT forms ---")
    dsv4_inflects = extract_dsv4_inflects(DSV4_PATH)
    stats["dsv4_inflect_raw"] = len(dsv4_inflects)
    case_map_before_dsv4 = len(case_map)
    merge_terms(case_map, dsv4_inflects, "DSV4 inflections")
    stats["after_dsv4"] = len(case_map)
    stats["dsv4_new"] = stats["after_dsv4"] - case_map_before_dsv4

    total = len(case_map)
    stats["total_unique"] = total

    # ── 4. 额外统计 ──
    # OBO synonym 中有多少已在 base 中
    base_lower_set = set()
    for src_path in SOURCES:
        if not os.path.exists(src_path):
            continue
        if src_path.endswith(".json"):
            with open(src_path, "r", encoding="utf-8") as f:
                for entry in json.load(f):
                    if "key" in entry and isinstance(entry["key"], str):
                        base_lower_set.add(entry["key"].lower())
        elif src_path.endswith(".txt"):
            with open(src_path, "r", encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term:
                        base_lower_set.add(term.lower())

    obo_overlap = sum(1 for s in obo_synonyms if s.lower() in base_lower_set)
    stats["obo_overlap_with_base"] = obo_overlap

    dsv4_overlap = sum(1 for f in dsv4_inflects if f.lower() in base_lower_set)
    stats["dsv4_overlap_with_base"] = dsv4_overlap

    # OBO 和 DSV4 之间的重叠
    obo_lower_set = set(s.lower() for s in obo_synonyms)
    dsv4_lower_set = set(f.lower() for f in dsv4_inflects)
    cross_overlap = len(obo_lower_set & dsv4_lower_set)
    stats["obo_dsv4_cross_overlap"] = cross_overlap

    # ── 5. 构建 Trie ──
    print("\n--- Step 5: Build Trie ---")
    nodes = build_trie(case_map)

    # ── 6. 构建 failure 指针 ──
    print("\n--- Step 6: Build failure links ---")
    nodes = build_failure_links(nodes)

    # ── 7. 序列化 ──
    print("\n--- Step 7: Serialize ---")
    trie_data = serialize(nodes, total)
    json_str = json.dumps(trie_data, ensure_ascii=False, separators=(",", ":"))
    file_size_kb = len(json_str) / 1024
    print(f"[SIZE] JSON size: {len(json_str):,} bytes ({file_size_kb:.1f} KB)")

    # ── 8. 验证 ──
    print("\n--- Step 8: Verify ---")
    verify(trie_data, [
        ("The propodeum is lateral to the pleuron", ["propodeum", "pleuron"]),
        ("Median area of propodeum: evenly reticulate", ["area", "median", "propodeum", "reticulate"]),
        ("The Mesopleuron is located posterior", ["mesopleuron"]),
        ("fore wing venation of Chalcidoidea", ["fore wing venation", "Chalcidoidea"]),
        ("The abdomen is segmented", ["abdomen"]),
        ("No terms here", []),
        ("PROPODEUM and Propodeum and propodeum", ["propodeum"]),
        # OBO synonym 匹配验证
        ("The whole organism displays polymorphism", ["whole organism"]),
        # DSV4 INFLECT 复数形式匹配验证
        ("Several anatomical structures are visible", ["anatomical structures"]),
        # DSV4 INFLECT 形容词形式匹配验证（"anatomically structural" 是整体匹配）
        ("The anatomically structural components vary", ["anatomically structural"]),
        # 大小写：OBO synonym 保留原始大小写 (der Hinterleib 为德语)
        ("Der Hinterleib ist segmentiert", ["der Hinterleib"]),
    ])

    # ── 9. 写入文件 ──
    print(f"\n--- Step 9: Write output ---")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(json_str)

    # ── 10. 统计数据报告 ──
    print()
    print("=" * 70)
    print("BUILD SUMMARY")
    print("=" * 70)
    print(f"  Base keys (hao_core + my_term + engine_test):    {stats['base_keys']:>6,d}")
    print(f"  OBO synonyms extracted (raw):                    {stats['obo_synonym_raw']:>6,d}")
    print(f"  OBO synonyms net new (not in base):              {stats['obo_new']:>6,d}")
    print(f"    (of which already in base:                     {stats['obo_overlap_with_base']:>6,d})")
    print(f"  DSV4 INFLECT forms extracted (raw):              {stats['dsv4_inflect_raw']:>6,d}")
    print(f"  DSV4 INFLECT net new (not in prior):             {stats['dsv4_new']:>6,d}")
    print(f"    (of which already in base:                     {stats['dsv4_overlap_with_base']:>6,d})")
    print(f"  Cross-overlap (OBO ∩ DSV4, lowercased):          {stats['obo_dsv4_cross_overlap']:>6,d}")
    print(f"  ───────────────────────────────────────────────────────")
    print(f"  TOTAL UNIQUE TERMS IN TRIE:                      {stats['total_unique']:>6,d}")
    print(f"  TOTAL NODES:                                     {len(nodes):>6,d}")
    print(f"  OUTPUT FILE SIZE:                                {file_size_kb:>7.1f} KB")
    print(f"  OUTPUT PATH:                                     {OUTPUT_PATH}")
    print("=" * 70)

    # 计算增量
    increase = stats["total_unique"] - stats["base_keys"]
    increase_pct = (increase / stats["base_keys"]) * 100 if stats["base_keys"] else 0
    print(f"\n[GROWTH] Trie expanded from {stats['base_keys']:,d} to {stats['total_unique']:,d} terms")
    print(f"[GROWTH] Net increase: +{increase:,d} terms (+{increase_pct:.1f}%)")
    print(f"[DONE] Written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
