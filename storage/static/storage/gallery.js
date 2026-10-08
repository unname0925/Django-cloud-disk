/* 相簿模式的燈箱：點圖片放大，左右鍵切換，Esc 關閉 */
(function () {
  "use strict";

  var links = Array.prototype.slice.call(document.querySelectorAll("[data-lightbox]"));
  if (!links.length) return;

  var overlay = document.createElement("div");
  overlay.className = "lightbox";
  overlay.hidden = true;
  overlay.innerHTML =
    '<button type="button" class="lightbox-close" aria-label="關閉">×</button>' +
    '<button type="button" class="lightbox-prev" aria-label="上一張">‹</button>' +
    '<figure><img alt=""><figcaption></figcaption></figure>' +
    '<button type="button" class="lightbox-next" aria-label="下一張">›</button>';
  document.body.appendChild(overlay);

  var image = overlay.querySelector("img");
  var caption = overlay.querySelector("figcaption");
  var current = 0;

  function show(index) {
    current = (index + links.length) % links.length;
    var link = links[current];
    image.src = link.href;
    image.alt = link.dataset.title;
    caption.textContent = link.dataset.title + "（" + (current + 1) + " / " + links.length + "）";
    overlay.hidden = false;
  }

  function close() {
    overlay.hidden = true;
    image.removeAttribute("src");
  }

  links.forEach(function (link, index) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      show(index);
    });
  });

  overlay.querySelector(".lightbox-close").addEventListener("click", close);
  overlay.querySelector(".lightbox-prev").addEventListener("click", function () { show(current - 1); });
  overlay.querySelector(".lightbox-next").addEventListener("click", function () { show(current + 1); });
  overlay.addEventListener("click", function (event) {
    if (event.target === overlay) close();
  });
  document.addEventListener("keydown", function (event) {
    if (overlay.hidden) return;
    if (event.key === "Escape") close();
    if (event.key === "ArrowLeft") show(current - 1);
    if (event.key === "ArrowRight") show(current + 1);
  });
})();
