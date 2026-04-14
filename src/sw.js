export const swScript = `
const WORKER_ORIGIN = self.location.origin;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  if (url.origin !== WORKER_ORIGIN) return;
  if (url.pathname === '/sw.js') return;
  if (url.searchParams.has('url')) return;

  e.respondWith((async () => {
    // 优先从 Referer 提取 base
    let base = null;
    const referer = e.request.referrer;
    if (referer) {
      try {
        const proxied = new URL(referer).searchParams.get('url');
        if (proxied) base = new URL(proxied).origin;
      } catch {}
    }

    // Referer 无效时，从当前活跃页面 URL 提取 base
    if (!base) {
      try {
        const clients = await self.clients.matchAll({ type: 'window' });
        for (const client of clients) {
          const proxied = new URL(client.url).searchParams.get('url');
          if (proxied) { base = new URL(proxied).origin; break; }
        }
      } catch {}
    }

    if (!base) return fetch(e.request);

    const originalUrl = base + url.pathname + url.search + url.hash;
    const proxyUrl = WORKER_ORIGIN + '/?url=' + encodeURIComponent(originalUrl);
    return fetch(proxyUrl, { headers: e.request.headers });
  })());
});
`;
