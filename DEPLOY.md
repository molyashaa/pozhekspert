# Размещение «ПожЭксперт+» на хостинге

Приложению нужны: **Python 3.10+** (лучше 3.12), **MySQL 8 или MariaDB 10.4+**, возможность
выполнить команды в консоли (SSH или веб-консоль хостинга). Подходят три варианта.

| Вариант | Когда выбирать |
|---|---|
| **A. VPS** (любой облачный сервер с Ubuntu 22.04/24.04) | самый надёжный: полный контроль, MySQL ставится одной командой |
| **B. Виртуальный хостинг с Python** (Passenger, например Beget, Timeweb) | дешевле, MySQL создаётся в панели; проверьте, что доступен Python 3.10+ и SSH |
| **C. PythonAnywhere** | проще всего; учтите, что у бесплатных аккаунтов, созданных с 2026 года, нет MySQL — нужен платный тариф или `DB_ENGINE=sqlite` |

Во всех вариантах порядок одинаковый: **загрузить код → создать `.env` → установить
зависимости → создать таблицы → загрузить демо-данные → собрать статику → запустить.**

---

## Общий шаг: файл `.env` на сервере

```ini
DJANGO_SECRET_KEY=<длинная случайная строка>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=pozhexpert.example.ru,www.pozhexpert.example.ru
DJANGO_CSRF_TRUSTED_ORIGINS=https://pozhexpert.example.ru,https://www.pozhexpert.example.ru
DJANGO_HTTPS=1
DB_ENGINE=mysql
DB_NAME=pozh_db
DB_USER=pozh_user
DB_PASSWORD=<пароль базы>
DB_HOST=127.0.0.1
DB_PORT=3306
DEMO_MODE=1
DEMO_QUICK_LOGIN=0
```

Секретный ключ можно получить командой:
`python -c "import secrets; print(secrets.token_urlsafe(50))"`.
`DEMO_QUICK_LOGIN=0` на публичном сайте — чтобы кнопки входа не были доступны всем
(на время показа можно включить `1`).

---

## A. VPS с Ubuntu (gunicorn + nginx + MySQL)

```bash
# 1. пакеты
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential pkg-config \
                    default-libmysqlclient-dev mysql-server nginx

# 2. база и пользователь
sudo mysql -e "CREATE DATABASE pozh_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER 'pozh_user'@'localhost' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';"
sudo mysql -e "GRANT ALL PRIVILEGES ON pozh_db.* TO 'pozh_user'@'localhost'; FLUSH PRIVILEGES;"

# 3. код (архив загрузите через scp/WinSCP или git clone)
sudo mkdir -p /srv/pozhexpert && sudo chown $USER /srv/pozhexpert
cd /srv/pozhexpert            # здесь должны лежать manage.py, core/, templates/ ...
nano .env                     # содержимое — см. «Общий шаг»

# 4. окружение, таблицы, демо-данные, статика
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
```

**Служба gunicorn** — файл `/etc/systemd/system/pozhexpert.service`:

```ini
[Unit]
Description=PozhExpert+ (gunicorn)
After=network.target mysql.service

[Service]
User=www-data
WorkingDirectory=/srv/pozhexpert
ExecStart=/srv/pozhexpert/venv/bin/gunicorn pozh_project.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /srv/pozhexpert/media /srv/pozhexpert/staticfiles
sudo systemctl daemon-reload && sudo systemctl enable --now pozhexpert
```

**nginx** — файл `/etc/nginx/sites-available/pozhexpert`:

```nginx
server {
    listen 80;
    server_name pozhexpert.example.ru;
    client_max_body_size 30M;          # лимит загрузки файлов (в приложении 25 МБ)

    location /static/ { alias /srv/pozhexpert/staticfiles/; }
    # /media/ намеренно НЕ раздаётся: файлы отдаются только через /files/<id>/ с проверкой прав
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/pozhexpert /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
# HTTPS (бесплатный сертификат):
sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d pozhexpert.example.ru
```

