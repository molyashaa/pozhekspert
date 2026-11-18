"""
Бизнес-логика: статусы этапов, зависимости, проверка результата,
замечания, уведомления, журнал аудита, расчёт загрузки сотрудников.

Все переходы статусов выполняются только здесь и проверяют права на сервере
(п. 8.2 ТЗ). Представления лишь вызывают эти функции.
"""
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from .models import (
    Assignment, AuditLog, DocumentVersion, Notification, Project, Remark, RemarkHistory,
    Review, Role, Stage, StageDependency, Task, User,
)


class BusinessError(Exception):
    """Нарушение правила процесса — показывается пользователю как понятное сообщение."""


# ---------------------------------------------------------------------------
# Журнал аудита и уведомления
# ---------------------------------------------------------------------------
def audit(user, action, description, obj=None, project=None, old="", new=""):
    return AuditLog.objects.create(
        user=user if (user and user.pk) else None,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=getattr(obj, "pk", None),
        project=project,
        description=description[:500],
        old_value=str(old or ""),
        new_value=str(new or ""),
    )


def notify(user, event_type, title, url="", project=None, message=""):
    if user is None:
        return None
    return Notification.objects.create(
        user=user, event_type=event_type, title=title[:255], url=url, project=project, message=message
    )


def stage_url(stage):
    return reverse("stage_detail", args=[stage.pk])


def review_url(stage):
    return reverse("review_detail", args=[stage.pk])


