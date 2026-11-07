// School Transport System — vehicle map release cache.
const CACHE_NAME = 'mst-v3-navigation';
const STATIC_ASSETS = ['/', '/static/css/style.css', '/static/js/admin.js', '/static/js/super.js', '/static/js/vehicle-map.js', '/static/manifest.json', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
self.addEventListener('install', event => { event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)).catch(() => {})); });
self.addEventListener('activate', event => { event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))); self.clients.claim(); });
self.addEventListener('message', event => { if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting(); });
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) { event.respondWith(fetch(event.request).catch(() => new Response(JSON.stringify({error: 'You are offline. Please check your connection.'}), {status: 503, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}}))); return; }
  if (event.request.headers.get('accept')?.includes('text/html')) { event.respondWith(fetch(event.request).then(response => { const copy = response.clone(); caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)); return response; }).catch(() => caches.match(event.request))); return; }
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request).then(response => { const copy = response.clone(); caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)); return response; })));
});
