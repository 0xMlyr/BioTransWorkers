# 术语注入系统开发文档 20260417

## 概述

本轮开发实现了 BioTransWorkers 的**最小可运行术语注入系统**（Phase 1）。系统从 Cloudflare KV 批量加载术语，通过 HTMLRewriter 流式处理代理页面，将匹配到的术语包裹在 `<span class="bio-term">` 标签中，并添加 CSS 高亮效果。

---

## 核心组件

### 1. term-handler.js — 术语管理模块

**位置**: `src/term-handler.js`

#### 功能
- **批量加载**: 从 KV `TERM_GLOSSARY` namespace 一次性加载所有 key（使用 `list()` + 并行 `get()`）
- **内存缓存**: 5分钟 TTL，避免重复 KV 查询
- **数据解析**: KV value 为 JSON 字符串，格式：`{"translation":"中文","phonetic":"/音标/"}`
- **正则构建**: 大小写敏感，按术语长度降序排序（优先匹配长术语如 "mesopleuron" 而非短术语 "pleuron"）

#### 关键代码
```javascript
// 转义正则特殊字符
const escaped = terms
  .map(t => t.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  .sort((a, b) => b.length - a.length);

// 构建单词边界正则（大小写敏感）
const regex = new RegExp(`\\b(${pattern})\\b`, 'g');
```

#### 日志标识
所有日志前缀 `[TERM-READ]`，便于 Wrangler Tail 过滤：
- `[TERM-READ] Starting to load all terms` — 开始加载
- `[TERM-READ] Found X keys in KV` — KV key 数量
- `[TERM-READ] Successfully loaded X valid terms` — 成功加载
- `[TERM-READ] Sample terms: ...` — 前5个示例术语
- `[TERM-READ] Terms loaded: X, Regex available: true` — 处理前状态
- `[TERM-READ] Injected X terms in text segment` — 注入成功

---

### 2. rewriter.js — HTMLRewriter 处理

**位置**: `src/rewriter.js`

#### 术语注入逻辑

1. **样式注入**（`<head>` 处理器）:
```javascript
el.append(`<style>
.bio-term {
  background: linear-gradient(180deg, rgba(0,86,179,0.15) 0%, rgba(0,86,179,0.25) 100%);
  border-bottom: 1px dotted #0056b3;
  padding: 0 2px;
  border-radius: 2px;
  cursor: help;
}
</style>`, { html: true });
```

2. **文本处理**（`body` 和 `*` 处理器）:
```javascript
// 预处理过滤：只有包含3+字母的内容才检查
if (!/[a-zA-Z]{3,}/.test(content)) return;

// 正则检测（使用 lastIndex = 0 重置）
regex.lastIndex = 0;
if (!regex.test(content)) return;

// 替换注入（只保留 data-term，不暴露翻译）
const replaced = content.replace(regex, (match) => 
  `<span class="bio-term" data-term="${match}">${match}</span>`
);
text.replace(replaced, { html: true });
```

#### 输出 HTML 结构
```html
<span class="bio-term" data-term="mesopleuron">mesopleuron</span>
```

---

### 3. index.js — 主流程集成

**位置**: `src/index.js`

#### 请求处理流程
1. 解析 `?url=` 参数获取目标 URL
2. 获取站点配置 (`getSiteConfig`)
3. 上游请求获取页面内容
4. **加载术语**: `const terms = await getTerms(env)`
5. **构建正则**: `const termRegex = buildTermRegex(terms)`
6. 创建 HTMLRewriter 并调用 `applyRewriter(rewriter, finalUrl, workerOrigin, siteConfig, terms, termRegex)`
7. 流式返回转换后的响应

---

## 术语匹配策略（关键扩展点）

### 当前实现

| 特性 | 实现方式 |
|------|----------|
| **大小写** | 敏感（`mesopleuron` ≠ `Mesopleuron`）|
| **匹配范围** | 整个 `body` 和所有元素文本节点 |
| **边界检测** | 单词边界 `\b`（避免匹配子串如 "pleuron" 在 "mesopleuron" 中）|
| **优先级** | 长术语优先（降序排序确保 "mesopleuron" 先于 "pleuron"）|
| **缓存** | 5分钟内存缓存 |

### 后期 NLP 扩展方向

#### 1. 大小写变体处理
当前问题：学术论文中术语可能首字母大写（句首）或全大写（标题）。

**候选方案**:
```javascript
// 方案 A: 预处理统一为小写匹配
const lowerContent = content.toLowerCase();
// 但需保留原文用于替换

// 方案 B: 正则修饰符 i + 大小写映射表
const regex = new RegExp(pattern, 'gi');
const caseMap = new Map(); // 存储原始大小写形式

// 方案 C: 为每个术语生成大小写变体
const patterns = terms.flatMap(t => [
  t.key,                          // original
  t.key.toLowerCase(),           // lowercase
  t.key[0].toUpperCase() + t.key.slice(1)  // capitalize
]);
```

#### 2. 短语识别（多词术语）
当前问题：只能匹配单单词如 "ovipositor"，无法匹配 "gregarious endoparasitoid of pupae"。

**候选方案**:
```javascript
// 将多词术语预处理为带空格的正则
const phrasePattern = "gregarious\\s+endoparasitoid\\s+of\\s+pupae";
// 或使用更灵活的空白匹配
const flexiblePattern = "gregarious\\s+endoparasitoid(?:\\s+of\\s+pupae)?";
```

