#!/usr/bin/env python3
"""
BioTermbase 深度数据正确性验证 — Round 2

聚焦"已有信息但填充错误/遗漏/错乱"的恶性问题：
  A. DSV4→DB 逐条对照（IPA & lemma 是否精确写入）
  B. lemma 链校验（不能 A→B→C，超过1跳即为异常）
  C. ackey←→DB 完整性 + 多余行溯源
  D. pos 列填充自洽性
  E. 交叉数据源同一 term 的矛盾（lemma 冲突）
  F. 空串/"脏"值扫描
"""

import os
import re
import sqlite3
import sys
from collections import defaultdict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(SCRIPT_DIR, "BioTermbase.db")
ACKEY_PATH = os.path.join(SCRIPT_DIR, "ackey_0714.txt")
DSV4_PATH = os.path.join(ROOT, "terms", "hao_expand_202607", "hao_dsv4.txt")
AAFC_PATH = os.path.join(ROOT, "terms", "aafc_hym_of_the_world", "aafc_glossary.json")
HAO_KV_PATH = os.path.join(ROOT, "terms", "hao_core", "hao_for_kv.json")
MYTERM_KV_PATH = os.path.join(ROOT, "terms", "my_trem_202604", "my_term_for_kv.json")
OBO_PATH = os.path.join(ROOT, "terms", "hao_core", "hao.obo")

DIV = "=" * 66
SUB = "-" * 54


# ============================================================
# Helpers
# ============================================================

def load_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return __import__("json").load(f)


def parse_dsv4_blocks(path):
    """返回:
      names:          {NAME: block_index}   (NAME出现在哪些block, 可能多个)
      name_ipa:       {NAME: IPA}
      name_zh:        {NAME: ZH}
      inflect_map:    {INFLECT_FORM: canonical_NAME}   (取首次遇到的那个)
    """
    names = {}           # NAME -> first block index
    name_blocks = defaultdict(list)  # NAME -> [block indices]
    name_ipa = {}
    name_zh = {}
    inflect_map = {}

    blocks = []
    current = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() == "":
                if current:
                    blocks.append(current)
                    current = []
            else:
                current.append(line.strip())
        if current:
            blocks.append(current)

    for bi, block in enumerate(blocks):
        block_name = None
        block_ipa = None
        block_zh = None
        for line in block:
            if line.startswith("NAME:"):
                block_name = line.split(":", 1)[1].strip()
            elif line.startswith("PHONETC:"):
                raw = line.split(":", 1)[1].strip()
                if raw and raw not in ("/null/", "/暂无音标/"):
                    block_ipa = raw
            elif line.startswith("ZH:"):
                raw = line.split(":", 1)[1].strip()
                if raw and raw != "[待译]":
                    block_zh = raw
            elif line.startswith("INFLECT:"):
                raw = line.split(":", 1)[1].strip()
                if raw and block_name:
                    for form in raw.split("|"):
                        form = form.strip()
                        if form and form.lower() != block_name.lower():
                            if form not in inflect_map:
                                inflect_map[form] = block_name

        if block_name:
            if block_name not in names:
                names[block_name] = bi
            name_blocks[block_name].append(bi)
            if block_ipa:
                # 如果同名 NAME 出现多次，取有 IPA 的那个
                if block_name not in name_ipa:
                    name_ipa[block_name] = block_ipa
            if block_zh:
                if block_name not in name_zh:
                    name_zh[block_name] = block_zh

    return names, name_ipa, name_zh, inflect_map, name_blocks


# ============================================================
# A. DSV4 → DB 逐条 IPA 对照
# ============================================================

