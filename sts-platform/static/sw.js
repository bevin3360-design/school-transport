// My School Transport — Service Worker v2
// Supports: offline caching, auto-update notification, skip waiting on demand

const CACHE_NAME = 'mst-v2';
const STATIC_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/admin.js',
  '/static/js/super.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

// ── INSTALL: cache static assets ────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .catch(() => {})   // don't fail install if a resource is missing
  );
  // Do NOT call skipWaiting here — wait for user to trigger update
});

// ── ACTIVATE: clean old caches ──────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME)
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── MESSAGE: handle skip-waiting ────────
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// ── FETCH: network-first for API, cache-first for static ──
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // Always go network-first for API calls — never serve stale API data
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          JSON.stringify({ error: 'You are offline. Please check your connection.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // For HTML pages — network first, fallback to cache
  if (event.request.headers.get('accept').includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // For static assets — cache first, then network
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
        return res;
      });
    })
  );
});
