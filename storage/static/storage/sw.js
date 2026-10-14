/*
 * Service Worker：讓網站可以安裝成 App，並在離線時顯示提示頁面。
 *
 * 只快取靜態檔案（CSS、JS、圖示）與離線頁面，不快取任何使用者的頁面或檔案，
 * 避免私人資料留在裝置的快取裡。
 */
"use strict";

var CACHE = "cloud-drive-static-v1";
var OFFLINE_URL = new URL("offline/", self.registration.scope).href;

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.add(OFFLINE_URL); })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) { return key !== CACHE; })
        .map(function (key) { return caches.delete(key); }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.indexOf("/static/") === 0) {
    // 靜態檔案：先用快取，同時在背景更新，下次開啟就會是新版本
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(request).then(function (cached) {
          var network = fetch(request).then(function (response) {
            if (response.ok) cache.put(request, response.clone());
            return response;
          });
          return cached || network;
        });
      })
    );
    return;
  }

  if (request.mode === "navigate") {
    // 頁面一律從網路取得，只有離線時才顯示離線頁面
    event.respondWith(
      fetch(request).catch(function () { return caches.match(OFFLINE_URL); })
    );
  }
});
