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
    if (this.blocklist.some(re => re.test(val))) { el.remove(); return; }
    el.setAttribute(this.attr, toProxyUrl(val, this.base, this.workerOrigin));
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

export function applyRewriter(rewriter, finalUrl, workerOrigin, siteConfig = {}) {
  const base = finalUrl;
  const scriptBlocklist = [...GLOBAL_SCRIPT_BLOCKLIST, ...(siteConfig.scriptBlocklist ?? [])];

  rewriter.on("head", {
    element(el) {
      el.prepend(`<script>(function(){if(!navigator.serviceWorker)return;navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(function(){});})();</script>`, { html: true });
    }
  });

  rewriter.on("base", new BaseRemover());

  rewriter.on("a[href]",          new AttributeRewriter("href",     base, workerOrigin));
  rewriter.on("img[src]",         new AttributeRewriter("src",      base, workerOrigin));
  rewriter.on("img[srcset]",      new SrcsetRewriter("srcset",      base, workerOrigin));
  rewriter.on("img[data-src]",    new AttributeRewriter("data-src", base, workerOrigin));
  rewriter.on("source[src]",      new AttributeRewriter("src",      base, workerOrigin));
  rewriter.on("source[srcset]",   new SrcsetRewriter("srcset",      base, workerOrigin));
  rewriter.on("link[href]",       new AttributeRewriter("href",     base, workerOrigin));
  rewriter.on("script[src]",      new ScriptRewriter("src",         base, workerOrigin, scriptBlocklist));
  rewriter.on("form[action]",     new AttributeRewriter("action",   base, workerOrigin));
  rewriter.on("iframe[src]",      new AttributeRewriter("src",      base, workerOrigin));
}
