# AC Trie 构建记录 — 2026-07-14

> 脚本：`glossary/automaton/build_ac.py`
> 产物：`glossary/automaton/ac_trie.json`
> 全量词形清单：`glossary/BioTermbase/ackey_0714.txt`

---

## 数据源

| 来源 | 文件 | 提取数 | 净新增 | 已在库中 |
|------|------|--------|--------|----------|
| Base | `hao_for_kv.json` | 2,596 | — | — |
| Base | `my_term_for_kv.json` | 129 | — | — |
| Base | `test_term.txt` | 1 | — | — |
| OBO synonyms | `hao.obo` | 2,593 | +2,299 | 294 |
| DSV4 INFLECT | `hao_dsv4.txt` | 4,353 | +4,118 | 235 |

OBO ∩ DSV4 交叉重叠（lowercase）：36 条。

## 规模

| 指标 | 旧（v2） | 新（2026-07-14） | 增幅 |
|------|----------|-------------------|------|
| 唯一术语数 | 2,605 | **9,022** | +246.3% |
| Trie 节点数 | 32,647 | **64,825** | +98.6% |
| JSON 大小 | ~1.6 MB | **~3.5 MB** | +118% |

## 词形特征

| 特征 | 数量 |
|------|------|
| ≤2 字符缩略词 | 28 |
| 多词组合（含空格） | 6,794 |
| 含数字 | 663 |
| 混合大小写 | 284 |

## 验证

11 项测试全部通过（含单词边界过滤 + 贪心去重叠）：

- 基础匹配、大小写无关、边界过滤、重叠处理 — PASS
- OBO synonym：`"whole organism"`、`"der Hinterleib"` — PASS
- DSV4 INFLECT：`"anatomical structures"`、`"anatomically structural"` — PASS

## 相关文件

- 构建脚本：`glossary/automaton/build_ac.py`
- 产物：`glossary/automaton/ac_trie.json`
- 词形清单：`glossary/BioTermbase/ackey_0714.txt`（9,022 行，每行一个术语）
