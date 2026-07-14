#!/usr/bin/env python3
"""
BioTermbase D1 数据库抽样验证脚本

目标状态 (v3 三层架构):
  lexicon           — 词形层：term(PK), lemma(FK→lexicon), pos, ipa, etymology, language
  concepts          — 概念层：concept_id(PK), domain, source_ontology, confidence_tier
  term_concept_map  — 关联层：term(FK→lexicon), concept_id(FK→concepts), relation_type

当前状态: 仅有 lexicon，缺 concepts / term_concept_map。
"""

import json
import os
import re
import sqlite3
import sys

# Windows console may choke on IPA unicode; force utf-8 or fallback
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def safe_str(s):
    """Return str safe for printing on any console."""
    if s is None:
        return "None"
    try:
        # try encoding as-is
        return str(s)
    except UnicodeEncodeError:
        return s.encode("ascii", errors="replace").decode("ascii")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(SCRIPT_DIR, "BioTermbase.db")
ACKEY_PATH = os.path.join(SCRIPT_DIR, "ackey_0714.txt")
AC_TRIE_PATH = os.path.join(ROOT, "automaton", "ac_trie.json")
DSV4_PATH = os.path.join(ROOT, "terms", "hao_expand_202607", "hao_dsv4.txt")
HAO_KV_PATH = os.path.join(ROOT, "terms", "hao_core", "hao_for_kv.json")
MYTERM_KV_PATH = os.path.join(ROOT, "terms", "my_trem_202604", "my_term_for_kv.json")
HAO_OBO_PATH = os.path.join(ROOT, "terms", "hao_core", "hao.obo")


# ============================================================
# Helpers
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_ackey_set():
    return set(load_lines(ACKEY_PATH))


def fmt_pct(n, total):
    if total == 0:
        return "N/A"
    return f"{n} ({n / total * 100:.1f}%)"


# ============================================================
# 1. 表结构检查
# ============================================================

def check_schema(conn):
    print("=" * 66)
    print("1. SCHEMA — 表结构检查")
    print("=" * 66)

    c = conn.cursor()
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r[0]: r[1] for r in c.fetchall()}

    expected = {"lexicon", "concepts", "term_concept_map"}
    existing = set(tables.keys())
    missing = expected - existing
    extra = existing - expected

    print(f"  Expected tables:  {sorted(expected)}")
    print(f"  Existing tables:  {sorted(existing)}")

    if missing:
        print(f"\n  ** MISSING TABLES: {sorted(missing)} **")
        for t in sorted(missing):
            print(f"     - {t}: 未创建 (v3 已设计, 待实施)")
    if extra:
        print(f"  Extra tables (unexpected): {sorted(extra)}")

    # 验证 lexicon 列
    if "lexicon" in tables:
        c.execute("PRAGMA table_info(lexicon)")
        cols = {r[1]: r[2] for r in c.fetchall()}
        print(f"\n  lexicon columns: { {k: v for k, v in cols.items()} }")
        expected_cols = {"term": "TEXT", "lemma": "TEXT", "pos": "TEXT",
                         "ipa": "TEXT", "etymology": "TEXT", "language": "TEXT"}
        for col, etype in expected_cols.items():
            if col not in cols:
                print(f"     ** MISSING column: {col}")
            elif cols[col] != etype:
                print(f"     ** TYPE MISMATCH: {col} (got {cols[col]}, expected {etype})")

        # PK
        c.execute("PRAGMA index_list(lexicon)")
        idxs = c.fetchall()
        print(f"  lexicon indices: {[(r[1], r[2]) for r in idxs]}")


# ============================================================
# 2. 行数一致性
# ============================================================

def check_row_counts(conn):
    print("\n" + "=" * 66)
    print("2. ROW COUNTS — 行数一致性")
    print("=" * 66)

    ackey = load_ackey_set()
    c = conn.cursor()
    c.execute("SELECT term FROM lexicon")
    db_terms = set(r[0] for r in c.fetchall())

    print(f"  ackey_0714.txt 行数:           {len(ackey):>6}")
    print(f"  lexicon 表行数:                {len(db_terms):>6}")

    in_ackey_not_db = ackey - db_terms
    in_db_not_ackey = db_terms - ackey

    if in_ackey_not_db:
        print(f"\n  ** ackey 有但 DB 无: {len(in_ackey_not_db)} 条")
        for t in sorted(in_ackey_not_db)[:10]:
            print(f"     - {t!r}")
        if len(in_ackey_not_db) > 10:
            print(f"     ... and {len(in_ackey_not_db) - 10} more")

    if in_db_not_ackey:
        print(f"\n  ** DB 有但 ackey 无: {len(in_db_not_ackey)} 条")
        for t in sorted(in_db_not_ackey)[:20]:
            print(f"     - {t!r}")
        if len(in_db_not_ackey) > 20:
            print(f"     ... and {len(in_db_not_ackey) - 20} more")

    # dups
    c.execute("SELECT term, COUNT(*) c FROM lexicon GROUP BY term HAVING c > 1")
    dups = c.fetchall()
    if dups:
        print(f"\n  ** DUPLICATE terms: {len(dups)}")
        for t, cnt in dups[:10]:
            print(f"     {t!r} ×{cnt}")
    else:
        print(f"\n  Duplicates: 0 (OK)")


