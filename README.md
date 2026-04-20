# 已支持的网站

| 网站 | 中文名/说明 | 首页 | 备注 |
|------|-------------|------|------|
| **MDPI** | 多学科数字出版机构 | https://www.mdpi.com | 综合 OA 期刊，含 Insects 等 |
| **PLOS** | 公共科学图书馆 | https://plos.org | 非盈利 OA 出版社 |
| **PenSoft ZooKeys** | 动物分类学钥匙 | https://zookeys.pensoft.net | Pensoft 旗舰期刊，分类学核心 |
| **NCBI** | 美国国家生物技术信息中心 | https://www.ncbi.nlm.nih.gov | PMC 全文、分类学数据库 |
| **EJT** | 欧洲分类学学报 | https://europeanjournaloftaxonomy.eu | 欧洲分类学会开放期刊 |
| **Mapress Zootaxa** | 动物分类学 | https://www.mapress.com/zootaxa | 全球分类学旗舰期刊 |



# BioTransWorkers 开发指南（完整版） 20260417

## 项目概述

**BioTransWorkers** 是一个专为昆虫形态学文献设计的边缘术语翻译工具，基于 Cloudflare Workers 部署。

- **部署地址**：https://biotrans.mlyr.top
- **使用方式**：`https://biotrans.mlyr.top/?url=目标论文地址`
- **运行环境**：Cloudflare Workers 免费层
- **KV 命名空间**：`TERM_GLOSSARY`（已绑定，已导入术语表）

### 技术栈

- Cloudflare Workers（边缘计算）
- HTMLRewriter（流式 HTML 处理）
- Cloudflare KV（术语存储）
- Service Worker（子资源拦截）
- Vanilla JS + CSS（无框架依赖）

### 开发阶段

| 阶段 | 状态 | 描述 |
|------|------|------|
| Phase 0 | ✅ 完成 | 透明代理框架：网页代理、资源重写、CSP处理 |
| Phase 1 | ✅ 完成 | 术语注入系统：KV读取、正则匹配、高亮标注 |
| Phase 2 | ✅ 完成 | 弹窗交互：术语点击弹窗、iframe 跨帧通信、多源数据展示 |
| Phase 3 | 🚧 开发中 | NLP增强：大小写变体、短语识别、词形还原 |
| Phase 4 | 📋 规划 | 站点扩展：MDPI、PLOS、NCBI等更多站点适配 |

## 架构与请求流程

### 页面代理流程

```
用户请求 /?url=https://paper.example.com
    ↓
index.js：
  - 解析 ?url= 参数
  - 获取站点配置 (getSiteConfig)
  - 上游请求获取页面内容
  - 加载术语：getTerms(env)
  - 构建正则：buildTermRegex(terms)
    ↓
HTMLRewriter（rewriter.js）：
  - 注入 SW 注册脚本到 <head>
  - 注入术语高亮 CSS + 弹窗交互 JS
  - 移除 <base> 标签
  - 重写所有资源路径为 /?url=绝对路径
  - 处理懒加载图片：img[data-src] → 同时设置 src（ZooKeys 兼容）
  - 过滤黑名单脚本（MathJax等）
  - 术语注入：在文本节点包裹 <span class="bio-term">
    ↓
返回给浏览器
    ↓
浏览器注册 Service Worker（sw.js）
SW 拦截后续无 ?url= 的同源请求，自动补全代理路径
```

### 术语弹窗交互流程

```
用户点击高亮术语（.bio-term）
    ↓
注入的 JS 监听点击事件
    ↓
API 查询 /api/term?key=术语
    ↓
index.js 多源整合（按 FIELD_PRIORITY 选择最佳字段）
    ↓
返回 {name, translation, phonetic, def, sources}
    ↓
主页面展示弹窗（倒计时5秒自动关闭）
    ↓
用户可展开查看全量原始数据

【iframe 站点特殊流程】（如 ZooKeys）
iframe 内术语点击 → postMessage 发送给主页面 → 主页面展示弹窗
```

## 文件结构

