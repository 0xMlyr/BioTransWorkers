# BioTransWorkers 项目演进史

> 以可查阅的提交记录、设计文档与代码为事实依据，梳理各阶段的技术决策、架构变化与设计理念差异。

---

## v0 — 透明代理框架（Phase 0）

**时间**: 2026-04-14 ~ 2026-04-21  
**关键提交**: `c995f90` Initial commit → `745c4ba` update  
**设计文档**: `src/sites/DEVELOPMENT_FOR_ZOOKEYS.md`

### 解决的问题

学术期刊网站的 HTML 内容需要被代理、注入术语翻译，但页面内嵌的大量子资源（JS、CSS、图片）路径会因代理后域名变化而 404。需要一套完整的路径重写和子资源拦截机制。

### 架构

```
用户请求 /?url=https://paper.example.com
  → 白名单校验 → 上游 fetch → 清理 CSP/安全头
  → HTMLRewriter：注入 SW 注册 + 路径重写 + 移除 <base>
  → 浏览器注册 Service Worker
  → SW 拦截后续无 ?url= 请求，自动补全代理路径
```

### 技术栈

- Cloudflare Workers（边缘计算）
- HTMLRewriter（流式 HTML 处理，4 类路径重写处理器：`href`/`src`/`srcset`/`action`）
- Service Worker（子资源拦截，以字符串形式内联导出，通过 `/sw.js` 路由动态返回）
- 单 KV 命名空间 `TERM_GLOSSARY`：术语存储与查询

### 关键设计决策

1. **子资源判断不依赖 Content-Type**：因为 404 页面也可能返回 `text/html`，改用请求 URL 文件扩展名判断（`/\.(js|css|png|...)$/i`）

2. **CSP 头直接删除而非 nonce 方案**：删除 `content-security-policy`、`content-security-policy-report-only`、`x-frame-options`，不做白名单注入

3. **Cookie 透传**：用户 Cookie 从请求头透传到上游，用于需会话的页面。但浏览器只带 `biotrans.mlyr.top` 域名下的 Cookie，无法带上目标网站的 Cookie

4. **Pensoft/ZooKeys 深度适配**：首个完整支持的站点。其正文在 `<iframe id="articleIframe">` 中动态加载，PHP 路径存在 URL rewrite 导致的多级路径 404 问题，增加根路径重试机制

5. **域名白名单**：当前 7 个允许代理的学术网站（PLOS、MDPI、ZooKeys、Zootaxa、NCBI、EJT、Mapress），新增域名直接追加数组

### 数据模型：一词一 JSON

```
key:   "abdomen"
value: "{\"translation\":\"腹部\",\"phonetic\":\"/null/\"}"
```

术语是扁平的键值对，每个 key 存储一个来源的一条翻译。**不存在多源数据整合能力——如果 "abdomen" 同时出现在 HAO 本体（有定义无翻译）和自定义词表（有翻译无定义）中，它们冲突存储而非合并。**

---

## v1 — 多源数据整合 + 正则术语匹配（Phase 1 早期）

**时间**: 2026-04-17 ~ 2026-04-19  
**关键提交**: `3ccab98` hao → `0c2827c` update  
**设计文档**: `glossary/README.md`

### 解决的问题

v0 的术语数据来自单一来源（自定义词表），没有本体学信息。引入 HAO (Hymenoptera Anatomy Ontology) 本体数据（~2,600 条术语，含 ID、定义、同义词、is_a 分类层级）后，同一个术语（如 `abdomen`）可能出现在 HAO 和自定义词表两个来源中，需要合并展示而非覆盖。

### 数据模型变化

从"一词一 JSON"变为**多源数据数组**：

```json
{
  "data": [
    { "metadata": {"source": "hao_core_2023", ...}, "detailed": {"id": "HAO:0000015", "name": "abdomen", "def": "..."} },
    { "metadata": {"source": "my_term_202604", ...}, "detailed": {"original": "abdomen", "translation": "腹部"} }
  ]
}
```

