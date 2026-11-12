const CACHE_NAME = "riku-football-lab-shell-v5";
const APP_SHELL = new URL("./index.html", self.registration.scope).href;
const STATIC_ASSETS = [
  APP_SHELL,
  new URL("./manifest.webmanifest", self.registration.scope).href,
  new URL("./app-icon.svg", self.registration.scope).href,
  new URL("./stage47-video-recovery.js", self.registration.scope).href,
  new URL("./stage48-video-restore.js", self.registration.scope).href
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key.startsWith("riku-football-lab-shell-") && key !== CACHE_NAME)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response && response.ok) {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(APP_SHELL, response.clone());
        }
        return response;
      } catch {
        const cached = await caches.match(APP_SHELL);
        return cached || Response.error();
      }
    })());
    return;
  }

  const staticAsset = STATIC_ASSETS.find(asset => new URL(asset).pathname === url.pathname);
  if (!staticAsset) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(staticAsset);
    const refresh = fetch(request)
      .then(response => {
        if (response && response.ok) cache.put(staticAsset, response.clone());
        return response;
      })
      .catch(() => cached);
    return cached || refresh;
  })());
});
