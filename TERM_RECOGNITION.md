# BioTransWorkers 术语识别系统详解

## 概述

术语识别系统是 BioTransWorkers 的核心功能，使用 **Aho-Corasick (AC) 自动机** 在 Cloudflare Workers 边缘端对代理页面进行流式术语匹配。AC自动机将全部术语（2605条）预构建为一棵有限状态机（Trie + 失败指针），匹配时对文本做**一次线性扫描**，同时找出所有出现的术语，取代了原正则方案。

---

## 一、数据存储结构

### 1.1 双命名空间设计

| 命名空间 | Binding | 用途 | KV操作/请求 |
|----------|---------|------|------------|
| `TERM_GLOSSARY` | `TERM_GLOSSARY` | 术语详情（翻译、音标、定义等多源数据） | 1次get（用户点击时） |
| `TERM_ACTRIE` | `TERM_ACTRIE` | AC自动机Trie（匹配引擎） | 1次get（启动加载） |

职责分离：Trie只管匹配，GLOSSARY只管数据存储。

### 1.2 术语详情格式（TERM_GLOSSARY）

```
Key: 术语言文（大小写敏感，如 "Chalcidoidea"）
Value: JSON 多源数据数组
```

```json
{
  "data": [
    {
      "metadata": {"source": "hao_core_2023", "ver": "1.0.0", "date": "20260419"},
      "detailed": {
        "id": "HAO:0000001",
        "name": "mesopleuron",
        "def": "The lateral plate of the mesothorax",
        "synonyms": [{"name": "pleural plate of mesothorax", ...}],
        "is_a": [{"id": "HAO:0001105", "name": "mesopleural region"}]
      }
    },
    {
      "metadata": {"source": "my_term_202604", "ver": "1.0.0", "date": "20260419"},
      "detailed": {
        "original": "mesopleuron",
        "translation": "中胸侧板",
        "phonetic": "/me-soh-PLOOR-on/"
      }
    }
  ]
}
```

### 1.3 AC自动机Trie格式（TERM_ACTRIE）

```json
{
  "version": "1.0",
  "built_at": "2026-07-12T08:08:38Z",
  "term_count": 2605,
  "node_count": 32647,
  "trie": [
    {"children": {"a": 1, "b": 5, ...}, "fail": 0, "output": []},
    {"children": {"r": 2},              "fail": 0, "output": []},
    ...
    {"children": {},                     "fail": 0, "output": ["area"]},
    {"children": {},                     "fail": 0, "output": ["propodeum"]}
  ]
}
```

每个节点字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `children` | `{string: number}` | 字符→下一节点索引映射 |
| `fail` | `number` | 失败指针（回退节点，根为0） |
| `output` | `string[]` | 该节点匹配到的术语列表（保留原始大小写） |

---

## 二、AC自动机加载

### 2.1 加载流程

```
请求到达 HTMLRewriter 阶段
    ↓
loadTrie(env)
    ↓
检查内存缓存（5分钟TTL）
    ↓
缓存有效？→ 返回缓存的 trie 数组
缓存过期？→ TERM_ACTRIE.get("ac_trie") → 1次KV get → JSON.parse → 更新缓存
    ↓
返回 trie 数组给 applyRewriter
    ↓
HTMLRewriter 注册文本处理器到白名单元素
```

```javascript
// term-handler.js:9-38
export async function loadTrie(env) {
  if (trieCache && now < trieCacheExpiry) return trieCache;
  const raw = await env.TERM_ACTRIE.get("ac_trie");
  const data = JSON.parse(raw);
  trieCache = data.trie;   // 32647个节点的数组
  return trieCache;
}
```

### 2.2 缓存机制

```javascript
let trieCache = null;
let trieCacheExpiry = 0;
const CACHE_TTL_MS = 5 * 60 * 1000;
```

- **内存缓存**：Worker 实例内5分钟缓存
- **冷启动**：Worker 实例间不共享，每次冷启动重新加载（仅1次KV get）
- **相比原方案**：从 955 次 KV get（list + 954次并行get）降到 **1 次**

---

## 三、AC自动机匹配算法

### 3.1 核心匹配

