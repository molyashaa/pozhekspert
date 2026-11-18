"""
Права доступа (п. 3.2–3.3 ТЗ, матрица доступа).

Принцип: пункт меню прав не даёт. Каждое представление (view) вызывает функции
этого модуля и при отсутствии права возвращает 403, даже если пользователь
подставил адрес вручную. Списки строятся только из разрешённых объектов.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.urls import reverse

from .models import AIArchiveEntry, Document, Project, Remark, Role, Stage

D, G, DS, C, E, S, A = (
    Role.DIRECTOR, Role.GIP, Role.DESIGNER, Role.CALCULATOR, Role.EXPERT, Role.ESTIMATOR, Role.APPROVAL,
)
ALL = (D, G, DS, C, E, S, A)

# (ключ, подпись, url-имя, иконка, роли)
MENU_ITEMS = [
    ("home", "Главная", "home", "home", ALL),
    ("projects", "Проекты", "projects", "folder", ALL),
    ("tasks", "Задачи", "tasks", "list", (D, G, DS, C, S, A)),
    ("reviews", "Проверки", "reviews", "clipboard", (D, G, E)),
    ("remarks", "Замечания", "remarks", "message", ALL),
    ("documents", "Документы", "documents", "file", ALL),
    ("approvals", "Согласования", "approvals", "send", (D, G, A)),
    ("clients", "Клиенты", "clients", "building", (D, G)),
    ("employees", "Сотрудники", "employees", "users", (D, G)),
    ("ai", "ИИ-помощник", "ai_assistant", "sparkle", ALL),
    ("ai_archive", "Архив ИИ", "ai_archive", "archive", (D, E)),
    ("reports", "Отчёты", "reports", "chart", (D, G)),
]


def menu_for(user, path=""):
    code = user.role_code
    items = []
    for key, title, url_name, icon, roles in MENU_ITEMS:
        if code not in roles and not (key == "employees" and user.can_manage_users) \
                and not (key == "clients" and user.can_manage_clients):
            continue
        url = reverse(url_name)
        active = (path == "/" and key == "home") or (url != "/" and path.startswith(url))
        if key == "ai" and path.startswith(reverse("ai_archive")):
            active = False
        badge = 0
        if key == "reviews":
            badge = review_queue(user).count()
        elif key == "remarks" and code in (DS, C, S, A):
            badge = Remark.objects.filter(assignee=user, status__in=(Remark.OPEN, Remark.REWORK)).count()
        items.append({"key": key, "title": title, "url": url, "icon": icon, "active": active, "badge": badge})
    return items


def require(condition, message="Доступ запрещён"):
    if not condition:
        raise PermissionDenied(message)


# ---------------------------------------------------------------------------
# Общие права
# ---------------------------------------------------------------------------
def can_manage_users(user):
    return user.is_director or user.can_manage_users


def can_view_employees(user):
    return can_manage_users(user) or user.is_gip


def can_manage_clients(user):
    return user.is_director or user.can_manage_clients


def can_view_clients(user):
    return can_manage_clients(user) or user.is_gip


def can_create_project(user):
    return user.is_gip or user.is_director


def can_manage_project(user, project):
    """Редактирование проекта, этапов, назначения, переносы сроков."""
    return user.is_director or project.gip_id == user.id


def can_manage_ai_archive(user):
    return user.is_director or user.is_expert


# ---------------------------------------------------------------------------
# Проекты
# ---------------------------------------------------------------------------
def project_filter(user):
    code = user.role_code
    if code == D:
        return Q()
    q = Q(stages__executor=user) | Q(stages__reviewer=user) | Q(stages__tasks__executor=user)
    if code == G:
        q |= Q(gip=user)
    if code == A:
        q |= Q(approval_manager=user)
    return q


def visible_projects(user):
    return Project.objects.filter(project_filter(user)).distinct()


def can_view_project(user, project):
    if user.is_director or project.gip_id == user.id or project.approval_manager_id == user.id:
        return True
    return visible_projects(user).filter(pk=project.pk).exists()


def get_project_or_403(user, pk):
    from django.shortcuts import get_object_or_404

    project = get_object_or_404(Project.objects.select_related("client", "gip"), pk=pk)
    require(can_view_project(user, project), "У вас нет доступа к этому проекту")
    return project


# ---------------------------------------------------------------------------
# Этапы
# ---------------------------------------------------------------------------
def can_view_stage(user, stage):
    return can_view_project(user, stage.project)


def can_work_on_stage(user, stage):
    """Загрузка результата и передача на проверку — исполнитель этапа или задачи."""
    if stage.executor_id == user.id:
        return True
    return stage.tasks.filter(executor=user).exists()


def can_upload_to_stage(user, stage):
    return can_work_on_stage(user, stage) or can_manage_project(user, stage.project) or \
        stage.project.approval_manager_id == user.id


def review_queue(user):
    qs = Stage.objects.filter(status=Stage.ON_REVIEW).select_related("project", "executor", "reviewer")
    if user.is_director:
        return qs
    if user.is_gip:
        return qs.filter(project__gip=user)
    return qs.filter(reviewer=user)


# ---------------------------------------------------------------------------
# Документы
# ---------------------------------------------------------------------------
def documents_filter(user):
    code = user.role_code
    if code == D:
        return Q()
    if code == G:
        return Q(project__gip=user) | Q(created_by=user)
    q = (
        Q(stage__executor=user) | Q(stage__reviewer=user) | Q(stage__tasks__executor=user)
        | Q(created_by=user) | Q(task__executor=user)
    )
    # исходные документы проекта (не привязанные к этапу) видны всем участникам проекта
    q |= Q(stage__isnull=True, project__in=visible_projects(user))
    if code == A:
        q |= Q(project__approval_manager=user)
    return q


def visible_documents(user):
    return Document.objects.filter(documents_filter(user)).distinct()


def can_view_document(user, document):
    if user.is_director:
        return True
    return visible_documents(user).filter(pk=document.pk).exists()


# ---------------------------------------------------------------------------
# Замечания
# ---------------------------------------------------------------------------
def remarks_filter(user):
    code = user.role_code
    if code == D:
        return Q()
    if code == G:
        return Q(project__gip=user)
    if code == E:
        return Q(author=user) | Q(stage__reviewer=user)
    if code == A:
        return Q(assignee=user) | Q(author=user) | Q(project__approval_manager=user, source="external")
    return Q(assignee=user)


def visible_remarks(user):
    return Remark.objects.filter(remarks_filter(user)).distinct()


def can_view_remark(user, remark):
    return visible_remarks(user).filter(pk=remark.pk).exists()


# ---------------------------------------------------------------------------
# Архив ИИ: в выдаче только записи, к которым у пользователя есть доступ
# ---------------------------------------------------------------------------
def visible_ai_entries(user):
    qs = AIArchiveEntry.objects.filter(status=AIArchiveEntry.INCLUDED)
    if user.is_director:
        return qs
    # обезличенные примеры (без проекта) доступны всем; остальные — только участникам проекта
    return qs.filter(Q(project__isnull=True) | Q(project__in=visible_projects(user)))
