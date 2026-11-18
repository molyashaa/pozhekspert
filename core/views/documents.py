"""Документы, версии, загрузка и скачивание с проверкой прав (п. 5.4, 8.2 ТЗ)."""
import os

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from ..forms import DocumentUploadForm, NewVersionForm
from ..models import DOC_TYPES, Document, DocumentVersion, Project, Stage
from ..permissions import (
    can_manage_project, can_upload_to_stage, can_view_document, require, visible_documents, visible_projects,
)
from ..services import BusinessError, audit
from .common import business_action, paginate


def _uploadable_projects(user):
    qs = visible_projects(user).exclude(status=Project.ARCHIVED)
    return qs


def _uploadable_stages(user, projects):
    stages = Stage.objects.filter(project__in=projects).exclude(status__in=(Stage.ON_REVIEW, Stage.ACCEPTED)).select_related("project")
    return [s for s in stages if can_upload_to_stage(user, s)]


def document_list(request):
    user = request.user
    qs = visible_documents(user).select_related("project", "stage", "created_by").prefetch_related("versions")
    q = request.GET.get("q", "").strip()
    project = request.GET.get("project", "")
    stage = request.GET.get("stage", "")
    doc_type = request.GET.get("type", "")
    version = request.GET.get("version", "")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(versions__original_name__icontains=q))
    if project:
        qs = qs.filter(project_id=project)
    if stage:
        qs = qs.filter(stage_id=stage)
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if version == "multi":
        qs = qs.filter(current_version_no__gt=1)
    elif version == "first":
        qs = qs.filter(current_version_no=1)
    qs = qs.distinct().order_by("-updated_at")
    projects = visible_projects(user)
    ctx = {
        "page": paginate(request, qs, 15), "q": q, "project": project, "stage": stage, "doc_type": doc_type,
        "version": version, "projects": projects, "doc_types": DOC_TYPES,
        "stages": Stage.objects.filter(project_id=project) if project else [],
        "filters_on": any([q, project, stage, doc_type, version]),
    }
    return render(request, "core/documents.html", ctx)


def document_upload(request):
    user = request.user
    projects = _uploadable_projects(user)
    stages_list = _uploadable_stages(user, projects)
    stage_ids = [s.pk for s in stages_list]
    form = DocumentUploadForm(request.POST or None, request.FILES or None, projects=projects,
                              stages=Stage.objects.filter(pk__in=stage_ids).select_related("project"),
                              initial={"project": request.GET.get("project"), "stage": request.GET.get("stage")})
    if request.method == "POST" and form.is_valid():
        project = form.cleaned_data["project"]
        stage = form.cleaned_data["stage"]
        if stage is None:
            allowed = can_manage_project(user, project) or project.approval_manager_id == user.id
            if not allowed:
                form.add_error("stage", "Исполнитель загружает результат в свой этап. Выберите этап.")
        if not form.errors:
            with transaction.atomic():
                doc = Document.objects.create(project=project, stage=stage, doc_type=form.cleaned_data["doc_type"],
                                              title=form.cleaned_data["title"].strip(), created_by=user,
                                              current_version_no=1)
                f = form.cleaned_data["file"]
                version = DocumentVersion(document=doc, version_no=1, original_name=os.path.basename(f.name)[:255],
                                          extension=form.extension, size=f.size,
                                          comment=form.cleaned_data["comment"], uploaded_by=user)
                version.file.save(f.name, f, save=False)
                version.save()
                audit(user, "document_uploaded", f"Загружен документ «{doc.title}» (версия 1)", doc, project,
                      "", version.original_name)
            messages.success(request, f"Документ «{doc.title}» загружен: {version.original_name}, "
                                      f"{version.size_display}, версия 1.")
            nxt = request.POST.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect("document_detail", pk=doc.pk)
    return render(request, "core/document_upload.html", {"form": form, "next": request.GET.get("next", "")})


