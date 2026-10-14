# Cloud Disk Django

用 Django 實作的個人雲端硬碟，可以架在家裡的電腦上，透過網域加 HTTPS 從外面存取。

## 功能

- **帳號**：註冊、登入、登出、變更密碼；可關閉公開註冊；同一 IP 連續登入失敗會暫時鎖定
- **活動紀錄**：記錄登入（含 IP 與裝置）與檔案操作；登入時提醒上次登入的時間與之後失敗的登入嘗試次數
- **兩步驟驗證**：支援 Google Authenticator 等 TOTP App，掃描 QR code 即可啟用，附 10 組一次性備用碼；後台登入也必須經過同一套流程
- **手機與 App**：手機上自動改成卡片式排版，可以直接拍照上傳；支援「加到主畫面」當成 App 使用（PWA），離線時顯示提示頁面
- **Email 通知**：新裝置登入、分享連結被下載、容量快滿時寄信通知（可個別關閉）；忘記密碼時可以用確認過的 Email 重設
- **上傳**：拖曳到頁面任何地方即可上傳，有進度條；大檔案分段上傳，斷線自動重試，關掉頁面後重新上傳同一個檔案會從中斷處繼續
- **檔案**：下載、重新命名、移動、刪除；列表模式可勾選多個項目一次移動、刪除或打包 zip
- **版本歷史**：上傳同名檔案到同一個資料夾時保留舊版本，可下載或還原；每個檔案保留最近 10 個版本
- **資料夾**：建立多層資料夾、麵包屑導覽、重新命名、刪除；整個資料夾或全部檔案打包成 zip 下載
- **資源回收筒**：刪除的檔案與資料夾保留 30 天，可還原或永久刪除，期限到了自動清除
- **相簿模式**：圖片顯示縮圖，點開後可用左右鍵切換；檢視模式會記住
- **搜尋與排序**：跨資料夾搜尋檔名，依名稱、大小、上傳時間排序
- **線上預覽**：圖片、PDF、純文字、音訊、影片可直接在瀏覽器開啟；支援 HTTP Range，影片可以拖曳進度條，下載中斷可以續傳
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
│  ├─ versions.py          檔案版本歷史
│  ├─ batch.py             批次操作
│  ├─ activity.py          活動紀錄
│  ├─ backup.py            備份與還原
│  └─ thumbnails.py        縮圖產生與快取
├─ views/                  依功能分檔：accounts、browse、duplicates、files、folders、shares、trash、uploads
├─ static/storage/         uploader.js（拖曳與分段上傳）、gallery.js（相簿燈箱）
├─ templates/storage/
├─ management/commands/    cleanup_storage（清理）、backup（備份）、restore（還原）
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

### 安全機制

- **Content-Security-Policy**：只允許載入本站的腳本，即使有地方忘了跳脫使用者輸入，注入的腳本也不會執行；在瀏覽器中預覽的使用者檔案另外放進 sandbox。
- **資源限制**：進行中的上傳會預留容量；過大的圖片不產生縮圖（防止解壓縮炸彈）；開放註冊時同一個 IP 每天最多註冊 3 個帳號。
- **登入保護**：同一個 IP 連續登入失敗會鎖定，建議所有帳號啟用兩步驟驗證。
- **套件更新**：Dependabot 每週檢查 Python 套件、GitHub Actions、Docker 映像檔的更新，有安全性更新時會自動開 Pull Request。

### 健康檢查與設定檢查

