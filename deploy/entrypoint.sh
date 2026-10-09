#!/bin/sh
set -e

mkdir -p "$MEDIA_ROOT" "$CACHE_DIR"
python manage.py migrate --noinput
python manage.py cleanup_storage

# 背景每天清理一次，並在設定 BACKUP_DIR 時自動備份
(
  while true; do
    sleep 86400
    python manage.py cleanup_storage || true
    if [ -n "$BACKUP_DIR" ] && [ "${AUTO_BACKUP:-True}" = "True" ]; then
      python manage.py backup || true
    fi
  done
) &

exec "$@"
