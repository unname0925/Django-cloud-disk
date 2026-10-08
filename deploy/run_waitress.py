"""Windows 用的正式伺服器啟動腳本（Windows 不支援 gunicorn）。

    pip install waitress
    python deploy/run_waitress.py

建議前面再放 Caddy 處理 HTTPS，見 README。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cloud.settings")

subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)
subprocess.run([sys.executable, "manage.py", "cleanup_storage"], check=True)

from waitress import serve  # noqa: E402

from cloud.wsgi import application  # noqa: E402

serve(
    application,
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    threads=int(os.environ.get("WAITRESS_THREADS", "8")),
    max_request_body_size=1024 * 1024 * 1024,
)