`metadata.source` 字段区分数据来源，`detailed` 内各源字段自由。

### 术语匹配：正则方案

Worker 启动时通过 `KV.list()` + 并行 `KV.get()` 加载全量术语，构建正则表达式用于 HTML 文本匹配。HTMLRewriter 的 `text()` 回调逐段匹配替换。

### 已知缺陷（文档记录）

| 缺陷 | 说明 |
|------|------|
| `list()` 分页缺失 | 默认最多 1000 条，代码未实现分页，大量 key 丢失 |
| API 调用超限 | 单次 Worker 调用并行 ~954 次 `get()`，触发 Cloudflare "Too many API requests" |
| 正则构建开销 | 每次启动需拼接 ~954 个 alternatives 的巨型正则 |
| 术语覆盖不全 | 本地 2,600+ 术语，KV 仅成功导入 ~954 条 |

这些缺陷在 `glossary/automaton/AC.md` §1.2-1.3 中有详细诊断记录。

### 数据导入工具

`glossary/terms/import_to_kv.py`：支持批量模式（覆盖写入，3 次 API 调用）和合并模式（按 source 字段去重合并）。解决重复 source 不重复写入的问题。

---

## v2 — AC 自动机 + 弹窗交互（Phase 1 重构 ~ Phase 3）

**时间**: 2026-07-11 ~ 2026-07-14  
**关键提交**: `6d6b318` updata → `b1602a8` Update rewriter.js  
**设计文档**: `glossary/automaton/AC.md`、`TERM_RECOGNITION.md`

### 解决的问题

v1 的正则匹配方案有根本性缺陷：KV API 调用量 955 次/请求（list + 954 并行 get），触发频率限制；正则构建开销大；术语覆盖不全。同时需要解决大小写匹配（"Propodeum" vs "propodeum" vs "PROPODEUM"）和跨帧通信（ZooKeys 正文在 iframe 内）问题。

### 架构核心变化：AC 自动机替代正则匹配

**设计原则**（`AC.md` §2.1-2.2）：将所有术语预构建为一棵 Aho-Corasick 自动机（Trie + failure 指针），对文本做一次线性扫描，同时找出所有出现的术语。复杂度 O(n + m + z)。

**三重职责分离**：

| 组件 | 存储 | 职责 |
|------|------|------|
| AC Trie | KV: `TERM_ACTRIE` | 只管"哪些词出现在文本中"——匹配引擎 |
| 术语详情 | KV: `TERM_GLOSSARY` | 只管"这个词是什么"——数据存储 |

Tri 不存内容，数据不存匹配。两者通过术语字符串关联。

**KV 操作对比**：

| 阶段 | v1 | v2 |
|------|-----|-----|
| 启动加载 | list() + 954 次 get = **955 次** | 1 次 `get("ac_trie")` = **1 次** |
| 文本匹配 | 正则逐段匹配 | Trie 逐字符遍历 |
| 用户点击 | 1 次 `get(term)` | 1 次 `get(term)`（不变） |

### Trie 构建

**构建脚本**: `glossary/automaton/build_ac.py`（Python，248 行）

**输入**: `hao_for_kv.json` + `my_term_for_kv.json` + `test_term.txt`

**构建步骤**:
1. 提取 key，构建 `{小写 → 原始大小写}` 映射（优先保留非全小写变体，如 `Chalcidoidea` 优于 `chalcidoidea`）
2. 插入小写 key 构建 Trie
3. BFS 构建 failure 指针（支持后缀匹配）
4. 序列化为 JSON

**产物**: `ac_trie.json` — 2,605 个术语，32,647 个节点，约 1.6 MB

**关键大小写处理决策**：Trie 结构用小写字符构建（匹配用），`output` 存储原始大小写术语（KV 查询用）。匹配前文本转小写，data-term 直接用 `output` 中的原始大小写作为 KV key。

### 术语注入机制

