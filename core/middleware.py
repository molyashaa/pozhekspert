"""Промежуточные обработчики: закрытые страницы и обязательная смена пароля."""
from django.shortcuts import redirect
from django.urls import reverse

PUBLIC_PREFIXES = ("/login", "/static/", "/admin/", "/favicon")


class LoginRequiredMiddleware:
    """Доступ к любой странице без авторизации запрещён (п. 3.1 ТЗ)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not request.user.is_authenticated and not path.startswith(PUBLIC_PREFIXES):
            return redirect(f"{reverse('login')}?next={path}")
        return self.get_response(request)


class ForcePasswordChangeMiddleware:
    """После выдачи временного пароля пользователь обязан задать свой."""

    allowed = ("/profile", "/logout", "/static/", "/login")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not request.path.startswith(self.allowed)
        ):
            return redirect(reverse("profile") + "#password")
        return self.get_response(request)
