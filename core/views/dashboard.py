"""Главные страницы по ролям (п. 3.2, 5.1 ТЗ)."""
from datetime import date, timedelta

from django.shortcuts import render

from ..models import ApprovalPackage, AuditLog, Project, Remark, Role, Stage, Task, User
from ..permissions import review_queue, visible_projects
from ..services import workload

URGENCY_ORDER = {Stage.REWORK: 0, Stage.IN_PROGRESS: 1, Stage.ON_REVIEW: 2, Stage.BLOCKED: 3, Stage.NOT_STARTED: 4}


def _stage_sort_key(stage):
    return (stage.deadline or date.max, URGENCY_ORDER.get(stage.status, 9))


def home(request):
    user = request.user
    code = user.role_code
    if code == Role.DIRECTOR:
        return director_dashboard(request)
    if code == Role.GIP:
        return gip_dashboard(request)
    if code == Role.EXPERT:
        return expert_dashboard(request)
    if code == Role.APPROVAL:
        return approval_dashboard(request)
    return executor_dashboard(request)


def _workload_rows():
    executors = User.objects.filter(status=User.STATUS_ACTIVE, role__code__in=Role.EXECUTOR_ROLES).select_related("role")
    rows = [workload(u) for u in executors]
    rows.sort(key=lambda r: r["percent"], reverse=True)
    return rows


def director_dashboard(request):
    projects = list(Project.objects.select_related("client", "gip").prefetch_related("stages"))
    active = [p for p in projects if p.status in Project.ACTIVE_STATUSES]
    today = date.today()
    soon = today + timedelta(days=7)
    risk = [p for p in active if p.status != Project.DRAFT and
            (p.is_overdue or (p.nearest_deadline and p.nearest_deadline <= soon))]
    risk.sort(key=lambda p: p.nearest_deadline or date.max)
    ctx = {
        "cards": {
            "total": len(projects),
            "in_work": sum(1 for p in projects if p.status in (Project.IN_PROGRESS, Project.APPROVAL)),
            "overdue": sum(1 for p in active if p.is_overdue),
            "waiting": Stage.objects.filter(status=Stage.ON_REVIEW).count(),
            "completed": sum(1 for p in projects if p.status in (Project.COMPLETED, Project.ARCHIVED)),
        },
        "risk_projects": risk[:6],
        "workload": _workload_rows()[:8],
        "deadlines": Stage.objects.filter(status__in=Stage.ACTIVE, deadline__isnull=False)
        .exclude(project__status__in=(Project.DRAFT, Project.COMPLETED, Project.ARCHIVED))
        .select_related("project", "executor").order_by("deadline")[:6],
        "events": AuditLog.objects.select_related("user", "project")
        .exclude(action__in=("login", "logout"))[:8],
    }
    return render(request, "core/dashboard_director.html", ctx)


def gip_dashboard(request):
    user = request.user
    projects = list(Project.objects.filter(gip=user).select_related("client").prefetch_related("stages"))
    stages = Stage.objects.filter(project__gip=user).exclude(
        project__status__in=(Project.COMPLETED, Project.ARCHIVED)).select_related("project", "executor", "reviewer")
    today = date.today()
    soon = today + timedelta(days=7)
    executors = {s.executor for s in stages if s.executor and s.status != Stage.ACCEPTED}
    overloaded = [w for w in (workload(u) for u in executors) if w["overloaded"]]
    ctx = {
        "projects": [p for p in projects if p.status in Project.ACTIVE_STATUSES][:8],
        "unassigned": [s for s in stages if not s.executor and s.status != Stage.ACCEPTED],
        "deadlines": sorted([s for s in stages if s.status != Stage.ACCEPTED and s.deadline and s.deadline <= soon
                             and s.project.status != Project.DRAFT], key=lambda s: s.deadline),
        "on_review": [s for s in stages if s.status == Stage.ON_REVIEW],
        "returns": [s for s in stages if s.status == Stage.REWORK],
        "overloaded": overloaded,
        "cards": {
            "projects": sum(1 for p in projects if p.status in Project.ACTIVE_STATUSES),
            "unassigned": sum(1 for s in stages if not s.executor and s.status != Stage.ACCEPTED),
            "overdue": sum(1 for s in stages if s.is_overdue and s.project.status != Project.DRAFT),
            "on_review": sum(1 for s in stages if s.status == Stage.ON_REVIEW),
        },
    }
    return render(request, "core/dashboard_gip.html", ctx)


def executor_dashboard(request):
    user = request.user
    today = date.today()
    week_end = today + timedelta(days=(6 - today.weekday()))
    stages = list(
        Stage.objects.filter(executor=user, status__in=Stage.ACTIVE)
        .exclude(project__status__in=(Project.DRAFT, Project.COMPLETED, Project.ARCHIVED))
        .select_related("project", "reviewer")
    )
    stages.sort(key=_stage_sort_key)
    tasks = Task.objects.filter(executor=user).exclude(status="done").select_related("stage", "stage__project")
    ctx = {
        "stages": stages,
        "tasks": tasks,
        "this_week": [s for s in stages if s.deadline and s.deadline <= week_end],
        "returned": [s for s in stages if s.status == Stage.REWORK],
        "my_remarks": Remark.objects.filter(assignee=user, status__in=(Remark.OPEN, Remark.REWORK))
        .select_related("stage", "project", "author")[:6],
        "load": workload(user),
    }
    return render(request, "core/dashboard_executor.html", ctx)


def expert_dashboard(request):
    user = request.user
    queue = list(review_queue(user))
    project_id = request.GET.get("project")
    urgency = request.GET.get("urgency")
    projects = sorted({s.project for s in queue}, key=lambda p: p.name)
    if project_id:
        queue = [s for s in queue if str(s.project_id) == project_id]
    if urgency == "overdue":
        queue = [s for s in queue if s.is_overdue]
    elif urgency == "week":
        queue = [s for s in queue if s.deadline and s.days_left is not None and s.days_left <= 7]
    queue.sort(key=lambda s: (s.deadline or date.max))
    for s in queue:
        s.open_remarks = s.remarks.filter(status__in=Remark.UNRESOLVED).count()
        s.last_version = (
            s.documents.order_by("-updated_at").first().latest_version if s.documents.exists() else None
        )
    ctx = {
        "queue": queue,
        "projects": projects,
        "recheck": Remark.objects.filter(stage__reviewer=user, status=Remark.FIXED).count(),
        "my_open": Remark.objects.filter(author=user, status__in=Remark.UNRESOLVED).count(),
        "accepted_month": Stage.objects.filter(reviewer=user, status=Stage.ACCEPTED,
                                               actual_end__gte=date.today() - timedelta(days=30)).count(),
    }
    return render(request, "core/dashboard_expert.html", ctx)


def approval_dashboard(request):
    user = request.user
    projects = visible_projects(user)
    packages = ApprovalPackage.objects.filter(project__in=projects).select_related("project")
    ctx = {
        "to_send": packages.filter(status="preparing"),
        "waiting": packages.filter(status="sent"),
        "external": Remark.objects.filter(source="external", project__in=projects)
        .exclude(status__in=(Remark.ACCEPTED, Remark.IRRELEVANT)).select_related("project", "stage")[:8],
        "stages": Stage.objects.filter(executor=user, status__in=Stage.ACTIVE)
        .exclude(project__status=Project.DRAFT).select_related("project"),
        "projects": projects.select_related("client")[:6],
    }
    return render(request, "core/dashboard_approval.html", ctx)
