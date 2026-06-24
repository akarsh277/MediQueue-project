const CACHE_NAME = "mediqueue-v1";

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(clients.claim());
});

self.addEventListener("fetch", (event) => {
    // Basic pass-through, just to satisfy PWA requirements
    // For real offline support, we would cache assets here.
    event.respondWith(fetch(event.request).catch(() => {
        return new Response('Offline mode not fully supported yet.');
    }));
});