def check_dsv4_ipa_consistency(conn):
    print(f"\n{DIV}")
    print("A. DSV4 -> DB: IPA 逐条对照")
    print(DIV)

    names, name_ipa, name_zh, inflect_map, name_blocks = parse_dsv4_blocks(DSV4_PATH)
    c = conn.cursor()

    print(f"  DSV4 NAME 总数:         {len(names)}")
    print(f"  DSV4 NAME 有 IPA:       {len(name_ipa)}")
    print(f"  DSV4 NAME 无 IPA (即 /null/): {len(names) - len(name_ipa)}")

    # 对每个有 IPA 的 NAME，验证 DB 中 IPA 是否精确匹配
    issues_ipa = []
    for name, expected_ipa in name_ipa.items():
        c.execute("SELECT ipa FROM lexicon WHERE term = ?", (name,))
        row = c.fetchone()
        if row is None:
            issues_ipa.append((name, expected_ipa, "TERM_NOT_IN_DB", None))
        elif row[0] != expected_ipa:
            issues_ipa.append((name, expected_ipa, "IPA_MISMATCH", row[0]))

    if issues_ipa:
        print(f"\n  ** IPA 异常 ({len(issues_ipa)} 条):")
        for name, expected, reason, got in issues_ipa[:30]:
            if reason == "TERM_NOT_IN_DB":
                print(f"     [{reason}] {name!r}  — 不在 DB!")
            else:
                print(f"     [{reason}] {name!r}  expected={expected!r}  got={got!r}")
        if len(issues_ipa) > 30:
            print(f"     ... and {len(issues_ipa) - 30} more")
    else:
        print(f"\n  IPA 全部正确 — 0 mismatches")


# ============================================================
# B. DSV4 → DB: Lemma 逐条对照
# ============================================================

def check_dsv4_lemma_consistency(conn):
    print(f"\n{DIV}")
    print("B. DSV4 -> DB: Lemma 逐条对照")
    print(DIV)

    names, name_ipa, name_zh, inflect_map, name_blocks = parse_dsv4_blocks(DSV4_PATH)
    c = conn.cursor()

    # B1: 同名 NAME 出现多个 block — 数据源问题
    multi_block_names = {n: idxs for n, idxs in name_blocks.items() if len(idxs) > 1}
    if multi_block_names:
        print(f"\n  [数据源] DSV4 中同名 NAME 出现 ≥2 次: {len(multi_block_names)} 个")
        for n in sorted(multi_block_names)[:10]:
            print(f"     {n!r} 出现在 blocks {name_blocks[n]}")
        if len(multi_block_names) > 10:
            print(f"     ... and {len(multi_block_names) - 10} more")
    else:
        print(f"  同名 NAME 多次出现: 0 (OK)")

    # B2: NAME 应为 self-lemma（挑出实际不是的）
    self_violations = []
    for name in names:
        c.execute("SELECT lemma FROM lexicon WHERE term = ?", (name,))
        row = c.fetchone()
        if row is None:
            self_violations.append((name, None, "TERM_NOT_IN_DB"))
        elif row[0] != name:
            # 检查是否因为 name 同时也是某条 INFLECT 被覆盖
            if name in inflect_map and inflect_map[name] == row[0]:
                self_violations.append((name, row[0], "OVERWRITTEN_BY_INFLECT"))
            else:
                self_violations.append((name, row[0], "UNEXPECTED_LEMMA"))

    if self_violations:
        print(f"\n  ** DSV4 NAME lemma != self ({len(self_violations)} 条):")
        overwritten = [x for x in self_violations if x[2] == "OVERWRITTEN_BY_INFLECT"]
        unexpected = [x for x in self_violations if x[2] == "UNEXPECTED_LEMMA"]
        not_in_db = [x for x in self_violations if x[2] == "TERM_NOT_IN_DB"]

        if overwritten:
            print(f"\n    [OVERWRITTEN_BY_INFLECT] — {len(overwritten)} 条：")
            print(f"      这些 NAME 同时作为其他 block 的 INFLECT 出现，")
            print(f"      init_db.py 的 INFLECT→lemma 覆盖了 NAME→self。")
            for name, lemma, _ in overwritten:
                print(f"       {name!r} -> {lemma!r}")
        if unexpected:
            print(f"\n    [UNEXPECTED] — {len(unexpected)} 条（需人工排查）:")
            for name, lemma, _ in unexpected:
                print(f"       {name!r} -> {lemma!r}")
        if not_in_db:
            print(f"\n    [TERM_NOT_IN_DB] — {len(not_in_db)} 条:")
            for name, _, _ in not_in_db[:10]:
                print(f"       {name!r}")
    else:
        print(f"\n  DSV4 NAME self-lemma: 全部正确")

    # B3: INFLECT 在 DB 中的 lemma 是否正确
    inflect_issues = []
    inflect_missing_db = 0
    for infl, canonical in inflect_map.items():
        c.execute("SELECT lemma FROM lexicon WHERE term = ?", (infl,))
        row = c.fetchone()
        if row is None:
            inflect_missing_db += 1
        elif row[0] != canonical:
            inflect_issues.append((infl, canonical, row[0]))

    print(f"\n  DSV4 INFLECT 总数: {len(inflect_map)}")
    if inflect_missing_db:
        print(f"   不在 DB 中: {inflect_missing_db}")
    if inflect_issues:
        print(f"  ** INFLECT lemma 不正确 ({len(inflect_issues)} 条):")
        for infl, expected, got in inflect_issues[:20]:
            print(f"     {infl!r}  expected->{expected!r}  got->{got!r}")
        if len(inflect_issues) > 20:
            print(f"     ... and {len(inflect_issues) - 20} more")
    else:
        print(f"  INFLECT lemma 全部正确: {len(inflect_map) - inflect_missing_db} / {len(inflect_map)}")


