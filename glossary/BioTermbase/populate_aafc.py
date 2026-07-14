#!/usr/bin/env python3
"""
AAFC 词形数据注入 — pos + lemma

从 aafc_glossary.json 的 variants 字段解析词性分类和变异词形：
  - 变异词形 → 填充 lemma（指向原词头） + pos（词性标签）
  - AAFC 原词头 → 填充 lemma（自身），仅当 lemma 当前为 NULL

用法:
    cd glossary/BioTermbase
    python populate_aafc.py
"""

import os
import re
import json
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TERMS_DIR = os.path.join(SCRIPT_DIR, "..", "terms")
DB_PATH = os.path.join(SCRIPT_DIR, "BioTermbase.db")
AAFC_PATH = os.path.join(TERMS_DIR, "aafc_hym_of_the_world", "aafc_glossary.json")

# pos 标签映射：AAFC 缩写 → 数据库存储值
POS_MAP = {
    "pl": "plural",
    "adj": "adjective",
    "sing": "singular",
    "n": "noun",
    "cf": None,           # 不填充 pos
    "adv": "adverb",
    "prep": None,
}


def parse_variants(variants_text: str) -> list[tuple[str, str]]:
    """
    解析 variants 字段，返回 [(词形, pos标签), ...]。

    输入:  "pl., antennae; adj., antennal"
    输出:  [("antennae", "plural"), ("antennal", "adjective")]
    """
    results: list[tuple[str, str]] = []
    if not variants_text or not variants_text.strip():
        return results

    skip_labels = {"pl", "adj", "sing", "n", "cf", "adv", "prep"}

    for group in variants_text.split(";"):
        group = group.strip()
        if not group:
            continue

        parts = [p.strip().rstrip(".").strip() for p in group.split(",")]
        if not parts:
            continue

        # 第一个 token 是词性标签
        label = parts[0].lower()
        pos = POS_MAP.get(label)
        if pos is None and label not in skip_labels:
            pos = label  # 未知标签原样保留

        # 后续 token 是词形
        for form in parts[1:]:
            if not form:
                continue
            if form.lower() in skip_labels:
                continue
            if not re.search(r"[a-zA-Z]", form):
                continue
            results.append((form, pos))

    return results


