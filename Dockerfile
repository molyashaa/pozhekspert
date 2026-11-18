# Образ для облачного хостинга (Amvera Cloud и любой другой, где есть Docker)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir "Django>=5.2,<5.3" PyMySQL scikit-learn whitenoise gunicorn
COPY . /app
# Настройки для хостинга. База SQLite и загруженные файлы — в постоянном хранилище /data
ENV DJANGO_DEBUG=0 \
    DJANGO_ALLOWED_HOSTS=* \
    DJANGO_CSRF_TRUSTED_ORIGINS=https://*.amvera.io,https://*.amvera.app,https://*.amvera.ru \
    DJANGO_HTTPS=1 \
    DB_ENGINE=sqlite \
    SQLITE_NAME=/data/db.sqlite3 \
    MEDIA_ROOT=/data/media \
    DEMO_MODE=1 \
    DEMO_QUICK_LOGIN=1
RUN export DJANGO_SECRET_KEY=build SQLITE_NAME=/tmp/build.sqlite3 && python manage.py makemigrations core && \
    python manage.py collectstatic --noinput && \
    chmod +x /app/start.sh
EXPOSE 8000
CMD ["/app/start.sh"]
