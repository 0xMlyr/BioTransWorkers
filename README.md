# BioTransWorkers 开发指南

## 项目概述

**BioTransWorkers** 是一个专为昆虫形态学英文文献设计的边缘术语翻译工具，基于 Cloudflare Workers 部署。代理学术期刊网站，拦截 HTML 内容并注入英文昆虫学术语的中文翻译，高亮可点击，点击弹窗显示翻译、音标、定义。

- **部署地址**：https://biotrans.mlyr.top
- **使用方式**：`https://biotrans.mlyr.top/?url=目标论文地址`
- **运行环境**：Cloudflare Workers 免费层

### 技术栈

- Cloudflare Workers（边缘计算）
- HTMLRewriter（流式 HTML 处理）
- Cloudflare KV（术语存储 + AC自动机Trie）
- Aho-Corasick 自动机（术语匹配引擎）
- Service Worker（子资源拦截）
- Vanilla JS + CSS（无框架依赖）
- Python 3（本地数据构建工具）

### 开发阶段

| 阶段 | 状态 | 描述 |
|------|------|------|
| Phase 0 | ✅ 完成 | 透明代理框架：网页代理、资源重写、CSP处理 |
| Phase 1 | ✅ 完成 | **(已重构)** 术语注入系统（AC自动机替代正则匹配） |
| Phase 2 | ✅ 完成 | 弹窗交互：术语点击弹窗、iframe 跨帧通信、多源数据展示、悬停暂停倒计时 |
| Phase 3 | ✅ 完成 | 大小写无关匹配（AC自动机+原始大小写保留） |
| Phase 4 | 📋 规划 | 站点扩展、词形还原、短语识别 |

## 架构与请求流程

### 页面代理流程

```
用户请求 /?url=https://paper.example.com
    ↓
index.js：
  - 解析 ?url= 参数
  - 获取站点配置 (getSiteConfig)
  - 上游请求获取页面内容
  - 加载 AC 自动机 Trie：loadTrie(env) —— 1次KV get
    ↓
HTMLRewriter（rewriter.js）：
  - 注入 SW 注册脚本到 <head>
  - 注入术语高亮 CSS + 弹窗交互 JS
  - 移除 <base> 标签
  - 重写所有资源路径为 /?url=绝对路径
  - 处理懒加载图片：img[data-src] → 同时设置 src
  - 过滤黑名单脚本（MathJax、Google Maps）
  - 术语注入：AC 自动机逐文本段匹配 → <span class="bio-term">
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
主页面展示弹窗（倒计时5秒自动关闭，鼠标悬停暂停）
    ↓
用户可展开查看全量原始数据

【iframe 站点特殊流程】（如 ZooKeys）
iframe 内术语点击 → postMessage 发送给主页面 → 主页面展示弹窗
```

## 文件结构