```
src/
  index.js          主入口，请求路由、上游代理、术语加载
  rewriter.js       HTMLRewriter 逻辑：路径重写、术语注入
  term-handler.js   术语管理：KV加载、正则构建、缓存
  sw.js             Service Worker 源码（字符串内联导出）
  webpage.js        错误页和落地页 HTML 模板
  sites/
    index.js        站点配置管理器
    pensoft.js      PenSoft/ZooKeys 站点特定配置
glossary/
  glossary.json     KV 批量导入文件
  glossary.txt      原始术语表
  hao.json          Hymenoptera Anatomy Ontology 完整数据
wrangler.jsonc      Wrangler 配置（KV绑定、兼容性日期）
```

## 核心组件详解

### 1. index.js — 主入口与请求路由

**关键职责**：
- 解析 `?url=` 参数，验证目标 URL
- 提供 Service Worker 脚本 (`/sw.js`)
- **API 端点 `/api/term`**：术语查询，多源数据整合，字段优先级选择
- 上游请求头构造（UA、Referer、Cookie透传）
- 区分主 HTML 和子资源（通过文件扩展名）
- CSP 头删除（content-security-policy, x-frame-options等）
- 协调术语加载与 HTMLRewriter 应用

**API 术语查询**（`/api/term?key=术语`）：
```javascript
// 多源数据整合，字段优先级配置
const FIELD_PRIORITY = {
  translation: ['my_term_202604', 'hao_core_2023', 'hao_inflect', 'engine_test'],
  phonetic: ['hao_core_2023', 'my_term_202604'],
  def: ['hao_core_2023', 'my_term_202604']
};
// 返回：name, translation, phonetic, def, translation_source, 及全量 sources 数据
```

**子资源判断逻辑**（不依赖 Content-Type，使用文件扩展名）：
```javascript
/\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|otf|eot|webp|json|xml|mp4|mp3)$/i
```

**PHP 路径重试**（Pensoft 特有）：
当上游返回 404 且路径包含 `.php` 时，自动尝试根路径：
```
/article/133127/article_preview.php → /article_preview.php
```

### 2. rewriter.js — HTMLRewriter 处理

**路径重写处理器**：

| 处理器 | 属性 | 说明 |
|--------|------|------|
| `HrefRewriter` | href | 链接重写，跳过锚点和 javascript: 协议 |
| `AttributeRewriter` | src, href, action | 通用属性重写 |
| `SrcsetRewriter` | srcset | 响应式图片路径重写 |
| `ScriptRewriter` | src | 脚本重写，支持黑名单过滤 |
| `ImgDataSrcRewriter` | data-src | **新增**：懒加载图片处理，同时设置 src 属性 |

**全局脚本黑名单**（无法代理的动态加载脚本）：
```javascript
/cdnjs\.cloudflare\.com\/ajax\/libs\/mathjax/i   // MathJax 动态加载子资源
/maps\.googleapis\.com/i                           // Google Maps
/maps\.gstatic\.com/i                              // Google Maps Static
```

**术语注入逻辑**：

1. **样式注入**（`<head>` 处理器）：
```css
.bio-term {
  background: linear-gradient(180deg, rgba(0,86,179,0.15) 0%, rgba(0,86,179,0.25) 100%);
  border-bottom: 1px dotted #0056b3;
  padding: 0 2px;
  border-radius: 2px;
  cursor: help;
}
```

2. **文本处理**：
```javascript
// 预处理过滤：只有包含3+字母的内容才检查
if (!/[a-zA-Z]{3,}/.test(content)) return;

// 正则检测（使用 lastIndex = 0 重置）
regex.lastIndex = 0;
if (!regex.test(content)) return;

// 替换注入
const replaced = content.replace(regex, (match) => 
  `<span class="bio-term" data-term="${match}">${match}</span>`
);
text.replace(replaced, { html: true });
```

3. **上下文感知排除（白名单模式）**：

明确列出允许注入的元素类型（而非黑名单）：
```javascript
const textSelectors = [
  'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'li', 'td', 'th', 'figcaption', 'caption', 'blockquote',
  'article', 'section', 'aside', 'header', 'footer', 'main',
  'em', 'strong', 'i', 'b', 'u', 'mark', 'small', 'del', 'ins',
  'sub', 'sup', 'time', 'label', 'summary', 'figcaption'
];
```

**明确排除的元素**：
| 元素 | 原因 |
|------|------|
| `script` | 破坏 JavaScript 代码 |
| `style` | 破坏 CSS 规则 |
| `noscript` | 同上 |
| `code`, `pre`, `kbd`, `samp` | 代码块不应被污染 |
| `textarea` | 用户输入区域 |
| `title` | 页面标题保持干净 |

