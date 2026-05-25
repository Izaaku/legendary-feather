/**
 * Legendary Feather — Service Worker
 *
 * Strategy:
 *  - Cache the app shell (HTML, CSS, fonts, icons) for offline / instant load.
 *  - NEVER cache API responses (/api/...), Stripe checkout, Socket.IO, or auth.
 *  - Network-first for HTML pages so updates ship immediately.
 *  - Cache-first for static assets (icons, fonts).
 *
 * Bump CACHE_VERSION whenever you change static assets to force update.
 */
const CACHE_VERSION = 'lf-v2';
const STATIC_CACHE = 'lf-static-' + CACHE_VERSION;
const RUNTIME_CACHE = 'lf-runtime-' + CACHE_VERSION;

const APP_SHELL = [
  '/',
  '/app',
  '/pricing',
  '/static/images/golden-feather-hero.png',
  '/static/images/golden-feather-nav.png',
  '/static/images/golden-feather-web.png',
  '/static/images/golden-feather-transparent.png',
  '/static/manifest.json',
  '/static/data/quick_phrases.json',
];

// Paths that should NEVER be cached (always go to network)
const NEVER_CACHE = [
  '/api/',
  '/socket.io/',
  '/auth/',
  'stripe.com',
  'script.google.com',
  '/webhook',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(APP_SHELL.map((url) => new Request(url, { credentials: 'same-origin' }))))
      .catch((err) => console.warn('[SW] Pre-cache failed:', err))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== STATIC_CACHE && k !== RUNTIME_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin GET requests.
  if (req.method !== 'GET') return;

  // Same-origin guard: never intercept cross-origin requests (Google Fonts,
  // CDNs, third-party APIs). Intercepting them made the SW call fetch()
  // — which the page CSP blocks — and then respondWith(undefined),
  // causing "TypeError: Failed to convert value to 'Response'". Let the
  // browser handle cross-origin resources natively.
  if (url.origin !== self.location.origin) return;

  // Skip never-cache paths (API, websocket, auth, third-party APIs)
  const fullUrl = req.url.toLowerCase();
  if (NEVER_CACHE.some((path) => fullUrl.includes(path))) return;

  // Network-first for HTML / navigation
  if (req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(RUNTIME_CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached || caches.match('/')))
    );
    return;
  }

  // Cache-first for static assets
  if (url.pathname.startsWith('/static/') || /\.(png|jpg|jpeg|svg|woff2?|ttf|css|js)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
          }
          return res;
        });
      })
    );
    return;
  }

  // Default: network with runtime cache fallback
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(RUNTIME_CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
        }
        return res;
      })
      // Never resolve to undefined — respondWith() requires a Response.
      .catch(() => caches.match(req).then(
        (cached) => cached || new Response('', { status: 504, statusText: 'Offline' })
      ))
  );
});

// Listen for messages from the page (e.g. force update)
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
