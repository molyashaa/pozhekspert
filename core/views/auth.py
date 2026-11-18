"""Вход, выход, профиль и смена пароля (п. 3.1, 5.7 ТЗ)."""
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..forms import LoginForm, PasswordChangeForm
from ..models import User
from ..services import audit

NEUTRAL_ERROR = "Не удалось войти. Проверьте данные или обратитесь к директору"


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password"]
        account = User.objects.filter(email__iexact=email).first()
        now = datetime.now()
        if account and account.locked_until and account.locked_until > now:
            minutes = int((account.locked_until - now).total_seconds() // 60) + 1
            error = f"Слишком много неудачных попыток. Вход временно заблокирован, попробуйте через {minutes} мин."
        else:
            user = authenticate(request, username=email, password=password)
            if user is not None:
                user.failed_login_attempts = 0
                user.locked_until = None
                user.save(update_fields=["failed_login_attempts", "locked_until"])
                login(request, user)
                audit(user, "login", f"Вход в систему: {user.short_name}", user)
                nxt = request.GET.get("next", "")
                if nxt.startswith("/") and not nxt.startswith("//"):
                    return redirect(nxt)
                return redirect("home")
            if account:
                account.failed_login_attempts += 1
                if account.failed_login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                    account.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                    account.failed_login_attempts = 0
                    audit(None, "login_locked", f"Вход для {account.email} заблокирован на "
                                                f"{settings.LOGIN_LOCK_MINUTES} минут после 5 неудачных попыток", account)
                account.save(update_fields=["failed_login_attempts", "locked_until"])
            error = NEUTRAL_ERROR
    elif request.method == "POST":
        error = NEUTRAL_ERROR
    demo_accounts = []
    if settings.DEMO_QUICK_LOGIN:
        demo_accounts = User.objects.filter(is_demo=True, status=User.STATUS_ACTIVE).select_related("role") \
            .order_by("role_id", "full_name")
    return render(request, "auth/login.html", {"form": form, "error": error, "demo_accounts": demo_accounts,
                                               "demo_password": settings.DEMO_PASSWORD})


def login_help(request):
    return render(request, "auth/login_help.html")


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        audit(request.user, "logout", f"Выход из системы: {request.user.short_name}", request.user)
    logout(request)
    messages.success(request, "Сеанс завершён.")
    return redirect("login")


def profile(request):
    user = request.user
    form = PasswordChangeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user.set_password(form.cleaned_data["new_password"])
        user.must_change_password = False
        user.save()
        update_session_auth_hash(request, user)
        audit(user, "password_changed", f"{user.short_name} сменил(а) пароль", user)
        messages.success(request, "Пароль изменён.")
        return redirect("profile")
    return render(request, "core/profile.html", {"form": form})
