const V = 'balance-v6';
const ARCHIVOS = ['./', './index.html', './descargar.html', './app.js', './style.css', './manifest.webmanifest',
  './assets/icon_192.png', './assets/icon_512.png', './assets/logo_small.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(ARCHIVOS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).then(resp => {
    if (resp && resp.ok) { const copia = resp.clone(); caches.open(V).then(c => c.put(e.request, copia)); }
    return resp;
  }).catch(() => caches.match(e.request).then(r => r || caches.match('./index.html'))));
});
