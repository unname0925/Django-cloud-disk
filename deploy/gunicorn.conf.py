import multiprocessing
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", min(4, multiprocessing.cpu_count() * 2 + 1)))
# 打包大型資料夾成 zip 需要比較長的時間
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 300))
accesslog = "-"