`rewriter.js` 中的 `createACTermHandler` 工厂函数生成文本处理器：
1. 快速过滤（无 3+ 连续字母跳过）
2. AC 匹配（单词边界过滤 + 贪心去重叠，同位置最长词优先）
3. 注入 `<span class="bio-term" data-term="{term}">`

**白名单元素**: 37 个安全文本元素（`p`, `div`, `span`, `h1-h6`, `li`, `td`, `th`, `em`, `strong` 等），排除 `script`、`style`、`code`、`pre`、`textarea`。

### 弹窗交互系统（Phase 2）

**架构**：

```
主页面 (parent)
  ├── 注入弹窗 DOM + 样式
  ├── 监听 .bio-term 点击 → fetch /api/term → showPopup()
  ├── 监听 postMessage（接收 iframe 术语点击）
  ├── 倒计时 5 秒自动关闭
  └── 鼠标悬停/触摸时暂停倒计时

iframe（ZooKeys 正文）
  ├── 术语高亮（通过代理注入）
  ├── 点击术语 → fetch /api/term
  └── postMessage 发送术语数据到主页面
```

**交互细节**：点击术语后 JS 请求 `/api/term?key=术语&token=密钥`，Worker 检索 KV 并按字段优先级（`FIELD_PRIORITY`）从多源中选择最佳 translation/phonetic/def，弹出深色主题弹窗，5 秒倒计时自动关闭，悬停暂停。用户可展开查看全量原始数据（所有来源的完整字段分条展示）。

### `/api/term` 字段优先级

```javascript
FIELD_PRIORITY = {
  translation: ['my_term_202604', 'hao_core_expand_dsv4', 'hao_core_2023', 'hao_inflect', 'engine_test'],
  phonetic:    ['hao_core_expand_dsv4', 'hao_core_2023', 'my_term_202604'],
  def:         ['hao_core_2023', 'my_term_202604']
};
```

自定义翻译 > LLM 翻译 > HAO 本体数据，音标优先 LLM 生成的 IPA。

### 设计理念差异（v1 → v2）

| 维度 | v1 | v2 |
|------|-----|-----|
| 匹配方式 | 正则（构建在 Worker 端） | AC 自动机（预构建在本地） |
| KV 调用 | 启动期 955 次 | 启动期 1 次 |
| 大小写 | 敏感匹配 | Trie 小写结构 + output 原始大小写 |
| 数据加载 | 全量加载所有 value | 按需加载（点击时才查 KV） |
| 同义词 | 无处理 | 无处理（仍为隐式） |

---

## LLM 辅助翻译管线（独立子项目）

**时间**: 2026-07-13  
**设计文档**: `LLMTRANS/README.md`

### 解决的问题

HAO 本体的 ~2,600 条术语有英文定义但无中文翻译和音标。需要批量翻译为汉语，生成国际音标和拉丁/希腊语形态变体。

### 三阶段尝试

| 轮次 | 模型 | API | 结果 |
|------|------|-----|------|
| Round 1 | GLM5 | 第三方代理 cqtbi.edu.cn | 50/2596 (2%) — 失败 |
| Round 2 | DeepSeek V3 | 同上 | 250/2596 (10%) — 失败 |
| **Round 3** | **DeepSeek V4 Pro** | **api.deepseek.com 官方** | **2596/2596 (100%)** |

失败根因：旧脚本硬编码批次上限；第三方代理 QPS 限制严苛。

### 提示词工程

系统提示词 `promote.txt`（~7.7 KB）设计了三级置信度标注体系：

| 级别 | 标注方式 | 示例 |
|------|---------|------|
| 确定 | 直接输出 | `ZH:并胸腹节` |
| 存疑 | 半角括号包裹 | `ZH:(中胸侧板前腹侧脊)` |
| 无译 | `[待译]` | `ZH:[待译]` |

### 关键技术点

- thinking 模式必须 disabled（默认开启会挤占输出 token）
- KVCache 自动开启：首次请求 system prompt 全量计费（$0.435/M tokens），后续 cache hit 仅 ~$0.0036/M tokens（约 50 倍便宜）
- 实际消耗：~7M input + 0.15M output ≈ **$0.13** 完成全部 2,596 条