# ---------------------------------------------------------------------------
# Зависимости этапов
# ---------------------------------------------------------------------------
def _ancestors(stage_id, edges):
    """Все этапы, от которых (прямо или косвенно) зависит stage_id."""
    seen, stack = set(), [stage_id]
    while stack:
        current = stack.pop()
        for dep in edges.get(current, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def check_dependencies(stage, new_dep_ids):
    """Запрет зависимостей на несуществующие/чужие этапы и циклических зависимостей."""
    project_stage_ids = set(Stage.objects.filter(project=stage.project).values_list("id", flat=True))
    for dep_id in new_dep_ids:
        if dep_id not in project_stage_ids:
            raise BusinessError("Нельзя создать зависимость на этап, которого нет в проекте.")
        if stage.pk and dep_id == stage.pk:
            raise BusinessError("Этап не может зависеть сам от себя.")
    if not stage.pk:
        return
    edges = {}
    for s_id, d_id in StageDependency.objects.filter(stage__project=stage.project).values_list("stage_id", "depends_on_id"):
        if s_id != stage.pk:
            edges.setdefault(s_id, set()).add(d_id)
    edges[stage.pk] = set(new_dep_ids)
    for dep_id in new_dep_ids:
        if stage.pk in _ancestors(dep_id, edges) or dep_id == stage.pk:
            dep = Stage.objects.get(pk=dep_id)
            raise BusinessError(
                f"Циклическая зависимость: этап {dep.sequence_no} уже зависит (прямо или через другие этапы) "
                f"от этапа {stage.sequence_no}. Уберите одну из связей."
            )


def set_dependencies(stage, dep_ids, user):
    dep_ids = set(int(x) for x in dep_ids)
    check_dependencies(stage, dep_ids)
    old = set(stage.dependency_links.values_list("depends_on_id", flat=True))
    if old == dep_ids:
        return
    stage.dependency_links.exclude(depends_on_id__in=dep_ids).delete()
    for dep_id in dep_ids - old:
        StageDependency.objects.create(stage=stage, depends_on_id=dep_id)
    names = lambda ids: ", ".join(  # noqa: E731
        str(n) for n in Stage.objects.filter(id__in=ids).order_by("sequence_no").values_list("sequence_no", flat=True)
    ) or "нет"
    audit(user, "stage_dependencies", f"Изменены зависимости этапа {stage.sequence_no} «{stage.name}»",
          stage, stage.project, names(old), names(dep_ids))


@transaction.atomic
def recompute_project(project, user=None):
    """
    Пересчитывает блокировки: этап открыт, только если все этапы, от которых он
    зависит, приняты. Независимые этапы выполняются параллельно.
    """
    if project.status == Project.DRAFT:
        return
    stages = list(project.stages.all())
    accepted = {s.id for s in stages if s.status == Stage.ACCEPTED}
    edges = {}
    for s_id, d_id in StageDependency.objects.filter(stage__project=project).values_list("stage_id", "depends_on_id"):
        edges.setdefault(s_id, []).append(d_id)
    today = date.today()
    for st in stages:
        if st.status == Stage.ACCEPTED:
            continue
        unmet = [d for d in edges.get(st.id, []) if d not in accepted]
        if unmet:
            if st.status != Stage.BLOCKED:
                old = st.get_status_display()
                st.status = Stage.BLOCKED
                st.save(update_fields=["status", "updated_at"])
                audit(user, "stage_blocked", f"Этап {st.sequence_no} «{st.name}» заблокирован зависимостью",
                      st, project, old, "Заблокирован")
        elif st.status in (Stage.BLOCKED, Stage.NOT_STARTED):
            st.status = Stage.IN_PROGRESS
            st.actual_start = st.actual_start or today
            st.save(update_fields=["status", "actual_start", "updated_at"])
            audit(user, "stage_opened", f"Этап {st.sequence_no} «{st.name}» открыт для работы",
                  st, project, "Заблокирован / не начат", "В работе")
            if st.executor:
                notify(st.executor, "assigned", f"Этап открыт: {st.name}", stage_url(st), project,
                       f"Проект {project.number}. Можно приступать к работе.")


# ---------------------------------------------------------------------------
# Проект
# ---------------------------------------------------------------------------
@transaction.atomic
def launch_project(project, user):
    if project.status != Project.DRAFT:
        raise BusinessError("Проект уже запущен.")
    if not project.stages.exists():
        raise BusinessError("Добавьте хотя бы один этап, прежде чем запускать проект.")
    project.status = Project.IN_PROGRESS
    project.save(update_fields=["status", "updated_at"])
    audit(user, "project_launched", f"Проект {project.number} запущен в работу", project, project,
          "Черновик", "В работе")
    recompute_project(project, user)


@transaction.atomic
def change_project_status(project, user, new_status):
    old = project.get_status_display()
    if new_status == Project.IN_PROGRESS and project.status == Project.DRAFT:
        return launch_project(project, user)
    if new_status == Project.COMPLETED:
        not_accepted = project.stages.exclude(status=Stage.ACCEPTED).count()
        if not_accepted:
            raise BusinessError(f"Нельзя завершить проект: {not_accepted} этап(ов) ещё не приняты. "
                                f"Проверьте комплектность.")
        project.actual_end_date = date.today()
    if new_status == Project.ARCHIVED and project.status != Project.COMPLETED:
        raise BusinessError("В архив переводится только завершённый проект.")
    if new_status not in dict(Project.STATUS_CHOICES):
        raise BusinessError("Неизвестный статус.")
    project.status = new_status
    project.save()
    audit(user, "project_status", f"Статус проекта {project.number} изменён", project, project,
          old, project.get_status_display())


# ---------------------------------------------------------------------------
# Загрузка сотрудников (п. 5.3 ТЗ)
# ---------------------------------------------------------------------------
def _workdays(start, end):
    days, current = 0, start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return max(days, 1)


def workload(user, period_end=None):
    today = date.today()
    horizon = period_end if period_end and period_end > today else today + timedelta(days=30)
    stages = list(
        Stage.objects.filter(executor=user, status__in=Stage.ACTIVE)
        .exclude(project__status__in=(Project.COMPLETED, Project.ARCHIVED))
    )
    tasks = list(
        Task.objects.filter(executor=user).exclude(status="done")
        .exclude(stage__status=Stage.ACCEPTED)
        .exclude(stage__project__status__in=(Project.COMPLETED, Project.ARCHIVED))
    )
    items = stages + tasks
    deadlines = [i.deadline for i in items if i.deadline]
    hours, approximate = 0, False
    for item in items:
        if item.labor_hours:
            hours += item.labor_hours
        else:
            hours += 16  # условная оценка, если трудоёмкость не задана
            approximate = True
    capacity = _workdays(today, horizon) * 8
    percent = round(hours * 100 / capacity) if capacity else 0
    count = len(items)
    overloaded = count > settings.OVERLOAD_TASKS or percent >= settings.OVERLOAD_PERCENT
    return {
        "user": user,
        "count": count,
        "nearest": min(deadlines) if deadlines else None,
        "has_overdue": any(d < today for d in deadlines),
        "hours": hours,
        "percent": percent,
        "bar": min(percent, 100),
        "approximate": approximate or not items,
        "overloaded": overloaded,
    }


def candidates_for_stage(stage):
    role = stage.executor_role
    qs = User.objects.filter(status=User.STATUS_ACTIVE).select_related("role")
    qs = qs.filter(role=role) if role else qs.filter(role__code__in=Role.EXECUTOR_ROLES)
    rows = [workload(u, stage.deadline) for u in qs]
    rows.sort(key=lambda r: (r["percent"], r["count"]))
    return rows


def reviewer_candidates(exclude_user_id=None):
    qs = User.objects.filter(
        status=User.STATUS_ACTIVE, role__code__in=(Role.EXPERT, Role.GIP, Role.DIRECTOR)
    ).select_related("role").order_by("role_id", "full_name")
    if exclude_user_id:
        qs = qs.exclude(pk=exclude_user_id)
    # эксперты — первыми
    return sorted(qs, key=lambda u: 0 if u.role_code == Role.EXPERT else 1)


@transaction.atomic
def assign_stage(stage, actor, executor, reviewer, reason=""):
    if executor and reviewer and executor.pk == reviewer.pk:
        raise BusinessError("Исполнитель не может быть проверяющим собственного результата.")
    if executor and executor.status != User.STATUS_ACTIVE:
        raise BusinessError("Нельзя назначить заблокированного или деактивированного сотрудника.")
    if executor:
        load = workload(executor, stage.deadline)
        if load["overloaded"] and stage.executor_id != executor.pk and not reason.strip():
            raise BusinessError(
                f"{executor.short_name} перегружен(а): {load['count']} активных задач, загрузка около "
                f"{load['percent']} %. Укажите причину выбора этого сотрудника."
            )
    project = stage.project
    if executor and stage.executor_id != executor.pk:
        previous = stage.executor
        Assignment.objects.create(stage=stage, user=executor, previous_user=previous, role_in_task="executor",
                                  assigned_by=actor, reason=reason)
        stage.executor = executor
        audit(actor, "assign_executor", f"Этап {stage.sequence_no} «{stage.name}»: назначен исполнитель",
              stage, project, previous.short_name if previous else "не назначен", executor.short_name)
        notify(executor, "assigned", f"Вам назначен этап «{stage.name}»", stage_url(stage), project,
               f"Проект {project.number}. Срок: {stage.deadline.strftime('%d.%m.%Y') if stage.deadline else 'не задан'}.")
        if previous:
            notify(previous, "reassigned", f"Этап «{stage.name}» передан другому исполнителю", stage_url(stage), project)
    if reviewer and stage.reviewer_id != reviewer.pk:
        previous = stage.reviewer
        Assignment.objects.create(stage=stage, user=reviewer, previous_user=previous, role_in_task="reviewer",
                                  assigned_by=actor, reason=reason)
        stage.reviewer = reviewer
        audit(actor, "assign_reviewer", f"Этап {stage.sequence_no} «{stage.name}»: назначен проверяющий",
              stage, project, previous.short_name if previous else "не назначен", reviewer.short_name)
        notify(reviewer, "assigned", f"Вы назначены проверяющим этапа «{stage.name}»", stage_url(stage), project)
    stage.save()


@transaction.atomic
def change_stage_deadline(stage, actor, new_deadline, reason):
    if not reason.strip():
        raise BusinessError("Укажите причину переноса срока.")
    if stage.start_date and new_deadline < stage.start_date:
        raise BusinessError("Срок не может быть раньше даты начала этапа.")
    old = stage.deadline
    stage.deadline = new_deadline
    stage.save(update_fields=["deadline", "updated_at"])
    audit(actor, "deadline_changed", f"Перенесён срок этапа {stage.sequence_no} «{stage.name}». Причина: {reason}",
          stage, stage.project, old.strftime("%d.%m.%Y") if old else "—", new_deadline.strftime("%d.%m.%Y"))
    for person in {stage.executor, stage.reviewer} - {None}:
        notify(person, "deadline", f"Изменён срок этапа «{stage.name}»", stage_url(stage), stage.project,
               f"Новый срок: {new_deadline.strftime('%d.%m.%Y')}. Причина: {reason}")


# ---------------------------------------------------------------------------
# Замечания
# ---------------------------------------------------------------------------
def set_remark_status(remark, user, new_status, comment=""):
    old = remark.status
    if old == new_status:
        return
    remark.status = new_status
    if new_status in (Remark.ACCEPTED, Remark.IRRELEVANT):
        remark.resolved_at = datetime.now()
        if new_status == Remark.ACCEPTED and remark.ai_status == "none":
            remark.ai_status = "candidate"  # закрытое замечание — кандидат в архив ИИ
    remark.save()
    RemarkHistory.objects.create(remark=remark, old_status=old, new_status=new_status, user=user, comment=comment)
    audit(user, "remark_status", f"Замечание {remark.number}: статус изменён", remark, remark.project,
          dict(Remark.STATUS_CHOICES).get(old), dict(Remark.STATUS_CHOICES).get(new_status))


@transaction.atomic
def create_remark(*, stage, author, text, section, severity, version=None, document=None, due_date=None,
                  category="", source="internal", review=None, assignee=None):
    if not text.strip() or not section.strip():
        raise BusinessError("Заполните текст замечания и раздел/лист.")
    assignee = assignee or stage.executor
    if assignee is None:
        raise BusinessError("У этапа нет исполнителя — замечание некому адресовать.")
    if version is not None:
        document = version.document
    remark = Remark.objects.create(
        number=Remark.next_number(), project=stage.project, stage=stage, document=document, version=version,
        section=section.strip(), text=text.strip(), severity=severity, category=category, source=source,
        author=author, assignee=assignee, due_date=due_date, review=review, status=Remark.OPEN,
    )
    RemarkHistory.objects.create(remark=remark, old_status="", new_status=Remark.OPEN, user=author,
                                 comment="Замечание создано")
    audit(author, "remark_created", f"Создано замечание {remark.number} к этапу {stage.sequence_no} «{stage.name}»",
          remark, stage.project)
    notify(assignee, "remark", f"Новое замечание {remark.number}: {stage.name}",
           reverse("remark_detail", args=[remark.pk]), stage.project, remark.text[:200])
    return remark


# ---------------------------------------------------------------------------
# Поэтапная проверка результата (п. 5.5 ТЗ)
# ---------------------------------------------------------------------------
def stage_draft_versions(stage):
    return DocumentVersion.objects.filter(document__stage=stage, review_status=DocumentVersion.DRAFT)


def submit_check(stage, user):
    """Возвращает текст причины, почему передать на проверку нельзя, или пустую строку."""
    if not (stage.executor_id == user.id or stage.tasks.filter(executor=user).exists()):
        return "Передать результат может только исполнитель этапа."
    if stage.project.status == Project.DRAFT:
        return "Проект ещё не запущен."
    if stage.status == Stage.BLOCKED:
        return f"Этап заблокирован. {stage.block_reason}."
    if stage.status == Stage.ON_REVIEW:
        return "Результат уже на проверке — дождитесь решения проверяющего."
    if stage.status == Stage.ACCEPTED:
        return "Этап уже принят."
    if stage.status not in (Stage.IN_PROGRESS, Stage.REWORK):
        return "Этап ещё не открыт для работы."
    if not stage.reviewer_id:
        return "Не назначен проверяющий — обратитесь к ГИПу."
    if stage.file_required and not stage_draft_versions(stage).exists():
        if stage.status == Stage.REWORK:
            return "Загрузите новую версию с исправлениями — без неё замечания нельзя закрыть."
        return "Для этапа обязателен файл результата. Загрузите документ."
    return ""


@transaction.atomic
def submit_stage(stage, user):
    reason = submit_check(stage, user)
    if reason:
        raise BusinessError(reason)
    drafts = list(stage_draft_versions(stage))
    for v in drafts:
        v.review_status = DocumentVersion.SUBMITTED
        v.save(update_fields=["review_status"])
    latest_by_doc = {}
    for v in drafts:
        latest_by_doc[v.document_id] = v
    for remark in stage.remarks.filter(status__in=(Remark.OPEN, Remark.REWORK)):
        remark.fixed_in_version = latest_by_doc.get(remark.document_id) or (drafts[0] if drafts else None)
        remark.save(update_fields=["fixed_in_version"])
        set_remark_status(remark, user, Remark.FIXED, "Исполнитель передал исправленный результат")
    stage.status = Stage.ON_REVIEW
    stage.submitted_at = datetime.now()
    stage.save(update_fields=["status", "submitted_at", "updated_at"])
    vers = ", ".join(f"{v.document.title} v{v.version_no}" for v in drafts) or "без файла"
    audit(user, "stage_submitted", f"Этап {stage.sequence_no} «{stage.name}» передан на проверку ({vers})",
          stage, stage.project, "В работе / На доработке", "Ожидает проверки")
    notify(stage.reviewer, "submitted", f"Результат на проверке: {stage.name}", review_url(stage), stage.project,
           f"Проект {stage.project.number}, исполнитель {user.short_name}. {vers}")


def _check_reviewer(stage, user):
    if stage.status != Stage.ON_REVIEW:
        raise BusinessError("Этап не находится на проверке.")
    if stage.executor_id == user.id or stage.tasks.filter(executor=user).exists():
        raise BusinessError("Исполнитель не может принять или вернуть собственный результат.")
    if stage.reviewer_id != user.id:
        raise BusinessError("Решение принимает только назначенный проверяющий этапа.")


@transaction.atomic
def accept_stage(stage, user, comment=""):
    _check_reviewer(stage, user)
    unresolved = stage.remarks.filter(status__in=(Remark.OPEN, Remark.REWORK))
    if unresolved.exists():
        nums = ", ".join(unresolved.values_list("number", flat=True))
        raise BusinessError(f"Есть неисправленные замечания ({nums}). Верните результат на доработку.")
    submitted = list(DocumentVersion.objects.filter(document__stage=stage, review_status=DocumentVersion.SUBMITTED))
    review = Review.objects.create(stage=stage, reviewer=user, decision="accepted", comment=comment)
    review.versions.set(submitted)
    for v in submitted:
        v.review_status = DocumentVersion.ACCEPTED
        v.save(update_fields=["review_status"])
    for remark in stage.remarks.filter(status=Remark.FIXED):
        set_remark_status(remark, user, Remark.ACCEPTED, "Исправление принято при приёмке результата")
    stage.status = Stage.ACCEPTED
    stage.actual_end = date.today()
    stage.save(update_fields=["status", "actual_end", "updated_at"])
    vers = ", ".join(f"{v.document.title} v{v.version_no}" for v in submitted) or "без файла"
    audit(user, "stage_accepted", f"Принят результат этапа {stage.sequence_no} «{stage.name}» ({vers})",
          stage, stage.project, "Ожидает проверки", "Принят")
    notify(stage.executor, "accepted", f"Результат принят: {stage.name}", stage_url(stage), stage.project, comment)
    if stage.project.gip_id != user.id:
        notify(stage.project.gip, "accepted", f"Принят этап {stage.sequence_no}: {stage.name}",
               reverse("project_detail", args=[stage.project_id]), stage.project)
    recompute_project(stage.project, user)
    return review


@transaction.atomic
def return_stage(stage, user, *, text, section, severity, version=None, due_date=None, comment=""):
    _check_reviewer(stage, user)
    if not text.strip() or not section.strip() or not severity:
        raise BusinessError("При возврате обязательно замечание: текст, раздел/лист и критичность.")
    submitted = list(DocumentVersion.objects.filter(document__stage=stage, review_status=DocumentVersion.SUBMITTED))
    if stage.file_required and version is None:
        raise BusinessError("Укажите документ и версию, к которой относится замечание.")
    if version is not None and version.document.stage_id != stage.id:
        raise BusinessError("Версия не относится к этому этапу.")
    review = Review.objects.create(stage=stage, reviewer=user, decision="returned", comment=comment)
    review.versions.set(submitted)
    for v in submitted:
        v.review_status = DocumentVersion.RETURNED
        v.save(update_fields=["review_status"])
    create_remark(stage=stage, author=user, text=text, section=section, severity=severity, version=version,
                  due_date=due_date, review=review)
    stage.status = Stage.REWORK
    stage.save(update_fields=["status", "updated_at"])
    audit(user, "stage_returned", f"Этап {stage.sequence_no} «{stage.name}» возвращён на доработку",
          stage, stage.project, "Ожидает проверки", "На доработке")
    notify(stage.executor, "returned", f"Возвращено на доработку: {stage.name}", stage_url(stage), stage.project,
           text[:200])
    recompute_project(stage.project, user)
    return review


@transaction.atomic
def cancel_acceptance(stage, user, reason):
    from .permissions import can_manage_project

    if not can_manage_project(user, stage.project):
        raise BusinessError("Отменить приёмку может только ГИП проекта.")
    if stage.status != Stage.ACCEPTED:
        raise BusinessError("Этап не принят.")
    if not reason.strip():
        raise BusinessError("Укажите причину отмены приёмки.")
    Review.objects.create(stage=stage, reviewer=user, decision="cancelled", comment=reason)
    stage.status = Stage.REWORK
    stage.actual_end = None
    stage.save(update_fields=["status", "actual_end", "updated_at"])
    audit(user, "acceptance_cancelled",
          f"Отменена приёмка этапа {stage.sequence_no} «{stage.name}». Причина: {reason}",
          stage, stage.project, "Принят", "На доработке")
    for person in {stage.executor, stage.reviewer} - {None}:
        notify(person, "returned", f"Отменена приёмка этапа «{stage.name}»", stage_url(stage), stage.project, reason)
    recompute_project(stage.project, user)


@transaction.atomic
def remark_review_action(remark, user, action, comment=""):
    """Повторная проверка конкретного замечания проверяющим."""
    stage = remark.stage
    if action in ("accept_fix", "not_fixed"):
        if stage.reviewer_id != user.id and remark.author_id != user.id:
            raise BusinessError("Решение по замечанию принимает проверяющий этапа.")
        if remark.assignee_id == user.id:
            raise BusinessError("Нельзя принять исправление собственного замечания.")
        if remark.status != Remark.FIXED:
            raise BusinessError("Замечание не ожидает проверки исправления.")
        if action == "accept_fix":
            set_remark_status(remark, user, Remark.ACCEPTED, comment or "Исправление принято")
        else:
            set_remark_status(remark, user, Remark.REWORK, comment or "Не исправлено")
            notify(remark.assignee, "returned", f"Замечание {remark.number} не исправлено",
                   reverse("remark_detail", args=[remark.pk]), remark.project, comment)
    elif action == "irrelevant":
        from .permissions import can_manage_project

        if not (can_manage_project(user, remark.project) or remark.author_id == user.id):
            raise BusinessError("Пометить замечание неактуальным может только уполномоченный сотрудник.")
        if not comment.strip():
            raise BusinessError("Укажите объяснение, почему замечание неактуально.")
        if remark.status not in Remark.UNRESOLVED:
            raise BusinessError("Замечание уже закрыто.")
        set_remark_status(remark, user, Remark.IRRELEVANT, comment)
    else:
        raise BusinessError("Неизвестное действие.")
