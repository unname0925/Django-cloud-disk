/* 註冊 Service Worker，讓網站可以「加到主畫面」當成 App 使用 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!("serviceWorker" in navigator) || !script) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker
      .register(script.dataset.worker, { scope: script.dataset.scope })
      .catch(function () { /* 不支援或被瀏覽器拒絕時，網站照常運作 */ });
  });
})();
