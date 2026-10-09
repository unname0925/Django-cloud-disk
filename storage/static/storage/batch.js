/* 列表模式的批次操作：全選、顯示已選取數量，沒有勾選時隱藏操作列 */
(function () {
  "use strict";

  var form = document.querySelector("[data-batch-form]");
  if (!form) return;

  var bar = form.querySelector("[data-batch-bar]");
  var count = form.querySelector("[data-batch-count]");
  var all = form.querySelector("[data-batch-all]");
  var boxes = Array.prototype.slice.call(
    form.querySelectorAll("input[type=checkbox][name=file], input[type=checkbox][name=folder]")
  );

  function update() {
    var checked = boxes.filter(function (box) { return box.checked; }).length;
    count.textContent = checked;
    bar.hidden = checked === 0;
    all.checked = checked > 0 && checked === boxes.length;
    all.indeterminate = checked > 0 && checked < boxes.length;
  }

  all.addEventListener("change", function () {
    boxes.forEach(function (box) { box.checked = all.checked; });
    update();
  });
  boxes.forEach(function (box) { box.addEventListener("change", update); });

  form.addEventListener("submit", function (event) {
    var button = event.submitter;
    if (button && button.dataset.confirm && !window.confirm(button.dataset.confirm)) {
      event.preventDefault();
    }
  });

  update();
})();
