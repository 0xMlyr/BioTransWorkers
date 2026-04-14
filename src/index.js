import { errorPage } from "./error.js";
import { applyRewriter } from "./rewriter.js";
import { swScript } from "./sw.js";

const CSP_HEADERS = [
  "content-security-policy",
  "content-security-policy-report-only",
  "x-frame-options",
];

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
      return htmlResponse(errorPage("400", "缺少 ?url= 参数"));
    }

    let targetUrl;
    try {
      targetUrl = new URL(targetRaw);
      if (!["http:", "https:"].includes(targetUrl.protocol)) throw new Error();
    } catch {
      return htmlResponse(errorPage("400", "无效的目标 URL"));
    }

    let upstream;
    try {
      upstream = await fetch(targetUrl.href, {
        headers: { "User-Agent": request.headers.get("User-Agent") || "Mozilla/5.0" },
        redirect: "follow",
      });
    } catch {
      return htmlResponse(errorPage("502", "无法连接到目标页面"));
    }

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
