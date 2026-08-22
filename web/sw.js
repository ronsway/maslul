// Maslul service worker - caches the app shell so the planner still opens
// offline. Network calls to Supabase and the Garmin backend are left alone
// (cross-origin, never intercepted here) - those simply fail naturally when
// offline, same as any other fetch() in the page.
const CACHE_NAME = 'maslul-v1.0.40';
const CORE_ASSETS = ['/', '/index.html', '/manifest.json', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // let cross-origin (Supabase, backend, fonts) pass through untouched

  // network-first so a normal online visit always gets the latest deploy;
  // fall back to whatever's cached (and finally the app shell) when offline.
  event.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        return res;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match('/index.html')))
  );
});
