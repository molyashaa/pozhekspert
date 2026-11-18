"""Уведомления, поиск, отчёты, журнал аудита, пакеты согласования."""
import csv
from datetime import date, datetime

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ApprovalPackageForm
from ..models import (
    ApprovalPackage, AuditLog, Document, Notification, Project, Remark, Review, Role, Stage, User,
)
from ..permissions import (
    require, visible_documents, visible_projects, visible_remarks,
)
from ..services import audit, workload
from .common import back, paginate


# ---------------------------------------------------------------------------
# Уведомления
# ---------------------------------------------------------------------------
def notification_list(request):
    qs = request.user.notifications.select_related("project")
    if request.GET.get("f") == "unread":
        qs = qs.filter(read_at__isnull=True)
    return render(request, "core/notifications.html", {"page": paginate(request, qs, 20),
                                                       "f": request.GET.get("f", "")})


@require_POST
def notification_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.read_at:
        n.read_at = datetime.now()
        n.save(update_fields=["read_at"])
    if request.POST.get("go") and n.url:
        return redirect(n.url)
    return back(request, "notifications")


@require_POST
def notification_read_all(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=datetime.now())
    messages.success(request, "Все уведомления отмечены прочитанными.")
    return back(request, "notifications")


# ---------------------------------------------------------------------------
# Глобальный поиск в пределах разрешённых данных
# ---------------------------------------------------------------------------
def search(request):
    user = request.user
    q = request.GET.get("q", "").strip()
    ctx = {"q": q, "projects": [], "documents": [], "remarks": []}
    if len(q) >= 2:
        ctx["projects"] = visible_projects(user).filter(
            Q(name__icontains=q) | Q(number__icontains=q) | Q(client__name__icontains=q)).select_related("client")[:10]
        ctx["documents"] = visible_documents(user).filter(title__icontains=q).select_related("project")[:10]
        ctx["remarks"] = visible_remarks(user).filter(
            Q(text__icontains=q) | Q(number__icontains=q)).select_related("project", "stage")[:10]
    ctx["total"] = len(ctx["projects"]) + len(ctx["documents"]) + len(ctx["remarks"])
    return render(request, "core/search.html", ctx)


# ---------------------------------------------------------------------------
# Отчёты и статистика
# ---------------------------------------------------------------------------
def _report_data(user):
    projects = visible_projects(user) if not user.is_director else Project.objects.all()
    if user.is_gip:
        projects = Project.objects.filter(gip=user)
    projects = projects.select_related("client", "gip").prefetch_related("stages")
    stages = Stage.objects.filter(project__in=projects)
    today = date.today()
    by_status = {code: 0 for code, _ in Project.STATUS_CHOICES}
    for p in projects:
        by_status[p.status] += 1
    stage_status = {code: 0 for code, _ in Stage.STATUS_CHOICES}
    for row in stages.values("status").annotate(n=Count("id")):
        stage_status[row["status"]] = row["n"]
    returns = Review.objects.filter(stage__project__in=projects, decision="returned").count()
    accepted = Review.objects.filter(stage__project__in=projects, decision="accepted").count()
    executors = User.objects.filter(status=User.STATUS_ACTIVE, role__code__in=Role.EXECUTOR_ROLES).select_related("role")
    remarks = Remark.objects.filter(project__in=projects)
    return {
        "projects": projects,
        "by_status": [(label, by_status[code], code) for code, label in Project.STATUS_CHOICES],
        "stage_status": [(label, stage_status[code], code) for code, label in Stage.STATUS_CHOICES],
        "stages_total": stages.count(),
        "overdue_stages": stages.filter(deadline__lt=today).exclude(status=Stage.ACCEPTED)
        .exclude(project__status=Project.DRAFT).select_related("project", "executor").order_by("deadline"),
        "returns": returns, "accepted": accepted,
        "return_rate": round(returns * 100 / (returns + accepted)) if returns + accepted else 0,
        "workload": sorted([workload(u) for u in executors], key=lambda r: r["percent"], reverse=True),
        "remarks_by_severity": remarks.values("severity").annotate(n=Count("id")),
        "remarks_open": remarks.filter(status__in=Remark.UNRESOLVED).count(),
        "remarks_total": remarks.count(),
    }