**为什么不使用 `rewriter.on("*")`？**
通配符会匹配 `<script>` 和 `<style>`，破坏页面功能。HTMLRewriter 没有元素退出回调，无法实现可靠的嵌套跟踪。

### 3. term-handler.js — 术语管理

**批量加载**：
```javascript
const keys = await env.TERM_GLOSSARY.list();
const terms = await Promise.all(
  keys.keys.map(async (keyObj) => {
    const value = await env.TERM_GLOSSARY.get(keyObj.name);
    const parsed = JSON.parse(value);
    return { key: keyObj.name, translation: parsed.translation, phonetic: parsed.phonetic };
  })
);
```

**内存缓存**：
- TTL：5分钟
- Worker 实例间不共享（冷启动会重新加载）

**正则构建**：
```javascript
// 转义正则特殊字符并按长度降序排序
const escaped = terms
  .map(t => t.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  .sort((a, b) => b.length - a.length);

// 大小写敏感，全局匹配，单词边界
const regex = new RegExp(`\\b(${pattern})\\b`, 'g');
```

**日志标识**：所有日志前缀 `[TERM-READ]`，便于 Wrangler Tail 过滤。

### 4. sw.js — Service Worker

**核心职责**：拦截页面内 JS 动态发出的无 `?url=` 请求（XHR、fetch），自动补全代理路径。

**放行规则**（不拦截）：
- 跨域请求（`url.origin !== WORKER_ORIGIN`）
- SW 自身（`/sw.js`）
- 已有 `?url=` 参数的请求

**base 提取**：从 `Referer` 头中的 `?url=` 参数提取原始域名，构建完整代理 URL。

## KV 术语表

### 数据结构（支持多源整合）

```
Key:   术语原文（大小写敏感，如 "mesopleuron"）
Value: 多源数据数组格式，支持字段优先级选择
```

**新格式**（多源数据）：
```json
{
  "data": [
    {
      "metadata": {"source": "hao_core_2023", "ver": "1.0", "date": "2026-04"},
      "detailed": {"name": "mesopleuron", "translation": "中胸侧板", "phonetic": "/me-soh-PLOOR-on/", "def": "The lateral plate of the mesothorax"}
    },
    {
      "metadata": {"source": "my_term_202604", "ver": "2.1", "date": "2026-04"},
      "detailed": {"translation": "中胸侧板", "chinese_name": "中胸侧板"}
    }
  ]
}
```

**兼容旧格式**（单源数据）：
```json
{"translation":"中胸侧板","phonetic":"/null/","source":"legacy"}
```

### 字段优先级配置

API 查询时按优先级选择最佳字段：
```javascript
const FIELD_PRIORITY = {
  translation: ['my_term_202604', 'hao_core_2023', 'hao_inflect', 'engine_test'],
  phonetic: ['hao_core_2023', 'my_term_202604'],
  def: ['hao_core_2023', 'my_term_202604']
};
```

### 批量导入格式（glossary.json）

```json
[
  {
    "key": "mesopleuron",
    "value": "{\"data\":[...]}"
  }
]
```

**注意**：`value` 是 JSON 字符串的 JSON 字符串（KV 存储格式）。

### 导入命令

```bash
npx wrangler kv bulk put --binding=TERM_GLOSSARY --remote --preview false glossary/glossary.json
```

## 站点特定配置

### Pensoft / ZooKeys 架构特点

**页面结构**：
- 主页面（`/article/133127/`）只包含导航、侧边栏、目录
- **正文内容完全在一个 `<iframe id="articleIframe">` 里渲染**
- iframe 的 `src` 由 `article_en.bundle.js` 动态设置为 `article_preview.php?id=133127`
- `article_preview.php` 重定向到 `articles.php?id=133127`，后者返回完整正文 HTML

**动态数据加载**：
```
/lib/ajax_srv/article_ajax_srv.php?action=get_article_localities&article_id=133127
/lib/ajax_srv/article_ajax_srv.php?action=get_main_list_element&element_type=4&article_id=133127
```

**站点配置**（`src/sites/pensoft.js`）：
```javascript
export const pensoftConfig = {
  phpRetry: true,
  scriptBlocklist: [/cdnjs\.cloudflare\.com\/ajax\/libs\/mathjax/i],
  termInjectionScope: "iframe#articleIframe"
};
```