```javascript
// term-handler.js:42-82
export function acMatch(text, trie) {
  const lower = text.toLowerCase();
  const rawMatches = [];
  let state = 0;

  // 单次线性扫描
  for (let i = 0; i < lower.length; i++) {
    const ch = lower[i];
    // 沿children走，走不通沿fail回退
    while (state !== 0 && !trie[state].children[ch]) {
      state = trie[state].fail;
    }
    state = trie[state].children[ch] || 0;
    // 收集所有匹配
    for (const term of trie[state].output) {
      rawMatches.push({ term, start: i - term.length + 1, end: i + 1 });
    }
  }
  ...
}
```

**复杂度**：O(n + m + z)，n=文本长度，m=总模式长度，z=匹配数。

### 3.2 单词边界过滤

AC自动机本身不处理单词边界。匹配结果额外检查前后字符：

```javascript
const withBoundaries = rawMatches.filter(m => {
  if (m.start > 0 && /\w/.test(text[m.start - 1])) return false;
  if (m.end < text.length && /\w/.test(text[m.end])) return false;
  return true;
});
```

### 3.3 重叠处理（长词优先）

```
匹配结果：["fore wing", "wing", "fore wing venation", "wing venation"]
    ↓ 按位置排序 → 同位置取最长
最终：["fore wing venation"]
```

```javascript
withBoundaries.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));

const final = [];
let lastEnd = 0;
for (const m of withBoundaries) {
  if (m.start >= lastEnd) {
    final.push(m);
    lastEnd = m.end;
  }
}
```

---

## 四、大小写处理

### 4.1 匹配策略

```
Trie中存储:  小写key（"propodeum", "chalcidoidea"）
匹配前:     文本转小写（"Propodeum" → "propodeum"）
output:     原始大小写（"Chalcidoidea" 而非 "chalcidoidea"）
```

### 4.2 原始大小写保留

在 `build_ac.py` 中构建 `{小写 → 原始大小写}` 映射表：

```python
case_map = {}  # "propodeum" → "propodeum", "chalcidoidea" → "Chalcidoidea"
# 优先保留非全小写变体（如分类群名称）
if lower not in case_map or (case_map[lower] == lower and key != key.lower()):
    case_map[lower] = key
```

匹配时 `data-term` 使用原始大小写，确保 KV 查询命中：

| 原文 | Trie匹配 | data-term | KV key | 结果 |
|------|---------|-----------|--------|------|
| `Chalcidoidea` | ✅ | `Chalcidoidea` | `Chalcidoidea` | ✅ |
| `Propodeum` | ✅ | `propodeum` | `propodeum` | ✅ |
| `PROPODEUM` | ✅ | `propodeum` | `propodeum` | ✅ |
| `abdomen` | ✅ | `abdomen` | `abdomen` | ✅ |

---

## 五、文本注入机制

### 5.1 HTMLRewriter 集成

```javascript
// rewriter.js:828-853
if (trie) {
  const termHandler = createACTermHandler(trie);
  for (const selector of textSelectors) {
    rewriter.on(selector, {
      text(text) { termHandler.handleText(text); }
    });
  }
}
```

### 5.2 白名单元素

37个安全文本元素，排除 script、style、code、pre、textarea 等。

### 5.3 文本处理流程

```javascript
// rewriter.js:856-891
function createACTermHandler(trie) {
  let totalMatches = 0;
  return {
    handleText(text) {
      const content = text.text;

      // Step 1: 快速过滤（无3+字母直接跳过）
      if (!/[a-zA-Z]{3,}/.test(content)) return;

      // Step 2: AC匹配（单词边界+去重叠）
      const matches = acMatch(content, trie);
      if (matches.length === 0) return;

      // Step 3: 执行替换
      let result = '';
      let last = 0;
      for (const m of matches) {
        result += content.slice(last, m.start);
        result += `<span class="bio-term" data-term="${m.term}">${content.slice(m.start, m.end)}</span>`;
        last = m.end;
      }
      result += content.slice(last);

      // Step 4: HTML注入
      text.replace(result, { html: true });
      totalMatches += matches.length;
      console.log(`[AC] Page total matched terms: ${totalMatches}`);
    }
  };
}
```

### 5.4 性能优化点

