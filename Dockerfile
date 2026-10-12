FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/db.sqlite3 \
    MEDIA_ROOT=/data/files \
    CACHE_DIR=/data/cache \
    BACKUP_DIR=/backups \
    AUTO_BACKUP=True \
    RCLONE_CONFIG=/config/rclone/rclone.conf

WORKDIR /app

# rclone 用來把備份上傳到雲端空間（異地備份）
RUN apt-get update \
    && apt-get install -y --no-install-recommends rclone ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt gunicorn==26.2.0

COPY . .
RUN DEBUG=True python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /data /backups \
    && chown -R app:app /data /backups \
    && chmod +x deploy/entrypoint.sh

USER app
VOLUME ["/data", "/backups"]
EXPOSE 8000

# 定期呼叫健康檢查；資料庫無法連線、檔案目錄無法寫入時容器會標示為 unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "deploy/healthcheck.py"]

ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "cloud.wsgi:application", "--config", "deploy/gunicorn.conf.py"]
