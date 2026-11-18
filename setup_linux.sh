#!/usr/bin/env bash
# Первичная установка на Linux/macOS (локально или на VPS). Запускать из папки проекта.
set -e
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt || pip install "Django>=5.2,<5.3" PyMySQL scikit-learn whitenoise gunicorn
[ -f .env ] || cp .env.example .env
python manage.py create_mysql_db || true
python manage.py makemigrations core
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
echo "Готово. Локально: source venv/bin/activate && python manage.py runserver"