# ============================================================
# 3. Lexicon 列填充质量
# ============================================================

def check_column_quality(conn):
    print("\n" + "=" * 66)
    print("3. COLUMN QUALITY — lexicon 列填充质量")
    print("=" * 66)

    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM lexicon")
    total = c.fetchone()[0]

    for col in ["lemma", "pos", "ipa", "etymology", "language"]:
        c.execute(f"SELECT COUNT(*) FROM lexicon WHERE {col} IS NOT NULL AND trim({col}) != ''")
        n = c.fetchone()[0]
        print(f"  {col:<12} : {fmt_pct(n, total)}")


# ============================================================
# 4. Lemma 引用完整性
# ============================================================

def check_lemma_integrity(conn):
    print("\n" + "=" * 66)
    print("4. LEMMA INTEGRITY — lemma 引用完整性")
    print("=" * 66)

    c = conn.cursor()
    c.execute("SELECT term, lemma FROM lexicon WHERE lemma IS NOT NULL AND trim(lemma) != ''")
    rows = c.fetchall()
    c.execute("SELECT term FROM lexicon")
    all_terms = {r[0] for r in c.fetchall()}

    total_lemma = len(rows)
    print(f"  带 lemma 的行: {total_lemma}")

    self_ref = sum(1 for t, l in rows if t == l)
    cross_ref = total_lemma - self_ref
    print(f"    self-references  (lemma = term):  {self_ref}")
    print(f"    cross-references (lemma != term): {cross_ref}")

    # 悬空 lemma
    dangling = [(t, l) for t, l in rows if l not in all_terms]
    if dangling:
        print(f"\n  ** DANGLING lemmas (lemma not in lexicon): {len(dangling)}")
        for t, l in dangling[:20]:
            print(f"     term={t!r}  →  lemma={l!r} (NOT FOUND)")
        if len(dangling) > 20:
            print(f"     ... and {len(dangling) - 20} more")
    else:
        print(f"\n  Dangling lemmas: 0 (OK)")

    # 抽样: random 10 cross-ref terms
    import random
    cross = [(t, l) for t, l in rows if t != l]
    if cross:
        sample = random.sample(cross, min(10, len(cross)))
        print(f"\n  抽样 cross-reference 示例:")
        for t, l in sample:
            print(f"    {t!r}  →  {l!r}")


# ============================================================
# 5. IPA 格式校验
# ============================================================

def check_ipa_quality(conn):
    print("\n" + "=" * 66)
    print("5. IPA QUALITY — 音标格式校验")
    print("=" * 66)

    c = conn.cursor()
    c.execute("SELECT term, ipa FROM lexicon WHERE ipa IS NOT NULL AND trim(ipa) != ''")
    rows = c.fetchall()

    print(f"  IPA entries: {len(rows)}")

    bad = []
    null_like = 0
    for term, ipa in rows:
        stripped = ipa.strip()
        # /null/ 类占位符
        if stripped in ("/null/", "/暂无音标/", "null", "/null"):
            null_like += 1
        # not enclosed in //
        elif not (stripped.startswith("/") and stripped.endswith("/")):
            bad.append((term, stripped))

    print(f"    null-placeholders: {null_like}")
    if bad:
        print(f"    Non-//-wrapped:    {len(bad)}")
        for t, v in bad[:10]:
            print(f"      {t!r}: {v}")
        if len(bad) > 10:
            print(f"      ... and {len(bad) - 10} more")
    else:
        print(f"    Non-//-wrapped: 0 (OK)")

    # duplicate IPAs: different terms sharing same IPA (may be suspicious)
    ipa_map = {}
    for term, ipa in rows:
        ipa_map.setdefault(ipa.strip(), []).append(term)
    dup_ipa = [(ipa, terms) for ipa, terms in ipa_map.items() if len(terms) > 1]
    dup_ipa.sort(key=lambda x: -len(x[1]))
    if dup_ipa:
        print(f"\n    Duplicate IPA values (shared by ≥2 terms): {len(dup_ipa)} groups")
        for ipa, terms in dup_ipa[:5]:
            try:
                print(f"      {ipa}")
            except UnicodeEncodeError:
                print(f"      {ipa.encode('ascii','replace').decode('ascii')}")
            print(f"        -> {terms[:5]}")
    else:
        print(f"\n    Duplicate IPA: 0 (OK)")


