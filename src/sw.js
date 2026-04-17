export const swScript = `
const WORKER_ORIGIN = self.location.origin;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  if (url.origin !== WORKER_ORIGIN) return;
  if (url.pathname === '/sw.js') return;
  if (url.pathname.startsWith('/api/')) return;  // 放行 API 请求
  if (url.searchParams.has('url')) return;

  const referer = e.request.referrer;
  if (!referer) return;

  let base;
  try {
    const proxied = new URL(referer).searchParams.get('url');
    if (!proxied) return;
    base = new URL(proxied).origin;
  } catch { return; }

  const originalUrl = base + url.pathname + url.search + url.hash;
  const proxyUrl = WORKER_ORIGIN + '/?url=' + encodeURIComponent(originalUrl);
  e.respondWith(fetch(proxyUrl, { headers: e.request.headers }));
});
`;
