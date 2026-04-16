function decodeHtmlEntities(str) {
  return str.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

function toProxyUrl(original, base, workerOrigin) {
  if (!original) return original;
  if (original.startsWith("data:") || original.startsWith("blob:") || original.startsWith("javascript:")) return original;
  try {
    const absolute = new URL(decodeHtmlEntities(original), base).href;
    return `${workerOrigin}/?url=${encodeURIComponent(absolute)}`;
  } catch {
    return original;
  }
}

class AttributeRewriter {
  constructor(attr, base, workerOrigin) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (val) el.setAttribute(this.attr, toProxyUrl(val, this.base, this.workerOrigin));
  }
}

// 专门的 href 处理器：跳过锚点链接和 javascript: 协议
class HrefRewriter {
  constructor(base, workerOrigin) {
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute("href");
    if (!val) return;
    // 锚点链接和 javascript: 协议不需要代理
    if (val.startsWith("#") || val.startsWith("javascript:")) {
      console.log(`[REWRITE] Skipping anchor/js href: ${val.substring(0, 50)}`);
      return;
    }
    const newVal = toProxyUrl(val, this.base, this.workerOrigin);
    if (newVal !== val) {
      console.log(`[REWRITE] href: ${val.substring(0, 60)}... -> ${newVal.substring(0, 60)}...`);
    }
    el.setAttribute("href", newVal);
  }
}

class BaseRemover {
  element(el) { el.remove(); }
}

class ScriptRewriter {
  constructor(attr, base, workerOrigin, blocklist) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
    this.blocklist = blocklist;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (!val) return;
    if (this.blocklist.some(re => re.test(val))) {
      console.log(`[BLOCK] Script removed: ${val.substring(0, 80)}...`);
      el.remove();
      return;
    }
    const newVal = toProxyUrl(val, this.base, this.workerOrigin);
    if (newVal !== val) {
      console.log(`[REWRITE] script src: ${val.substring(0, 50)}... -> ${newVal.substring(0, 50)}...`);
    }
    el.setAttribute(this.attr, newVal);
  }
}

class SrcsetRewriter {
  constructor(attr, base, workerOrigin) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (!val) return;
    const rewritten = val.split(",").map(part => {
      const [url, ...descriptor] = part.trim().split(/\s+/);
      const proxied = toProxyUrl(url, this.base, this.workerOrigin);
      return descriptor.length ? `${proxied} ${descriptor.join(" ")}` : proxied;
    }).join(", ");
    el.setAttribute(this.attr, rewritten);
  }
}

// 通用脚本黑名单：这些外部脚本会在运行时动态加载子资源，代理后无法正常工作
const GLOBAL_SCRIPT_BLOCKLIST = [
  /maps\.googleapis\.com/i,
  /maps\.gstatic\.com/i,
];