# ============================================================
# 6. 特殊词形检查
# ============================================================

def check_term_shapes(conn):
    print("\n" + "=" * 66)
    print("6. TERM SHAPES — 特殊词形检查")
    print("=" * 66)

    c = conn.cursor()
    c.execute("SELECT term FROM lexicon")
    all_terms = [r[0] for r in c.fetchall()]

    short = [t for t in all_terms if len(t) <= 2]
    with_digits = [t for t in all_terms if re.search(r'\d', t)]
    multibyte = [t for t in all_terms if not all(ord(ch) < 128 for ch in t)]
    has_space = [t for t in all_terms if ' ' in t]
    starts_punct = [t for t in all_terms if t and not t[0].isalnum()]
    mixed_case = [t for t in all_terms if t != t.lower() and t != t.upper()]

    print(f"  ≤2 chars:           {len(short)}")
    if short:
        print(f"    {short[:15]}")
    print(f"  contains digit:     {len(with_digits)}")
    if with_digits:
        print(f"    {with_digits[:10]}")
    print(f"  non-ASCII:          {len(multibyte)}")
    if multibyte:
        print(f"    {multibyte[:10]}")
    print(f"  multi-word (space): {len(has_space)}")
    print(f"  starts with punct:  {len(starts_punct)}")
    if starts_punct:
        print(f"    {starts_punct[:10]}")
    print(f"  mixed case:         {len(mixed_case)}")
    if mixed_case:
        print(f"    {mixed_case[:10]}")


# ============================================================
# 7. AC Trie ↔ DB 对照
# ============================================================

def check_ac_trie_consistency(conn):
    print("\n" + "=" * 66)
    print("7. AC TRIE ↔ DB — 一致性对照")
    print("=" * 66)

    if not os.path.exists(AC_TRIE_PATH):
        print(f"  ** ac_trie.json not found at {AC_TRIE_PATH}")
        return

    ac = load_json(AC_TRIE_PATH)
    c = conn.cursor()

    # 从 Trie output 收集所有术语
    trie_terms = set()
    for node in ac.get("trie", []):
        for t in node.get("output", []):
            trie_terms.add(t)

    print(f"  Trie 中术语 (unique output): {len(trie_terms)}")
    print(f"  Trie metadata term_count:     {ac.get('term_count', 'N/A')}")
    print(f"  Trie 节点数:                  {ac.get('node_count', 'N/A')}")

    c.execute("SELECT term FROM lexicon")
    db_terms = set(r[0] for r in c.fetchall())

    in_trie_not_db = trie_terms - db_terms
    in_db_not_trie = db_terms - trie_terms

    if in_trie_not_db:
        print(f"\n  ** Trie有但DB无: {len(in_trie_not_db)} 条")
        for t in sorted(in_trie_not_db)[:15]:
            print(f"     - {t!r}")
        if len(in_trie_not_db) > 15:
            print(f"     ... and {len(in_trie_not_db) - 15} more")
    else:
        print(f"\n  Trie有但DB无: 0 (OK)")

    if in_db_not_trie:
        print(f"  DB有但Trie无:   {len(in_db_not_trie)} 条")
        for t in sorted(in_db_not_trie)[:15]:
            print(f"     - {t!r}")
        if len(in_db_not_trie) > 15:
            print(f"     ... and {len(in_db_not_trie) - 15} more")


# ============================================================
# 8. DSV4 数据源对照
# ============================================================