# ============================================================
# C. Lemma 链深度校验
# ============================================================

def check_lemma_chains(conn):
    print(f"\n{DIV}")
    print("C. Lemma 链深度 — 不允许 A->B->C (>1跳)")
    print(DIV)

    c = conn.cursor()
    c.execute("SELECT term, lemma FROM lexicon WHERE lemma IS NOT NULL AND trim(lemma) != ''")
    lemma_map = {r[0]: r[1] for r in c.fetchall()}

    # 对每个 term，追踪 lemma 链直到稳定
    multi_hop = []
    cycles = []
    max_steps = 5

    for term, lemma in lemma_map.items():
        if term == lemma:
            continue  # self-ref 是终点

        visited = [term]
        current = lemma
        steps = 1
        while current != lemma_map.get(current, current) and steps < max_steps:
            if current in visited:
                cycles.append((term, visited + [current]))
                break
            visited.append(current)
            next_lemma = lemma_map.get(current)
            if next_lemma is None:
                break  # 链断了
            current = next_lemma
            steps += 1

        if steps > 1 and current not in visited:
            multi_hop.append((term, visited + [current]))

    if multi_hop:
        print(f"  ** 多跳链 ({len(multi_hop)} 条, 应 A→B 即止):")
        for term, chain in multi_hop[:15]:
            print(f"     {' → '.join(repr(x) for x in chain)}")
        if len(multi_hop) > 15:
            print(f"     ... and {len(multi_hop) - 15} more")
    else:
        print(f"  多跳链: 0 (OK)")

    if cycles:
        print(f"\n  ** 循环引用 ({len(cycles)} 条):")
        for term, chain in cycles[:10]:
            print(f"     {' → '.join(repr(x) for x in chain)}  (CYCLE)")
    else:
        print(f"  循环引用: 0 (OK)")

    # 互指检查 (A→B, B→A)
    mutual = []
    for a in lemma_map:
        b = lemma_map[a]
        if a != b and b in lemma_map:
            if lemma_map[b] == a:
                mutual.append((a, b))
    if mutual:
        print(f"\n  ** 互指对 ({len(mutual)} 对, A→B 且 B→A):")
        for a, b in mutual[:10]:
            print(f"     {a!r} ⇄ {b!r}")
    else:
        print(f"  互指对: 0 (OK)")


# ============================================================
# D. ackey ↔ DB 精确对齐 + 多余行溯源
# ============================================================