- `/<SECRET_URL_PREFIX>/healthz/` 回傳 JSON，檢查資料庫、檔案目錄能否寫入、硬碟剩餘空間、最近的備份與異地備份。有錯誤時回傳 503，只有警告時回傳 200。
- Docker 每 30 秒呼叫一次健康檢查，`docker compose ps` 會顯示 `healthy` 或 `unhealthy`；Caddy 會等網站健康後才啟動。也可以用 [Uptime Kuma](https://github.com/louislam/uptime-kuma) 等工具監控這個網址，出問題時通知你。
- 啟動時會執行 `python manage.py check --deploy`，列出設定上的問題，例如 `SECRET_URL_PREFIX` 還是預設值、正式環境開放註冊、沒有啟用 HTTPS。管理員登入網站時，頁面上方也會顯示這些提醒。

## Email 通知

設定 SMTP 後就會啟用寄信，沒有設定時所有寄信相關功能都會隱藏。以 Gmail 為例：

1. Google 帳戶啟用兩步驟驗證後，到「應用程式密碼」產生一組 16 碼密碼。
2. 在 `.env` 加上：

```bash
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=你的帳號@gmail.com
EMAIL_HOST_PASSWORD=應用程式密碼
SITE_URL=https://mydisk.duckdns.org   # 信中連結使用的網址
```

3. 寄一封測試信確認設定正確：`python manage.py send_test_email 你的信箱`

使用方式：

- 每位使用者在「帳號安全 → Email 與通知」設定 Email，點確認信中的連結後才會收到通知。變更 Email 需要輸入目前的密碼，避免別人改成自己的信箱來重設你的密碼。
- 通知：新裝置（新的 IP 或瀏覽器）登入、分享連結被下載（同一個連結一小時最多一封）、容量超過 90%（用量降到 80% 以下後才會再次提醒）。
- 忘記密碼：登入頁的「忘記密碼？」只會寄到確認過的 Email，連結 1 小時內有效且只能使用一次；同一個 IP 每小時最多申請 5 次。有啟用兩步驟驗證的帳號，重設密碼後登入仍然需要驗證碼。
- 寄信失敗不會影響網站操作，錯誤會記錄在伺服器 log 中。
- 開發時可以設定 `EMAIL_ENABLED=True`，信件內容會直接印在終端機。

## 手機與 PWA

- 用手機瀏覽器開啟網站，選「加到主畫面」（iPhone 在 Safari 的分享選單中，Android 在 Chrome 的選單中）就能像 App 一樣全螢幕開啟。
- 需要 HTTPS 才能安裝（本機的 `localhost` 除外）。
- Service Worker 只快取 CSS、JS、圖示與離線頁面，**不會快取任何檔案或頁面內容**，私人資料不會留在手機的快取裡。

## 備份與還原

```bash
python manage.py backup                 # 備份到 BACKUP_DIR（預設 backups/），保留最新 7 份
python manage.py backup --keep 30       # 保留最新 30 份
python manage.py restore backups/cloud-disk-20261009-030000.tar.gz
```

- 備份檔包含資料庫快照與所有使用者檔案（縮圖和上傳中的暫存檔會略過，可以重新產生）。資料庫使用 SQLite 的 backup API，伺服器運作中也能安全備份。
- **還原前請先停止伺服器**。原本的資料庫與檔案不會被刪除，而是改名為 `*.before-restore-時間`，確認沒問題後再自行刪除。還原後會自動執行 migration。
- 每份備份建立後都會先驗證（可以完整讀取、資料庫通過 SQLite 完整性檢查），確認可以還原。
- 備份和資料放在同一顆硬碟上，硬碟壞掉時會一起不見，**請設定下面的異地備份**。

### 異地備份

備份完成後可以自動複製到其他地方，兩種方式可以同時使用：

```bash
# 外接硬碟或 NAS 掛載的目錄
python manage.py backup --copy-dir /mnt/usb-backup

# 用 rclone 上傳到雲端（Google Drive、OneDrive、Dropbox、S3 等）
python manage.py backup --rclone-remote gdrive:cloud-disk-backups
```

也可以用環境變數 `BACKUP_COPY_DIR`、`BACKUP_RCLONE_REMOTE` 設定，自動備份時就會一起執行。異地只保留最新的 `BACKUP_OFFSITE_KEEP` 份（預設 14），不會刪除目的地裡不是備份的檔案。異地備份失敗時指令會回傳錯誤，健康檢查也會在超過 36 小時沒有成功時發出警告。

設定 rclone（以 Google Drive 為例，Docker 部署）：

```bash
mkdir rclone
docker run --rm -it -v "$PWD/rclone:/config/rclone" rclone/rclone config   # 建立名為 gdrive 的遠端
# 在 .env 加上 BACKUP_RCLONE_REMOTE=gdrive:cloud-disk-backups
docker compose up -d
docker compose exec web python manage.py backup                            # 測試一次
```

rclone 的設定檔包含雲端帳號的存取權杖，請妥善保管 `rclone/` 目錄（已加入 `.gitignore`）。

Docker 部署會每天自動備份到 `backups` volume，取出備份：

```bash
docker compose exec web python manage.py backup        # 立即備份
docker compose cp web:/backups ./backups               # 複製到主機
```

還原（Docker）：

```bash
docker compose cp ./cloud-disk-xxx.tar.gz web:/backups/
docker compose stop caddy                              # 先停止對外服務
docker compose exec web python manage.py restore /backups/cloud-disk-xxx.tar.gz --yes
docker compose restart web caddy
```

Windows 可以用「工作排程器」每天執行 `python manage.py backup`。

## 自動測試（CI）

推送到 GitHub 或建立 Pull Request 時，GitHub Actions 會自動：

- 執行 pyflakes 靜態檢查、確認 migration 齊全、跑完所有測試
- 建立 Docker 映像檔、啟動容器確認服務正常、執行一次備份、確認 Docker 健康檢查回報 healthy
- 驗證 Caddy 設定檔

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
| `STORAGE_MAX_VERSIONS` | `10` | 每個檔案保留幾個舊版本 |
| `ACTIVITY_LOG_RETENTION_DAYS` | `180` | 活動紀錄保留天數 |
| `BACKUP_DIR` | `backups/` | backup 指令的預設存放位置（Docker 為 `/backups`） |
| `BACKUP_KEEP` | `7` | 保留最新的幾份備份 |
| `AUTO_BACKUP` | `False`（Docker 為 `True`） | 是否每天自動備份；啟用時健康檢查會確認備份夠新 |
| `BACKUP_COPY_DIR` | 空 | 異地備份：另外複製到這個目錄（外接硬碟、NAS） |
| `BACKUP_RCLONE_REMOTE` | 空 | 異地備份：用 rclone 上傳到這個位置，例如 `gdrive:cloud-disk-backups` |
| `BACKUP_OFFSITE_KEEP` | `14` | 異地保留最新的幾份 |
| `HEALTH_MIN_FREE_PERCENT` | `5` | 硬碟剩餘空間低於這個百分比時，健康檢查發出警告 |
| `HEALTH_MAX_BACKUP_AGE_HOURS` | `36` | 備份超過這麼多小時沒有更新時，健康檢查發出警告 |
| `REGISTRATIONS_PER_IP_PER_DAY` | `3` | 開放註冊時，同一個 IP 每天最多註冊幾個帳號 |
| `EMAIL_HOST` | 空 | SMTP 主機，設定後才會寄信，例如 `smtp.gmail.com` |
| `EMAIL_PORT` | `587` | SMTP 連接埠 |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | 空 | SMTP 帳號與密碼（Gmail 請用應用程式密碼） |
| `EMAIL_USE_TLS` / `EMAIL_USE_SSL` | `True` / `False` | 加密方式；使用 465 埠時改成 `EMAIL_USE_SSL=True` |
| `DEFAULT_FROM_EMAIL` | 同 `EMAIL_HOST_USER` | 寄件者 |
| `SITE_URL` | 空 | 信中連結使用的網址，例如 `https://mydisk.duckdns.org` |
| `QUOTA_WARNING_PERCENT` | `90` | 用量超過這個百分比時寄出容量警告 |
| `PASSWORD_RESETS_PER_IP_PER_HOUR` | `5` | 同一個 IP 每小時最多申請幾次重設密碼 |
| `STORAGE_THUMBNAIL_MAX_PIXELS` | `100000000` | 超過這個像素數的圖片不產生縮圖 |
| `LOGIN_MAX_ATTEMPTS` | `5` | 同一 IP 連續登入失敗幾次後鎖定 |
| `LOGIN_LOCKOUT_SECONDS` | `900` | 鎖定秒數 |
| `USE_HTTPS` | `False` | 有 HTTPS 時設為 `True`，Cookie 只走 HTTPS 並自動轉址 |
| `TRUST_PROXY_HEADERS` | `False` | 在反向代理後方時設為 `True` |
| `CSRF_TRUSTED_ORIGINS` | 空 | 透過網域存取時填入，例如 `https://mydisk.duckdns.org` |
| `DATABASE_PATH` | `db.sqlite3` | SQLite 資料庫路徑 |
| `MEDIA_ROOT` | `private_storage/` | 使用者檔案存放位置 |
| `CACHE_DIR` | 空（使用記憶體） | 檔案快取目錄，多個 worker 時必須設定 |