#### 3. 词形还原（可选）
处理复数形式：
- `setae` → `seta`（拉丁复数）
- `tubercles` → `tubercle`（英语复数）

**候选方案**:
```javascript
// 添加复数变体到模式
const variants = terms.flatMap(t => [
  t.key,
  t.key + 's',           // English plural
  t.key.replace(/a$/, 'ae'),  // Latin plural -a → -ae
  t.key.replace(/um$/, 'a'),  // Latin plural -um → -a
]);
```

#### 4. 上下文感知排除（白名单模式）

**当前实现（白名单）**:
使用白名单模式，明确列出允许注入的元素类型，而非黑名单排除（避免遗漏）。

```javascript
// 明确列出的 31 种安全文本元素
const textSelectors = [
  'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'li', 'td', 'th', 'figcaption', 'caption', 'blockquote',
  'article', 'section', 'aside', 'header', 'footer', 'main',
  'em', 'strong', 'i', 'b', 'u', 'mark', 'small', 'del', 'ins',
  'sub', 'sup', 'time', 'label', 'summary', 'figcaption'
];

// 为每个选择器注册处理器
for (const selector of textSelectors) {
  rewriter.on(selector, {
    text(text) { termHandler.handleText(text); }
  });
}
```

**明确排除的元素**（不会注入术语）：
| 元素 | 原因 |
|------|------|
| `script` | 破坏 JavaScript 代码 |
| `style` | 破坏 CSS 规则 |
| `noscript` | 同上 |
| `code`, `pre`, `kbd`, `samp` | 代码块不应被污染 |
| `textarea` | 用户输入区域 |
| `title` | 页面标题保持干净 |
| `img`, `video` 等媒体的 `alt` 属性 | HTMLRewriter 的 `text` 处理器只处理文本节点，不触及属性 |

**为什么不使用黑名单？**
黑名单容易遗漏（如 `<svg>` 内的 `<text>`、自定义组件等），白名单更安全可控。

**为什么不使用 `rewriter.on("*")`？**
通配符会匹配 `<script>` 和 `<style>`，破坏页面功能。HTMLRewriter 没有元素退出回调，无法实现可靠的嵌套跟踪。

**替代方案（如果后期需要扩展）**:
```javascript
// 黑名单模式（不推荐，仅供参考）
const excludeElements = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE']);
rewriter.on("*", {
  element(el) { if (excludeElements.has(el.tagName)) skipDepth++; },
  text(text) { if (skipDepth === 0) termHandler.handleText(text); }
});
// 缺点：无法检测元素结束，嵌套元素深度跟踪失效
```

#### 5. 站点特定选择器（已预留配置）
`src/sites/pensoft.js` 已配置 `termInjectionScope`，可扩展为：
```javascript
// 只处理特定区域内的文本
export const pensoftConfig = {
  contentSelectors: ["iframe#articleIframe", ".P-Article-Preview-Form"],
  excludeSelectors: [".headlineContainer", "footer", ".references"]
};
```

---

## KV 数据结构

### Key
术语原文（大小写敏感，如 `mesopleuron`）

### Value
```json
{
  "translation": "中胸侧板",
  "phonetic": "/null/"
}
```

### 批量导入格式（glossary.json）
```json
[
  {
    "key": "mesopleuron",
    "value": "{\"translation\":\"中胸侧板\",\"phonetic\":\"/null/\"}"
  }
]
```

**注意**: `value` 是 JSON 字符串的 JSON 字符串（KV 存储格式）。

---

## 性能考虑

| 项目 | 当前策略 | 限制 |
|------|----------|------|
| KV 加载 | 批量 `list()` + 并行 `get()` | 受 CF Workers CPU 时间限制（< 50ms 推荐）|
| 缓存 | 5分钟内存缓存 | Worker 实例间不共享，冷启动会重新加载 |
| 正则构建 | 请求时构建 | 可优化为预构建静态正则 |
| 文本处理 | 流式 HTMLRewriter | 只处理文本节点，不构建完整 DOM |

---

## 测试验证

### 已验证站点
- ✅ ZooKeys (Pensoft) — `zookeys.pensoft.net`
- ✅ 预期支持所有 Pensoft 旗下期刊

### 验证方法
1. 访问代理页面: `https://biotrans.mlyr.top/?url=https://zookeys.pensoft.net/article/5713/`
2. 搜索 `span.bio-term` 元素数量（测试时达到 664 个）
3. 检查高亮效果（淡蓝背景 + 虚线边框）
4. 确认无默认 tooltip（已移除 `title` 属性）

---

## 下一步开发方向

1. **Phase 2 — 弹窗交互**
   - 注入轻量级 JS 监听 `.bio-term` 点击事件
   - 从 `data-term` 读取术语，查询 KV 显示翻译弹窗
   - 移动端适配（触摸点击 vs 悬停）

2. **Phase 3 — NLP 增强**
   - 实现大小写变体匹配
   - 支持多词术语短语识别
   - 添加排除区域配置

3. **Phase 4 — 站点扩展**
   - 分析 MDPI、PLOS、NCBI 等站点的正文选择器
   - 在 `src/sites/index.js` 添加更多站点配置

---

## 相关文件

- `src/term-handler.js` — 术语加载与正则构建
- `src/rewriter.js` — HTMLRewriter 与文本注入
- `src/index.js` — 主流程与 KV 绑定
- `src/sites/pensoft.js` — 站点特定配置
- `glossary/glossary.json` — 本地术语数据备份
