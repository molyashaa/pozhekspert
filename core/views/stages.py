"""Этапы, задачи, назначение исполнителей и поэтапная проверка (п. 5.3, 5.5 ТЗ)."""
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import NewVersionForm, ReturnForm, StageForm, TaskForm
from ..models import AIArchiveEntry, Assignment, DocumentVersion, Project, Remark, Role, Stage, Task, User
from ..permissions import (
    can_manage_project, can_upload_to_stage, can_view_project, can_work_on_stage, get_project_or_403, require,
    visible_projects,
)
from ..services import (
    BusinessError, accept_stage, assign_stage, audit, cancel_acceptance, change_stage_deadline, notify,
    recompute_project, remark_review_action, return_stage, set_dependencies, stage_url, submit_check, submit_stage,
)
from .common import back, business_action


def _get_stage(user, pk):
    stage = get_object_or_404(Stage.objects.select_related("project", "project__client", "project__gip", "executor",
                                                           "reviewer", "executor_role"), pk=pk)
    require(can_view_project(user, stage.project), "У вас нет доступа к этому этапу")
    return stage


def stage_create(request, pk):
    user = request.user
    project = get_project_or_403(user, pk)
    require(can_manage_project(user, project), "Этапы формирует ГИП проекта")
    form = StageForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                stage = form.save(commit=False)
                stage.project = project
                stage.sequence_no = (project.stages.aggregate(m=Max("sequence_no"))["m"] or 0) + 1
                stage.status = Stage.NOT_STARTED
                stage.save()
                set_dependencies(stage, [s.pk for s in form.cleaned_data["dependencies"]], user)
                audit(user, "stage_created", f"Добавлен этап {stage.sequence_no} «{stage.name}»", stage, project)
                recompute_project(project, user)
        except BusinessError as exc:
            form.add_error("dependencies", str(exc))
        else:
            messages.success(request, f"Этап {stage.sequence_no} добавлен. Назначьте исполнителя и проверяющего.")
            return redirect(f"/projects/{project.pk}/?tab=stages&assign={stage.pk}")
    return render(request, "core/stage_form.html", {"form": form, "project": project, "is_new": True})