### 翻译产物

输出文件 `hao_dsv4.txt`（640 KB），格式与源文件对齐。统计结果：

| 级别 | 数量 | 占比 |
|------|------|------|
| 确定 | 1,069 | 41% |
| 存疑 | 894 | 34% |
| 确定+存疑 | 483 | 19% |
| 无译 | 150 | 6% |

**94% 的术语获得可用汉语翻译。**

---

## v3 — 三层关系型架构（设计阶段，未实施）

**时间**: 2026-07-14  
**设计文档**: `DEVELOP_V3.md`  
**配置**: `wrangler.jsonc` 已关联 D1 数据库 `bio_termbase`（id: `1608b79c-d394-4f9e-bfc8-553a14c21f57`）

### 核心问题认知

DEVELOP_V3.md 开篇即指出 v1/v2 的根本局限：

> v1（一词一 JSON）和 v2（多源数据整合）版本的局限，根源都在于把词形层和概念层压进了同一张表/同一个 key。

**一词多义**（`mandible` 昆虫上颚 vs 人体下颚）与**多词一义**（`scape` 有 9 个同义词指向同一解剖结构）是同一问题的两面：词形与概念之间是多对多关系。

### 三层架构设计

```
AC Trie (KV: TERM_ACTRIE)    — 输入层：多模式串匹配，从噪声文本中命中已知 term
        ↓
D1 (BIO_TERMBASE)            — 关系层：词形 ↔ 概念的多对多拓扑 + 语言学元数据
        ↓
KV (TERM_GLOSSARY)           — 内容层：概念的多源异质 payload（定义/译名/图片/出处）
```

### 分工原则

| 层级 | 工具 | 为何 |
|------|------|------|
| AC Trie | KV 单一 key | 需要多模式串匹配速度，不需要关系查询 |
| 关系层 | D1 (SQLite) | 需要 JOIN、双向查询、事务一致性、外键约束 |
| 内容层 | KV | 多源字段异质、持续生长，不适合固定 SQL 列 |

> "没有一层替另一层承担职责" — DEVELOP_V3.md §2

### D1 Schema

三张表，极度克制：

```sql
lexicon            — 词形层：term（主键）、lemma_id（自引用规范词形）、pos、ipa、etymology、language
concepts           — 概念层：concept_id（无语义纯位置符）、domain、source_ontology、confidence_tier
term_concept_map   — 关联层：term ↔ concept_id 多对多，relation_type 采用 OBO 标准分类
```

**关键设计决策**：

1. **概念 ID 无语义**：如 `HAO:0000234`、`FMA:xxx`、`SELF:xxx`——ID 本身不携带内容，只负责把散落在各处的词形、定义、来源"缝"在一起。如果用英文词当 ID，会让概念结构性偏向某一语言的命名传统。

2. **内容不进 D1**：多源数据（HAO 官方词条、DeepSeek 批处理翻译、自行标注等）字段种类随来源增加持续生长，不适合预先声明为固定列。KV key 格式为 `concept_payload:{concept_id}:{source_name}`。

3. **同义词反查不再冗余**：v2 中同义词需要在每个 term 的 value 里各存一份列表。v3 中同义关系是"多个词条共享同一 concept_id 的推论"——改一次概念定义，所有同义词自动同步。

4. **不做自动消歧**：`mandible` 在 `term_concept_map` 中对应两行（`domain: insect_morphology` 和 `domain: human_anatomy`），查询返回全部，按 domain 分组展示，类似词典多义项条目。

5. **relation_type 采用 OBO 标准**：exact / narrow / broad / related synonym，而非自造分类体系。

### 设计理念差异（v2 → v3）

