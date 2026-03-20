# Cloud Disk Django

簡單雲端硬碟系統，使用 Django 實作。

* 用戶可以註冊/登入。
* 每個帳號對應一個專屬資料夾，無法存取其他用戶資料。
* 上傳、下載、刪除檔案功能。
* 可透過自家外網 IP 搭配路由轉發存取。

---

## 目錄結構範例
```bash
cloud_disk/
├─ cloud/
│   ├─ settings.py
│   ├─ urls.py
│   └─ wsgi.py
├─ manage.py
├─ storage/
│   ├─ models.py
│   ├─ views.py
│   ├─ admin.py
│   ├─ forms.py
│   └─ templates/
├─ private_storage/   # 用戶檔案儲存資料夾
├─ venv/             # Python 虛擬環境（建議建立）
└─ requirements.txt
```
---

## 環境需求

* Python 3.11+
* Django 4.x+
* SQLite

---

## 安裝流程

1. **建立虛擬環境並啟動**

```bash
python -m venv venv
venv\Scripts\activate   # Windows
source venv/bin/activate  # macOS / Linux
```

2. **安裝依賴**

```bash
pip install -r requirements.txt
```

3. **設定環境變數**

Windows CMD 範例：

```cmd
set DJANGO_SECRET_KEY="隨機生成的長字串"
set DEBUG="True"
set ALLOWED_HOSTS="*"
```

macOS / Linux 範例：

```bash
export DJANGO_SECRET_KEY="隨機生成的長字串"
export DEBUG="True"
export ALLOWED_HOSTS="*"
```

> 注意：
>
> * `DJANGO_SECRET_KEY` 用於 Django 安全性。
> * `DEBUG=True` 為開發模式，正式上線建議設 `False`。
> * `ALLOWED_HOSTS` 指定可訪問的 IP 或 `*` 允許全部。

---

4. **資料庫遷移**

```bash
python manage.py makemigrations
python manage.py migrate
```

5. **建立管理員帳號（可選）**

```bash
python manage.py createsuperuser
```

---

## 執行伺服器

```bash
python manage.py runserver 0.0.0.0:8000
```

* 透過外網 IP + 路由轉發即可訪問。
* 例如：http://<你的外網 IP>:8000/

---

## 功能說明

* 註冊 / 登入 / 登出
* 使用者個人專屬資料夾
* 上傳、下載、刪除檔案
* 後台管理（`/admin/`）

---

## 注意事項

* 上線前請務必將 `DEBUG=False`。
* `DJANGO_SECRET_KEY` 必須保密。
* 路由轉發與防火牆需確保外網可訪問 8000 埠號。

