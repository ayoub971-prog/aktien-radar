// Aktien-Radar Service Worker: App-Huelle aus dem Cache, data/*.json zuerst vom Netz (sonst letzter Stand)
var CACHE = 'aktien-radar-shell-v2';
var DATA = 'aktien-radar-data-v2';
var CORE = ['./', './index.html', './app.js', './manifest.webmanifest', './watchlist.json',
  './icon.svg', './icon-192.png', './icon-512.png', './icon-maskable-512.png', './apple-touch-icon.png',
  './fonts/Fraunces-latin.woff2', './fonts/Outfit-latin.woff2'];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return c.addAll(CORE.map(function (u) { return new Request(u, { cache: 'reload' }); }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE && k !== DATA; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
function isData(u) { return /\/data\/[^\/]+\.json$/.test(u.pathname) || /\/watchlist\.json$/.test(u.pathname); }
self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  var u = new URL(e.request.url);
  if (u.origin !== location.origin) return;
  if (isData(u)) {
    e.respondWith(fetch(e.request).then(function (r) {
      if (r && r.ok) { var copy = r.clone(); caches.open(DATA).then(function (c) { c.put(u.pathname, copy); }); }
      return r;
    }).catch(function () {
      return caches.open(DATA).then(function (c) { return c.match(u.pathname); }).then(function (hit) {
        return hit || new Response('{"error":"offline"}', { status: 503, headers: { 'content-type': 'application/json' } });
      });
    }));
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(function (hit) {
    return hit || fetch(e.request).then(function (r) {
      if (r && r.ok) { var copy = r.clone(); caches.open(CACHE).then(function (c) { c.put(e.request, copy); }); }
      return r;
    }).catch(function () { return caches.match('./index.html'); });
  }));
});
