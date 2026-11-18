"""Создаёт базу данных MySQL/MariaDB из настроек .env (если её ещё нет), кодировка utf8mb4."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Создать базу данных MySQL с кодировкой utf8mb4 (CREATE DATABASE IF NOT EXISTS)"

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if "mysql" not in db["ENGINE"]:
            self.stdout.write("DB_ENGINE не mysql — используется SQLite, создавать базу не нужно.")
            return
        import MySQLdb  # при необходимости это PyMySQL (см. settings.py)

        name = db["NAME"]
        if not name.replace("_", "").isalnum():
            raise CommandError("Имя базы может содержать только латинские буквы, цифры и _")
        try:
            conn = MySQLdb.connect(host=db["HOST"], user=db["USER"], passwd=db["PASSWORD"], port=int(db["PORT"] or 3306),
                                   charset="utf8mb4")
        except Exception as exc:  # noqa: BLE001
            raise CommandError(
                f"Не удалось подключиться к MySQL ({db['HOST']}:{db['PORT']}): {exc}\n"
                "Проверьте, что MySQL запущен (XAMPP → MySQL → Start) и логин/пароль в .env верны."
            )
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
        conn.close()
        self.stdout.write(self.style.SUCCESS(f"База данных «{name}» готова (utf8mb4)."))
