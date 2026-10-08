# Cloud Disk Django

用 Django 實作的個人雲端硬碟，可以架在家裡的電腦上，透過網域加 HTTPS 從外面存取。

## 功能

- **帳號**：註冊、登入、登出、變更密碼；可關閉公開註冊；同一 IP 連續登入失敗會暫時鎖定
- **兩步驟驗證**：支援 Google Authenticator 等 TOTP App，掃描 QR code 即可啟用，附 10 組一次性備用碼；後台登入也必須經過同一套流程
- **上傳**：拖曳到頁面任何地方即可上傳，有進度條；大檔案分段上傳，斷線自動重試，關掉頁面後重新上傳同一個檔案會從中斷處繼續
- **檔案**：下載、重新命名、移動、刪除
- **資料夾**：建立多層資料夾、麵包屑導覽、重新命名、刪除；整個資料夾或全部檔案打包成 zip 下載
- **資源回收筒**：刪除的檔案與資料夾保留 30 天，可還原或永久刪除，期限到了自動清除
- **相簿模式**：圖片顯示縮圖，點開後可用左右鍵切換；檢視模式會記住
- **搜尋與排序**：跨資料夾搜尋檔名，依名稱、大小、上傳時間排序
- **線上預覽**：圖片、PDF、純文字、音訊、影片可直接在瀏覽器開啟
- **分享連結**：分享單一檔案或整個資料夾（可瀏覽子資料夾、下載 zip），免登入；可設定有效期限、密碼、下載次數上限，隨時撤銷；「我的分享」集中管理所有連結
- **重複檔案**：用 SHA-256 判斷內容相同的檔案，同一位使用者的相同內容只存一份、只算一次容量；「重複檔案」頁面列出所有副本
- **容量配額**：每位使用者有容量上限（可在後台個別調整），首頁顯示用量
- **隔離**：每個帳號的檔案存放在獨立的 UUID 資料夾，無法存取其他使用者的檔案

## 目錄結構

```
cloud/                     專案設定（settings、urls）
storage/
├─ models.py               UserProfile、Folder、StoredFile、ShareLink、UploadSession、RecoveryCode
├─ forms.py                表單
├─ signals.py              自動建立 profile；刪除紀錄時一併刪除實體檔案與縮圖
├─ services/
│  ├─ trash.py             資源回收筒（丟棄、還原、永久刪除、過期清除）
│  ├─ uploads.py           容量檢查、分段上傳
│  ├─ archive.py           資料夾打包成 zip
│  ├─ twofactor.py         兩步驟驗證（TOTP、備用碼）
│  ├─ shares.py            分享連結（密碼、下載次數、資料夾分享）
│  ├─ dedupe.py            重複檔案偵測與合併
│  └─ thumbnails.py        縮圖產生與快取
├─ views/                  依功能分檔：accounts、browse、duplicates、files、folders、shares、trash、uploads
├─ static/storage/         uploader.js（拖曳與分段上傳）、gallery.js（相簿燈箱）
├─ templates/storage/
├─ management/commands/    cleanup_storage 清理指令
└─ tests/                  自動化測試
deploy/                    Docker、gunicorn、Caddy、waitress 部署設定
```

## 本機開發

需求：Python 3.12+

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # 建立管理員（可選）
```

啟動（Windows CMD）：

```cmd
set DEBUG=True
set SECRET_URL_PREFIX=自訂的隨機字串
python manage.py runserver
```

啟動（macOS / Linux）：

```bash
DEBUG=True SECRET_URL_PREFIX=自訂的隨機字串 python manage.py runserver
```

開啟 `http://127.0.0.1:8000/<SECRET_URL_PREFIX>/`，後台在 `/<SECRET_URL_PREFIX>/admin/`。

執行測試：

```bash
DEBUG=True python manage.py test          # macOS / Linux
set DEBUG=True && python manage.py test   # Windows CMD
```

## 對外部署

