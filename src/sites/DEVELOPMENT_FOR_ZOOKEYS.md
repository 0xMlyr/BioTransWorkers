# BioTransWorkers 开发资料（Phase 0 完成后）

## 项目概况

- 部署地址：https://biotrans.mlyr.top
- 使用方式：`https://biotrans.mlyr.top/?url=目标论文地址`
- 运行环境：Cloudflare Workers 免费层
- KV 命名空间：`TERM_GLOSSARY`（已绑定，已导入术语表）

---

## 文件结构

```
src/
  index.js     主入口，请求路由、代理逻辑、白名单
  rewriter.js  HTMLRewriter 路径重写逻辑
  sw.js        Service Worker 源码（以字符串形式内联导出）
  error.js     错误页 HTML 模板
glossary/
  glossary.txt 原始术语表（英文 翻译）
  convert.js   术语表转换脚本（生成 glossary.json）
  glossary.json KV 批量导入文件（gitignore 可选）
```

---

## 架构与请求流程

```
用户请求 /?url=https://paper.example.com
    ↓
index.js：白名单校验 → fetch 上游 → 清理响应头
    ↓
HTMLRewriter（rewriter.js）：
  - 注入 SW 注册脚本到 <head>
  - 移除 <base> 标签
  - 重写所有资源路径为 /?url=绝对路径
  - 过滤黑名单脚本（MathJax 等）
    ↓
返回给浏览器
    ↓
浏览器注册 Service Worker（sw.js）
SW 拦截后续无 ?url= 的同源请求，自动补全代理路径
```

---

## 关键技术细节

### 1. 路径重写

所有 HTML 属性中的 URL（`href`、`src`、`srcset`、`action`）统一转换为：
```
/?url=encodeURIComponent(绝对路径)
```
相对路径通过 `new URL(original, base)` 解析为绝对路径，base 使用**重定向后的最终 URL**（`upstream.url`），而非请求时的原始 URL。

### 2. CSP 处理

直接删除以下响应头，不使用 nonce 方案：
- `content-security-policy`
- `content-security-policy-report-only`
- `x-frame-options`
- `x-content-type-options`

### 3. 子资源判断

不依赖上游响应的 `content-type`（因为 404 页面也会返回 `text/html`），改用请求 URL 的**文件扩展名**判断是否为子资源：
```js
/\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|webp|json|xml|mp4|mp3)$/i
```
子资源直接透传，不走 HTMLRewriter。

### 4. Service Worker

SW 以字符串形式内联在 `sw.js` 中，通过 `/sw.js` 路由动态返回，无需静态文件托管。

SW 的核心职责：拦截页面内 JS 动态发出的无 `?url=` 请求（如 XHR、fetch），自动补全代理路径。

base 提取优先级：
1. 请求的 `Referer` 头中的 `?url=` 参数
2. `clients.matchAll()` 找到当前活跃窗口的 URL 中的 `?url=` 参数

SW 对以下请求不拦截，直接放行：
- 跨域请求（`url.origin !== WORKER_ORIGIN`）
- SW 自身（`/sw.js`）
- 已有 `?url=` 参数的请求

### 5. Referer 自动补全（Worker 端）

当 Worker 收到无 `?url=` 参数的请求时（SW 未激活或 XHR 时机过早），从 `Referer` 头提取原始域名自动补全。

仅对子资源生效，通过 `sec-fetch-dest` 头判断是否为导航请求，避免直接访问 `biotrans.mlyr.top/` 时被意外重定向。

### 6. 上游请求头

```js
{
  "User-Agent": 透传用户 UA,
  "Referer": targetUrl.origin + "/",
  "Cookie": 透传用户 Cookie（如有）
}
```

Cookie 透传用于需要会话的页面，但注意浏览器只会在请求 `biotrans.mlyr.top` 时带上该域名下的 Cookie，不会自动带上目标网站的 Cookie。

### 7. PHP 路径重试

部分网站（如 pensoft）使用服务器 URL rewrite，导致多级路径下的 `.php` 文件返回 404，但根路径下同名文件正常。

当上游返回 404 且路径包含 `.php` 时，自动用根路径重试：
```
/article/133127/article_preview.php → /article_preview.php
```

---

## Pensoft / ZooKeys 特有架构

这是调试过程中掌握的 pensoft 网站架构，对后续 Phase 1 术语注入有直接影响。

### 页面结构

- 主页面（`/article/133127/`）只包含导航、侧边栏、目录
- **正文内容完全在一个 `<iframe id="articleIframe">` 里渲染**
- iframe 的 `src` 由 `article_en.bundle.js` 动态设置为 `article_preview.php?id=133127`
- `article_preview.php` 在服务器端重定向到 `articles.php?id=133127`，后者返回完整正文 HTML

### 动态数据加载

正文渲染依赖两个 XHR 接口：
```
/lib/ajax_srv/article_ajax_srv.php?action=get_article_localities&article_id=133127
/lib/ajax_srv/article_ajax_srv.php?action=get_main_list_element&element_type=4&article_id=133127
```
这些接口无需登录，公开可访问。

### 被移除的脚本

MathJax（来自 cdnjs）在运行时用相对路径动态加载子文件，无法被代理，已加入黑名单直接移除：
```js
/cdnjs\.cloudflare\.com\/ajax\/libs\/mathjax/i
```
影响：数学公式显示为原始 LaTeX 源码，对昆虫形态学文献无实质影响。

### 无法修复的问题

- `<iframe>` 内的跨域 JS 访问父页面 DOM（浏览器同源策略，预期行为）
- 部分第三方追踪脚本被广告拦截器屏蔔（无害）

---

## KV 术语表

### 数据结构

```
key:   "abdomen"
value: "{\"translation\":\"腹部\",\"phonetic\":\"/null/\"}"
```

- `translation`：中文翻译，保留括号和分号（括号表示非惯用译名）
- `phonetic`：音标，当前全部为 `/null/` 占位，后续更新

### 导入流程

```bash
node glossary/convert.js   # 生成 glossary.json
npx wrangler kv bulk put --binding=TERM_GLOSSARY --remote --preview false glossary/glossary.json
```

---

## 域名白名单

当前允许代理的域名（`src/index.js` 中的 `ALLOWED_HOSTS`）：

```
pensoft.net（及所有子域名）
pmc.ncbi.nlm.nih.gov
www.ncbi.nlm.nih.gov
academic.oup.com
www.journals.uchicago.edu
onlinelibrary.wiley.com
link.springer.com
www.mapress.com
resjournals.onlinelibrary.wiley.com
```

新增域名直接在数组里追加即可。

---

## 本地开发注意事项

- `wrangler dev` 在本地模拟运行时出站网络不稳定（ETIMEDOUT），建议直接部署到生产环境测试
- 部署命令：`npx wrangler deploy`
- KV 操作需加 `--remote` 和 `--preview false` 参数

---

## Phase 1 开发准备

下一步：在 iframe 内的正文 HTML（`articles.php` 返回的内容）中注入术语标注。

关键约束：
- HTMLRewriter 的 `.text()` 回调会将文本节点**分块**传入，单个术语可能被切断在两个 chunk 之间，需要做 chunk 缓冲
- 仅在文本节点操作，不修改元素结构
- 大小写敏感匹配
- 需要从 KV 读取术语列表，建议在 Worker 启动时一次性读取并缓存，不要每个请求都读
- 注入格式：`<span class="bio-term" data-term="abdomen">abdomen</span>`
