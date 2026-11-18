"""Общие помощники представлений."""
from functools import wraps

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect

from ..services import BusinessError


def paginate(request, queryset, per_page=12):
    paginator = Paginator(queryset, per_page)
    page = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    page.querystring = params.urlencode()
    return page


def business_action(view):
    """Переводит нарушения правил процесса в понятные сообщения вместо ошибки 500."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except BusinessError as exc:
            messages.error(request, str(exc))
            return redirect(request.META.get("HTTP_REFERER") or "home")

    return wrapper


def back(request, fallback="home"):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(request.META.get("HTTP_REFERER") or fallback)
