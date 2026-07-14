# 膜翅目形态学术语库 — 架构设计文档

> 术语数据库 版本：v3
> 用途：项目开发语料 / 架构备忘
> 定位：输入任意昆虫（含跨生物学垂直领域）相关英文术语——无论正式名称、历史名称、缩写、复数或形容词形式——定位到正确概念，获取定义、中文译名、本体关系与出处。

---

## 1. 核心问题

术语翻译看似是"查词典"问题，实际拆解后暴露出两个独立的层级混淆在一起：

- **词形层（lexical layer）**：词的表面形式——拼写、词性、复数/形容词变化、音标、词源、历史沿用写法。
- **概念层（conceptual layer）**：词指向的实际所指——解剖学结构本身，具有定义、跨语言译名、OBO本体关系（part_of、is_a）、多个数据来源。

**一词多义**（如 `mandible` 同时指昆虫上颚与人体解剖学下颚）与**多词一义**（如 `scape` / `pedunculus` / `torulus` 等九个同义词共同指向同一解剖结构）是同一枚硬币的两面：词形与概念之间，从来不是一一对应，而是多对多关系。v1（一词一 JSON）和 v2（多源数据整合）版本的局限，根源都在于把这两层压进了同一张表/同一个 key。

**关键改进**：概念的标识符（concept_id）本身应当是无语义的纯位置符。如果 ID 本身携带语义（例如直接用英文词当 ID），会让概念结构性地偏向某一语言的命名传统。ID 不携带内容，只负责把散落在各处的词形、定义、来源"缝"在一起——概念本身不是一个被存储的实体，而是所有指向它的痕迹共同织出的焦点。

---

## 2. 三层架构总览

```
┌─────────────────────────────────────────────────────────┐
│  输入层：AC 自动机（Trie，单一KV值存储 TERM_ACTRIE）      │
│  职责：从任意文本中做多模式串匹配，命中所有已知 term         │
│  （含缩写、复数、形容词变形等词形变体）                    │
└───────────────────────┬─────────────────────────────────┘
                         │ 命中 term ，HTML流式注入完成高亮显示
                         ▼
┌─────────────────────────────────────────────────────────┐
│  关系层：Cloudflare D1（SQLite，关系型 BIO_TERMBASE）     │
│  职责：词形 ↔ 概念的多对多关系拓扑 + 语言学元数据            │
│  表：lexicon / concepts / term_concept_map               │
└───────────────────────┬─────────────────────────────────┘
                         │ 返回 concept_id 列表（可能 =0 或 >1，跨领域歧义）
                         ▼
┌─────────────────────────────────────────────────────────┐
│  内容层：Cloudflare KV（键值存储 TERM_GLOSSARY）          │
│  职责：概念的多源异质 payload（定义/译名/图片/出处等）       │
│  key 由 concept_id 构成，value 为不透明 JSON              │
└─────────────────────────────────────────────────────────┘
```

**分工原则**：每一层只做自己结构性最擅长的事，没有一层替另一层承担职责。

| 层级 | 数据结构本质 | 为何用这个工具 |
|---|---|---|
| Trie / AC 自动机 | 稳定、可预知的字符串集合 | 需要多模式匹配的速度，不需要关系查询 |
| D1 | 稳定、可预知的关系拓扑 | 需要 JOIN、双向查询、事务一致性、外键约束 |
| KV | 开放、逐渐生长、字段不对齐的内容 | 每个来源提供的字段不平行，不适合固定列 |

---

## 3. D1 关系层设计

### 3.1 三张表 （设计举例，具体待定）

```sql
-- 词形层：词的表面形式与语言学信息
CREATE TABLE lexicon (
  term        TEXT PRIMARY KEY,   -- 如 "scape", "scapes", "antennal scape"
  lemma       TEXT REFERENCES lexicon(term),  -- 指向 canonical 形式；自身即 canonical 则指向自己
  pos         TEXT,               -- 词性
  ipa         TEXT,               -- 音标
  etymology   TEXT,               -- 词源
  language    TEXT                -- 处理非英语同义词，如 "Schaft" 的 language = "de"
);

-- 概念层：仅存在本体意义上的概念，只存稳定字段
CREATE TABLE concepts (
  concept_id       TEXT PRIMARY KEY,  -- 复合形式："HAO:0000234" / "FMA:xxx" / "SELF:xxx"
  domain           TEXT,              -- "insect_morphology" / "human_anatomy" / ...
  source_ontology  TEXT,              -- "HAO" / "FMA" / "self-defined"
  confidence_tier  INTEGER
  -- 注意：definition、image_url 等易变/多源字段不放在这里，见 3.3
);

-- 关联层：词形 ↔ 概念的多对多关系，同时是 v1/v2 中"同义词冗余存储"问题的正解
CREATE TABLE term_concept_map (
  term          TEXT REFERENCES lexicon(term),
  concept_id    TEXT REFERENCES concepts(concept_id),
  relation_type TEXT,  -- exact / narrow / broad / related / historical-conflation（参考 OBO 本体学标准同义词分类）
  PRIMARY KEY (term, concept_id)
);

CREATE INDEX idx_tcm_concept ON term_concept_map(concept_id);
```

### 3.2 同义词反查不再冗余存储

v2 的痛点：以KV实现同义词反查，需要 `scape` 要存一份包含全部同义词的列表，`antennal scape` 又要存一份几乎相同的列表——冗余且难以维护一致性。

