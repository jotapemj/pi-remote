/* Service worker de pi-remote. La version la inyecta el puente, asi que
   cada bump cambia el nombre de la cache y el cascaron viejo se purga.

   Solo cachea el cascaron (para que abra al instante y sin barra del
   navegador). Nada dinamico: es un control remoto de un proceso vivo, no
   una app offline. La API y el WebSocket ni se tocan. */
const CACHE = "piremote-__VERSION__";
const SHELL = [
  "/",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys())
      if (k !== CACHE) await caches.delete(k);   // fuera versiones viejas
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;    // solo lo propio
  if (url.pathname.startsWith("/api/") || url.pathname === "/ws") return;

  // La navegacion (el HTML) va primero a la red, para no servir un build
  // viejo; si no hay red, cae al cascaron cacheado.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req).then(r => {
        caches.open(CACHE).then(c => c.put("/", r.clone())).catch(() => {});
        return r;
      }).catch(() => caches.match("/")));
    return;
  }

  // El resto del cascaron (fuentes, iconos) es inmutable: cache primero.
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(r => {
    if (r.ok) {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
    }
    return r;
  })));
});
