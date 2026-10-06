FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/db.sqlite3 \
    MEDIA_ROOT=/data/files \
    CACHE_DIR=/data/cache

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt gunicorn==26.2.0

COPY . .
RUN DEBUG=True python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data \
    && chmod +x deploy/entrypoint.sh

USER app
VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "cloud.wsgi:application", "--config", "deploy/gunicorn.conf.py"]