`runserver` 只適合開發。對外開放時請用下面任一種方式，兩種都由 [Caddy](https://caddyserver.com/) 自動申請並更新 Let's Encrypt 的 HTTPS 憑證。

### 事前準備

1. **網域**：需要一個指向你家對外 IP 的網域。沒有的話可以用 [DuckDNS](https://www.duckdns.org/) 之類的免費動態 DNS，例如 `mydisk.duckdns.org`。
2. **路由器**：把 **80** 和 **443** 埠轉發到要架站的電腦。80 埠是申請憑證時驗證用的，不能省略。
3. 如果電信業者封鎖了 80/443 埠，就無法用這個方式自動申請憑證。

### 方式一：Docker（推薦，Linux / macOS / Windows 皆可）

```bash
cp .env.example .env      # 修改 DOMAIN、DJANGO_SECRET_KEY、SECRET_URL_PREFIX
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

完成後開啟 `https://<DOMAIN>/<SECRET_URL_PREFIX>/`。

- 資料庫、使用者檔案和快取都存在 Docker volume `data`（容器內的 `/data`），備份這個 volume 即可。
- 容器啟動時會自動執行 migration，並且每天清理一次資源回收筒和逾時的上傳。
- 更新程式：`git pull && docker compose up -d --build`

### 方式二：Windows + waitress + Caddy

```cmd
pip install -r requirements.txt waitress
set DJANGO_SECRET_KEY=隨機長字串
set SECRET_URL_PREFIX=自訂的隨機字串
set ALLOWED_HOSTS=mydisk.duckdns.org
set CSRF_TRUSTED_ORIGINS=https://mydisk.duckdns.org
set USE_HTTPS=True
set TRUST_PROXY_HEADERS=True
set ALLOW_REGISTRATION=False
python deploy\run_waitress.py
```

另開一個視窗，下載 [Caddy](https://caddyserver.com/download) 後執行：

```cmd
set DOMAIN=mydisk.duckdns.org
caddy run --config deploy\Caddyfile.local
```

並用「工作排程器」每天執行一次 `python manage.py cleanup_storage`（也可以不設定，每次打開資源回收筒時會清除自己過期的項目）。

### 部署時的注意事項

- `TRUST_PROXY_HEADERS=True` **只能**在前面有反向代理（Caddy / nginx）時開啟，否則使用者可以偽造 IP 繞過登入鎖定。
- gunicorn 有多個 worker 時請設定 `CACHE_DIR`（Docker 已預設），登入失敗次數才會在 worker 之間共用。
- 分段上傳的暫存檔放在 `MEDIA_ROOT/tmp_uploads/`，逾時未完成的會由 `cleanup_storage` 清除。
- 資源回收筒裡的檔案仍會佔用容量。
- `cleanup_storage` 也會補算舊檔案的 SHA-256，並合併同一位使用者內容相同的檔案以釋出空間。
- 使用者同時遺失手機和備用碼時，管理員可以在後台「User profiles」勾選該使用者，執行「重設兩步驟驗證」。
- 下載 zip 時會先在伺服器的暫存目錄建立壓縮檔，請確保硬碟有足夠的剩餘空間（約為資料夾大小）。

## 環境變數

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| `DEBUG` | `False` | 開發時設為 `True` |
| `DJANGO_SECRET_KEY` | 無 | `DEBUG=False` 時必填，請用隨機長字串 |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | 允許的網域或 IP，逗號分隔 |
| `SECRET_URL_PREFIX` | `x8FqP2vM4wA1` | 網址前綴，例如 `/<前綴>/login/`。**預設值已公開在 GitHub 上，請務必自行設定** |
| `ALLOW_REGISTRATION` | `True` | 設為 `False` 關閉註冊，改由管理員在後台建立帳號 |
| `STORAGE_DEFAULT_QUOTA_MB` | `1024` | 每位使用者的預設容量（MB） |
| `STORAGE_MAX_UPLOAD_SIZE_MB` | `100` | 單一檔案大小上限（MB） |
| `STORAGE_CHUNK_SIZE_MB` | `5` | 分段上傳每段大小（MB） |
| `STORAGE_UPLOAD_SESSION_HOURS` | `24` | 未完成的分段上傳保留多久 |
| `STORAGE_TRASH_RETENTION_DAYS` | `30` | 資源回收筒保留天數 |
| `LOGIN_MAX_ATTEMPTS` | `5` | 同一 IP 連續登入失敗幾次後鎖定 |
| `LOGIN_LOCKOUT_SECONDS` | `900` | 鎖定秒數 |
| `USE_HTTPS` | `False` | 有 HTTPS 時設為 `True`，Cookie 只走 HTTPS 並自動轉址 |
| `TRUST_PROXY_HEADERS` | `False` | 在反向代理後方時設為 `True` |
| `CSRF_TRUSTED_ORIGINS` | 空 | 透過網域存取時填入，例如 `https://mydisk.duckdns.org` |
| `DATABASE_PATH` | `db.sqlite3` | SQLite 資料庫路徑 |
| `MEDIA_ROOT` | `private_storage/` | 使用者檔案存放位置 |
| `CACHE_DIR` | 空（使用記憶體） | 檔案快取目錄，多個 worker 時必須設定 |
