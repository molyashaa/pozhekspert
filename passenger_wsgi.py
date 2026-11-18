"""Точка входа для виртуального хостинга с Phusion Passenger (Beget, Timeweb и др.)."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
# если виртуальное окружение лежит рядом с проектом в папке venv — подключаем его пакеты
for candidate in ("venv", ".venv"):
    lib = os.path.join(BASE_DIR, candidate, "lib")
    if os.path.isdir(lib):
        for name in os.listdir(lib):
            site = os.path.join(lib, name, "site-packages")
            if os.path.isdir(site):
                sys.path.insert(1, site)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pozh_project.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
