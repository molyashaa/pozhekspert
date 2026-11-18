"""Шаблонные теги интерфейса: иконки, метки статусов, даты по-русски."""
from datetime import date, datetime

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    "folder": '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="m9 13 2 2 4-4"/>',
    "message": '<path d="M4 5h16v11H8l-4 4z"/>',
    "file": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>',
    "send": '<path d="M21 3 10 14"/><path d="m21 3-7 18-4-7-7-4z"/>',
    "building": '<path d="M4 21V4h10v17M14 9h6v12M8 8h2M8 12h2M8 16h2M17 13h1M17 17h1M2 21h20"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
    "sparkle": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><path d="m12 8 1.5 2.5L16 12l-2.5 1.5L12 16l-1.5-2.5L8 12l2.5-1.5z"/>',
    "archive": '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v12h14V8M10 12h4"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>',
    "bell": '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "alert": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "logout": '<path d="M15 4h4v16h-4M10 17l5-5-5-5M15 12H3"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "flame": '<path d="M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.5 1.5-4 2.5-5 .3 1.6 1 2.6 2 3 0-3 .5-5.5.5-8z"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "thumbup": '<path d="M7 10v10H4V10zM7 10l4-7a2 2 0 0 1 2 2v4h6a2 2 0 0 1 2 2.3l-1.3 7A2 2 0 0 1 17.7 20H7"/>',
    "thumbdown": '<path d="M7 14V4H4v10zM7 14l4 7a2 2 0 0 0 2-2v-4h6a2 2 0 0 0 2-2.3l-1.3-7A2 2 0 0 0 17.7 4H7"/>',
}


@register.simple_tag
def icon(name, size=18, cls=""):
    body = ICONS.get(name, ICONS["info"])
    return mark_safe(
        f'<svg class="ico {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


# цвет метки статуса: green / amber / red / gray / blue
STATUS_TONES = {
    # этапы
    "not_started": "gray", "blocked": "gray", "in_progress": "blue", "on_review": "amber", "rework": "blue",
    "accepted": "green",
    # проекты
    "draft": "gray", "approval": "amber", "completed": "green", "archived": "gray",
    # замечания
    "open": "gray", "fixed": "amber", "irrelevant": "gray",
    # критичность
    "minor": "gray", "significant": "amber", "critical": "red",
    # версии
    "submitted": "amber", "returned": "blue",
    # пользователи
    "active": "green", "blocked_user": "amber", "deactivated": "gray",
    # задачи
    "todo": "gray", "done": "green",
    # пакеты
    "preparing": "gray", "sent": "amber", "remarks": "red", "approved": "green",
    # архив ИИ
    "candidate": "gray", "checked": "blue", "included": "green", "excluded": "gray",
    # решения
    "cancelled": "red",
}


@register.simple_tag
def badge(code, label=None, tone=None):
    tone = tone or STATUS_TONES.get(code, "gray")
    return format_html('<span class="badge badge-{}"><i></i>{}</span>', tone, label if label is not None else code)


@register.simple_tag
def user_badge(user):
    tone = {"active": "green", "blocked": "amber", "deactivated": "gray"}.get(user.status, "gray")
    return format_html('<span class="badge badge-{}"><i></i>{}</span>', tone, user.get_status_display())


MONTHS = ["янв.", "февр.", "марта", "апр.", "мая", "июня", "июля", "авг.", "сент.", "окт.", "нояб.", "дек."]


@register.filter
def short_date(value):
    """date → «25 сент.»; другой год — с годом."""
    if not value:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    text = f"{value.day} {MONTHS[value.month - 1]}"
    if value.year != date.today().year:
        text += f" {value.year}"
    return text


@register.filter
def when(value):
    """datetime → «сегодня, 08:55» / «вчера, 18:10» / «3 нояб., 11:30»."""
    if not value:
        return "—"
    d = value.date()
    delta = (date.today() - d).days
    t = value.strftime("%H:%M")
    if delta == 0:
        return f"сегодня, {t}"
    if delta == 1:
        return f"вчера, {t}"
    return f"{short_date(d)}, {t}"


def _plural(n, one, few, many):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


@register.filter
def plural(n, forms):
    """{{ n|plural:"задача,задачи,задач" }}"""
    one, few, many = forms.split(",")
    return _plural(int(n or 0), one, few, many)


@register.simple_tag
def deadline(value, done=False):
    """Срок с подсветкой: красный при просрочке с числом дней, янтарный — 3 дня и меньше."""
    if not value:
        return mark_safe('<span class="muted">не задан</span>')
    days = (value - date.today()).days
    text = short_date(value)
    if done is True or done in ("accepted", "done", "completed", "archived"):
        return format_html('<span>{}</span>', text)
    if days < 0:
        n = -days
        return format_html('<span class="dl dl-over">{}<small>просрочен на {} {}</small></span>', text, n,
                           _plural(n, "день", "дня", "дней"))
    if days == 0:
        return format_html('<span class="dl dl-soon">{}<small>сегодня</small></span>', text)
    if days <= 3:
        return format_html('<span class="dl dl-soon">{}<small>через {} {}</small></span>', text, days,
                           _plural(days, "день", "дня", "дней"))
    return format_html('<span class="dl">{}</span>', text)


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Изменяет параметры текущего запроса: {% qs page=2 %}"""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + params.urlencode()


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def pct(value, total):
    try:
        return round(int(value) * 100 / int(total)) if int(total) else 0
    except (TypeError, ValueError):
        return 0
