import { errorPage } from "./error.js";
import { applyRewriter } from "./rewriter.js";
import { swScript } from "./sw.js";

const CSP_HEADERS = [
  "content-security-policy",
  "content-security-policy-report-only",
  "x-frame-options",
];

// 允许代理的学术出版商域名（支持子域名）
const ALLOWED_HOSTS = [
  "pensoft.net",
  "zookeys.pensoft.net",
  "pmc.ncbi.nlm.nih.gov",
  "www.ncbi.nlm.nih.gov",
  "academic.oup.com",
  "www.journals.uchicago.edu",
  "onlinelibrary.wiley.com",
  "link.springer.com",
  "www.mapress.com",
  "resjournals.onlinelibrary.wiley.com",
];

function isAllowedHost(hostname) {
  return ALLOWED_HOSTS.some(h => hostname === h || hostname.endsWith('.' + h));
}

export default {
  async fetch(request, env, ctx) {
    const reqUrl = new URL(request.url);
    const workerOrigin = reqUrl.origin;

    // Service Worker 脚本路由
    if (reqUrl.pathname === "/sw.js") {
      return new Response(swScript, {
        headers: { "content-type": "application/javascript;charset=UTF-8" },
      });
    }

    const params = reqUrl.searchParams;
    const targetRaw = params.get("url");

    if (!targetRaw) {
      // 仅对非导航请求（子资源）尝试 Referer 自动补全
      const fetchDest = request.headers.get('sec-fetch-dest') || '';
      const isNavigation = fetchDest === 'document' || fetchDest === 'iframe' || fetchDest === '';
      const referer = request.headers.get('referer');
      if (!isNavigation && referer) {
        try {
          const refUrl = new URL(referer);
          const proxiedBase = refUrl.searchParams.get('url');
          if (proxiedBase) {
            const proxiedUrl = new URL(proxiedBase);
            const originalUrl = proxiedUrl.origin + reqUrl.pathname + reqUrl.search + reqUrl.hash;
            const proxyUrl = `${workerOrigin}/?url=${encodeURIComponent(originalUrl)}`;
            return Response.redirect(proxyUrl, 302);
          }
        } catch {}
      }
      return htmlResponse(errorPage("400", "缺少 ?url= 参数"));
    }

    let targetUrl;
    try {
      targetUrl = new URL(targetRaw);
      if (!["http:", "https:"].includes(targetUrl.protocol)) throw new Error();
    } catch {
      return htmlResponse(errorPage("400", "无效的目标 URL"));
    }

    if (!isAllowedHost(targetUrl.hostname)) {
      return htmlResponse(errorPage("403", "该域名不在支持列表内"));
    }

    let upstream;
    try {
      const upstreamHeaders = {
        "User-Agent": request.headers.get("User-Agent") || "Mozilla/5.0",
        "Referer": targetUrl.origin + "/",
      };
      const cookie = request.headers.get("Cookie");
      if (cookie) upstreamHeaders["Cookie"] = cookie;

      upstream = await fetch(targetUrl.href, {
        headers: upstreamHeaders,
        redirect: "follow",
      });

      // 上游 404 且路径包含 .php，尝试用根路径重试
      if (!upstream.ok && targetUrl.pathname.includes('.php') && targetUrl.pathname !== '/' + targetUrl.pathname.split('/').pop()) {
        const rootUrl = targetUrl.origin + '/' + targetUrl.pathname.split('/').pop() + targetUrl.search;
        const retryUpstream = await fetch(rootUrl, { headers: upstreamHeaders, redirect: "follow" });
        if (retryUpstream.ok) upstream = retryUpstream;
      }
    } catch {
      return htmlResponse(errorPage("502", "无法连接到目标页面"));
    }

    // 使用重定向后的最终 URL 作为 rewriter 的 base
    const finalUrl = upstream.url || targetUrl.href;

    // 清理响应头
    const headers = new Headers(upstream.headers);
    CSP_HEADERS.forEach(h => headers.delete(h));
    headers.delete("x-content-type-options");

    // 用请求 URL 扩展名判断是否为子资源，避免依赖上游 404 页的 content-type
    const reqPath = targetUrl.pathname;
    const isSubResource = /\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|webp|json|xml|mp4|mp3)$/i.test(reqPath);

    if (isSubResource) {
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    const contentType = upstream.headers.get("content-type") || "";
    const isHtml = contentType.includes("text/html");

    if (!isHtml || !upstream.ok) {
      if (!upstream.ok) return htmlResponse(errorPage(upstream.status, `目标页面返回 ${upstream.status}`));
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    // 主 HTML：重写路径
    const rewriter = new HTMLRewriter();
    applyRewriter(rewriter, targetUrl.href, workerOrigin);

    return rewriter.transform(new Response(upstream.body, { status: upstream.status, headers }));
  },
};

function htmlResponse(html, status = 200) {
  return new Response(html, {
    status,
    headers: { "content-type": "text/html;charset=UTF-8" },
  });
}
