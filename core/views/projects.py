"""Проекты: список, поиск и фильтры, карточка, создание и редактирование (п. 5.1–5.2 ТЗ)."""
from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ProjectForm
from ..models import AuditLog, Client, Document, Project, Remark, Review, Role, Stage, User
from ..permissions import (
    can_create_project, can_manage_clients, can_manage_project, get_project_or_403, require, visible_projects,
)
from ..services import audit, candidates_for_stage, change_project_status, launch_project, reviewer_candidates
from .common import business_action, paginate

SORTS = {
    "number": "number", "-number": "-number", "name": "name", "-name": "-name",
    "start": "start_date", "-start": "-start_date", "end": "planned_end_date", "-end": "-planned_end_date",
}


def _valid_date(value):
    try:
        return date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return ""


def project_list(request):
    user = request.user
    qs = visible_projects(user).select_related("client", "gip").prefetch_related("stages")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    client = request.GET.get("client", "")
    gip = request.GET.get("gip", "")
    date_from = _valid_date(request.GET.get("from", ""))
    date_to = _valid_date(request.GET.get("to", ""))
    overdue = request.GET.get("overdue") == "1"
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(number__icontains=q) | Q(client__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if client:
        qs = qs.filter(client_id=client)
    if gip:
        qs = qs.filter(gip_id=gip)
    if date_from:
        qs = qs.filter(planned_end_date__gte=date_from)
    if date_to:
        qs = qs.filter(planned_end_date__lte=date_to)
    if overdue:
        ids = [p.id for p in qs if p.is_overdue and p.status != Project.DRAFT]
        qs = qs.filter(id__in=ids)
    sort = request.GET.get("sort", "-number")
    qs = qs.order_by(SORTS.get(sort, "-number"))
    page = paginate(request, qs, 10)
    filters_on = any([q, status, client, gip, date_from, date_to, overdue])
    ctx = {
        "page": page, "q": q, "status": status, "client": client, "gip": gip, "date_from": date_from,
        "date_to": date_to, "overdue": overdue, "sort": sort, "filters_on": filters_on,
        "statuses": Project.STATUS_CHOICES,
        "clients": Client.objects.filter(projects__in=visible_projects(user)).distinct(),
        "gips": User.objects.filter(role__code=Role.GIP),
        "can_create": can_create_project(user),
    }
    return render(request, "core/projects.html", ctx)


def project_create(request):
    user = request.user
    require(can_create_project(user), "Создавать проекты могут ГИП и директор")
    form = ProjectForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.number = Project.next_number()
        project.status = Project.DRAFT
        project.created_by = user
        project.save()
        audit(user, "project_created", f"Создан проект {project.number} «{project.name}»", project, project)
        messages.success(request, f"Проект {project.number} создан в статусе «Черновик». Добавьте этапы.")
        return redirect("project_detail", pk=project.pk)
    return render(request, "core/project_form.html", {
        "form": form, "is_new": True, "can_add_client": can_manage_clients(user),
        "has_clients": Client.objects.filter(status="active").exists(),
    })


def project_edit(request, pk):
    user = request.user
    project = get_project_or_403(user, pk)
    require(can_manage_project(user, project), "Редактировать проект может ГИП проекта")
    old = {"name": project.name, "client": str(project.client), "start_date": project.start_date,
           "planned_end_date": project.planned_end_date, "gip": str(project.gip)}
    form = ProjectForm(request.POST or None, instance=project, user=user)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        reason = form.cleaned_data.get("change_reason", "")
        new = {"name": project.name, "client": str(project.client), "start_date": project.start_date,
               "planned_end_date": project.planned_end_date, "gip": str(project.gip)}
        labels = {"name": "название", "client": "заказчик", "start_date": "дата начала",
                  "planned_end_date": "плановое окончание", "gip": "ГИП"}
        for key, old_value in old.items():
            if old_value != new[key]:
                audit(user, "project_changed",
                      f"Проект {project.number}: изменено поле «{labels[key]}»" + (f". Причина: {reason}" if reason else ""),
                      project, project, old_value, new[key])
        started = project.stages.exclude(status=Stage.NOT_STARTED).exists()
        if started and ("start_date" in form.changed_data or "planned_end_date" in form.changed_data):
            messages.warning(request, "Изменены сроки проекта, в котором уже есть начатые этапы. "
                                      "Проверьте сроки этапов.")
        messages.success(request, "Изменения сохранены и записаны в историю проекта.")
        return redirect("project_detail", pk=project.pk)
    return render(request, "core/project_form.html", {
        "form": form, "is_new": False, "project": project, "can_add_client": can_manage_clients(user),
        "has_clients": True,
    })


@require_POST
@business_action
def project_status(request, pk):
    user = request.user
    project = get_project_or_403(user, pk)
    require(can_manage_project(user, project))
    new_status = request.POST.get("status", "")
    if new_status == Project.IN_PROGRESS and project.status == Project.DRAFT:
        launch_project(project, user)
        messages.success(request, "Проект запущен. Этапы без зависимостей открыты для работы.")
    else:
        change_project_status(project, user, new_status)
        messages.success(request, f"Статус проекта: «{project.get_status_display()}».")
    return redirect("project_detail", pk=project.pk)


def project_detail(request, pk):
    user = request.user
    project = get_project_or_403(user, pk)
    tab = request.GET.get("tab", "stages")
    stages = list(project.stages.select_related("executor", "reviewer", "executor_role").prefetch_related(
        "dependency_links__depends_on", "tasks"))
    counts = project.stage_counts()
    manage = can_manage_project(user, project)
    ctx = {
        "project": project, "tab": tab, "stages": stages, "counts": counts, "manage": manage,
        "today": date.today(),
    }
    if tab == "overview":
        ctx["team"] = sorted({s.executor for s in stages if s.executor} | {s.reviewer for s in stages if s.reviewer},
                             key=lambda u: u.full_name)
        ctx["source_docs"] = project.documents.filter(stage__isnull=True)
        ctx["recent"] = AuditLog.objects.filter(project=project).select_related("user")[:5]
    elif tab == "documents":
        ctx["documents"] = Document.objects.filter(project=project).select_related("stage", "created_by") \
            .prefetch_related("versions")
    elif tab == "reviews":
        ctx["reviews"] = Review.objects.filter(stage__project=project).select_related("stage", "reviewer") \
            .prefetch_related("versions__document")
        ctx["remarks"] = Remark.objects.filter(project=project).select_related("stage", "author", "assignee", "version")
    elif tab == "history":
        ctx["events"] = AuditLog.objects.filter(project=project).select_related("user")[:200]
    # Диалог назначения исполнителя (?assign=<id этапа>)
    assign_id = request.GET.get("assign")
    if assign_id and manage:
        stage = get_object_or_404(Stage, pk=assign_id, project=project)
        rows = candidates_for_stage(stage)
        ctx["assign_stage"] = stage
        ctx["candidates"] = rows
        ctx["any_approx"] = any(r["approximate"] for r in rows)
        ctx["reviewers"] = reviewer_candidates()
    return render(request, "core/project_detail.html", ctx)
