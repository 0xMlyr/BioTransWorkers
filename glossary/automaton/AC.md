# AC自动机术语匹配重构方案

## 1. 背景与问题

### 1.1 当前架构

Worker 启动时通过 `KV.list()` 获取所有术语key，再并行 `KV.get()` 读取每个key的value，构建正则表达式用于HTML文本匹配。

### 1.2 已确认的缺陷

| 缺陷 | 说明 |
|---|---|
| **KV list() 分页缺失** | `list()` 默认最多返回1000条key，代码未实现分页，导致大量key丢失 |
| **KV API调用次数超限** | 单次Worker调用中并行发起~954次 `get()`，触发 Cloudflare "Too many API requests" 限制 |
| **正则构建开销** | 每次启动需拼接~954个alternatives的巨型正则字符串，占用内存和CPU |
| **术语覆盖不全** | 本地glossary文件包含~2600+术语，但KV中仅成功导入~954条 |

### 1.3 根因定位日志（诊断过程记录）

```
[DIAG] list() contains "propodeum": false          ← KV list()未返回该key
[DIAG] Key "propodeum" NOT in validTerms!          ← 从未进入术语列表
[DIAG] Key "propodeum" NOT in termCache after fresh load!  ← KV加载阶段已丢失
[TERM-READ] ERROR parsing key "xxx": Too many API requests  ← 触发API次数限制
```

---

## 2. 目标架构

### 2.1 核心思想

**Aho-Corasick (AC) 自动机**：将所有术语构建成一棵 Trie（前缀树）+ 失败指针（failure link），形成有限状态机。匹配时对文本做**一次线性扫描**，同时找出所有出现的术语。

### 2.2 职责分离

```
┌──────────────────────────────────────────────────────────┐
│  KV 命名空间 TERM_GLOSSARY                               │
│                                                          │
│  Key: "ac_trie"                                          │
│  Value: {version, term_count, trie: [...]}               │
│  用途: 术语匹配引擎（Worker启动时加载1次）                 │
│                                                          │
│  Key: "propodeum"                                        │
│  Value: {data: [{metadata, detailed}, ...]}              │
│  用途: 术语详情（用户点击时按需get，与现有格式完全一致）    │
│                                                          │
│  Key: "mesopleuron"                                      │
│  Value: {data: [{metadata, detailed}, ...]}              │
│  ...                                                     │
└──────────────────────────────────────────────────────────┘
```

- **ac_trie**：只管"哪些词出现在文本中"——匹配引擎
- **各术语key**：只管"这个词是什么"——数据存储

### 2.3 KV操作对比

| 阶段 | 当前方案 | AC自动机方案 |
|---|---|---|
| 启动加载 | list() + 954次get = **955次** | 1次get("ac_trie") = **1次** |
| 文本匹配 | 正则逐段匹配 | Trie逐字符遍历 |
| 用户点击 | 1次get(term) | 1次get(term)（不变） |

---

## 3. 构建流程

### 3.1 输入数据

```
glossary/hao_core/hao_for_kv.json          → HAO本体术语（~2500+条）
glossary/my_trem_202604/my_term_for_kv.json → 自定义术语（129条）
```

两个文件的key可能存在重叠（如 "abdomen" 同时出现在两个源中），构建时需去重。

### 3.2 处理步骤

```
Step 1: 提取key并去重合并
  遍历两个JSON文件 → 收集所有key → 去重
  同一key出现在多个源 → 只保留一个key（value的合并由KV层处理）

Step 2: 大小写归一化
  "Propodeum" → "propodeum"
  "MeSoPleuRoN" → "mesopleuron"
  每个key只存小写形式到Trie

Step 3: 构建Trie
  逐字符插入，构建children映射
  BFS构建failure指针
  叶子节点标记output（匹配到的原始key列表）

Step 4: 序列化为JSON
  输出 ac_trie.json
```

### 3.3 大小写处理策略

- Trie中统一存储**小写key**
- 匹配前将输入文本**转小写**
- 匹配结果中的术语直接作为KV key使用（KV key本身也是小写）

```
源数据: "Propodeum", "propodeum", "PROPODEUM"
    ↓ 统一转小写
Trie中: "propodeum" (一份)

文本: "The Propodeum is..."
    ↓ 转小写
"the propodeum is..."
    ↓ AC匹配
命中: "propodeum"
    ↓ 作为KV key
KV.get("propodeum") → 返回多源数据
```

### 3.4 Trie序列化格式

```json
{
  "version": "1.0",
  "built_at": "2026-07-12T00:00:00Z",
  "term_count": 2600,
  "trie": [
    {
      "children": {"a": 1, "b": 5, "m": 12},
      "fail": 0,
      "output": []
    },
    {
      "children": {"r": 2},
      "fail": 0,
      "output": []
    },
    {
      "children": {"e": 3},
      "fail": 0,
      "output": []
    },
    {
      "children": {"a": 4},
      "fail": 0,
      "output": []
    },
    {
      "children": {},
      "fail": 0,
      "output": ["area"]
    }
  ]
}
```

每个节点字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `children` | `{string: number}` | 字符 → 下一节点索引的映射 |
| `fail` | `number` | 失败指针（回退节点索引，根节点为0） |
| `output` | `string[]` | 该节点匹配到的术语列表（处理前缀共享情况） |