v3 的解法：同义关系不是词条之间的字段，而是**多个词条共享同一 concept_id 的推论**。查询"scape 的所有同义词"变成：

```sql
SELECT term, relation_type FROM term_concept_map
WHERE concept_id = (
  SELECT concept_id FROM term_concept_map WHERE term = 'scape'
);
```

改一次概念定义，所有同义词自动同步，无需手动维护多份镜像。

### 3.3 跨领域歧义（一词多义）

`mandible` 在 `term_concept_map` 中对应两行，指向两个不同 domain 的 concept_id：

```
term       | concept_id  | relation_type
mandible   | HAO:xxx     | exact   (domain: insect_morphology)
mandible   | FMA:yyy     | exact   (domain: human_anatomy)
```

**消歧策略：不做自动消歧，交由用户选择。** 查询返回全部命中的 concept_id，按 domain 分组展示，类似词典的多义项条目（如"bank"分河岸/银行两个义项）。D1 查询本身不引入 domain 过滤或置信度排序逻辑，保持确定性——唯一的"猜测"环节在输入端的模糊匹配（trie），输出端的歧义解决权交还用户。

---

## 4. KV 内容层设计

### 4.1 为什么内容不放在 D1

多源数据（HAO 官方词条、DeepSeek 批处理翻译、自行标注等）提供的字段并不平行——某条概念有定义、图片、出处，另一条可能只有定义。这不是简单的 NULL 值问题（少数字段偶尔缺失可以用 NULL 处理），而是字段种类本身随数据源增加持续生长，不适合预先声明为固定列（否则每接入一个新源就要 `ALTER TABLE`，长期演变为大量列几乎全为 NULL 的稀疏怪表）。

### 4.2 Key 设计

```
concept_payload:{concept_id}:{source_name}
```

示例：`concept_payload:HAO:0000234:hao_official`、`concept_payload:HAO:0000234:deepseek_batch`

Value 为不透明 JSON，各源字段自由，不强制对齐，比如：

```json
{
  "definition": "...",
  "chinese_translation": "柄节",
  "image_url": "...",
  "source_citation": "..."
}
```

D1 中是否额外维护一张 `concept_sources` 索引表（记录某 concept_id 有哪些 source_name，避免遍历猜测 key）可按需添加。（待定）

---

## 5. AC 自动机：模糊输入的入口

**解决的问题**：D1 的 `lexicon.term` 是精确主键，但真实的输入（包括基于网页识别的HTML文本数据）是模糊的（拼写变体、句子中嵌入的术语、缩写）。AC 自动机基于 Trie 树，对全量词形数据做一次预构建，实现任意文本流中的多模式串匹配，一次扫描命中所有已知 term。

**职责边界**：AC 自动机只负责"从噪声文本中找出精确 term"，不做任何语义判断——语义/关系查询完全下放给 D1，内容查询完全下放给 KV。

---

## 6. 端到端查询流程

```
输入文本
    ↓
AC 自动机扫描 → 命中已知 term（含变体）
    ↓
对 term 进行 /api/term 查询
    ↓
D1: SELECT term_concept_map JOIN concepts WHERE term = ?
    → 返回该 term 对应的一个或多个 (concept_id, domain, relation_type)
    ↓
【若命中 >1 个 concept_id，跨领域歧义】→ 展示义项列表，用户选择
    ↓
KV: GET concept_payload:{concept_id}:* （遍历该概念全部来源）
    → 多源 payload 分条展示
    ↓
最终呈现：词典式条目 —— 词形信息（D1）+ 分领域义项（D1 分组）+ 各源定义/译名/出处（KV）
```

---

## 7. 三方一致性维护（重要）

系统中存在三处需要保持同步的数据：

ACz自动机的 **Trie** ↔ **D1** 的 `lexicom` 表主键 term 
**D1** 的 `concepts` 表主键 concepts_id ↔ **KV** 的 主键key concepts_id

**原则**：任何一次数据变更（新增词条、新增来源、修改概念归属）都应通过单一入口的脚本/流程触发三处同步更新，而非分头手动维护。

---

## 8. 其它信息

- `relation_type` 字段建议直接采用 OBO 本体学标准的同义词分级（exact / narrow / broad / related synonym），而非自造分类体系，以保持与其他本体库对接时的语义兼容性。
- 该三层设计（原子级词条 / 概念唯一标识 / 多对多关联表）与医学信息学领域的 UMLS Metathesaurus（CUI 概念号 + AUI 原子词形 + MRCONSO 关联表）结构同构，可作为进一步扩展时的参考对标。

---

## 9. 已排除的方案与理由

| 方案 | 排除理由 |
|---|---|
| 纯 KV，双向索引手动镜像存储 | 无事务保证，双写易产生不一致；本项目在 2.6k 级别键值对覆写中已观察到实际写入/读取失败 |
| 纯 D1，多源内容也存表内 | 多源字段异质、不断生长，会导致大量 NULL 列的稀疏表，且每接入新源需改表结构 |
| 图数据库（如 Neo4j） | 表达力最强，尤其适合未来若要建模 HAO 的 part_of/is_a 层级关系，但对当前 15,570 行规模的体量而言部署与运维成本过重，留作后续升级选项 |
| 概念 ID 使用有语义的字符串（如直接用英文词） | 会使概念结构性偏向某一语言的命名传统，破坏"多词一义"归并的中立性 |
