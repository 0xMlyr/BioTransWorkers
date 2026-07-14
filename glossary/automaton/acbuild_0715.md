# AC Trie 构建记录 — 2026-07-15

> 脚本：`glossary/automaton/build_ac.py` (ackey驱动版)
> 产物：`glossary/automaton/ac_trie.json`
> 全量词形清单：`glossary/BioTermbase/ackey_0715.txt`

---

## 相比上一版 (2026-07-14) 的变更

| 变更 | 说明 |
|------|------|
| 输入方式 | 从多源逐文件提取 → 以 ackey_0715.txt 为权威清单 |
| 新增 AAFC 词条 | 31 条 (adventitious vein, episternal groove 等，来自 AAFC 词典) |
| 新增 OBO synonym | 3 条 (t2, t3, t4 — 独立 HAO 概念，非 T2/T3/T4 大小写变体) |
| 新增 DSV4 INFLECT | 1 条 (abdominal sternite 6) |
| 剔除 | lemma 列已全部清空 → 不影响 Trie 构建 |

## 数据源 (ackey = 7 源并集)

| 来源 | 说明 | 条数 |
|------|------|------|
| `hao_for_kv.json` | HAO 核心键 | ~2,537 |
| `my_term_for_kv.json` | 自定义翻译 | 128 |
| `test_term.txt` | 工程测试词 | 1 |
| `hao.obo` | OBO synonym 词形 | ~2,482 |
| `hao_dsv4.txt` | LLM 生成 INFLECT 变形 | ~4,200 |
| `aafc_glossary.json` | AAFC 词典词头 + variants | 307 |

## 规模

| 指标 | v2 | 2026-07-14 | **2026-07-15** | 增幅 |
|------|-----|------------|----------------|------|
| 输入行数 | — | 9,022 | **9,057** | +35 |
| 唯一术语 (lowercase) | 2,605 | 9,022 | **9,053** | +31 |
| Trie 节点数 | 32,647 | 64,825 | **64,950** | +125 |
| JSON 大小 | ~1.6 MB | ~3.5 MB | **~3.4 MB** | -0.1 MB |

注：JSON 反而变小 0.1 MB — 因为 31 条新增 AAFC 词偏短 (apical, basal, discal 等)，前缀共享率高。

## 词形特征

| 特征 | 数量 |
|------|------|
| ≤2 字符 | 28 |
| 含数字 | 663 |
| 非 ASCII | 42 |
| 多词 (含空格) | 6,803 |
| 标点开头 | 2 |
| 混合大小写 | 284 |

## 大小写碰撞 (4 对, 小写变体被丢弃)

| 保留 (preferred) | 丢弃 (lowercase) |
|---|---|
| `T2` | `t2` |
| `T3` | `t3` |
| `T4` | `t4` |
| `Abdominal sternite 6` | `abdominal sternite 6` |

Trie 匹配大小写无关，输入 `t2`/`T2` 均命中 `T2` 节点的 output。

## 验证

13 项测试全部通过（含单词边界过滤 + 贪心去重叠）：

- 基础匹配、大小写无关、边界过滤、重叠处理 — PASS
- OBO synonym：`"whole organism"`、`"der Hinterleib"` — PASS
- DSV4 INFLECT：`"anatomical structures"`、`"anatomically structural"` — PASS
- 新增大小写概念区分：`"T2"` — PASS
- 新增 INFLECT：`"abdominal sternite 6"` — PASS

## 相关文件

- 构建脚本：`glossary/automaton/build_ac.py` (ackey驱动版)
- 产物：`glossary/automaton/ac_trie.json`
- 词形清单：`glossary/BioTermbase/ackey_0715.txt` (9,057 行)