Без домена можно открыть по IP: в `.env` укажите `DJANGO_ALLOWED_HOSTS=<IP сервера>`,
`DJANGO_HTTPS=0` и `server_name <IP>;` в nginx.

После изменения кода: `source venv/bin/activate && python manage.py migrate && python manage.py collectstatic --noinput && sudo systemctl restart pozhexpert`.

---

## B. Виртуальный хостинг с Python (Passenger)

1. В панели хостинга создайте сайт/домен и **базу MySQL** — запишите имя базы,
   пользователя, пароль и хост.
2. Загрузите файлы проекта в папку сайта (по FTP или через файловый менеджер).
   В корне уже есть **`passenger_wsgi.py`** — точка входа для Passenger.
3. Подключитесь по SSH, перейдите в папку проекта и выполните:

   ```bash
   python3 --version            # нужна 3.10 или новее
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt   # если mysqlclient не собирается — удалите его строку, будет PyMySQL
   nano .env                         # реквизиты базы из панели, DJANGO_DEBUG=0, домен
   python manage.py makemigrations core
   python manage.py migrate
   python manage.py seed_demo
   python manage.py collectstatic --noinput
   ```
4. В панели включите Python/Passenger для сайта (у каждого хостинга это называется
   немного по-разному — смотрите раздел справки «Django» вашего хостинга) и
   перезапустите приложение (часто — создать файл `tmp/restart.txt`).
5. Если вместо сайта «Internal Server Error» — включите лог ошибок в панели: чаще всего
   причина в версии Python, неверном пароле базы в `.env` или домене, не указанном в
   `DJANGO_ALLOWED_HOSTS`.

---

## C. PythonAnywhere

1. Загрузите архив во вкладке **Files** и распакуйте в консоли (`unzip pozhexpert.zip`).
2. **Bash console:**
   ```bash
   cd ~/pozhexpert
   python3.12 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
3. База: при наличии MySQL (вкладка **Databases**) — имя базы вида `ВАШЛОГИН$pozh_db`,
   хост `ВАШЛОГИН.mysql.pythonanywhere-services.com`; укажите их в `.env`. Если MySQL в
   аккаунте недоступен — `DB_ENGINE=sqlite`.
4. `python manage.py makemigrations core && python manage.py migrate && python manage.py seed_demo && python manage.py collectstatic --noinput`
5. Вкладка **Web** → Add a new web app → Manual configuration → Python 3.12.
   - *Virtualenv*: `/home/ВАШЛОГИН/pozhexpert/venv`
   - *Static files*: URL `/static/` → `/home/ВАШЛОГИН/pozhexpert/staticfiles`
   - *WSGI configuration file* — замените содержимое на:
     ```python
     import os, sys
     path = "/home/ВАШЛОГИН/pozhexpert"
     if path not in sys.path:
         sys.path.insert(0, path)
     os.environ["DJANGO_SETTINGS_MODULE"] = "pozh_project.settings"
     from django.core.wsgi import get_wsgi_application
     application = get_wsgi_application()
     ```
   - В `.env`: `DJANGO_ALLOWED_HOSTS=ВАШЛОГИН.pythonanywhere.com`,
     `DJANGO_CSRF_TRUSTED_ORIGINS=https://ВАШЛОГИН.pythonanywhere.com`, `DJANGO_HTTPS=1`.
6. Нажмите **Reload**. Сайт: `https://ВАШЛОГИН.pythonanywhere.com`.

---

## Проверка после размещения

1. Открывается страница входа, CSS на месте (если страница «голая» — не выполнен
   `collectstatic` или не настроена раздача `/static/`).
2. Вход под директором → главная со сводкой.
3. Под проектировщиком загрузите PDF в этап 7 «Склад «Север»» и скачайте его обратно.
4. Под экспертом откройте этап 6 — PDF показывается во встроенном просмотре.
5. ИИ-помощник находит похожие замечания.

Резервное копирование на сервере: `mysqldump -u pozh_user -p pozh_db > backup.sql`
плюс копия папки `media/` (см. README, раздел 5).
