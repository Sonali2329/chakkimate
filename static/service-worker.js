// ChakkiMate (चक्कीमेट) - Progressive Web App Service Worker
const CACHE_NAME = 'chakkimate-v2.1';

const PRECACHE_ASSETS = [
  '/offline/',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'
];

// Install Event
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ChakkiMate SW] Pre-caching offline assets...');
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('[ChakkiMate SW] Pre-caching warning:', err);
      });
    })
  );
});

// Activate Event - clean up obsolete caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            console.log('[ChakkiMate SW] Deleting obsolete cache:', cache);
            return caches.delete(cache);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Strategy:
// HTML navigations: Network-first, fallback to /offline/
// Static assets: Cache-first, fallback to network
self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Ignore non-GET requests (e.g. POST for sales/grinding orders)
  if (request.method !== 'GET') {
    return;
  }

  // HTML page navigation
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          return response;
        })
        .catch(async () => {
          console.log('[ChakkiMate SW] Device is offline, showing offline page');
          const cache = await caches.open(CACHE_NAME);
          const cachedResponse = await cache.match('/offline/');
          return cachedResponse || new Response('<h1>ChakkiMate - Offline</h1><p>कृपया इंटरनेट तपासा.</p>', {
            headers: { 'Content-Type': 'text/html; charset=utf-8' }
          });
        })
    );
    return;
  }

  // Static Assets (CDN, Images, CSS, JS)
  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(request).then((networkResponse) => {
        if (
          networkResponse &&
          networkResponse.status === 200 &&
          (request.url.includes('/static/') || request.url.includes('cdn.jsdelivr.net'))
        ) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseToCache);
          });
        }
        return networkResponse;
      });
    })
  );
});