| 维度 | v2 | v3 |
|------|-----|-----|
| 数据模型 | 词→义的单一映射（多源合并在一个 value 里） | 词形→概念的多对多关系拓扑 |
| 存储介质 | 纯 KV（2 个命名空间） | KV（输入+内容）+ D1（关系） |
| 一词多义 | 不支持，同一 key 只有一个合并后的 value | 支持，term_concept_map 多行连向不同 concept_id |
| 多词同义 | 隐式（synonyms 数组在 JSON 内部，不可查询） | 显式（term_concept_map 反查，所有同义词共享 concept_id） |
| 同形异义 | 不支持 | 支持（同一 term 关联多个 concept，按 domain 区分） |
| 概念标识 | 术语字符串（有语义） | 纯位置符（HAO:xxx / SELF:xxx，无语义） |
| 消歧策略 | 不存在此问题 | 用户手动选择义项 |
| KV key 格式 | `{term}` | `concept_payload:{concept_id}:{source_name}` |
| 字段优先级 | `FIELD_PRIORITY` 硬编码排序 | 按 domain 分组展示，各源 payload 平级 |

### 架构对标

v3 的三层设计与医学信息学领域 UMLS Metathesaurus 结构同构：

| UMLS | BioTrans v3 |
|------|-------------|
| CUI (概念号) | `concepts.concept_id` |
| AUI (原子词形) | `lexicon.term` |
| MRCONSO (关联表) | `term_concept_map` |

### 已排除的方案（DEVELOP_V3.md §9 记录）

| 方案 | 排除理由 |
|------|----------|
| 纯 KV，双向索引手动镜像 | 无事务保证，双写易不一致。实测 2.6k 级别键值对覆写中已观察到写入/读取失败 |
| 纯 D1，多源内容也存表内 | 多源字段异质、持续生长，会导致大量 NULL 列的稀疏表 |
| 图数据库（Neo4j） | 表达力最强但部署与运维成本过重，留作后续升级选项 |

---

## 附录：各阶段文件结构对比

### v0-v1 时期（2026-04）

```
src/
  index.js      主入口，路由、代理、白名单
  rewriter.js   HTMLRewriter 路径重写逻辑
  sw.js         Service Worker（字符串内联导出）
  webpage.js    错误页和落地页模板
glossary/
  terms/        HAO 本体 + 自定义词表
  import_to_kv.py    KV 批量/合并导入
```

### v2 时期（2026-07）

```
src/
  index.js           主入口（+ API 端点、AC 自动机加载协调）
  rewriter.js        HTMLRewriter（+ AC 术语注入、弹窗系统）
  term-handler.js    新增：AC 自动机 Trie 加载与匹配算法
  sw.js
  webpage.js
  sites/
    index.js         站点配置管理器
    pensoft.js       Pensoft 站点特定配置
glossary/
  terms/             术语数据源（HAO、自定义、测试、LLM 翻译）
  automaton/
    AC.md            AC 自动机设计文档
    build_ac.py      AC 自动机构建脚本
    ac_trie.json     构建产物
LLMTRANS/            LLM 辅助翻译子项目
```

### v3 设计（2026-07-14，配置已就绪）

```
wrangler.jsonc      新增 d1_databases.bio_termbase binding
DEVELOP_V3.md       三层架构设计文档
```

计划新增（尚未创建）：
```
migrations/         D1 建表与数据迁移脚本
```

---

## 附录：提交时间线摘要

| 日期 | 关键事件 |
|------|----------|
| 2026-04-14 | 项目初始化，Cloudflare Workers 基础框架 |
| 2026-04-15 | ZooKeys 透明代理完成，SW 注册机制建立 |
| 2026-04-16~19 | 落地页 UI、术语卡片、HAO 数据导入、KV 导入工具 |
| 2026-07-11 | 开始 v2 重构 |
| 2026-07-12 | AC 自动机核心实现（Trie 构建、匹配算法、大小写处理） |
| 2026-07-13 | LLM 翻译管线完成（DSV4 Pro，2,596/2,596），弹窗 UI 更新 |
| 2026-07-14 | API 鉴权、弹窗系统完善、D1 数据库关联、v3 架构设计 |