```
src/
  index.js          主入口，请求路由、上游代理、AC自动机加载
  rewriter.js       HTMLRewriter 逻辑：路径重写、AC自动机术语注入、弹窗系统
  term-handler.js   AC自动机 Trie 加载与匹配算法
  sw.js             Service Worker 源码（字符串内联导出）
  webpage.js        错误页和落地页 HTML 模板
  sites/
    index.js        站点配置管理器
    pensoft.js      PenSoft/ZooKeys 站点特定配置

glossary/
  README.md         术语数据集文档
  terms/
    import_to_kv.py Python KV 导入工具（批量/合并模式）
    hao_core/       HAO 本体术语（~2600条）
    my_trem_202604/ 自定义术语（129条）
    engine_test/    工程测试词汇
  automaton/
    AC.md           AC自动机设计文档
    build_ac.py     AC自动机构建脚本（Python）
    ac_trie.json    构建产物（32647节点，1.6MB）

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
- 协调 AC 自动机加载与 HTMLRewriter 应用

**AC 自动机加载**（1次 KV get，955次 → 1次）：
```javascript
const trie = await loadTrie(env);  // TERM_ACTRIE.get("ac_trie")
```

**API 术语查询**（`/api/term?key=术语`）：
```javascript
const FIELD_PRIORITY = {
  translation: ['my_term_202604', 'hao_core_2023', 'hao_inflect', 'engine_test'],
  phonetic: ['hao_core_2023', 'my_term_202604'],
  def: ['hao_core_2023', 'my_term_202604']
};
```

**子资源判断逻辑**（不依赖 Content-Type，使用文件扩展名）：
```javascript
/\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|otf|eot|webp|json|xml|mp4|mp3)$/i
```

### 2. rewriter.js — HTMLRewriter 处理

**路径重写处理器**：

| 处理器 | 属性 | 说明 |
|--------|------|------|
| `HrefRewriter` | href | 链接重写，跳过锚点和 javascript: 协议 |
| `AttributeRewriter` | src, href, action | 通用属性重写 |
| `SrcsetRewriter` | srcset | 响应式图片路径重写 |
| `ScriptRewriter` | src | 脚本重写，支持黑名单过滤 |
| `ImgDataSrcRewriter` | data-src | 懒加载图片处理，同时设置 src |

**AC自动机术语注入**（替代原正则方案）：
```javascript
// 文本段 → AC匹配 → 直接替换
const matches = acMatch(content, trie);  // 返回 [{term, start, end}, ...]
// 过滤单词边界 + 去重叠（同位置取最长）
// 注入 <span class="bio-term" data-term="propodeum">propodeum</span>
```

**上下文感知排除（白名单模式）**：
37个安全文本元素，排除 `script`, `style`, `code`, `pre`, `textarea` 等。

**弹窗系统**：
- 主页面：注入完整弹窗 DOM + 样式 + 倒计时（5秒，悬停暂停）
- iframe：检测 `window.self !== window.top`，点击术语通过 `postMessage` 发送给父页面
- 欢迎弹窗：首次访问显示代理说明

### 3. term-handler.js — AC自动机引擎

**Trie 加载**（缓存5分钟）：
```javascript
export async function loadTrie(env) {
  const raw = await env.TERM_ACTRIE.get("ac_trie");
  const data = JSON.parse(raw);
  return data.trie;  // 32647节点，2605条术语
}
```

**AC匹配算法**：
```javascript
export function acMatch(text, trie) {
  // 1. 文本转小写，逐字符遍历Trie
  // 2. 沿children走，走不通沿fail回退
  // 3. 收集所有匹配 {term, start, end}
  // 4. 过滤单词边界（前后非\w字符）
  // 5. 贪心去重叠，同位置取最长
}
```

**大小写处理**：
- Trie 结构用小写 key 构建
- 匹配前文本转小写
- `output` 存储**原始大小写**术语（如 "Chalcidoidea" 而非 "chalcidoidea"）
- `data-term` 直接作为 KV key 使用，大小写匹配

**日志标签**：`[AC]`

### 4. sw.js — Service Worker

拦截页面内动态发出的无 `?url=` 请求，自动补全代理路径。放行跨域、SW自身、已有 `?url=` 的请求。

## KV 命名空间

| 命名空间 | Binding | 用途 | 操作次数/请求 |
|----------|---------|------|-------------|
| `TERM_GLOSSARY` | `TERM_GLOSSARY` | 术语详情数据（多源value） | 1次get（用户点击时） |
| `TERM_ACTRIE` | `TERM_ACTRIE` | AC自动机Trie（匹配引擎） | 1次get（启动加载） |

### 术语数据结构（多源整合）

```json
{
  "data": [
    {
      "metadata": {"source": "hao_core_2023", "ver": "1.0.0", "date": "20260419"},
      "detailed": {"id": "HAO:0000001", "name": "mesopleuron", "def": "...", "synonyms": [...]}
    },
    {
      "metadata": {"source": "my_term_202604", "ver": "1.0.0", "date": "20260419"},
      "detailed": {"translation": "中胸侧板", "phonetic": "/me-soh-PLOOR-on/"}
    }
  ]
}
```

### 字段优先级

| 字段 | 优先级顺序 |
|------|-----------|
| translation | my_term_202604 > hao_core_2023 > hao_inflect > engine_test |
| phonetic | hao_core_2023 > my_term_202604 |
| def | hao_core_2023 > my_term_202604 |

## 站点配置

### 已支持站点

| 网站 | 首页 | 状态 |
|------|------|------|
| **MDPI** | https://www.mdpi.com | 代理框架就绪 |
| **PLOS** | https://plos.org | 代理框架就绪 |
| **PenSoft ZooKeys** | https://zookeys.pensoft.net | ✅ 完整支持 |
| **NCBI** | https://www.ncbi.nlm.nih.gov | 代理框架就绪 |
| **EJT** | https://europeanjournaloftaxonomy.eu | 代理框架就绪 |
| **Mapress Zootaxa** | https://www.mapress.com/zootaxa | 代理框架就绪 |

### ZooKeys 特殊处理

- 正文在 `<iframe id="articleIfile">` 中动态加载
- PHP 路径重试：`/article/xxx/article_preview.php` → 404 → 尝试 `/article_preview.php`
- 术语注入覆盖 iframe 内容

## 本地开发

```bash
# 本地开发（热重载）
npx wrangler dev

# 部署到生产环境
npx wrangler deploy

# 构建 AC 自动机
cd glossary/automaton && python build_ac.py

# 导入自动机到 KV
npx wrangler kv key put --binding=TERM_ACTRIE --remote --preview false --key="ac_trie" --path=glossary/automaton/ac_trie.json
```

## 相关文件速查

| 文件 | 职责 |
|------|------|
| `src/index.js` | 主流程、请求路由、上游代理 |
| `src/rewriter.js` | HTMLRewriter、路径重写、AC自动机术语注入、弹窗系统 |
| `src/term-handler.js` | AC自动机 Trie 加载与匹配算法 |
| `src/sw.js` | Service Worker 源码 |
| `src/webpage.js` | 错误页和落地页模板 |
| `src/sites/index.js` | 站点配置管理器 |
| `src/sites/pensoft.js` | Pensoft 站点特定配置 |
| `glossary/terms/` | 术语数据源（HAO、自定义、测试） |
| `glossary/automaton/build_ac.py` | AC自动机构建脚本 |
| `glossary/automaton/AC.md` | AC自动机重构设计文档 |
| `wrangler.jsonc` | Workers 配置和 KV 绑定 |
