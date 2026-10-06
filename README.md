# Cloud Disk Django

用 Django 實作的個人雲端硬碟，可以架在家裡的電腦上，透過外網 IP 加路由轉發存取。

## 功能

- **帳號**：註冊、登入、登出；可關閉公開註冊；同一 IP 連續登入失敗會暫時鎖定
- **檔案**：多檔上傳、下載、重新命名、移動、刪除
- **資料夾**：建立多層資料夾、麵包屑導覽、重新命名、刪除（連同內容）
- **搜尋與排序**：跨資料夾搜尋檔名，依名稱、大小、上傳時間排序
- **線上預覽**：圖片、PDF、純文字、音訊、影片可直接在瀏覽器開啟
- **分享連結**：產生免登入的下載連結，可設定 1/7/30 天或永不過期，可隨時撤銷，並記錄下載次數
- **容量配額**：每位使用者有容量上限（可在後台個別調整），首頁顯示用量
- **隔離**：每個帳號的檔案存放在獨立的 UUID 資料夾，無法存取其他使用者的檔案

## 目錄結構

```
cloud/                 專案設定（settings、urls）
storage/
├─ models.py           UserProfile、Folder、StoredFile、ShareLink
├─ forms.py            上傳、資料夾、重新命名、移動、分享表單
├─ signals.py          自動建立 profile、刪除紀錄時一併刪除實體檔案
├─ views/
│  ├─ accounts.py      註冊、登入（含失敗鎖定）、登出
│  ├─ browse.py        檔案列表、搜尋、排序、用量
│  ├─ files.py         上傳、下載、預覽、重新命名、移動、刪除
│  ├─ folders.py       資料夾建立、重新命名、刪除
│  └─ shares.py        分享連結管理與公開下載
├─ templates/storage/
└─ tests/              自動化測試
private_storage/       使用者上傳的檔案（不納入版本控制）
```

## 環境需求

- Python 3.12+
- Django 6.0
- SQLite

## 安裝

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # 建立管理員（可選）
```

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
| `LOGIN_MAX_ATTEMPTS` | `5` | 同一 IP 連續登入失敗幾次後鎖定 |
| `LOGIN_LOCKOUT_SECONDS` | `900` | 鎖定秒數 |
| `USE_HTTPS` | `False` | 架好 HTTPS 後設為 `True`，Cookie 只走 HTTPS 並自動轉址 |
| `CSRF_TRUSTED_ORIGINS` | 空 | 透過反向代理或自訂網域存取時填入，例如 `https://disk.example.com` |

Windows CMD 範例：

```cmd
set DEBUG=True
set SECRET_URL_PREFIX=自訂的隨機字串
python manage.py runserver
```

macOS / Linux 範例：

```bash
export DEBUG=True
export SECRET_URL_PREFIX="自訂的隨機字串"
python manage.py runserver
```

啟動後開啟 `http://127.0.0.1:8000/<SECRET_URL_PREFIX>/`，後台在 `/<SECRET_URL_PREFIX>/admin/`。

## 執行測試

```bash
DEBUG=True python manage.py test          # macOS / Linux
set DEBUG=True && python manage.py test   # Windows CMD
```

## 對外開放的注意事項

- `runserver` 只適合開發。對外開放請改用 WSGI 伺服器（Windows 可用 `waitress`，Linux 可用 `gunicorn`），前面再加 nginx 或 Caddy 並啟用 HTTPS，否則帳號密碼會以明文傳送。
- 正式環境請設定 `DEBUG=False`、`DJANGO_SECRET_KEY`、`SECRET_URL_PREFIX`，並將 `ALLOWED_HOSTS` 設為實際的網域或 IP。
- 只給自己或家人使用時，建議設定 `ALLOW_REGISTRATION=False`。
- 登入失敗鎖定使用記憶體快取，伺服器重啟後會重置；在反向代理後方時，請確認 `REMOTE_ADDR` 是使用者的真實 IP。
