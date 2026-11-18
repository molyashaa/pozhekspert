"""
Настройки информационной системы «ПожЭксперт+».

Все параметры окружения (секретный ключ, подключение к БД, режим отладки)
читаются из файла .env в корне проекта или из переменных окружения сервера.
Пример — файл .env.example. Реальный .env в репозиторий не кладётся.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Чтение .env без сторонних библиотек
# ---------------------------------------------------------------------------
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "да")


def env_list(key, default=""):
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Базовые параметры
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-before-hosting")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
]
try:  # whitenoise раздаёт CSS/JS на хостинге при DEBUG=False
    import whitenoise  # noqa: F401

    MIDDLEWARE.append("whitenoise.middleware.WhiteNoiseMiddleware")
    HAS_WHITENOISE = True
except ImportError:  # pragma: no cover
    HAS_WHITENOISE = False

MIDDLEWARE += [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.LoginRequiredMiddleware",
    "core.middleware.ForcePasswordChangeMiddleware",
]

ROOT_URLCONF = "pozh_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "pozh_project.wsgi.application"


# ---------------------------------------------------------------------------
# База данных
#   DB_ENGINE=mysql  — MySQL / MariaDB (XAMPP, хостинг)  ← основной вариант по ТЗ
#   DB_ENGINE=sqlite — файл db.sqlite3 (быстрый запуск без MySQL, запасной вариант)
# ---------------------------------------------------------------------------
DB_ENGINE = env("DB_ENGINE", "sqlite").lower()

if DB_ENGINE == "mysql":
    # Основной драйвер — mysqlclient. Если его не удалось установить
    # (бывает на Windows/хостинге), автоматически используется PyMySQL.
    try:
        import MySQLdb  # noqa: F401
    except ImportError:
        import pymysql

        pymysql.version_info = (2, 2, 1, "final", 0)
        pymysql.install_as_MySQLdb()

    DATABASES = {
        "default": {
            # Собственная обёртка над стандартным MySQL-бэкендом Django:
            # разрешает работу с MariaDB 10.4 из пакета XAMPP.
            "ENGINE": "pozh_project.mysql_backend",
            "NAME": env("DB_NAME", "pozh_db"),
            "USER": env("DB_USER", "root"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env("SQLITE_NAME", "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"  # INT AUTO_INCREMENT, как в схеме БД
AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
SESSION_COOKIE_AGE = 60 * 60 * 10  # 10 часов — рабочий день
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ---------------------------------------------------------------------------
# Язык и время
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = env("TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ = False  # единое серверное время; не требует таблиц часовых поясов в MySQL

# ---------------------------------------------------------------------------
# Статика и файлы
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if HAS_WHITENOISE:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
    WHITENOISE_USE_FINDERS = True  # статика работает даже без collectstatic

# Загруженные документы. Отдаются ТОЛЬКО через маршрут /files/<id>/ с проверкой прав,
# прямого URL на каталог media нет.
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

FILE_UPLOAD_MAX_MB = int(env("FILE_UPLOAD_MAX_MB", "25"))
ALLOWED_UPLOAD_EXTENSIONS = ["pdf", "docx", "xlsx", "dwg", "dxf"]
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ---------------------------------------------------------------------------
# Безопасность входа (п. 3.1 ТЗ)
# ---------------------------------------------------------------------------
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15

# ---------------------------------------------------------------------------
# ИИ-помощник (п. 5.8 ТЗ)
# ---------------------------------------------------------------------------
AI_THRESHOLD = float(env("AI_THRESHOLD", "0.15"))  # порог релевантности 0..1
AI_MAX_RESULTS = 5

# Режим учебного прототипа: в шапке показывается метка «Демо-данные»
DEMO_MODE = env_bool("DEMO_MODE", True)
# Кнопки быстрого входа под демо-ролями на странице входа (удобно на защите).
# По ТЗ пароли демо-учёток описываются только в локальной инструкции, поэтому
# по умолчанию выключено. Включается строкой DEMO_QUICK_LOGIN=1 в .env.
DEMO_QUICK_LOGIN = env_bool("DEMO_QUICK_LOGIN", False)
DEMO_PASSWORD = "Demo2026!"

# Перегрузка сотрудника: больше N активных задач или загрузка выше X %
OVERLOAD_TASKS = 5
OVERLOAD_PERCENT = 90

# ---------------------------------------------------------------------------
# Настройки для хостинга (включаются, когда DEBUG=False)
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    if env_bool("DJANGO_HTTPS", False):
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
