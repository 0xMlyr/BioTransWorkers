import { errorPage } from "./error.js";
import { applyRewriter } from "./rewriter.js";

const CSP_HEADERS = [
  "content-security-policy",
  "content-security-policy-report-only",
  "x-frame-options",
];

export default {
  async fetch(request, env, ctx) {
    const workerOrigin = new URL(request.url).origin;
    const params = new URL(request.url).searchParams;
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

    const contentType = upstream.headers.get("content-type") || "";
    const isHtml = contentType.includes("text/html");

    // 清理响应头
    const headers = new Headers(upstream.headers);
    CSP_HEADERS.forEach(h => headers.delete(h));
    headers.delete("x-content-type-options");

    if (!isHtml) {
      // 子资源直接透传（包括失败状态）
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    if (!upstream.ok) {
      return htmlResponse(errorPage(upstream.status, `目标页面返回 ${upstream.status}`));
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
