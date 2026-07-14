#!/usr/bin/env python3
"""
fix_db.py — 执行两项修复：
  1. 覆写 3 条来自 DSV4 的正确 IPA
  2. 清空全部 lemma 列 (SET NULL)
"""

import os
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(SCRIPT_DIR, "BioTermbase.db")

# 任务一：DSV4 正确 IPA
IPA_FIXES = {
    "cardo":          "/ˈkɑːdəʊ/",
    "margin":         "/ˈmɑːdʒɪn/",
    "mesepisternum":  "/ˌmɛsˌɛpɪˈstɜːnəm/",
}


def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── 任务一：覆写 3 条 IPA ──
    print("=" * 56)
    print("TASK 1: Fix 3 IPA mismatches (DSV4 as source of truth)")
    print("=" * 56)
    for term, correct_ipa in IPA_FIXES.items():
        c.execute("SELECT ipa FROM lexicon WHERE term = ?", (term,))
        row = c.fetchone()
        if row is None:
            print(f"  [SKIP] {term!r} — not in DB")
            continue
        old_ipa = row[0]
        if old_ipa == correct_ipa:
            print(f"  [SKIP] {term!r} — already correct ({correct_ipa})")
            continue
        c.execute("UPDATE lexicon SET ipa = ? WHERE term = ?", (correct_ipa, term))
        print(f"  [FIXED] {term!r}: {old_ipa!r} -> {correct_ipa!r}")

    conn.commit()

    # ── 任务二：清空全部 lemma ──
    print(f"\n{'=' * 56}")
    print("TASK 2: Clear ALL lemma values (SET NULL)")
    print("=" * 56)

    c.execute("SELECT COUNT(*) FROM lexicon WHERE lemma IS NOT NULL")
    before = c.fetchone()[0]
    print(f"  Before: {before} rows with lemma")

    c.execute("UPDATE lexicon SET lemma = NULL")
    conn.commit()

    c.execute("SELECT COUNT(*) FROM lexicon WHERE lemma IS NOT NULL")
    after = c.fetchone()[0]
    print(f"  After:  {after} rows with lemma")
    print(f"  Cleared: {before} rows")

    conn.close()
    print(f"\n[DONE]")


if __name__ == "__main__":
    main()
