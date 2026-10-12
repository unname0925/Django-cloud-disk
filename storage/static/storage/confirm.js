/*
 * 送出前確認：表單或送出按鈕加上 data-confirm="訊息" 即可。
 * 取代 onsubmit="return confirm(...)"，因為 Content-Security-Policy 不允許內嵌腳本。
 */
(function () {
  "use strict";

  document.addEventListener("submit", function (event) {
    var form = event.target;
    var button = event.submitter;
    var message = (button && button.dataset.confirm) || form.dataset.confirm;
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
})();