| 优化 | 实现 | 效果 |
|------|------|------|
| 快速字母检测 | `/[a-zA-Z]{3,}/` | 跳过不含英文的文本节点 |
| AC一次扫描 | O(n)线性 | 替代正则O(nk)的alternatives回溯 |
| 预构建Trie | 本地Python构建 | 不在Worker端构建匹配结构 |
| 5分钟缓存 | 内存缓存 | 避免每次请求重新加载Trie |

---

## 六、本地构建流程

### 6.1 构建脚本

```bash
cd glossary/automaton && python build_ac.py
```

输入：`glossary/terms/hao_core/hao_for_kv.json`（2596条） + `my_term_for_kv.json`（129条） + `test_term.txt`

输出：`ac_trie.json`（32647节点，1.6MB）

### 6.2 构建步骤

```
Step 1: 提取key，构建 {小写→原始大小写} 映射
          → 2605个唯一key

Step 2: 构建Trie（小写key构建结构）
          → 32547节点

Step 3: BFS构建失败指针（failure link）
          → 支持后缀匹配

Step 4: 序列化为JSON
          → ac_trie.json

Step 5: 上传到KV
          → wrangler kv key put --binding=TERM_ACTRIE ... --key="ac_trie"
```

---

## 七、客户端弹窗系统

### 7.1 架构

```
主页面 (parent)
  ├── 注入弹窗 DOM + 样式
  ├── 监听 .bio-term 点击 → fetch API → showPopup()
  ├── 监听 postMessage（接收iframe术语点击）
  ├── 倒计时5秒自动关闭
  └── 鼠标悬停/触摸时暂停倒计时

iframe (正文内容)
  ├── 术语高亮（通过代理注入）
  ├── 点击术语 → fetch API
  └── postMessage 发送术语数据到主页面
```

### 7.2 倒计时暂停机制

```javascript
let isPaused = false;
popup.addEventListener('mouseenter', () => { isPaused = true; });
popup.addEventListener('mouseleave', () => { isPaused = false; });

setInterval(() => {
  if (isPaused) return;  // 暂停时不递减
  countdownValue--;
  if (countdownValue <= 0) closePopup();
}, 1000);
```

---

## 八、日志系统

所有日志前缀：

| 前缀 | 用途 |
|------|------|
| `[REQ]` | 请求路径和方法 |
| `[SW]` | Service Worker |
| `[API]` | 术语查询结果 |
| `[UPSTREAM]` | 上游请求和响应 |
| `[REWRITER]` / `[REWRITE]` | HTMLRewriter 处理 |
| `[BLOCK]` | 被屏蔽的脚本 |
| `[AC]` | AC自动机加载和匹配 |
| `[BioTrans]` | 客户端弹窗交互 |

```bash
# 查看 AC 自动机相关日志
npx wrangler tail | grep "\[AC\]"

# 示例
[AC] Loading trie from KV...
[AC] Loaded trie: 2605 terms, 32647 nodes
[AC] Page total matched terms: 38
```

---

## 九、当前限制与未来优化

### 当前限制

| 限制 | 说明 |
|------|------|
| 无词形还原 | "setae" 无法匹配 "seta"，"tubercles" 无法匹配 "tubercle" |
| 无短语智能识别 | 所有短语按逐字符匹配，不依赖语义 |
| 单词边界限制 | "mesopleuronites" 中的 "mesopleuron" 不匹配（需独立单词） |

### 规划

| 方向 | 优先级 | 说明 |
|------|--------|------|
| 词形还原 | P1 | 处理复数、所有格、形容词变体 |
| 更多站点适配 | P1 | MDPI、PLOS、NCBI |
| 术语数据完善 | P2 | 补充缺失术语到KV |

---

## 十、关键代码位置速查

| 功能 | 文件 | 函数/代码块 |
|------|------|-------------|
| AC自动机加载 | `term-handler.js` | `loadTrie()` |
| AC匹配算法 | `term-handler.js` | `acMatch()` |
| AC文本处理器 | `rewriter.js` | `createACTermHandler()` |
| API 端点 | `index.js` | `/api/term` 处理 |
| 字段优先级 | `index.js` | `FIELD_PRIORITY` + `pickBestField()` |
| 白名单元素 | `rewriter.js` | `textSelectors` 数组 |
| 弹窗系统 | `rewriter.js` | 内联JS嵌入在 `<body>` 处理器 |
| 构建脚本 | `glossary/automaton/build_ac.py` | `build_trie()` + `build_failure_links()` |
