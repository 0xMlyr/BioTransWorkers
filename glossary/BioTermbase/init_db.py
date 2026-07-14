#!/usr/bin/env python3
"""
D1 本地数据库初始化脚本 — lexicon 表

1. 建表 lexicon (term, lemma, pos, ipa, etymology, language)
2. 从 ackey_0714.txt 填充 term 列
3. 从 hao_dsv4.txt 提取 PHONETC → 填充 ipa 列
4. 从 hao_dsv4.txt 构建 lemma 关系：
   - NAME 词条的 lemma = NAME（自身 canonical）
   - INFLECT 词条的 lemma = 所属块 NAME（指向 canonical）
   - 不在 DSV4 中的词条 lemma = NULL

用法:
    cd glossary/BioTermbase
    python init_db.py
"""

import os
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TERMS_DIR = os.path.join(SCRIPT_DIR, "..", "terms")
DB_PATH = os.path.join(SCRIPT_DIR, "BioTermbase.db")
ACKEY_PATH = os.path.join(SCRIPT_DIR, "ackey_0714.txt")
DSV4_PATH = os.path.join(TERMS_DIR, "hao_expand_202607", "hao_dsv4.txt")

DDL = """
CREATE TABLE IF NOT EXISTS lexicon (
    term        TEXT PRIMARY KEY,
    lemma       TEXT,
    pos         TEXT,
    ipa         TEXT,
    etymology   TEXT,
    language    TEXT
);
"""


