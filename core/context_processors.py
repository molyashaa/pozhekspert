from django.conf import settings

from .permissions import menu_for


def app_context(request):
    user = request.user
    ctx = {"DEMO_MODE": settings.DEMO_MODE, "MAX_UPLOAD_MB": settings.FILE_UPLOAD_MAX_MB,
           "ALLOWED_EXT": settings.ALLOWED_UPLOAD_EXTENSIONS}
    if user.is_authenticated:
        ctx["menu"] = menu_for(user, request.path)
        ctx["unread_count"] = user.notifications.filter(read_at__isnull=True).count()
    return ctx
