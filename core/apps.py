from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _create_roles(sender, **kwargs):
    from .models import ensure_roles

    ensure_roles()


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "core"
    verbose_name = "ПожЭксперт+"

    def ready(self):
        post_migrate.connect(_create_roles, sender=self)
