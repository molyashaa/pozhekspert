@echo off
chcp 65001 >nul
call venv\Scripts\activate
start "" http://127.0.0.1:8000/
python manage.py runserver 127.0.0.1:8000
