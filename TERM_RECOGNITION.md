# BioTransWorkers 术语识别系统详解

## 概述

术语识别系统是 BioTransWorkers 的核心功能，负责从代理的网页内容中识别昆虫形态学术语，并通过高亮标注和弹窗展示翻译信息。

---

## 一、数据存储结构

### 1.1 KV 存储格式

```
Key: 术语原文（大小写敏感，如 "mesopleuron"）
Value: JSON 字符串
```

### 1.2 多源数据格式

术语数据采用多源聚合设计，支持多个数据源的合并：

```json
{
  "data": [
    {
      "metadata": {
        "source": "my_term_202604",
        "ver": "1.0",
        "date": "2026-04"
      },
      "detailed": {
        "translation": "中胸侧板",
        "phonetic": "/null/",
        "def": "定义文本...",
        "id": "HAO:0000001",
        "name": "mesopleuron",
        "synonyms": [...],
        "is_a": [...],
        "xrefs": [...],
        "def_refs": [...]
      }
    },
    {
      "metadata": {
        "source": "hao_core_2023",
        "ver": "2023.12",
        "date": "2023-12"
      },
      "detailed": { ... }
    }
  ]
}
```

### 1.3 数据源优先级

```javascript
const FIELD_PRIORITY = {
  translation: ['my_term_202604', 'hao_core_2023', 'hao_inflect', 'engine_test'],
  phonetic: ['hao_core_2023', 'my_term_202604'],
  def: ['hao_core_2023', 'my_term_202604']
};
```

- **人工翻译表** (`my_term_202604`) 在翻译字段上享有最高优先级
- **HAO本体** (`hao_core_2023`) 在音标和定义字段上优先
- 字段按优先级排序后，取第一个有效值

---

## 二、术语加载与缓存

### 2.1 加载流程

```
请求到达
    ↓
getTerms(env) —— 检查缓存
    ↓
缓存有效? → 返回缓存数据
缓存过期? → loadAllTerms(env) → 更新缓存
    ↓
返回术语列表
```

### 2.2 缓存机制

```javascript
// term-handler.js:3-5
let termCache = null;
let termCacheExpiry = 0;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5分钟
```

- **内存缓存**：Worker 实例内5分钟缓存
- **冷启动重新加载**：Worker 实例间不共享缓存，每次冷启动会重新加载
- **并发优化**：使用 `Promise.all()` 并行获取所有 KV 键值

### 2.3 多源合并逻辑

```javascript
// 按翻译优先级排序数据源
const sortedData = [...dataArray].sort((a, b) => {
  const aIdx = FIELD_PRIORITY.translation.indexOf(aSrc);
  const bIdx = FIELD_PRIORITY.translation.indexOf(bSrc);
  return (aIdx === -1 ? 99 : aIdx) - (bIdx === -1 ? 99 : bIdx);
});

// 字段级合并策略
for (const item of sortedData) {
  // translation: 取第一个有效的（非空且不以"汉译"开头）
  // phonetic: 取第一个非 /null/ 的
  // definition: 取第一个非空的
  // id, is_a: 取第一个有的
  // synonyms: 合并去重
}
```

合并后的术语对象：
```javascript
{
  key: "mesopleuron",
  id: "HAO:0000001",
  translation: "中胸侧板",
  phonetic: "/null/",
  definition: "...",
  synonyms: [...],      // 去重后的同义词数组
  isA: [...],           // 分类层级
  sources: ['my_term_202604', 'hao_core_2023'], // 数据源列表
  rawData: [...]        // 保留原始数据供展卷使用
}
```

---

## 三、正则构建策略

### 3.1 构建流程

```javascript
// term-handler.js:171-199
export function buildTermRegex(terms) {
  // 1. 过滤短术语
  const validTerms = terms.filter(t => t.key && t.key.length >= 3);
  
  // 2. 转义正则特殊字符
  const escaped = validTerms
    .map(t => t.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .sort((a, b) => b.length - a.length); // 3. 长度降序排序
  
  // 4. 构建正则
  const pattern = escaped.join('|');
  return new RegExp(`\\b(${pattern})\\b`, 'g');
}
```

### 3.2 关键设计决策

| 设计点 | 实现 | 原因 |
|--------|------|------|
| 长度过滤 | `key.length >= 3` | 避免匹配 "1", "A", "1A" 等编号和短序列 |
| 特殊字符转义 | `replace(/[.*+?^${}()|[\]\\]/g, '\\$&')` | 防止术语如 "seta(s)" 破坏正则 |
| 长度降序排序 | `sort((a, b) => b.length - a.length)` | **长术语优先匹配**，确保 "mesopleuron" 先于 "pleuron" |
| 单词边界 | `\b...\b` | 确保完整单词匹配，不匹配子串 |
| 全局匹配 | `g` 标志 | 一行中匹配所有出现 |
| 大小写敏感 | 默认行为 | "mesopleuron" ≠ "Mesopleuron" |

### 3.3 长术语优先示例

