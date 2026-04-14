# HymenoTerm-Edge 开发指南（精简版）

## 项目目标（MVP）

BioTransWorks 是一个专为昆虫形态学文献设计的边缘术语翻译工具。

**当前最小目标（MVP）**：  
实现一个能正常工作的网页代理 + 术语注入基础框架。

具体要求：
- 通过 `/?url=目标论文地址` 代理学术文献网页
- 正确处理图片、CSS、JS 等资源路径（不出现断链）
- 处理 CSP 限制，让后续注入的样式和脚本能正常工作
- 在 HTML 文本中注入 `<span class="bio-term">` 标签（先不要求完美匹配）
- 不破坏原网页排版和布局
- 完全运行在 Cloudflare Workers 免费层

## 技术栈

- Cloudflare Workers
- HTMLRewriter（流式处理）
- Cloudflare KV（用于存储术语表）
- 纯 Vanilla JS + CSS（后续注入微交互）

## 当前项目状态

- 项目已初始化，wrangler.jsonc 配置完成
- 本地 `wrangler dev` 可正常运行 
    [wrangler:info] Ready on http://127.0.0.1:8787
- 已绑定自定义域名
    https://biotrans.mlyr.top/
- KV Namespace `"TERM_GLOSSARY"` 已创建并绑定

## 最小可运行版本（MVP）开发

### Phase 0 - 透明代理框架（当前最优先）

必须完成：
1. 支持 `?url=` 参数代理任意网页
2. 区分主 HTML 和子资源（图片、CSS、JS 等）
3. 重写资源路径（img src、link href、script src 等）
4. 处理 CSP（推荐使用 nonce，或开发阶段直接 delete）
5. 使用 HTMLRewriter 安全地扫描和修改文本节点

### Phase 1 - 基础术语匹配

- 从 KV 读取术语列表
- 实现简单的大小写敏感匹配（先用字符串包含或简单 replace）
- 在文本节点中包裹 `<span class="bio-term" data-term="xxx">`

### Phase 2 - 注入样式与气泡（后续）

- 注入简单 JS 实现悬停提示, 即鼠标移动到可翻译词汇上时，在词汇上方弹出一个不影响网页布局的临时小气泡，给出翻译。移动端可以点击后弹出。

## 关键注意事项

- **大小写敏感**：匹配时不要使用 `.toLowerCase()`
- **资源重写**：所有相对路径必须改写为 `?url=完整原始地址`
- **CSP**：学术网站通常有严格 CSP，必须处理，否则注入的样式/脚本会被阻挡
- **排版安全**：仅在 `text` 节点操作，不要修改元素结构
- **性能**：HTMLRewriter 是流式的，尽量保持逻辑轻量

## 本地开发命令

```bash
# 本地开发（热重载）
npx wrangler dev

# 部署到生产环境 慎用！
npx wrangler deploy