def check_dsv4_coverage(conn):
    print("\n" + "=" * 66)
    print("8. DSV4 COVERAGE — 翻译数据覆盖度")
    print("=" * 66)

    if not os.path.exists(DSV4_PATH):
        print(f"  ** hao_dsv4.txt not found at {DSV4_PATH}")
        return

    c = conn.cursor()

    # 解析 DSV4
    blocks = []
    current = []
    with open(DSV4_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() == "":
                if current:
                    blocks.append(current)
                    current = []
            else:
                current.append(line.strip())
        if current:
            blocks.append(current)

    names = []
    name_set = set()
    inflects = set()
    name_ipa = {}

    for block in blocks:
        name = None
        ipa = None
        for line in block:
            if line.startswith("NAME:"):
                name = line.split(":", 1)[1].strip()
                if name not in name_set:
                    names.append(name)
                    name_set.add(name)
            elif line.startswith("PHONETC:"):
                raw = line.split(":", 1)[1].strip()
                if raw and raw != "/null/" and raw != "/暂无音标/":
                    ipa = raw
            elif line.startswith("INFLECT:"):
                raw = line.split(":", 1)[1].strip()
                if raw:
                    for form in raw.split("|"):
                        form = form.strip()
                        if form:
                            inflects.add(form)
        if name and ipa:
            name_ipa[name] = ipa

    print(f"  DSV4 NAME blocks:     {len(names)}")
    print(f"  DSV4 INFLECT forms:   {len(inflects)}")
    print(f"  DSV4 NAME with IPA:   {len(name_ipa)}")

    # 检查 NAME 覆盖
    names_in_db = 0
    names_not_in_db = []
    for n in names:
        c.execute("SELECT 1 FROM lexicon WHERE term = ?", (n,))
        if c.fetchone():
            names_in_db += 1
        else:
            names_not_in_db.append(n)

    print(f"\n  NAME in lexicon:      {fmt_pct(names_in_db, len(names))}")
    if names_not_in_db:
        print(f"  NAME NOT in lexicon:  {len(names_not_in_db)}")
        for n in names_not_in_db[:10]:
            print(f"    - {n!r}")
        if len(names_not_in_db) > 10:
            print(f"    ... and {len(names_not_in_db) - 10} more")

    # INFLECT 覆盖
    infl_in_db = 0
    infl_not_in_db = []
    for ft in inflects:
        c.execute("SELECT 1 FROM lexicon WHERE term = ?", (ft,))
        if c.fetchone():
            infl_in_db += 1
        else:
            infl_not_in_db.append(ft)

    print(f"\n  INFLECT in lexicon:   {fmt_pct(infl_in_db, len(inflects))}")
    if infl_not_in_db:
        print(f"  INFLECT NOT in lex:   {len(infl_not_in_db)}")
        for ft in sorted(infl_not_in_db)[:10]:
            print(f"    - {ft!r}")
        if len(infl_not_in_db) > 10:
            print(f"    ... and {len(infl_not_in_db) - 10} more")

    # 检查 DSV4 NAME → DB lemma 是否正确
    c.execute("SELECT term, lemma FROM lexicon WHERE term IN ({})".format(
        ",".join("?" for _ in name_set)
    ), list(name_set))
    name_lemma = {r[0]: r[1] for r in c.fetchall()}

    bad_lemma = []
    for name in name_set:
        if name in name_lemma and name_lemma[name] != name:
            bad_lemma.append((name, name_lemma[name]))

    if bad_lemma:
        print(f"\n  ** DSV4 NAME with wrong lemma (should be self): {len(bad_lemma)}")
        for name, lemma in bad_lemma[:10]:
            print(f"     {name!r} → lemma={lemma!r}")
    else:
        print(f"\n  DSV4 NAME self-lemma: all OK")


# ============================================================
# 9. HAO / MyTerm KV ↔ DB 一致性
# ============================================================

def check_kv_source_consistency(conn):
    print("\n" + "=" * 66)
    print("9. KV ↔ DB — 术语数据源一致性")
    print("=" * 66)

    c = conn.cursor()

    # HAO for_kv.json
    if os.path.exists(HAO_KV_PATH):
        hao = load_json(HAO_KV_PATH)
        hao_keys = set()
        for entry in hao:
            if isinstance(entry, dict) and "key" in entry:
                hao_keys.add(entry["key"])
        print(f"  hao_for_kv.json keys:    {len(hao_keys)}")
        hao_in_db = 0
        hao_not_in_db = []
        for k in hao_keys:
            c.execute("SELECT 1 FROM lexicon WHERE term = ?", (k,))
            if c.fetchone():
                hao_in_db += 1
            else:
                hao_not_in_db.append(k)
        print(f"    in lexicon:            {fmt_pct(hao_in_db, len(hao_keys))}")
        if hao_not_in_db:
            print(f"    NOT in lexicon:         {len(hao_not_in_db)}")
            for k in hao_not_in_db[:8]:
                print(f"      - {k!r}")
    else:
        print(f"  hao_for_kv.json: not found")

    # my_term_for_kv.json
    if os.path.exists(MYTERM_KV_PATH):
        myterm = load_json(MYTERM_KV_PATH)
        myterm_keys = set()
        for entry in myterm:
            if isinstance(entry, dict) and "key" in entry:
                myterm_keys.add(entry["key"])
        print(f"\n  my_term_for_kv.json keys: {len(myterm_keys)}")
        mt_in_db = 0
        mt_not_in_db = []
        for k in myterm_keys:
            c.execute("SELECT 1 FROM lexicon WHERE term = ?", (k,))
            if c.fetchone():
                mt_in_db += 1
            else:
                mt_not_in_db.append(k)
        print(f"    in lexicon:              {fmt_pct(mt_in_db, len(myterm_keys))}")
        if mt_not_in_db:
            print(f"    NOT in lexicon:           {len(mt_not_in_db)}")
            for k in mt_not_in_db[:8]:
                print(f"      - {k!r}")
    else:
        print(f"  my_term_for_kv.json: not found")


# ============================================================
# 10. v3 目标状态差距总结
# ============================================================

def check_v3_gaps(conn):
    print("\n" + "=" * 66)
    print("10. v3 TARGET GAPS — 目标状态差距")
    print("=" * 66)

    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in c.fetchall()}

    gaps = []

    if "concepts" not in tables:
        gaps.append((
            "concepts 表缺失",
            """v3 设计: concept_id(PK), domain, source_ontology, confidence_tier
  需要构建: 从 HAO OBO + 自定义概念中抽取概念实体""",
            "HIGH",
        ))
    if "term_concept_map" not in tables:
        gaps.append((
            "term_concept_map 表缺失",
            """v3 设计: term(FK→lexicon), concept_id(FK→concepts), relation_type
  需要构建: HAO OBO 的 synonym/related 关系 + my_term 的精确映射""",
            "HIGH",
        ))

    c.execute("SELECT COUNT(*) FROM lexicon WHERE pos IS NOT NULL AND trim(pos) != ''")
    if c.fetchone()[0] == 0:
        gaps.append((
            "lexicon.pos 全为空",
            "需从词形推断词性 (n./adj./v.)，或由 OBO/Lexinfo 导入",
            "LOW",
        ))

    c.execute("SELECT COUNT(*) FROM lexicon WHERE etymology IS NOT NULL AND trim(etymology) != ''")
    if c.fetchone()[0] == 0:
        gaps.append((
            "lexicon.etymology 全为空",
            "需从外部词源数据导入",
            "LOW",
        ))

    c.execute("SELECT COUNT(*) FROM lexicon WHERE language IS NOT NULL AND trim(language) != ''")
    if c.fetchone()[0] == 0:
        gaps.append((
            "lexicon.language 全为空",
            "非英语词形 (如 der Hinterleib→de, 7. Sternit→de) 未标注语言",
            "MEDIUM",
        ))

    c.execute("SELECT COUNT(*) FROM lexicon WHERE lemma IS NULL")
    missing_lemma = c.fetchone()[0]
    if missing_lemma > 0:
        gaps.append((
            f"lexicon: {missing_lemma} 条无 lemma",
            "不在 DSV4 覆盖范围内的术语 (如 OBO 独有 synonym、my_term) 无法获得 lemma",
            "MEDIUM",
        ))

    c.execute("SELECT COUNT(*) FROM lexicon WHERE ipa IS NULL OR trim(ipa) = ''")
    missing_ipa = c.fetchone()[0]
    gaps.append((
        f"lexicon: {missing_ipa} 条无 IPA",
        "仅 DSV4 的 2,596 NAME 有 IPA。其余 OBO synonym / infl / my_term / aafc 均缺失",
        "MEDIUM",
    ))

    for title, detail, priority in gaps:
        print(f"\n  [{priority}] {title}")
        print(f"  {detail}")

    if len(gaps) == 0:
        print("  无差距 — DB 已达 v3 目标状态")


# ============================================================
# Main
# ============================================================

def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        check_schema(conn)
        check_row_counts(conn)
        check_column_quality(conn)
        check_lemma_integrity(conn)
        check_ipa_quality(conn)
        check_term_shapes(conn)
        check_ac_trie_consistency(conn)
        check_dsv4_coverage(conn)
        check_kv_source_consistency(conn)
        check_v3_gaps(conn)
    finally:
        conn.close()

    print("\n" + "=" * 66)
    print("VERIFY COMPLETE")
    print("=" * 66)


if __name__ == "__main__":
    main()
