import { errorPage, landingPage } from "./webpage.js";
import { applyRewriter } from "./rewriter.js";
import { swScript } from "./sw.js";
import { getSiteConfig } from "./sites/index.js";
import { getTerms, buildTermRegex } from "./term-handler.js";

const CSP_HEADERS = [
  "content-security-policy",
  "content-security-policy-report-only",
  "x-frame-options",
];


export default {
  async fetch(request, env, ctx) {
    const reqUrl = new URL(request.url);
    const workerOrigin = reqUrl.origin;
    console.log(`[REQ] ${request.method} ${reqUrl.pathname}${reqUrl.search}`);

    if (reqUrl.pathname === "/sw.js") {
      console.log("[SW] Serving service worker script");
      return new Response(swScript, {
        headers: { 
          "content-type": "application/javascript;charset=UTF-8",
          "cache-control": "public, max-age=86400"
        },
      });
    }

    const targetRaw = reqUrl.searchParams.get("url");
    console.log(`[TARGET] url param: ${targetRaw || "(none - landing page)"}`);

    if (!targetRaw) {
      const fetchDest = request.headers.get("sec-fetch-dest") || "";
      const isNavigation = fetchDest === "document" || fetchDest === "iframe";
      const referer = request.headers.get("referer");
      if (!isNavigation && referer) {
        try {
          const refUrl = new URL(referer);
          const proxiedBase = refUrl.searchParams.get("url");
          if (proxiedBase) {
            const proxiedUrl = new URL(proxiedBase);
            const originalUrl = proxiedUrl.origin + reqUrl.pathname + reqUrl.search + reqUrl.hash;
            return Response.redirect(`${workerOrigin}/?url=${encodeURIComponent(originalUrl)}`, 302);
          }
        } catch {}
      }
      return htmlResponse(landingPage());
    }

    let targetUrl;
    try {
      targetUrl = new URL(targetRaw);
      if (!["http:", "https:"].includes(targetUrl.protocol)) throw new Error();
    } catch {
      console.log("[ERROR] Invalid target URL");
      return htmlResponse(errorPage("400", "无效的目标 URL"));
    }

    console.log(`[CONFIG] Host: ${targetUrl.hostname}, SiteConfig: ${JSON.stringify(getSiteConfig(targetUrl.hostname))}`);
    const siteConfig = getSiteConfig(targetUrl.hostname);

    let upstream;
    try {
      const upstreamHeaders = {
        "User-Agent": request.headers.get("User-Agent") || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": targetUrl.origin + "/",
        "Accept": request.headers.get("Accept") || "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": request.headers.get("Accept-Language") || "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "identity",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
      };
      const cookie = request.headers.get("Cookie");
      if (cookie) upstreamHeaders["Cookie"] = cookie;

      console.log(`[UPSTREAM] Fetching: ${targetUrl.href}`);
      upstream = await fetch(targetUrl.href, { headers: upstreamHeaders, redirect: "follow" });
      console.log(`[UPSTREAM] Response: ${upstream.status} ${upstream.statusText}, Final URL: ${upstream.url || targetUrl.href}`);

      // pensoft 特有：PHP 路径重试
      if (
        siteConfig.phpRetry &&
        !upstream.ok &&
        targetUrl.pathname.includes(".php") &&
        targetUrl.pathname !== "/" + targetUrl.pathname.split("/").pop()
      ) {
        const filename = targetUrl.pathname.split("/").pop();
        if (filename) {
          const rootUrl = targetUrl.origin + "/" + filename + targetUrl.search;
          const retry = await fetch(rootUrl, { headers: upstreamHeaders, redirect: "follow" });
          if (retry.ok) {
            console.log(`[RETRY] PHP retry succeeded: ${rootUrl}`);
            upstream = retry;
          }
        }
      }
    } catch (err) {
      console.log(`[ERROR] Upstream fetch failed: ${err.message}`);
      return htmlResponse(errorPage("502", "无法连接到目标页面"));
    }

    const finalUrl = upstream.url || targetUrl.href;

    const headers = new Headers(upstream.headers);
    CSP_HEADERS.forEach(h => headers.delete(h));
    headers.delete("x-content-type-options");

    const isSubResource = /\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|otf|eot|webp|json|xml|mp4|mp3)$/i.test(targetUrl.pathname);
    console.log(`[TYPE] isSubResource: ${isSubResource}, ContentType: ${upstream.headers.get("content-type") || "(none)"}`);

    if (isSubResource) {
      console.log("[PASS] Subresource - direct pass through");
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    const contentType = upstream.headers.get("content-type") || "";
    console.log(`[HTML] Processing HTML response, ContentType: ${contentType}`);

    if (!contentType.includes("text/html") || !upstream.ok) {
      if (!upstream.ok) {
        console.log(`[ERROR] Upstream returned ${upstream.status}`);
        return htmlResponse(errorPage(upstream.status, `目标页面返回 ${upstream.status}`));
      }
      console.log("[PASS] Non-HTML content - direct pass through");
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    console.log("[REWRITE] Applying HTMLRewriter...");
    
    // 加载术语并构建正则
    const terms = await getTerms(env);
    const termRegex = buildTermRegex(terms);
    console.log(`[TERM-READ] Terms loaded: ${terms.length}, Regex available: ${!!termRegex}`);
    
    const rewriter = new HTMLRewriter();
    applyRewriter(rewriter, finalUrl, workerOrigin, siteConfig, terms, termRegex);

    console.log("[DONE] Returning transformed response");
    return rewriter.transform(new Response(upstream.body, { status: upstream.status, headers }));
  },
};

function htmlResponse(html, status = 200) {
  return new Response(html, {
    status,
    headers: { "content-type": "text/html;charset=UTF-8" },
  });
}