def document_detail(request, pk):
    user = request.user
    doc = get_object_or_404(Document.objects.select_related("project", "stage", "created_by"), pk=pk)
    require(can_view_document(user, doc), "У вас нет доступа к этому документу")
    versions = doc.versions.select_related("uploaded_by").prefetch_related("reviews__reviewer", "remarks")
    can_new = False
    reason = ""
    if doc.stage:
        if not can_upload_to_stage(user, doc.stage):
            reason = "Новую версию загружает исполнитель этапа."
        elif doc.stage.status == Stage.ON_REVIEW:
            reason = "Версия на проверке — дождитесь решения проверяющего."
        elif doc.stage.status == Stage.ACCEPTED:
            reason = "Этап принят. Если нужна правка, ГИП отменяет приёмку."
        else:
            can_new = True
    else:
        can_new = can_manage_project(user, doc.project) or doc.project.approval_manager_id == user.id
        reason = "" if can_new else "Исходные документы загружает ГИП."
    latest = versions.first()
    return render(request, "core/document_detail.html", {
        "doc": doc, "versions": versions, "latest": latest, "can_new": can_new, "reason": reason,
        "form": NewVersionForm(), "preview": latest if latest and latest.is_pdf else None,
    })


@require_POST
@business_action
def document_new_version(request, pk):
    user = request.user
    doc = get_object_or_404(Document.objects.select_related("project", "stage"), pk=pk)
    require(can_view_document(user, doc))
    if doc.stage:
        require(can_upload_to_stage(user, doc.stage), "Новую версию загружает исполнитель этапа")
        if doc.stage.status == Stage.ON_REVIEW:
            raise BusinessError("Отправленная на проверку версия зафиксирована. Дождитесь решения проверяющего.")
        if doc.stage.status == Stage.ACCEPTED:
            raise BusinessError("Этап принят: принятую версию изменить нельзя.")
    else:
        require(can_manage_project(user, doc.project) or doc.project.approval_manager_id == user.id)
    form = NewVersionForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"Версия не загружена. {errors}")
        return redirect(request.POST.get("next") or f"/documents/{doc.pk}/")
    with transaction.atomic():
        doc = Document.objects.select_for_update().get(pk=doc.pk)
        number = doc.current_version_no + 1
        f = form.cleaned_data["file"]
        version = DocumentVersion(document=doc, version_no=number, original_name=os.path.basename(f.name)[:255],
                                  extension=form.extension, size=f.size, comment=form.cleaned_data["comment"],
                                  uploaded_by=user)
        version.file.save(f.name, f, save=False)
        version.save()
        # предыдущие черновые (не отправленные) версии этого документа остаются в истории
        doc.current_version_no = number
        doc.save(update_fields=["current_version_no", "updated_at"])
        audit(user, "version_uploaded", f"Загружена версия {number} документа «{doc.title}»: {version.comment}",
              doc, doc.project, f"версия {number - 1}", f"версия {number}")
    messages.success(request, f"Загружена версия {number}: {version.original_name} ({version.size_display}). "
                              f"Прежние версии сохранены.")
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect("document_detail", pk=doc.pk)


@xframe_options_sameorigin
def version_download(request, pk):
    """Скачивание только через этот маршрут: сначала проверяется право на документ."""
    user = request.user
    version = get_object_or_404(DocumentVersion.objects.select_related("document", "document__project"), pk=pk)
    require(can_view_document(user, version.document), "У вас нет доступа к этому файлу")
    if not version.file or not version.file.storage.exists(version.file.name):
        raise Http404("Файл не найден в хранилище. Проверьте восстановление каталога media из резервной копии.")
    inline = request.GET.get("inline") == "1" and version.is_pdf
    response = FileResponse(version.file.open("rb"), as_attachment=not inline, filename=version.original_name)
    if inline:
        response["Content-Type"] = "application/pdf"
    return response