### 3.5 体积估算

```
Trie节点数：~5000-8000（取决于前缀共享程度）
每个节点JSON：~60-80 bytes
Trie总大小：~400-640 KB
```

CF KV 单个value最大 25MB，完全足够。

---

## 4. 文件结构

```
glossary/automaton/
├── AC.md              # 本文档
├── build_ac.py        # 构建脚本
└── ac_trie.json       # 构建产物（序列化的Trie，导入KV用）
```

### 4.1 build_ac.py 职责

1. 读取 `glossary/hao_core/hao_for_kv.json` 和 `glossary/my_trem_202604/my_term_for_kv.json`
2. 提取所有key，去重，转小写
3. 构建AC自动机（Trie + failure指针）
4. 序列化为JSON，输出到 `ac_trie.json`

### 4.2 部署方式（手动）

```bash
# 构建
cd glossary/automaton
python build_ac.py

# 导入KV
cd ../../
npx wrangler kv key put --binding=TERM_GLOSSARY --remote --key="ac_trie" --path=glossary/automaton/ac_trie.json

# 导入各术语的value（从现有JSON文件）
npx wrangler kv bulk put --binding=TERM_GLOSSARY --remote glossary/hao_core/hao_for_kv.json
npx wrangler kv bulk put --binding=TERM_GLOSSARY --remote glossary/my_trem_202604/my_term_for_kv.json
```

---

## 5. Worker端实现设计

### 5.1 启动阶段

```javascript
// 1次KV get，加载自动机
const acData = JSON.parse(await env.TERM_GLOSSARY.get("ac_trie"));
const trie = acData.trie;
```

### 5.2 匹配算法（AC自动机遍历）

```javascript
function acMatch(text, trie) {
  let state = 0;
  const results = [];
  const lower = text.toLowerCase();

  for (let i = 0; i < lower.length; i++) {
    const ch = lower[i];
    // 沿children走，走不通就沿fail回退
    while (state !== 0 && !trie[state].children[ch]) {
      state = trie[state].fail;
    }
    state = trie[state].children[ch] || 0;
    // 收集该节点的所有匹配
    for (const term of trie[state].output) {
      results.push({ term, index: i });
    }
  }
  return results;
}
```

复杂度：O(n + m + z)，n=文本长度，m=总模式长度，z=匹配数。

### 5.3 HTML注入

对匹配结果中的每个术语，在原文中对应位置注入`<span class="bio-term" data-term="...">`。

### 5.4 用户点击

```javascript
// 与现有逻辑完全一致
const value = await env.TERM_GLOSSARY.get(termKey);
// 返回 {data: [...]} 多源数据
```

### 5.5 可移除的现有代码

| 模块 | 说明 |
|---|---|
| `term-handler.js` 的 `loadAllTerms()` | 不再需要全量加载 |
| `term-handler.js` 的 `buildTermRegex()` | 不再需要构建正则 |
| `term-handler.js` 的 `createTextHandler()` | 被AC匹配替代 |
| `rewriter.js` 中的 `createTermHandler()` | 被AC匹配替代 |
| `index.js` 中的 `getTerms()` + `buildTermRegex()` 调用 | 替换为加载自动机 |

---

## 6. 注意事项

### 6.1 前缀共享与output标记

当一个key是另一个key的前缀时（如 `pleuron` 是 `mesopleuron` 的子串），AC自动机的failure指针会自动处理：

- 匹配到 `mesopleuron` 末尾时，沿failure回退可找到 `pleuron` 的匹配
- 无需为每个key存储多个大小写变体

### 6.2 匹配边界

当前使用 `\b` 单词边界。AC自动机本身不处理边界，需要在匹配结果上额外判断：

```javascript
// 匹配后检查边界
function isWordBoundary(text, index, length) {
  const before = index > 0 ? text[index - 1] : ' ';
  const after = index + length < text.length ? text[index + length] : ' ';
  return /\W/.test(before) && /\W/.test(after);
}
```

### 6.3 与现有KV数据的关系

构建自动机时从**本地JSON文件**读取数据，不依赖现有KV。部署时：
1. 先导入 `ac_trie.json` 到KV
2. 再确保各术语key在KV中有对应的value
3. 切换Worker代码到自动机匹配逻辑

### 6.4 开发阶段调试

自动机构建在本地Python完成，可直接用测试文本验证匹配结果：

```python
# build_ac.py 中可包含测试逻辑
trie = build_automaton(terms)
results = ac_match("The propodeum is lateral to the pleuron", trie)
# 应匹配: ["propodeum", "pleuron"]
```

---

## 7. 待实施项

| 优先级 | 任务 | 说明 |
|---|---|---|
| P0 | 编写 `build_ac.py` | 从本地JSON构建AC自动机 |
| P0 | 构建并导入 `ac_trie.json` | 手动部署到KV |
| P0 | 导入术语value到KV | 确保每个key有对应value |
| P1 | 重写Worker匹配逻辑 | 替换正则为AC自动机遍历 |
| P1 | 移除冗余代码 | term-handler.js中的旧逻辑 |
| P2 | 重新启用缓存 | 自动机加载后缓存到内存 |
| P2 | 清理诊断日志 | 移除所有[DIAG]日志 |
