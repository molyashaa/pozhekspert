"""Замечания: список с фильтрами, карточка, переписка, внешние замечания (п. 5.6 ТЗ)."""
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ExternalRemarkForm
from ..models import SEVERITY_CHOICES, Document, Remark, RemarkComment, Stage
from ..permissions import can_manage_project, can_view_remark, require, visible_projects, visible_remarks
from ..services import BusinessError, create_remark, notify, remark_review_action
from .common import business_action, paginate

FILTERS = [
    ("mine", "Назначенные мне"),
    ("open", "Открытые"),
    ("rework", "На доработке"),
    ("fixed", "Ожидают повторной проверки"),
    ("closed", "Закрытые"),
]


def remark_list(request):
    user = request.user
    qs = visible_remarks(user).select_related("project", "stage", "document", "version", "author", "assignee")
    f = request.GET.get("f", "")
    q = request.GET.get("q", "").strip()
    project = request.GET.get("project", "")
    severity = request.GET.get("severity", "")
    if f == "mine":
        qs = qs.filter(assignee=user)
    elif f == "open":
        qs = qs.filter(status=Remark.OPEN)
    elif f == "rework":
        qs = qs.filter(status=Remark.REWORK)
    elif f == "fixed":
        qs = qs.filter(status=Remark.FIXED)
    elif f == "closed":
        qs = qs.filter(status__in=(Remark.ACCEPTED, Remark.IRRELEVANT))
    if q:
        qs = qs.filter(Q(text__icontains=q) | Q(number__icontains=q) | Q(section__icontains=q))
    if project:
        qs = qs.filter(project_id=project)
    if severity:
        qs = qs.filter(severity=severity)
    can_external = user.is_approval_manager or user.is_gip or user.is_director
    return render(request, "core/remarks.html", {
        "page": paginate(request, qs.order_by("-created_at"), 15), "f": f, "q": q, "project": project,
        "severity": severity, "filters": FILTERS, "severities": SEVERITY_CHOICES,
        "projects": visible_projects(user), "filters_on": any([f, q, project, severity]),
        "can_external": can_external,
    })


def remark_detail(request, pk):
    user = request.user
    remark = get_object_or_404(Remark.objects.select_related(
        "project", "stage", "document", "version", "fixed_in_version", "author", "assignee"), pk=pk)
    require(can_view_remark(user, remark), "У вас нет доступа к этому замечанию")
    stage = remark.stage
    versions = remark.document.versions.all() if remark.document else []
    return render(request, "core/remark_detail.html", {
        "remark": remark, "stage": stage, "history": remark.history.select_related("user"),
        "comments": remark.comments.select_related("author"), "versions": versions,
        "can_recheck": remark.status == Remark.FIXED and stage.reviewer_id == user.id and remark.assignee_id != user.id,
        "can_irrelevant": remark.status in Remark.UNRESOLVED and (
            can_manage_project(user, remark.project) or remark.author_id == user.id),
    })


@require_POST
@business_action
def remark_action(request, pk):
    user = request.user
    remark = get_object_or_404(Remark, pk=pk)
    require(can_view_remark(user, remark))
    remark_review_action(remark, user, request.POST.get("action", ""), request.POST.get("comment", ""))
    messages.success(request, f"Замечание {remark.number}: «{remark.get_status_display()}».")
    return redirect("remark_detail", pk=remark.pk)


@require_POST
def remark_comment(request, pk):
    user = request.user
    remark = get_object_or_404(Remark, pk=pk)
    require(can_view_remark(user, remark))
    text = request.POST.get("text", "").strip()
    if not text:
        messages.error(request, "Введите текст сообщения.")
    else:
        RemarkComment.objects.create(remark=remark, author=user, text=text)
        for person in {remark.author, remark.assignee} - {user}:
            notify(person, "remark", f"Новое сообщение по замечанию {remark.number}",
                   f"/remarks/{remark.pk}/", remark.project, text[:200])
        messages.success(request, "Сообщение добавлено.")
    return redirect("remark_detail", pk=remark.pk)


def remark_external(request):
    """Регистрация замечания согласующей стороны (менеджер по согласованию)."""
    user = request.user
    require(user.is_approval_manager or user.is_gip or user.is_director,
            "Внешние замечания регистрирует менеджер по согласованию")
    projects = visible_projects(user)
    stages = Stage.objects.filter(project__in=projects, executor__isnull=False).select_related("project")
    documents = Document.objects.filter(project__in=projects)
    form = ExternalRemarkForm(request.POST or None, stages=stages, documents=documents)
    form.fields["stage"].label_from_instance = lambda s: f"{s.project.number} · этап {s.sequence_no}: {s.name}"
    if request.method == "POST" and form.is_valid():
        stage = form.cleaned_data["stage"]
        document = form.cleaned_data["document"]
        version = document.latest_version if document else None
        try:
            remark = create_remark(stage=stage, author=user, text=form.cleaned_data["text"],
                                   section=form.cleaned_data["section"], severity=form.cleaned_data["severity"],
                                   version=version, document=document, due_date=form.cleaned_data["due_date"],
                                   source="external", category="Замечание согласующей стороны")
        except BusinessError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Замечание согласующей стороны зарегистрировано как {remark.number}.")
            return redirect("remark_detail", pk=remark.pk)
    return render(request, "core/remark_external.html", {"form": form})