## 性能考虑

| 项目 | 当前策略 | 限制 |
|------|----------|------|
| KV 加载 | 批量 `list()` + 并行 `get()` | 受 CF Workers CPU 时间限制（< 50ms 推荐）|
| 缓存 | 5分钟内存缓存 | Worker 实例间不共享 |
| 正则构建 | 请求时构建 | 可优化为预构建静态正则 |
| 文本处理 | 流式 HTMLRewriter | 只处理文本节点，不构建完整 DOM |

## 关键注意事项

- **大小写敏感**：匹配时保留原文大小写，`mesopleuron` ≠ `Mesopleuron`
- **资源重写**：所有相对路径必须改写为 `?url=完整原始地址`
- **CSP 处理**：学术网站通常有严格 CSP，直接删除相关响应头
- **排版安全**：仅在 `text` 节点操作，不修改元素结构
- **长术语优先**：正则构建时按长度降序排序，确保 "mesopleuron" 先于 "pleuron" 匹配

## 本地开发

```bash
# 本地开发（热重载）
npx wrangler dev

# 部署到生产环境
npx wrangler deploy

# KV 操作（必须加 --remote）
npx wrangler kv bulk put --binding=TERM_GLOSSARY --remote glossary/glossary.json
```

**注意**：`wrangler dev` 本地模拟运行时出站网络不稳定（ETIMEDOUT），建议直接部署到生产环境测试。

## 已实现功能详情

### Phase 2 — 弹窗交互系统（✅ 已完成）

**核心实现**：
1. **术语点击监听**：注入轻量级 JS 监听 `.bio-term` 点击事件
2. **API 查询**：通过 `/api/term?key=术语` 获取多源整合数据
3. **弹窗展示**：
   - 主显示区：术语名、音标、定义、翻译（带来源标注）
   - 倒计时自动关闭（5秒）
   - 展开按钮查看全量原始数据
4. **iframe 跨帧通信**：
   - iframe 内术语点击 → `window.parent.postMessage` → 主页面接收并展示弹窗
   - 支持 Pensoft ZooKeys 等 iframe 架构站点

**代码位置**：`rewriter.js` 中 `applyRewriter` 函数末尾注入的 popup system JS

## 下一步开发方向

### Phase 3 — NLP 增强（🚧 开发中）
- **大小写变体处理**：句首大写、标题全大写匹配
- **短语识别**：多词术语如 "gregarious endoparasitoid of pupae"
- **词形还原**：处理复数形式（setae → seta, tubercles → tubercle）

### Phase 4 — 站点扩展（📋 规划）
- 分析 MDPI、PLOS、NCBI 等站点的正文选择器
- 在 `src/sites/index.js` 添加更多站点配置
- 适配各站点的动态加载机制（懒加载、AJAX）

## 已支持的网站

| 网站 | 中文名 | 首页 | 状态 |
|------|--------|------|------|
| **MDPI** | 多学科数字出版机构 | https://www.mdpi.com | 代理框架就绪 |
| **PLOS** | 公共科学图书馆 | https://plos.org | 代理框架就绪 |
| **PenSoft ZooKeys** | 动物分类学钥匙 | https://zookeys.pensoft.net | ✅ 完整支持（术语注入+图片代理+弹窗） |
| **NCBI** | 美国国家生物技术信息中心 | https://www.ncbi.nlm.nih.gov | 代理框架就绪 |
| **EJT** | 欧洲分类学学报 | https://europeanjournaloftaxonomy.eu | 代理框架就绪 |
| **Mapress Zootaxa** | 动物分类学 | https://www.mapress.com/zootaxa | 代理框架就绪 |

---

## 相关文件速查

| 文件 | 职责 |
|------|------|
| `src/index.js` | 主流程、请求路由、上游代理 |
| `src/rewriter.js` | HTMLRewriter、路径重写、术语注入 |
| `src/term-handler.js` | 术语加载、正则构建、缓存管理 |
| `src/sw.js` | Service Worker 源码 |
| `src/webpage.js` | 错误页和落地页模板 |
| `src/sites/index.js` | 站点配置管理器 |
| `src/sites/pensoft.js` | Pensoft 站点特定配置 |
| `glossary/glossary.json` | 本地术语数据备份 |
| `wrangler.jsonc` | Workers 配置和 KV 绑定 |