def parse_dsv4(dsv4_path: str) -> dict:
    """
    解析 hao_dsv4.txt，返回三部分信息：
      phonetics:  {NAME: IPA}           — 音标映射
      self_lemmas: set[NAME]            — NAME 自身即为 canonical
      inflect_lemmas: {INFLECT_TERM: NAME}  — 变形词 → canonical

    格式（每 6 行一块，空行分隔）：
        NAME:scape
        DEF:...
        ZH:...
        INFLECT:scapes|scapal|scapus
        PHONETC:/skeɪp/
    """
    phonetics: dict[str, str] = {}
    self_lemmas: set[str] = set()
    inflect_lemmas: dict[str, str] = {}

    blocks = []
    current_block: list[str] = []

    with open(dsv4_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() == "":
                if current_block:
                    blocks.append(current_block)
                    current_block = []
            else:
                current_block.append(line.strip())
        if current_block:
            blocks.append(current_block)

    print(f"[PARSE] {len(blocks)} blocks found in hao_dsv4.txt")

    for block in blocks:
        name: str | None = None
        phonetic: str | None = None
        inflect_terms: list[str] = []

        for line in block:
            if line.startswith("NAME:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("PHONETC:"):
                raw = line.split(":", 1)[1].strip()
                if raw and raw != "/null/" and raw != "/暂无音标/":
                    phonetic = raw
            elif line.startswith("INFLECT:"):
                raw = line.split(":", 1)[1].strip()
                if raw:
                    for form in raw.split("|"):
                        form = form.strip()
                        if form:
                            inflect_terms.append(form)

        if not name:
            continue

        # NAME → IPA
        if phonetic:
            phonetics[name] = phonetic

        # NAME 自身 → canonical
        self_lemmas.add(name)

        # INFLECT 变形词 → canonical = NAME
        for ft in inflect_terms:
            # 如果变形词恰好等于 NAME，跳过（不覆盖 self-mapping）
            if ft.lower() == name.lower():
                continue
            # 保留第一个 NAME 的映射（DSV4 中同名 NAME 可能出现多次，以首次遇到为准）
            if ft not in inflect_lemmas:
                inflect_lemmas[ft] = name

    return {
        "phonetics": phonetics,
        "self_lemmas": self_lemmas,
        "inflect_lemmas": inflect_lemmas,
    }


def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[INIT] Removed existing {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(DDL)
    print("[DDL] Created lexicon table")

    # ── 1. 填充 term ──
    with open(ACKEY_PATH, "r", encoding="utf-8") as f:
        terms = [line.strip() for line in f if line.strip()]

    conn.executemany("INSERT INTO lexicon (term) VALUES (?)", [(t,) for t in terms])
    print(f"[DATA] Inserted {len(terms)} term rows")

    # ── 2. 解析 DSV4 ──
    dsv4 = parse_dsv4(DSV4_PATH)
    phonetics = dsv4["phonetics"]
    self_lemmas = dsv4["self_lemmas"]
    inflect_lemmas = dsv4["inflect_lemmas"]

    print(f"[DSV4] NAME self-lemmas: {len(self_lemmas)}")
    print(f"[DSV4] INFLECT→canonical mappings: {len(inflect_lemmas)}")

    # ── 3. 填充 ipa ──
    ipa_updated = 0
    for term, ipa in phonetics.items():
        c = conn.execute("UPDATE lexicon SET ipa = ? WHERE term = ?", (ipa, term))
        ipa_updated += c.rowcount
    conn.commit()
    print(f"[IPA] Updated {ipa_updated} rows")

    # ── 4. 填充 lemma：NAME 自身 ──
    for name in self_lemmas:
        conn.execute("UPDATE lexicon SET lemma = ? WHERE term = ?", (name, name))

    # ── 5. 填充 lemma：INFLECT → canonical ──
    inflect_filled = 0
    inflect_not_found = 0
    for inflect_term, canonical in inflect_lemmas.items():
        c = conn.execute(
            "UPDATE lexicon SET lemma = ? WHERE term = ?", (canonical, inflect_term)
        )
        if c.rowcount == 0:
            inflect_not_found += 1
        else:
            inflect_filled += 1
    conn.commit()

    lemma_total = conn.execute(
        "SELECT COUNT(*) FROM lexicon WHERE lemma IS NOT NULL"
    ).fetchone()[0]

    print(f"[LEMMA] Self-filled:      {len(self_lemmas)}")
    print(f"[LEMMA] Inflect-filled:   {inflect_filled}")
    print(f"[LEMMA] Inflect not in DB:{inflect_not_found}")
    print(f"[LEMMA] Total with lemma:  {lemma_total}")

    # ── 验证报告 ──
    total = conn.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]
    with_ipa = conn.execute("SELECT COUNT(*) FROM lexicon WHERE ipa IS NOT NULL").fetchone()[0]
    with_lemma = conn.execute("SELECT COUNT(*) FROM lexicon WHERE lemma IS NOT NULL").fetchone()[0]
    without_lemma = total - with_lemma

    print(f"\n{'='*60}")
    print(f"VERIFICATION")
    print(f"{'='*60}")
    print(f"  Total rows:           {total:>6,d}")
    print(f"  With IPA:             {with_ipa:>6,d}")
    print(f"  Without IPA:          {total - with_ipa:>6,d}")
    print(f"  With lemma:           {with_lemma:>6,d}")
    print(f"  Without lemma:        {without_lemma:>6,d}")

    # ── 抽检验证 ──
    print(f"\n{'─'*60}")
    print(f"SPOT CHECKS")
    print(f"{'─'*60}")

    checks = [
        # (term, expected_lemma, expected_ipa_prefix_or_None)
        ("scape", "scape", "/skeɪp/"),
        ("scapes", "scape", None),
        ("scapal", "scape", None),
        ("scapus", "scape", None),
        ("propodeum", "propodeum", "<NOT_NULL>"),    # 验证 IPA 非空
        ("anatomical structures", "anatomical structure", None),
        ("anatomically structural", "anatomical structure", None),
        ("mesopleuron", "mesopleuron", "<NOT_NULL>"),  # DSV4 NAME，有音标
        ("whole organism", None, None),              # OBO synonym，不在 DSV4
        ("der Hinterleib", None, None),              # OBO synonym，不在 DSV4
        ("abdomen", "abdomen", "/ˈæbdəmən/"),
        ("Chalcidoidea", None, None),                # 来自 my_term，不在 DSV4
        ("A1 flap", "A1 flap", "/eɪ wʌn flæp/"),
        ("Symphyta", None, None),                    # 来自 my_term
    ]

    for term, exp_lemma, exp_ipa_check in checks:
        row = conn.execute(
            "SELECT term, lemma, ipa FROM lexicon WHERE term = ?", (term,)
        ).fetchone()
        if row is None:
            print(f"  [MISSING] '{term}' -- not found in DB!")
            continue

        _, got_lemma, got_ipa = row
        lemma_ok = got_lemma == exp_lemma

        if exp_ipa_check == "<NOT_NULL>":
            ipa_ok = got_ipa is not None and len(got_ipa) > 0
        elif exp_ipa_check is None:
            ipa_ok = (got_ipa is None)
        else:
            ipa_ok = (got_ipa is not None and got_ipa.startswith(exp_ipa_check))

        status = "OK" if (lemma_ok and ipa_ok) else "FAIL"
        details = []
        if not lemma_ok:
            details.append(f"lemma: got={got_lemma!r} expected={exp_lemma!r}")
        if not ipa_ok:
            details.append(f"ipa: got={got_ipa!r} expected={exp_ipa_check!r}")

        detail_str = " | ".join(details) if details else ""
        line = f"  [{status}] '{term}'"
        if detail_str:
            line += f" -- {detail_str}"
        try:
            print(line)
        except UnicodeEncodeError:
            # 回退到 ascii-safe 输出
            line_ascii = f"  [{status}] '{term}'"
            if detail_str:
                line_ascii += f" -- {detail_str.encode('ascii','replace').decode('ascii')}"
            print(line_ascii)

    conn.close()
    print(f"\n[DONE] {DB_PATH}")


if __name__ == "__main__":
    create_db()