export function applyRewriter(rewriter, finalUrl, workerOrigin, siteConfig = {}, terms = [], termRegex = null) {
  const base = finalUrl;
  const scriptBlocklist = [...GLOBAL_SCRIPT_BLOCKLIST, ...(siteConfig.scriptBlocklist ?? [])];
  console.log(`[REWRITER] Base: ${base}, Blocklist count: ${scriptBlocklist.length}`);

  // 创建术语处理器
  const termHandler = createTermHandler(terms, termRegex);

  rewriter.on("head", {
    element(el) {
      console.log("[REWRITER] <head> found - injecting SW registration and term styles");
      // 注入 Service Worker 注册
      el.prepend(`<script>(function(){if(!navigator.serviceWorker)return;navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(function(){});})();</script>`, { html: true });
      
      // 注入术语高亮样式
      const termStyles = `<style>
.bio-term {
  background: linear-gradient(180deg, rgba(46,125,50,0.15) 0%, rgba(46,125,50,0.25) 100%);
  border-bottom: 1px dotted #2e7d32;
  padding: 0 2px;
  border-radius: 2px;
  cursor: help;
  transition: background 0.2s ease;
}
.bio-term:hover {
  background: linear-gradient(180deg, rgba(46,125,50,0.25) 0%, rgba(46,125,50,0.35) 100%);
  border-bottom: 1px solid #2e7d32;
}
</style>`;
      el.append(termStyles, { html: true });
      console.log("[TERM-READ] Injected term highlight styles");
    }
  });

  rewriter.on("base", {
    element(el) {
      console.log("[REWRITER] <base> found - removing");
      el.remove();
    }
  });

  rewriter.on("a[href]",                    new HrefRewriter(base, workerOrigin));
  rewriter.on("div[href]",                  new HrefRewriter(base, workerOrigin)); // MDPI 特殊用法
  rewriter.on("*[data-counterslinkmanual]", new AttributeRewriter("data-counterslinkmanual", base, workerOrigin));
  rewriter.on("img[src]",                   new AttributeRewriter("src",      base, workerOrigin));
  rewriter.on("img[srcset]",                new SrcsetRewriter("srcset",      base, workerOrigin));
  rewriter.on("img[data-src]",              new AttributeRewriter("data-src", base, workerOrigin));
  rewriter.on("img[data-lsrc]",             new AttributeRewriter("data-lsrc", base, workerOrigin));
  rewriter.on("source[src]",                new AttributeRewriter("src",      base, workerOrigin));
  rewriter.on("source[srcset]",             new SrcsetRewriter("srcset",      base, workerOrigin));
  rewriter.on("link[href]",                 new AttributeRewriter("href",     base, workerOrigin));
  rewriter.on("script[src]",                new ScriptRewriter("src",         base, workerOrigin, scriptBlocklist));
  rewriter.on("form[action]",               new AttributeRewriter("action",   base, workerOrigin));
  rewriter.on("iframe[src]",                new AttributeRewriter("src",      base, workerOrigin));

  // 术语注入：只在安全的文本元素中处理
  if (termRegex) {
    console.log("[TERM-READ] Setting up text handlers for term injection");
    
    // 明确列出要处理的文本元素（白名单模式）
    // 排除：script, style, noscript, code, pre, textarea, kbd, samp, title, alt属性等
    const textSelectors = [
      'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'li', 'td', 'th', 'figcaption', 'caption', 'blockquote',
      'article', 'section', 'aside', 'header', 'footer', 'main',
      'em', 'strong', 'i', 'b', 'u', 'mark', 'small', 'del', 'ins',
      'sub', 'sup', 'time', 'label', 'summary', 'figcaption'
    ];
    
    // 为每个选择器注册文本处理器
    for (const selector of textSelectors) {
      rewriter.on(selector, {
        text(text) {
          termHandler.handleText(text);
        }
      });
    }
    
    console.log(`[TERM-READ] Registered text handlers for ${textSelectors.length} element types`);
    
  } else {
    console.log("[TERM-READ] No term regex, skipping text handlers");
  }
}

// 创建术语处理器
function createTermHandler(terms, regex) {
  if (!regex || !terms || terms.length === 0) {
    return {
      handleText(text) {
        // 不处理
      }
    };
  }

  // 创建术语到翻译的映射
  const termMap = new Map();
  for (const term of terms) {
    termMap.set(term.key, term.translation || "");
  }

  let matchCount = 0;

  return {
    handleText(text) {
      const content = text.text;
      if (!content || typeof content !== 'string') return;
      
      // 简单过滤：检查是否包含可能的大写或小写英文单词
      if (!/[a-zA-Z]{3,}/.test(content)) return;
      
      // 检查是否包含任何术语
      regex.lastIndex = 0;
      if (!regex.test(content)) return;
      
      // 重置并执行替换
      regex.lastIndex = 0;
      
      const replaced = content.replace(regex, (match) => {
        matchCount++;
        // 只保留 data-term，不显示 title 避免默认 tooltip
        // 翻译数据通过 data-term 后续从 KV 查询
        return `<span class="bio-term" data-term="${match}">${match}</span>`;
      });
      
      text.replace(replaced, { html: true });
      
      if (matchCount > 0 && matchCount <= 5) {
        console.log(`[TERM-READ] Injected ${matchCount} terms in text segment`);
      }
    }
  };
}
