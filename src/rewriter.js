function toProxyUrl(original, base, workerOrigin) {
  if (!original) return original;
  if (original.startsWith("data:") || original.startsWith("blob:") || original.startsWith("javascript:")) return original;
  try {
    const absolute = new URL(original, base).href;
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
  element(el) {
    el.remove();
  }
}

export function applyRewriter(rewriter, targetUrl, workerOrigin) {
  const base = targetUrl;

  // 注入 Service Worker 注册脚本
  rewriter.on("head", {
    element(el) {
      el.prepend(`<script>
(function(){
  if (!navigator.serviceWorker) return;
  navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function(){});
})();
</script>`, { html: true });
    }
  });

  // 移除 <base> 标签避免干扰路径解析
  rewriter.on("base", new BaseRemover());

  rewriter.on("a[href]",      new AttributeRewriter("href",   base, workerOrigin));
  rewriter.on("img[src]",     new AttributeRewriter("src",    base, workerOrigin));
  rewriter.on("img[srcset]",  new SrcsetRewriter("srcset",    base, workerOrigin));
  rewriter.on("source[src]",  new AttributeRewriter("src",    base, workerOrigin));
  rewriter.on("source[srcset]", new SrcsetRewriter("srcset",  base, workerOrigin));
  rewriter.on("link[href]",   new AttributeRewriter("href",   base, workerOrigin));
  rewriter.on("script[src]",  new ScriptRewriter("src", base, workerOrigin));
  rewriter.on("form[action]", new AttributeRewriter("action", base, workerOrigin));
  rewriter.on("iframe[src]",  new AttributeRewriter("src",    base, workerOrigin));
}

const IFRAME_BLOCKLIST = [];

// 动态加载库黑名单：这些库会在运行时用相对路径请求子文件，无法被代理
const SCRIPT_BLOCKLIST = [
  /cdnjs\.cloudflare\.com\/ajax\/libs\/mathjax/i,
];

class ScriptRewriter {
  constructor(attr, base, workerOrigin) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (!val) return;
    if (SCRIPT_BLOCKLIST.some(re => re.test(val))) {
      el.remove();
      return;
    }
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
