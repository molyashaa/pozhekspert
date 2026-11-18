@echo off
chcp 65001 >nul
REM Первичная установка «ПожЭксперт+» на Windows. Запускать из папки проекта.
REM Перед запуском: в XAMPP Control Panel нажмите Start у MySQL.
echo === 1. Виртуальное окружение ===
if not exist venv (py -3 -m venv venv || python -m venv venv)
call venv\Scripts\activate
echo === 2. Зависимости ===
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo mysqlclient не установился — ставим без него, будет использован PyMySQL
  pip install "Django>=5.2,<5.3" PyMySQL scikit-learn whitenoise
)
echo === 3. Файл настроек ===
if not exist .env copy .env.example .env
echo === 4. База данных pozh_db (utf8mb4) ===
python manage.py create_mysql_db
echo === 5. Таблицы ===
python manage.py makemigrations core
python manage.py migrate
echo === 6. Демо-данные ===
python manage.py seed_demo
echo.
echo Готово. Запуск: start_windows.bat  ^(или: venv\Scripts\activate ^&^& python manage.py runserver^)
pause