```
术语列表: ["pleuron", "mesopleuron"]

未排序正则: \b(pleuron|mesopleuron)\b
  文本: "The mesopleuron and pleuron are..."
  匹配: "pleuron" (先匹配到短术语，长术语被截断)

排序后正则: \b(mesopleuron|pleuron)\b
  文本: "The mesopleuron and pleuron are..."
  匹配: "mesopleuron" (长术语优先完整匹配)
```

---

## 四、文本注入机制

### 4.1 HTMLRewriter 集成

```javascript
// rewriter.js:101
export function applyRewriter(rewriter, finalUrl, workerOrigin, siteConfig, terms, termRegex) {
  // 创建术语处理器
  const termHandler = createTermHandler(terms, termRegex);
  
  // 注册文本处理器到白名单元素
  const textSelectors = ['p', 'div', 'span', 'h1', ...]; // 18个元素
  for (const selector of textSelectors) {
    rewriter.on(selector, {
      text(text) { termHandler.handleText(text); }
    });
  }
}
```

### 4.2 白名单元素策略

```javascript
// rewriter.js:811-817
const textSelectors = [
  // 文本容器
  'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'li', 'td', 'th', 'figcaption', 'caption', 'blockquote',
  'article', 'section', 'aside', 'header', 'footer', 'main',
  // 行内文本
  'em', 'strong', 'i', 'b', 'u', 'mark', 'small', 'del', 'ins',
  'sub', 'sup', 'time', 'label', 'summary', 'figcaption'
];
```

**明确排除的元素**（避免破坏页面功能）：
- `script` - 破坏 JavaScript 代码
- `style`, `noscript` - 破坏 CSS 规则
- `code`, `pre`, `kbd`, `samp` - 代码块不应污染
- `textarea` - 用户输入区域
- `title` - 页面标题保持干净

### 4.3 为什么不使用 `rewriter.on("*")`？

> HTMLRewriter 没有元素退出回调，无法实现可靠的嵌套跟踪。使用通配符会匹配到 `<script>` 和 `<style>`，导致 JavaScript 代码和 CSS 规则被破坏。

### 4.4 文本处理流程

```javascript
// rewriter.js:836-881
function createTermHandler(terms, regex) {
  const termMap = new Map(terms.map(t => [t.key, t.translation]));
  
  return {
    handleText(text) {
      const content = text.text;
      if (!content || typeof content !== 'string') return;
      
      // Step 1: 快速过滤 - 检查是否包含3+字母
      if (!/[a-zA-Z]{3,}/.test(content)) return;
      
      // Step 2: 检测是否包含任何术语
      regex.lastIndex = 0;
      if (!regex.test(content)) return;
      
      // Step 3: 重置并执行替换
      regex.lastIndex = 0;
      const replaced = content.replace(regex, (match) => {
        return `<span class="bio-term" data-term="${match}">${match}</span>`;
      });
      
      // Step 4: HTML注入
      text.replace(replaced, { html: true });
    }
  };
}
```

### 4.5 性能优化点

| 优化 | 实现 | 效果 |
|------|------|------|
| 快速字母检测 | `/[a-zA-Z]{3,}/` | 跳过不含英文的文本节点 |
| 预检测再替换 | `regex.test()` → `regex.replace()` | 避免无匹配时的替换开销 |
| 正则 lastIndex 重置 | `regex.lastIndex = 0` | 防止全局正则状态污染 |
| 术语到翻译映射 | `Map` 结构 | O(1) 查询翻译（虽然实际注入时不使用，为后续扩展保留） |

---

## 五、API 查询与字段选择

### 5.1 `/api/term` 端点

```
GET /api/term?key=mesopleuron
```

### 5.2 响应格式

```json
{
  "key": "mesopleuron",
  "name": "mesopleuron",
  "translation": "中胸侧板",
  "translation_source": "my_term_202604",
  "phonetic": "/null/",
  "phonetic_source": "hao_core_2023",
  "def": "The mesopleuron is the...",
  "def_source": "hao_core_2023",
  "sources": [
    {
      "metadata": { "source": "my_term_202604", ... },
      "detailed": { ... }
    },
    { ... }
  ]
}
```

### 5.3 字段优先级选择算法

```javascript
// index.js:60-85
function pickBestField(fieldName) {
  const priority = FIELD_PRIORITY[fieldName] || [];
  
  // 按优先级排序数据源
  const sorted = [...dataArray].sort((a, b) => {
    const aIdx = priority.indexOf(a.metadata?.source);
    const bIdx = priority.indexOf(b.metadata?.source);
    return (aIdx === -1 ? 999 : aIdx) - (bIdx === -1 ? 999 : bIdx);
  });
  
  // 返回第一个有效值
  for (const item of sorted) {
    const val = fieldName === 'translation' 
      ? (d.translation || d.chinese_name || '')
      : (d[fieldName] || '');
    if (val && !val.startsWith('汉译')) return { value: val, source: item.metadata?.source };
  }
  return { value: null, source: null };
}
```

