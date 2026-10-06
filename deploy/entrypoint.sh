#!/bin/sh
set -e

mkdir -p "$MEDIA_ROOT" "$CACHE_DIR"
python manage.py migrate --noinput
python manage.py cleanup_storage

# 背景每天清一次回收筒與逾時的上傳
(
  while true; do
    sleep 86400
    python manage.py cleanup_storage || true
  done
) &

exec "$@"
