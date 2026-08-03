/**
 * Service worker minimal.
 * Objectif principal : satisfaire les critères d'installabilité PWA/TWA
 * (présence d'un service worker actif avec un gestionnaire fetch).
 * Bonus : un repli hors-ligne simple pour la navigation, sans mettre en
 * cache les données de puzzles (qui doivent toujours être fraîches).
 */

const CACHE_NAME = 'puzzle-replay-shell-v1';
const OFFLINE_URL = '/static/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.add(OFFLINE_URL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // On ne gère que la navigation (chargement de page) : le reste (API,
  // assets) passe directement au réseau, sans mise en cache — les
  // données de puzzles doivent toujours être à jour.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(OFFLINE_URL))
    );
  }
});