def check_ackey_alignment(conn):
    print(f"\n{DIV}")
    print("D. ackey_0714.txt ↔ DB 精确对齐")
    print(DIV)

    ackey = set(load_lines(ACKEY_PATH))
    c = conn.cursor()
    c.execute("SELECT term FROM lexicon")
    db_terms = set(r[0] for r in c.fetchall())

    only_db = db_terms - ackey
    only_ackey = ackey - db_terms

    print(f"  ackey 行数:      {len(ackey)}")
    print(f"  DB 行数:          {len(db_terms)}")
    print(f"  DB 多余:          {len(only_db)}")
    print(f"  ackey 多余:       {len(only_ackey)}")

    if only_ackey:
        print(f"\n  ** ackey 有但 DB 无: {len(only_ackey)}")
        for t in sorted(only_ackey)[:15]:
            print(f"     {t!r}")
        if len(only_ackey) > 15:
            print(f"     ... and {len(only_ackey) - 15} more")

    # 溯源 DB 多余的 31 条 → 是否来自 AAFC
    if only_db:
        # Load AAFC terms
        aafc_terms = set()
        if os.path.exists(AAFC_PATH):
            aafc = load_json(AAFC_PATH)
            for e in aafc.get("entries", []):
                aafc_terms.add(e.get("term", ""))
                variants = e.get("variants", "")
                if variants:
                    for v in variants.replace("adj.,", "").replace("pl.,", "").replace("adj.", "").replace("pl.", "").split(","):
                        v = v.strip()
                        if v:
                            aafc_terms.add(v)

        # Also check OBO synonyms (might have been added to ackey, but some new)
        obo_syns = set()
        if os.path.exists(OBO_PATH):
            syn_pat = re.compile(r'^synonym:\s*"([^"]*)"')
            with open(OBO_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    m = syn_pat.match(line)
                    if m:
                        obo_syns.add(m.group(1).strip())

        print(f"\n  DB 多余的 31 条来源分析:")
        matched_aafc = []
        matched_obo = []
        unmatched = []
        for t in sorted(only_db):
            sources = []
            if t in aafc_terms:
                sources.append("AAFC")
                matched_aafc.append(t)
            if t in obo_syns:
                sources.append("OBO")
                matched_obo.append(t)
            if not sources:
                sources.append("UNKNOWN")
                unmatched.append(t)
            if t in matched_aafc or t in unmatched:  # print only once
                flag = "  OK" if sources != ["UNKNOWN"] else "  ??"
                print(f"     {flag}  {t!r}  ← {', '.join(sources)}")

        print(f"\n  归因:   AAFC={len(matched_aafc)}, OBO-new={len(matched_obo)}, UNKNOWN={len(unmatched)}")


# ============================================================
# E. 脏值扫描
# ============================================================

def check_dirty_values(conn):
    print(f"\n{DIV}")
    print("E. 脏值扫描 — 空串 / null-like / 乱码")
    print(DIV)

    c = conn.cursor()

    # 空串 (应该 NULL 但实际是 '')
    for col in ["lemma", "pos", "ipa", "etymology", "language"]:
        c.execute(f"SELECT COUNT(*) FROM lexicon WHERE {col} = ''")
        n = c.fetchone()[0]
        if n > 0:
            print(f"  ** {col}: {n} 行 = '' (空串而非 NULL)")

    # IPA 明显异常值
    c.execute("SELECT term, ipa FROM lexicon WHERE ipa IS NOT NULL AND ipa != ''")
    bad_ipa = []
    for term, ipa in c.fetchall():
        stripped = ipa.strip()
        if stripped in ("/null/", "/暂无音标/", "null", "/null", "//"):
            bad_ipa.append((term, stripped, "PLACEHOLDER"))
        elif len(stripped) < 4:
            bad_ipa.append((term, stripped, "TOO_SHORT"))
        elif not stripped.startswith("/"):
            bad_ipa.append((term, stripped, "NO_SLASH_START"))
        elif not stripped.endswith("/"):
            bad_ipa.append((term, stripped, "NO_SLASH_END"))
    if bad_ipa:
        print(f"\n  ** IPA 脏值 ({len(bad_ipa)}):")
        for term, val, reason in bad_ipa[:15]:
            print(f"     [{reason}] {term!r}  ipa={val!r}")
        if len(bad_ipa) > 15:
            print(f"     ... and {len(bad_ipa) - 15} more")
    else:
        print(f"  IPA 脏值: 0 (OK)")

    # pos 值白名单检查
    c.execute("SELECT DISTINCT pos FROM lexicon WHERE pos IS NOT NULL AND trim(pos) != ''")
    pos_vals = [r[0] for r in c.fetchall()]
    valid_pos = {"adjective", "plural", "noun", "verb", "pronoun", "adverb", "preposition"}
    bad_pos = [v for v in pos_vals if v.lower() not in valid_pos and v.lower() not in {""," "}]
    if bad_pos:
        print(f"\n  ** pos 非标准值: {bad_pos}")
    else:
        print(f"  pos 标准值: {pos_vals} (OK)")

    # term 空白/纯空格
    c.execute("SELECT term FROM lexicon WHERE trim(term) = ''")
    blank = c.fetchall()
    if blank:
        print(f"  ** 空白 term: {len(blank)} 行")

    # term 含控制字符
    c.execute("SELECT term FROM lexicon WHERE term LIKE '%' || char(10) || '%' "
              "OR term LIKE '%' || char(13) || '%' OR term LIKE '%' || char(9) || '%'")
    ctrl = c.fetchall()
    if ctrl:
        print(f"  ** term 含控制字符 (\\n \\r \\t): {len(ctrl)}")
        for r in ctrl[:10]:
            print(f"     {r[0]!r}")


# ============================================================
# F. 数据源冲突 — 同一 term 在不同源中的 lemma 矛盾
# ============================================================

def check_cross_source_conflict(conn):
    print(f"\n{DIV}")
    print("F. 跨数据源 lemma 冲突检查")
    print(DIV)

    names, name_ipa, name_zh, inflect_map, name_blocks = parse_dsv4_blocks(DSV4_PATH)
    c = conn.cursor()

    # 找出: 一个 term 既是 DSV4 NAME（应 self-lemma），
    #        又是 DSV4 INFLECT（指向另一个 canonical）→ 这叫 OVERWRITTEN，已在前面对照中报告
    #
    # 新角度: OBO synonym 中是否有同形词被当成了不同东西？
    # 实际上当前 DB 没有 concepts 表，无法检测概念级冲突。
    # 这里只做词形级的冗余检查。

    c.execute("SELECT term, lemma FROM lexicon WHERE lemma IS NOT NULL AND lemma != term")
    cross_rows = c.fetchall()

    # 检查: canonical form 本身是否在 DB 中有正确的 self-lemma
    canon_issues = []
    canon_set = set()
    for term, lemma in cross_rows:
        canon_set.add(lemma)
    for canon in canon_set:
        c.execute("SELECT lemma FROM lexicon WHERE term = ?", (canon,))
        row = c.fetchone()
        if row is None:
            canon_issues.append((canon, "CANONICAL_NOT_IN_DB"))
        elif row[0] != canon:
            canon_issues.append((canon, f"CANONICAL_HAS_WRONG_LEMMA: {row[0]!r}"))

    if canon_issues:
        print(f"  ** Canonical 词形自身 lemma 异常 ({len(canon_issues)}):")
        for canon, reason in canon_issues[:20]:
            print(f"     {canon!r}  — {reason}")
        if len(canon_issues) > 20:
            print(f"     ... and {len(canon_issues) - 20} more")
    else:
        print(f"  Canonical lemma 自洽: {len(canon_set)} canonical forms, all OK")

    # DSV4 canonical forms 的自我一致性
    dsv4_canon = set(inflect_map.values()) | set(names.keys())
    dsv4_canon_issues = []
    for canon in dsv4_canon:
        c.execute("SELECT lemma FROM lexicon WHERE term = ?", (canon,))
        row = c.fetchone()
        if row is None:
            # Canonical 不在 DB — 可能是 INFLECT->lemma 指向了 DB 中没有的词
            dsv4_canon_issues.append((canon, "CANONICAL_NOT_IN_DB"))
        elif row[0] != canon:
            dsv4_canon_issues.append((canon, f"lemma={row[0]!r}"))
    if dsv4_canon_issues:
        print(f"\n  ** DSV4 canonical 异常 ({len(dsv4_canon_issues)}):")
        for canon, reason in dsv4_canon_issues[:20]:
            print(f"     {canon!r}  — {reason}")
        if len(dsv4_canon_issues) > 20:
            print(f"     ... and {len(dsv4_canon_issues) - 20} more")
    else:
        print(f"  DSV4 canonical: {len(dsv4_canon)} forms, all OK")


# ============================================================
# Main
# ============================================================

def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    try:
        check_dsv4_ipa_consistency(conn)
        check_dsv4_lemma_consistency(conn)
        check_lemma_chains(conn)
        check_ackey_alignment(conn)
        check_dirty_values(conn)
        check_cross_source_conflict(conn)
    finally:
        conn.close()

    print(f"\n{DIV}")
    print("ROUND 2 COMPLETE")
    print(DIV)


if __name__ == "__main__":
    main()
