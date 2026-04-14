export const swScript = `
const WORKER_ORIGIN = self.location.origin;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // 已经是代理请求、或是 SW 自身、或是 worker origin 的非代理路径
  if (url.origin !== WORKER_ORIGIN) return;
  if (url.pathname === '/sw.js') return;
  if (url.searchParams.has('url')) return;

  // 从 Referer 或 client URL 里找到当前代理的原始 base
  const referer = e.request.referrer;
  if (!referer) return;

  let base;
  try {
    const refUrl = new URL(referer);
    const proxied = refUrl.searchParams.get('url');
    if (!proxied) return;
    base = new URL(proxied).origin;
  } catch {
    return;
  }

  // 拼出原始绝对路径，再包装为代理 URL
  const originalUrl = base + url.pathname + url.search + url.hash;
  const proxyUrl = WORKER_ORIGIN + '/?url=' + encodeURIComponent(originalUrl);

  e.respondWith(fetch(proxyUrl, { headers: e.request.headers }));
});
`;
