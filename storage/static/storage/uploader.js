/*
 * 拖曳上傳與分段上傳
 *
 * 檔案切成固定大小的分段依序上傳，每段失敗會自動重試。
 * 上傳進度記在 localStorage，重新整理或斷線後再上傳同一個檔案會從中斷處繼續。
 */
(function () {
  "use strict";

  var MAX_RETRIES = 5;

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input) return input.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function formatSize(bytes) {
    var units = ["B", "KB", "MB", "GB", "TB"];
    var i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
      bytes /= 1024;
      i++;
    }
    return (i === 0 ? bytes : bytes.toFixed(1)) + " " + units[i];
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  var store = {
    get: function (key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set: function (key, value) { try { localStorage.setItem(key, value); } catch (e) { /* 無痕模式 */ } },
    remove: function (key) { try { localStorage.removeItem(key); } catch (e) { /* 無痕模式 */ } },
  };

  function FatalError(message) {
    this.message = message;
  }

  function request(method, url, data, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open(method, url);
      xhr.setRequestHeader("X-CSRFToken", csrfToken());
      xhr.responseType = "json";
      if (onProgress) {
        xhr.upload.onprogress = function (event) { onProgress(event.loaded); };
      }
      xhr.onload = function () { resolve({ status: xhr.status, body: xhr.response || {} }); };
      xhr.onerror = function () { reject(new Error("網路連線中斷")); };
      xhr.send(data);
    });
  }

  function UploadItem(list, file) {
    var li = document.createElement("li");
    li.className = "upload-item";
    li.innerHTML =
      '<div class="upload-row"><span class="upload-name"></span>' +
      '<span class="upload-status muted"></span>' +
      '<button type="button" class="btn upload-cancel">取消</button></div>' +
      '<progress max="100" value="0"></progress>';
    li.querySelector(".upload-name").textContent = file.name + "（" + formatSize(file.size) + "）";
    this.status = li.querySelector(".upload-status");
    this.bar = li.querySelector("progress");
    this.cancelButton = li.querySelector(".upload-cancel");
    this.li = li;
    this.setStatus("等待中");
    list.appendChild(li);
  }

  UploadItem.prototype.setStatus = function (text) {
    this.status.textContent = text;
  };
  UploadItem.prototype.progress = function (loaded, total) {
    var percent = total ? Math.min(100, Math.floor((loaded / total) * 100)) : 100;
    this.bar.value = percent;
    this.setStatus(percent + "%");
  };
  UploadItem.prototype.finish = function (ok, text) {
    this.bar.value = ok ? 100 : this.bar.value;
    this.li.classList.add(ok ? "done" : "failed");
    this.cancelButton.remove();
    this.setStatus(text);
  };

  function Uploader(zone) {
    this.zone = zone;
    this.startUrl = zone.dataset.startUrl;
    this.sessionTemplate = zone.dataset.sessionUrl;
    this.list = zone.querySelector("[data-upload-list]");
    this.queue = [];
    this.running = false;
    this.succeeded = 0;
    this.failed = 0;
    this.bind();
  }

  Uploader.prototype.sessionUrl = function (id) {
    return this.sessionTemplate.replace("00000000-0000-0000-0000-000000000000", id);
  };

  Uploader.prototype.folder = function () {
    var selector = this.zone.dataset.folderSelect;
    var select = selector && document.querySelector(selector);
    return select ? select.value : this.zone.dataset.folder || "";
  };

  Uploader.prototype.bind = function () {
    var self = this;
    var input = this.zone.querySelector("[data-upload-input]");
    var pick = this.zone.querySelector("[data-upload-pick]");
    if (pick && input) {
      pick.addEventListener("click", function () { input.click(); });
      input.addEventListener("change", function () {
        self.add(input.files);
        input.value = "";
      });
    }

    // 有表單時（上傳頁面）攔截送出，改用分段上傳
    var form = this.zone.querySelector("form[data-upload-form]");
    if (form) {
      form.addEventListener("submit", function (event) {
        var fileInput = form.querySelector("input[type=file]");
        if (!fileInput.files.length) return;
        event.preventDefault();
        self.add(fileInput.files);
        fileInput.value = "";
      });
    }

    // 拖曳範圍：data-upload-page 時整個頁面都可以放
    var target = this.zone.hasAttribute("data-upload-page") ? document.body : this.zone;
    var depth = 0;
    target.addEventListener("dragenter", function (event) {
      if (!hasFiles(event)) return;
      depth++;
      document.body.classList.add("dragging");
    });
    target.addEventListener("dragleave", function () {
      depth = Math.max(0, depth - 1);
      if (!depth) document.body.classList.remove("dragging");
    });
    target.addEventListener("dragover", function (event) {
      if (hasFiles(event)) event.preventDefault();
    });
    target.addEventListener("drop", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      document.body.classList.remove("dragging");
      self.add(event.dataTransfer.files);
    });

    window.addEventListener("beforeunload", function (event) {
      if (self.running) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  };

  function hasFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return types && Array.prototype.indexOf.call(types, "Files") !== -1;
  }

  Uploader.prototype.add = function (files) {
    var folder = this.folder();
    for (var i = 0; i < files.length; i++) {
      var job = { file: files[i], folder: folder, cancelled: false };
      job.item = new UploadItem(this.list, files[i]);
      job.item.cancelButton.addEventListener("click", function () { this.cancelled = true; }.bind(job));
      this.queue.push(job);
    }
    this.zone.classList.add("has-uploads");
    this.run();
  };

  Uploader.prototype.run = async function () {
    if (this.running) return;
    this.running = true;
    while (this.queue.length) {
      var job = this.queue.shift();
      try {
        await this.uploadFile(job);
        job.item.finish(true, "完成");
        this.succeeded++;
      } catch (error) {
        job.item.finish(false, error.message || "上傳失敗");
        this.failed++;
      }
    }
    this.running = false;
    this.afterAll();
  };

  Uploader.prototype.afterAll = function () {
    if (!this.succeeded) return;
    var done = this.zone.dataset.doneUrl;
    var folder = this.folder();
    if (done && folder && this.zone.dataset.doneFolderUrl) {
      done = this.zone.dataset.doneFolderUrl.replace("/0/", "/" + folder + "/");
    }
    if (this.failed) {
      // 有失敗時留在頁面讓使用者看到錯誤
      var link = document.createElement("a");
      link.href = done || window.location.href;
      link.textContent = "查看已上傳的檔案";
      this.list.appendChild(link);
    } else {
      window.location.href = done || window.location.href;
    }
  };

  Uploader.prototype.uploadFile = async function (job) {
    var file = job.file;
    var key = ["cloud-upload", job.folder, file.name, file.size, file.lastModified].join(":");
    var session = null;

    var savedId = store.get(key);
    if (savedId) {
      var existing = await request("GET", this.sessionUrl(savedId)).catch(function () { return null; });
      if (existing && existing.status === 200 && existing.body.id) {
        session = existing.body;
      } else {
        store.remove(key);
      }
    }

    if (!session) {
      var data = new FormData();
      data.append("name", file.name);
      data.append("size", file.size);
      if (job.folder) data.append("folder", job.folder);
      var started = await request("POST", this.startUrl, data);
      if (started.status !== 201 || !started.body.id) {
        throw new FatalError(started.body.error || "無法開始上傳，請重新登入後再試");
      }
      session = started.body;
      if (!session.done) store.set(key, session.id);
    } else if (session.received_bytes > 0) {
      job.item.setStatus("從 " + formatSize(session.received_bytes) + " 處繼續");
    }

    var offset = session.received_bytes;
    while (!session.done) {
      if (job.cancelled) {
        await request("POST", this.sessionUrl(session.id) + "cancel/").catch(function () {});
        store.remove(key);
        throw new FatalError("已取消");
      }
      var chunk = file.slice(offset, offset + session.chunk_size);
      var base = offset;
      session = await this.sendChunk(session.id, offset, chunk, function (loaded) {
        job.item.progress(base + loaded, file.size);
      });
      offset = session.received_bytes;
      job.item.progress(offset, file.size);
    }
    store.remove(key);
  };

  Uploader.prototype.sendChunk = async function (id, offset, chunk, onProgress) {
    for (var attempt = 0; ; attempt++) {
      var data = new FormData();
      data.append("offset", offset);
      data.append("chunk", chunk, "chunk");
      try {
        var response = await request("POST", this.sessionUrl(id), data, onProgress);
        // 409 代表伺服器上的進度和前端不同，依伺服器回傳的位置繼續
        if ((response.status === 200 || response.status === 409) && response.body.id) {
          return response.body;
        }
        if (response.status === 200 || (response.status >= 400 && response.status < 500)) {
          throw new FatalError(response.body.error || "上傳失敗（" + response.status + "），請重新登入後再試");
        }
      } catch (error) {
        if (error instanceof FatalError || attempt >= MAX_RETRIES) throw error;
      }
      if (attempt >= MAX_RETRIES) throw new FatalError("伺服器錯誤，請稍後再試");
      await sleep(1000 * Math.pow(2, attempt));
    }
  };

  document.querySelectorAll("[data-upload-zone]").forEach(function (zone) {
    new Uploader(zone);
  });
})();
