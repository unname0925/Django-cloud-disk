#!/bin/sh
set -e

mkdir -p "$MEDIA_ROOT" "$CACHE_DIR"
# 印出設定上的問題（例如 SECRET_URL_PREFIX 沒改）；只有警告時照常啟動
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py cleanup_storage
if [ -n "$BACKUP_DIR" ] && [ "$AUTO_BACKUP" = "True" ]; then
  # 最近一天內沒有備份時（例如第一次啟動）先補一份
  python manage.py backup --if-older-than 20 || true
fi

# 背景每天清理一次，並在設定 BACKUP_DIR 時自動備份
(
  while true; do
    sleep 86400
    python manage.py cleanup_storage || true
    if [ -n "$BACKUP_DIR" ] && [ "$AUTO_BACKUP" = "True" ]; then
      python manage.py backup || true
    fi
  done
) &

exec "$@"