def reports(request):
    user = request.user
    require(user.is_director or user.is_gip, "Отчёты доступны директору и ГИП")
    data = _report_data(user)
    sev = {row["severity"]: row["n"] for row in data["remarks_by_severity"]}
    data["severity_rows"] = [("Критическое", sev.get("critical", 0), "critical"),
                             ("Существенное", sev.get("significant", 0), "significant"),
                             ("Незначительное", sev.get("minor", 0), "minor")]
    data["max_status"] = max([n for _, n, _ in data["by_status"]] + [1])
    data["max_stage"] = max([n for _, n, _ in data["stage_status"]] + [1])
    return render(request, "core/reports.html", data)


def reports_export(request):
    user = request.user
    require(user.is_director or user.is_gip)
    data = _report_data(user)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="pozhexpert_report_{date.today():%Y%m%d}.csv"'
    response.write("﻿")  # BOM, чтобы Excel правильно открыл кириллицу
    w = csv.writer(response, delimiter=";")
    w.writerow(["Номер", "Проект", "Заказчик", "ГИП", "Статус", "Начало", "Окончание (план)", "Выполнение, %",
                "Ближайший срок", "Просрочка"])
    for p in data["projects"]:
        w.writerow([p.number, p.name, p.client.name, p.gip.short_name, p.get_status_display(),
                    p.start_date.strftime("%d.%m.%Y"), p.planned_end_date.strftime("%d.%m.%Y"), p.progress,
                    p.nearest_deadline.strftime("%d.%m.%Y") if p.nearest_deadline else "",
                    "да" if p.is_overdue else "нет"])
    w.writerow([])
    w.writerow(["Сотрудник", "Роль", "Активных задач", "Загрузка, % (приблизительно)", "Перегрузка"])
    for r in data["workload"]:
        w.writerow([r["user"].full_name, r["user"].role.name, r["count"], r["percent"], "да" if r["overloaded"] else "нет"])
    audit(user, "report_export", "Выгружен отчёт по проектам (CSV)")
    return response


def audit_log(request):
    user = request.user
    require(user.is_director, "Журнал аудита доступен директору")
    qs = AuditLog.objects.select_related("user", "project")
    q = request.GET.get("q", "").strip()
    who = request.GET.get("user", "")
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(action__icontains=q))
    if who:
        qs = qs.filter(user_id=who)
    return render(request, "core/audit.html", {"page": paginate(request, qs, 30), "q": q, "who": who,
                                               "users": User.objects.all()})


# ---------------------------------------------------------------------------
# Согласование: пакеты документов и внешние ответы
# ---------------------------------------------------------------------------
def _can_manage_package(user, project):
    return user.is_director or project.approval_manager_id == user.id or project.gip_id == user.id


def approval_list(request):
    user = request.user
    require(user.is_approval_manager or user.is_gip or user.is_director, "Раздел доступен менеджеру по согласованию")
    projects = visible_projects(user)
    qs = ApprovalPackage.objects.filter(project__in=projects).select_related("project", "created_by") \
        .annotate(docs=Count("documents"))
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    return render(request, "core/approvals.html", {"packages": qs, "status": status,
                                                   "statuses": ApprovalPackage.STATUS_CHOICES})


def approval_form(request, pk=None):
    user = request.user
    package = get_object_or_404(ApprovalPackage, pk=pk) if pk else None
    projects = visible_projects(user)
    if package:
        require(_can_manage_package(user, package.project))
    else:
        require(user.is_approval_manager or user.is_gip or user.is_director)
    documents = Document.objects.filter(project__in=projects).select_related("project")
    form = ApprovalPackageForm(request.POST or None, instance=package, projects=projects, documents=documents)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        require(_can_manage_package(user, obj.project), "Нет прав на этот проект")
        old = package.get_status_display() if package else ""
        if not obj.pk:
            obj.created_by = user
        obj.save()
        form.save_m2m()
        if obj.status == "sent" and obj.project.status == Project.IN_PROGRESS:
            obj.project.status = Project.APPROVAL
            obj.project.save(update_fields=["status"])
        audit(user, "approval_package", f"Пакет согласования «{obj.title}»: {obj.get_status_display()}", obj,
              obj.project, old, obj.get_status_display())
        messages.success(request, "Пакет согласования сохранён.")
        return redirect("approvals")
    return render(request, "core/approval_form.html", {"form": form, "package": package})