def populate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    with open(AAFC_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    print(f"[LOAD] {len(entries)} entries from aafc_glossary.json")

    stats = {
        "lemma_headword_self": 0,
        "lemma_headword_skipped": 0,
        "lemma_variant_set": 0,
        "lemma_variant_not_found": 0,
        "pos_set": 0,
        "pos_skipped": 0,
    }

    for entry in entries:
        headword = entry.get("term", "").strip()
        if not headword:
            continue

        # ── 1. 原词头的 lemma（自身）──
        row = conn.execute(
            "SELECT lemma FROM lexicon WHERE term = ?", (headword,)
        ).fetchone()
        if row is None:
            print(f"  [WARN] Headword not in lexicon: '{headword}'")
            continue

        if row[0] is None:
            conn.execute(
                "UPDATE lexicon SET lemma = ? WHERE term = ?",
                (headword, headword),
            )
            stats["lemma_headword_self"] += 1
        else:
            stats["lemma_headword_skipped"] += 1

        # ── 2. 变异词形的 lemma + pos ──
        variants_text = entry.get("variants", "")
        parsed = parse_variants(variants_text)

        for form, pos in parsed:
            # 如果变异词形恰好 = 原词头，跳过
            if form.lower() == headword.lower():
                continue

            row = conn.execute(
                "SELECT lemma, pos FROM lexicon WHERE term = ?", (form,)
            ).fetchone()
            if row is None:
                stats["lemma_variant_not_found"] += 1
                continue

            # lemma：指向原词头（仅在 NULL 时设置）
            if row[0] is None:
                conn.execute(
                    "UPDATE lexicon SET lemma = ? WHERE term = ?",
                    (headword, form),
                )
                stats["lemma_variant_set"] += 1

            # pos：仅在 NULL 时设置
            if pos is not None and row[1] is None:
                conn.execute(
                    "UPDATE lexicon SET pos = ? WHERE term = ?",
                    (pos, form),
                )
                stats["pos_set"] += 1
            elif pos is not None:
                stats["pos_skipped"] += 1

    conn.commit()

    # ── 验证 ──
    total = conn.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]
    with_lemma = conn.execute(
        "SELECT COUNT(*) FROM lexicon WHERE lemma IS NOT NULL"
    ).fetchone()[0]
    with_pos = conn.execute(
        "SELECT COUNT(*) FROM lexicon WHERE pos IS NOT NULL"
    ).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"  Headword lemma (self):        {stats['lemma_headword_self']:>4d}")
    print(f"  Headword lemma (skipped):     {stats['lemma_headword_skipped']:>4d}")
    print(f"  Variant lemma set:            {stats['lemma_variant_set']:>4d}")
    print(f"  Variant not in lexicon:       {stats['lemma_variant_not_found']:>4d}")
    print(f"  Variant pos set:              {stats['pos_set']:>4d}")
    print(f"  Variant pos skipped:          {stats['pos_skipped']:>4d}")
    print(f"  ──────────────────────────────────")
    print(f"  Total rows:                   {total:>4d}")
    print(f"  With lemma:                   {with_lemma:>4d}")
    print(f"  With pos:                     {with_pos:>4d}")

    # ── 抽检验证 ──
    print(f"\n{'─'*60}")
    print(f"SPOT CHECKS")
    print(f"{'─'*60}")

    checks = [
        # (term, expected_lemma, expected_pos)
        ("abdomen", "abdomen", None),           # 原词头 → 自身
        ("abdominal", "abdomen", "adjective"),  # 变异词 adj
        ("abscissa", "abscissa", None),         # 原词头 → 自身
        ("abscissae", "abscissa", "plural"),    # 变异词 pl
        ("antenna", "antenna", None),           # 原词头（DSV4 已设）
        ("antennae", "antenna", "plural"),      # 变异词 pl（DSV4 已设 lemma，AAFC 补 pos）
        ("antennal", "antenna", "adjective"),   # 变异词 adj
        ("tubular vein", "tubular vein", None), # 新词头（AAFC only）
        ("apical", "apex", "adjective"),        # 变异词 adj
        ("apices", "apex", "plural"),           # 变异词 pl
        ("scapal", "scape", None),              # DSV4 变异词，AAFC 没有此词条
    ]

    for term, exp_lemma, exp_pos in checks:
        row = conn.execute(
            "SELECT term, lemma, pos FROM lexicon WHERE term = ?", (term,)
        ).fetchone()
        if row is None:
            print(f"  [MISSING] '{term}'")
            continue
        _, got_lemma, got_pos = row
        lemma_ok = got_lemma == exp_lemma
        pos_ok = got_pos == exp_pos
        status = "OK" if (lemma_ok and pos_ok) else "FAIL"
        details = []
        if not lemma_ok:
            details.append(f"lemma: got={got_lemma!r} expected={exp_lemma!r}")
        if not pos_ok:
            details.append(f"pos: got={got_pos!r} expected={exp_pos!r}")
        line = f"  [{status}] '{term}'"
        if details:
            line += " -- " + " | ".join(details)
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))

    # pos 分布统计
    pos_dist = conn.execute(
        "SELECT pos, COUNT(*) FROM lexicon WHERE pos IS NOT NULL GROUP BY pos ORDER BY COUNT(*) DESC"
    ).fetchall()
    print(f"\n{'─'*60}")
    print(f"POS DISTRIBUTION")
    print(f"{'─'*60}")
    for p, c in pos_dist:
        print(f"  {p:>12s}: {c:>4d}")

    conn.close()
    print(f"\n[DONE]")


if __name__ == "__main__":
    populate()