### 5.4 字段映射规则

| 输出字段 | 数据源字段 | 优先级 |
|----------|-----------|--------|
| `translation` | `translation` > `chinese_name` | my_term_202604 > hao_core_2023 > ... |
| `phonetic` | `phonetic` | hao_core_2023 > my_term_202604 |
| `def` | `def` | hao_core_2023 > my_term_202604 |
| `name` | `name` | 优先从 hao_core_2023 取，否则任一有name的源 |

---

## 六、客户端弹窗系统

### 6.1 跨 Frame 架构

由于 PenSoft/ZooKeys 使用 iframe 加载正文，需要跨 frame 通信：

```
主页面 (parent)
  ├── 注入术语高亮样式
  ├── 注入弹窗 DOM 和样式
  ├── 监听 postMessage 接收 iframe 术语点击
  └── 显示弹窗

iframe (正文内容)
  ├── 术语高亮（通过代理注入）
  ├── 点击术语 → fetch API
  └── postMessage 发送术语数据到主页面
```

### 6.2 iframe 检测与分支逻辑

```javascript
// rewriter.js:146-784
const iframeDetectionScript = `<script>
(function() {
  const isInIframe = window.self !== window.top;
  console.log('[BioTrans] Page context:', isInIframe ? 'iframe' : 'main page');
  
  if (!isInIframe) {
    // ===== 主页面逻辑 =====
    // 1. 注入弹窗样式和 DOM
    // 2. 显示术语弹窗 (showPopup)
    // 3. 监听 message 事件接收 iframe 点击
    // 4. 显示首屏欢迎弹窗
  } else {
    // ===== iframe 逻辑 =====
    // 1. 监听 .bio-term 点击
    // 2. fetch /api/term 获取数据
    // 3. postMessage 发送给主页面显示
  }
})();
</script>`;
```

### 6.3 弹窗交互流程

```
用户点击高亮术语
    ↓
iframe 中: fetch /api/term?key=xxx
    ↓
获取完整术语数据（多源合并后）
    ↓
window.parent.postMessage({ type: 'BIOTERM_SHOW', term: data })
    ↓
主页面监听 message 事件
    ↓
showPopup(term) 显示弹窗
    ↓
启动 5 秒倒计时自动关闭
    ↓
用户可点击"查看更多信息"展开全量数据
```

---

## 七、当前限制与未来优化

### 7.1 当前限制

| 限制 | 说明 | 影响 |
|------|------|------|
| 大小写敏感 | "mesopleuron" ≠ "Mesopleuron" | 句首大写术语无法匹配 |
| 单词边界 | 要求完整单词 | "mesopleura" (复数) 无法匹配 "mesopleuron" |
| 无短语识别 | 单术语匹配 | "gregarious endoparasitoid of pupae" 无法识别 |
| 无词形还原 | 原形匹配 | 复数、所有格无法匹配原形 |
| Worker 内存限制 | KV 全量加载 | 术语数量受限于 Worker 内存 |
| 正则长度限制 | 所有术语合并为一个正则 | 超长正则可能影响性能 |

### 7.2 Phase 3 规划（NLP 增强）

- **大小写变体处理**：句首大写、标题全大写匹配
- **短语识别**：多词术语识别与匹配
- **词形还原**：复数形式还原（setae → seta, tubercles → tubercle）

---

## 八、关键代码位置速查

| 功能 | 文件 | 行号 | 函数/代码块 |
|------|------|------|-------------|
| 术语加载 | `term-handler.js` | 8-152 | `loadAllTerms()` |
| 缓存获取 | `term-handler.js` | 155-168 | `getTerms()` |
| 正则构建 | `term-handler.js` | 171-199 | `buildTermRegex()` |
| 多源合并 | `term-handler.js` | 66-112 | 排序+合并循环 |
| API 端点 | `index.js` | 31-126 | `/api/term` 处理 |
| 字段优先级 | `index.js` | 60-64 | `FIELD_PRIORITY` |
| 字段选择 | `index.js` | 67-85 | `pickBestField()` |
| 术语处理器 | `rewriter.js` | 836-882 | `createTermHandler()` |
| 白名单元素 | `rewriter.js` | 811-817 | `textSelectors` 数组 |
| 文本处理 | `rewriter.js` | 853-880 | `handleText()` |
| iframe 检测 | `rewriter.js` | 146-784 | `iframeDetectionScript` |

---

## 九、调试与日志

所有术语相关日志使用 `[TERM-READ]` 前缀，便于 Wrangler Tail 过滤：

```bash
# 查看术语加载日志
npx wrangler tail | grep "TERM-READ"

# 示例日志输出
[TERM-READ] Starting to load all terms from KV...
[TERM-READ] Found 1847 keys in KV
[TERM-READ] Successfully loaded 1847 valid terms
[TERM-READ] Built regex with 1847 patterns
[TERM-READ] Injected term highlight styles
[TERM-READ] Registered text handlers for 18 element types
[TERM-READ] Injected 3 terms in text segment
```