def stage_edit(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    project = stage.project
    require(can_manage_project(user, project), "Изменять этап может ГИП проекта")
    old_deadline = stage.deadline
    form = StageForm(request.POST or None, instance=stage, project=project)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                new_deadline = form.cleaned_data["deadline"]
                stage = form.save(commit=False)
                stage.deadline = old_deadline
                stage.save()
                if new_deadline != old_deadline:
                    change_stage_deadline(stage, user, new_deadline,
                                          form.cleaned_data.get("change_reason") or "уточнение плана до начала этапа")
                set_dependencies(stage, [s.pk for s in form.cleaned_data["dependencies"]], user)
                audit(user, "stage_changed", f"Изменён этап {stage.sequence_no} «{stage.name}»", stage, project)
                recompute_project(project, user)
        except BusinessError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Этап сохранён.")
            return redirect("stage_detail", pk=stage.pk)
    return render(request, "core/stage_form.html", {"form": form, "project": project, "stage": stage, "is_new": False})


@require_POST
@business_action
def stage_assign(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    require(can_manage_project(user, stage.project), "Назначать исполнителей может ГИП проекта")
    executor = User.objects.filter(pk=request.POST.get("executor") or 0).first()
    reviewer = User.objects.filter(pk=request.POST.get("reviewer") or 0).first()
    if not executor and not stage.executor:
        raise BusinessError("Выберите исполнителя.")
    if reviewer and reviewer.role_code not in (Role.EXPERT, Role.GIP, Role.DIRECTOR):
        raise BusinessError("Проверяющим может быть эксперт, ГИП или директор.")
    assign_stage(stage, user, executor or stage.executor, reviewer, request.POST.get("reason", ""))
    messages.success(request, "Назначение сохранено. Исполнитель получил уведомление, событие записано в историю.")
    return redirect(f"/projects/{stage.project_id}/?tab=stages")


@require_POST
@business_action
def stage_deadline(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    require(can_manage_project(user, stage.project), "Переносить сроки может ГИП проекта")
    try:
        new_deadline = date.fromisoformat(request.POST.get("deadline", ""))
    except ValueError:
        raise BusinessError("Укажите новую дату срока.")
    change_stage_deadline(stage, user, new_deadline, request.POST.get("reason", ""))
    messages.success(request, "Срок изменён, исполнитель уведомлён.")
    return redirect("stage_detail", pk=stage.pk)


def stage_detail(request, pk):
    """Страница этапа / задачи исполнителя: замечания, загрузка версии, передача на проверку."""
    user = request.user
    stage = _get_stage(user, pk)
    project = stage.project
    documents = stage.documents.prefetch_related("versions__uploaded_by").order_by("created_at")
    remarks = stage.remarks.select_related("author", "assignee", "version", "version__document").order_by("created_at")
    open_remarks = [r for r in remarks if r.status in Remark.UNRESOLVED]
    ctx = {
        "stage": stage, "project": project, "documents": documents, "remarks": remarks,
        "open_remarks": open_remarks,
        "prereqs": stage.prerequisites(), "dependents": stage.dependents(),
        "tasks": stage.tasks.select_related("executor"),
        "is_executor": can_work_on_stage(user, stage),
        "can_upload": can_upload_to_stage(user, stage) and stage.status not in (Stage.ON_REVIEW, Stage.ACCEPTED)
        and project.status not in (Project.COMPLETED, Project.ARCHIVED),
        "manage": can_manage_project(user, project),
        "submit_reason": submit_check(stage, user) if can_work_on_stage(user, stage) else "",
        "drafts": DocumentVersion.objects.filter(document__stage=stage, review_status=DocumentVersion.DRAFT),
        "version_form": NewVersionForm(),
        "task_form": TaskForm(),
        "assignments": Assignment.objects.filter(stage=stage).select_related("user", "previous_user", "assigned_by")[:10],
        "reviews": stage.reviews.select_related("reviewer").prefetch_related("versions__document"),
        "today": date.today(),
    }
    return render(request, "core/stage_detail.html", ctx)


@require_POST
@business_action
def stage_submit(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    submit_stage(stage, user)
    messages.success(request, "Результат передан на проверку. Версия зафиксирована, проверяющий уведомлён.")
    return redirect("stage_detail", pk=stage.pk)


def review_detail(request, pk):
    """Страница проверки результата экспертом."""
    user = request.user
    stage = _get_stage(user, pk)
    project = stage.project
    submitted = DocumentVersion.objects.filter(document__stage=stage).select_related("document", "uploaded_by")
    current = [v for v in submitted if v.review_status == DocumentVersion.SUBMITTED]
    is_reviewer = stage.reviewer_id == user.id and stage.executor_id != user.id
    draft_text = ""
    if request.GET.get("ai_draft"):
        entry = AIArchiveEntry.objects.filter(pk=request.GET["ai_draft"]).first()
        if entry:
            draft_text = entry.text
    versions_qs = DocumentVersion.objects.filter(document__stage=stage).select_related("document")
    initial = {"text": draft_text}
    if current:
        initial["version"] = current[0].pk
    form = ReturnForm(versions=versions_qs, initial=initial)
    ctx = {
        "stage": stage, "project": project, "current": current, "all_versions": submitted.order_by("-uploaded_at"),
        "preview": next((v for v in current if v.is_pdf), None),
        "fixed_remarks": stage.remarks.filter(status=Remark.FIXED).select_related("version", "fixed_in_version"),
        "other_remarks": stage.remarks.exclude(status=Remark.FIXED).select_related("version"),
        "is_reviewer": is_reviewer and stage.status == Stage.ON_REVIEW,
        "form": form, "draft_text": draft_text,
        "reviews": stage.reviews.select_related("reviewer"),
    }
    return render(request, "core/review_detail.html", ctx)


@require_POST
@business_action
def stage_accept(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    accept_stage(stage, user, request.POST.get("comment", ""))
    messages.success(request, f"Результат этапа «{stage.name}» принят. Зависимые этапы обновлены.")
    return redirect("reviews")


@require_POST
def stage_return(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    versions_qs = DocumentVersion.objects.filter(document__stage=stage).select_related("document")
    form = ReturnForm(request.POST, versions=versions_qs)
    if form.is_valid():
        try:
            return_stage(stage, user, text=form.cleaned_data["text"], section=form.cleaned_data["section"],
                         severity=form.cleaned_data["severity"], version=form.cleaned_data["version"],
                         due_date=form.cleaned_data["due_date"])
        except BusinessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Результат возвращён на доработку. Замечание привязано к версии, "
                                      "исполнитель уведомлён.")
            return redirect("reviews")
    else:
        messages.error(request, "При возврате обязательно замечание: заполните подсвеченные поля.")
    # показываем форму снова, не теряя введённых данных
    return _rerender_review(request, stage, form)


def _rerender_review(request, stage, form):
    submitted = DocumentVersion.objects.filter(document__stage=stage).select_related("document", "uploaded_by")
    current = [v for v in submitted if v.review_status == DocumentVersion.SUBMITTED]
    ctx = {
        "stage": stage, "project": stage.project, "current": current,
        "all_versions": submitted.order_by("-uploaded_at"), "preview": next((v for v in current if v.is_pdf), None),
        "fixed_remarks": stage.remarks.filter(status=Remark.FIXED),
        "other_remarks": stage.remarks.exclude(status=Remark.FIXED),
        "is_reviewer": stage.reviewer_id == request.user.id and stage.status == Stage.ON_REVIEW,
        "form": form, "open_return": True, "reviews": stage.reviews.select_related("reviewer"),
    }
    return render(request, "core/review_detail.html", ctx)


@require_POST
@business_action
def stage_cancel(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    cancel_acceptance(stage, user, request.POST.get("reason", ""))
    messages.warning(request, "Приёмка отменена. Этап возвращён на доработку, зависимые этапы заблокированы.")
    return redirect("stage_detail", pk=stage.pk)


@require_POST
@business_action
def remark_review(request, pk):
    user = request.user
    remark = get_object_or_404(Remark, pk=pk)
    require(can_view_project(user, remark.project))
    remark_review_action(remark, user, request.POST.get("action", ""), request.POST.get("comment", ""))
    messages.success(request, f"Замечание {remark.number}: статус «{remark.get_status_display()}».")
    return back(request, "reviews")


# ---------------------------------------------------------------------------
# Задачи внутри этапа
# ---------------------------------------------------------------------------
@require_POST
def task_create(request, pk):
    user = request.user
    stage = _get_stage(user, pk)
    require(can_manage_project(user, stage.project), "Задачи формирует ГИП проекта")
    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.stage = stage
        task.created_by = user
        task.save()
        Assignment.objects.create(stage=stage, task=task, user=task.executor, role_in_task="executor", assigned_by=user)
        audit(user, "task_created", f"Добавлена задача «{task.title}» в этап {stage.sequence_no}", task, stage.project,
              "", task.executor.short_name)
        notify(task.executor, "assigned", f"Новая задача: {task.title}", stage_url(stage), stage.project)
        messages.success(request, "Задача добавлена, исполнитель уведомлён.")
    else:
        messages.error(request, "Задача не добавлена: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("stage_detail", pk=stage.pk)


@require_POST
@business_action
def task_status(request, pk):
    user = request.user
    task = get_object_or_404(Task.objects.select_related("stage__project"), pk=pk)
    require(task.executor_id == user.id or can_manage_project(user, task.stage.project),
            "Статус задачи меняет её исполнитель")
    new = request.POST.get("status")
    if new not in dict(Task.STATUS_CHOICES):
        raise BusinessError("Неизвестный статус задачи.")
    old = task.get_status_display()
    task.status = new
    from datetime import datetime

    task.completed_at = datetime.now() if new == "done" else None
    task.save()
    audit(user, "task_status", f"Задача «{task.title}»: статус изменён", task, task.stage.project, old,
          task.get_status_display())
    return back(request, "tasks")


def task_list(request):
    """«Задачи»: свои этапы и задачи для исполнителя, все этапы своих проектов — для ГИП/директора."""
    user = request.user
    flt = request.GET.get("f", "")
    if user.is_gip or user.is_director:
        stages = Stage.objects.filter(project__in=visible_projects(user)).exclude(
            project__status__in=(Project.COMPLETED, Project.ARCHIVED))
        if user.is_gip:
            stages = stages.filter(project__gip=user)
    else:
        stages = Stage.objects.filter(executor=user).exclude(project__status__in=(Project.DRAFT, Project.ARCHIVED))
    stages = stages.select_related("project", "executor", "reviewer")
    if flt == "unassigned":
        stages = stages.filter(executor__isnull=True)
    elif flt == "rework":
        stages = stages.filter(status=Stage.REWORK)
    elif flt == "review":
        stages = stages.filter(status=Stage.ON_REVIEW)
    elif flt == "overdue":
        stages = stages.filter(deadline__lt=date.today()).exclude(status=Stage.ACCEPTED)
    elif flt == "active":
        stages = stages.exclude(status=Stage.ACCEPTED)
    elif flt == "accepted":
        stages = stages.filter(status=Stage.ACCEPTED)
    elif not flt:
        stages = stages.exclude(status=Stage.ACCEPTED)
    stages = sorted(stages, key=lambda s: (s.deadline or date.max, s.sequence_no))
    tasks = Task.objects.filter(executor=user).select_related("stage", "stage__project").order_by("status", "deadline")
    return render(request, "core/tasks.html", {"stages": stages, "tasks": tasks, "f": flt,
                                               "manager_view": user.is_gip or user.is_director})
