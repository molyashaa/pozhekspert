"""ИИ-помощник и управление архивом ИИ (п. 5.8–5.9 ТЗ)."""
from datetime import datetime

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import ai
from ..forms import AIEntryForm, AISearchForm
from ..models import AIArchiveEntry, AIFeedback, Remark, Stage
from ..permissions import can_manage_ai_archive, can_view_project, require, visible_ai_entries
from ..services import audit
from .common import back


def _stage_choices():
    names = set(AIArchiveEntry.objects.exclude(stage_type="").values_list("stage_type", flat=True))
    return sorted(names)


def assistant(request):
    user = request.user
    initial = {
        "query": request.GET.get("q", ""),
        "stage_type": request.GET.get("stage_type", ""),
        "doc_type": request.GET.get("doc_type", ""),
    }
    data = request.GET if "query" in request.GET else None
    choices = _stage_choices()
    if initial["stage_type"] and initial["stage_type"] not in choices:
        choices.insert(0, initial["stage_type"])
    form = AISearchForm(data, initial=initial, stage_choices=choices)
    results, info, searched = [], {}, False
    return_to = request.GET.get("return_to", "")
    if not (return_to.startswith("/") and not return_to.startswith("//")):
        return_to = ""
    if data is not None and form.is_valid():
        searched = True
        entries = visible_ai_entries(user)
        results, info = ai.search(form.cleaned_data["query"], entries, form.cleaned_data["stage_type"],
                                  form.cleaned_data["doc_type"])
        for r in results:
            e = r["entry"]
            r["can_open_source"] = bool(e.remark_id and can_view_project(user, e.remark.project))
    return render(request, "core/ai_assistant.html", {
        "form": form, "results": results, "info": info, "searched": searched, "return_to": return_to,
        "algorithm": "TF-IDF + косинусное сходство (scikit-learn)" if ai.HAS_SKLEARN else "ключевые слова",
    })


def entry_detail(request, pk):
    user = request.user
    entry = get_object_or_404(AIArchiveEntry.objects.select_related("remark", "checked_by"), pk=pk)
    visible = visible_ai_entries(user).filter(pk=pk).exists() or can_manage_ai_archive(user)
    require(visible, "Запись архива недоступна")
    source_remark = entry.remark if entry.remark_id and can_view_project(user, entry.remark.project) else None
    return render(request, "core/ai_entry.html", {"entry": entry, "source_remark": source_remark,
                                                  "manage": can_manage_ai_archive(user),
                                                  "feedback": entry.feedback.select_related("user")[:10]})


@require_POST
def feedback(request, pk):
    entry = get_object_or_404(AIArchiveEntry, pk=pk)
    require(visible_ai_entries(request.user).filter(pk=pk).exists())
    AIFeedback.objects.create(entry=entry, user=request.user, useful=request.POST.get("useful") == "1",
                              reason=request.POST.get("reason", "")[:255], query=request.POST.get("query", ""))
    messages.success(request, "Спасибо, оценка сохранена. Алгоритм автоматически не меняется — "
                              "оценки просматривает ответственный специалист.")
    return back(request, "ai_assistant")


# ---------------------------------------------------------------------------
# Экран управления архивом ИИ
# ---------------------------------------------------------------------------
def archive(request):
    user = request.user
    require(can_manage_ai_archive(user), "Архивом ИИ управляет директор или назначенный эксперт")
    qs = AIArchiveEntry.objects.select_related("checked_by")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(text__icontains=q) | Q(category__icontains=q))
    candidates = Remark.objects.filter(ai_status="candidate", status=Remark.ACCEPTED).select_related("stage", "project")
    return render(request, "core/ai_archive.html", {
        "entries": qs, "status": status, "q": q, "statuses": AIArchiveEntry.STATUS_CHOICES, "candidates": candidates,
        "counts": {s: AIArchiveEntry.objects.filter(status=s).count() for s, _ in AIArchiveEntry.STATUS_CHOICES},
    })


def entry_form(request, pk=None, remark_pk=None):
    user = request.user
    require(can_manage_ai_archive(user))
    entry = get_object_or_404(AIArchiveEntry, pk=pk) if pk else None
    remark = get_object_or_404(Remark, pk=remark_pk) if remark_pk else None
    initial = {}
    if remark:
        initial = {"title": remark.text[:80], "text": remark.text, "category": remark.category or "Замечание экспертизы",
                   "stage_type": remark.stage.name, "doc_type": remark.document.doc_type if remark.document else "",
                   "source_label": f"{remark.project.number} · этап «{remark.stage.name}» · {remark.number}",
                   "record_date": remark.created_at.date()}
    form = AIEntryForm(request.POST or None, instance=entry, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.created_by = user
            obj.status = AIArchiveEntry.CANDIDATE
            if remark:
                obj.remark = remark
                obj.project = remark.project
        obj.save()
        if remark:
            remark.ai_status = "included"
            remark.save(update_fields=["ai_status"])
        audit(user, "ai_entry_saved", f"Архив ИИ: сохранена запись «{obj.title}»", obj, obj.project)
        messages.success(request, "Запись сохранена. Чтобы она участвовала в поиске, проверьте её и включите в архив ИИ.")
        return redirect("ai_entry", pk=obj.pk)
    return render(request, "core/ai_entry_form.html", {"form": form, "entry": entry, "remark": remark})


@require_POST
def entry_action(request, pk):
    user = request.user
    require(can_manage_ai_archive(user))
    entry = get_object_or_404(AIArchiveEntry, pk=pk)
    action = request.POST.get("action")
    old = entry.get_status_display()
    now = datetime.now()
    if action == "check":
        entry.status = AIArchiveEntry.CHECKED
        entry.checked_by, entry.checked_at = user, now
    elif action == "include":
        entry.status = AIArchiveEntry.INCLUDED
        entry.checked_by = entry.checked_by or user
        entry.checked_at = entry.checked_at or now
        entry.indexed_at = now
    elif action == "exclude":
        entry.status = AIArchiveEntry.EXCLUDED
        entry.indexed_at = None
    else:
        messages.error(request, "Неизвестное действие.")
        return back(request, "ai_archive")
    entry.save()
    audit(user, "ai_entry_status", f"Архив ИИ: «{entry.title}» — {entry.get_status_display()}", entry, entry.project,
          old, entry.get_status_display())
    messages.success(request, f"Запись «{entry.title}»: {entry.get_status_display()}. "
                              f"Индекс поиска пересчитывается при следующем запросе.")
    return back(request, "ai_archive")


@require_POST
def candidate_reject(request, remark_pk):
    user = request.user
    require(can_manage_ai_archive(user))
    remark = get_object_or_404(Remark, pk=remark_pk)
    remark.ai_status = "rejected"
    remark.save(update_fields=["ai_status"])
    audit(user, "ai_candidate_rejected", f"Замечание {remark.number} не включено в архив ИИ", remark, remark.project)
    messages.success(request, f"Замечание {remark.number} не будет включено в архив ИИ.")
    return redirect("ai_archive")


def stage_hint(request, pk):
    """Переход к помощнику из страницы этапа с заполненным контекстом."""
    stage = get_object_or_404(Stage, pk=pk)
    require(can_view_project(request.user, stage.project))
    from urllib.parse import urlencode

    params = {"stage_type": stage.name, "return_to": request.GET.get("return_to", "")}
    return redirect("/ai/?" + urlencode(params))
