"""Формы ввода с проверкой данных (п. 5.2, 5.4, 7.2 ТЗ)."""
import os

from django import forms
from django.conf import settings
from django.contrib.auth.password_validation import validate_password

from .models import (
    DOC_TYPES, SEVERITY_CHOICES, AIArchiveEntry, ApprovalPackage, Client, Document, Project, Role, Stage, Task, User,
)

FORBIDDEN_EXT = {"exe", "bat", "cmd", "com", "msi", "sh", "ps1", "js", "vbs", "jar", "scr", "php", "py", "dll"}
SIGNATURES = {"pdf": [b"%PDF"], "docx": [b"PK"], "xlsx": [b"PK"], "dwg": [b"AC1"]}


class StyledMixin:
    """Добавляет CSS-классы полям, чтобы формы выглядели одинаково."""

    def _style(self):
        for name, field in self.fields.items():
            widget = field.widget
            css = "input"
            if isinstance(widget, forms.Select):
                css = "input select"
            elif isinstance(widget, forms.Textarea):
                css = "input textarea"
                widget.attrs.setdefault("rows", 3)
            elif isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = ""
            if css:
                widget.attrs["class"] = (widget.attrs.get("class", "") + " " + css).strip()
            if field.required and css:
                widget.attrs["required"] = "required"


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(*args, **kwargs)


def validate_upload(uploaded):
    """Проверка расширения, сигнатуры файла и размера. Возвращает расширение."""
    name = uploaded.name or ""
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    allowed = settings.ALLOWED_UPLOAD_EXTENSIONS
    if ext in FORBIDDEN_EXT:
        raise forms.ValidationError(
            f"Файл не загружен: исполняемые файлы (.{ext}) запрещены. Выберите {', '.join(a.upper() for a in allowed)}."
        )
    if ext not in allowed:
        raise forms.ValidationError(
            f"Файл не загружен: формат .{ext or '?'} не поддерживается. "
            f"Выберите {', '.join(a.upper() for a in allowed)}."
        )
    max_bytes = settings.FILE_UPLOAD_MAX_MB * 1024 * 1024
    if uploaded.size > max_bytes:
        raise forms.ValidationError(
            f"Превышен максимальный размер: {uploaded.size / 1024 / 1024:.1f} МБ при лимите "
            f"{settings.FILE_UPLOAD_MAX_MB} МБ."
        )
    if uploaded.size == 0:
        raise forms.ValidationError("Файл пустой.")
    sigs = SIGNATURES.get(ext)
    if sigs:
        head = uploaded.read(8)
        uploaded.seek(0)
        if not any(head.startswith(s) for s in sigs):
            raise forms.ValidationError(f"Содержимое файла не соответствует формату .{ext}. Проверьте файл.")
    return ext


# ---------------------------------------------------------------------------
# Вход и профиль
# ---------------------------------------------------------------------------
class LoginForm(forms.Form):
    email = forms.EmailField(label="Рабочая электронная почта",
                             widget=forms.EmailInput(attrs={"placeholder": "Введите рабочую почту", "autofocus": True,
                                                            "class": "input", "autocomplete": "username"}))
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput(
        attrs={"placeholder": "Введите пароль", "class": "input", "autocomplete": "current-password"}))


class PasswordChangeForm(StyledMixin, forms.Form):
    old_password = forms.CharField(label="Текущий пароль", widget=forms.PasswordInput)
    new_password = forms.CharField(label="Новый пароль", widget=forms.PasswordInput,
                                   help_text="Не менее 8 символов, не только цифры.")
    new_password2 = forms.CharField(label="Повторите новый пароль", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self._style()

    def clean_old_password(self):
        value = self.cleaned_data["old_password"]
        if not self.user.check_password(value):
            raise forms.ValidationError("Текущий пароль указан неверно.")
        return value

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("new_password"), data.get("new_password2")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password2", "Пароли не совпадают.")
        if p1:
            try:
                validate_password(p1, self.user)
            except forms.ValidationError as exc:
                self.add_error("new_password", exc)
        return data


# ---------------------------------------------------------------------------
# Сотрудники
# ---------------------------------------------------------------------------
class EmployeeForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "email", "role", "department", "phone", "can_manage_users", "can_manage_clients"]
        labels = {"full_name": "ФИО полностью"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.all()
        self.fields["role"].empty_label = "Выберите роль"
        self._style()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Сотрудник с такой рабочей почтой уже есть.")
        return email

    def clean_full_name(self):
        value = " ".join(self.cleaned_data["full_name"].split())
        if len(value.split()) < 2:
            raise forms.ValidationError("Укажите фамилию и имя (и отчество, если есть).")
        return value


# ---------------------------------------------------------------------------
# Клиенты
# ---------------------------------------------------------------------------
class ClientForm(StyledMixin, forms.ModelForm):
    confirm_duplicate = forms.BooleanField(required=False, label="Всё равно сохранить — это другой клиент")

    class Meta:
        model = Client
        fields = ["name", "client_type", "inn", "contact_person", "phone", "email", "address", "source", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"source": "Например: заявка заказчика от 12.03.2026, договор № 45"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
        self._style()

    def clean(self):
        data = super().clean()
        name = (data.get("name") or "").strip()
        inn = (data.get("inn") or "").strip()
        qs = Client.objects.all()
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        dups = list(qs.filter(name__iexact=name)) if name else []
        if inn:
            dups += [c for c in qs.filter(inn=inn) if c not in dups]
        if dups and not data.get("confirm_duplicate"):
            self.duplicates = dups
            raise forms.ValidationError(
                "Похожий клиент уже есть в справочнике. Откройте существующую запись или подтвердите, что это другой клиент."
            )
        return data


# ---------------------------------------------------------------------------
# Проекты и этапы
# ---------------------------------------------------------------------------
class ProjectForm(StyledMixin, forms.ModelForm):
    change_reason = forms.CharField(label="Причина изменений", required=False, widget=forms.Textarea(attrs={"rows": 2}),
                                    help_text="Обязательна, если меняются название, заказчик или сроки запущенного проекта.")

    class Meta:
        model = Project
        fields = ["name", "client", "gip", "approval_manager", "start_date", "planned_end_date", "object_address",
                  "description"]
        widgets = {
            "start_date": DateInput(),
            "planned_end_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        clients = Client.objects.filter(status="active")
        if self.instance.pk:
            clients = Client.objects.filter(pk=self.instance.client_id) | clients
        self.fields["client"].queryset = clients.distinct()
        self.fields["client"].empty_label = "Выберите заказчика из справочника"
        self.fields["gip"].queryset = User.objects.filter(role__code=Role.GIP, status=User.STATUS_ACTIVE)
        self.fields["gip"].empty_label = "Выберите ГИП"
        self.fields["gip"].label = "ГИП / ответственный"
        self.fields["approval_manager"].queryset = User.objects.filter(role__code=Role.APPROVAL,
                                                                       status=User.STATUS_ACTIVE)
        self.fields["approval_manager"].empty_label = "Не назначен"
        if user is not None and user.is_gip and not self.instance.pk:
            self.fields["gip"].initial = user.pk
        self._style()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not 3 <= len(name) <= 200:
            raise forms.ValidationError("Название — от 3 до 200 символов.")
        return name

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("planned_end_date")
        if start and end and end < start:
            self.add_error("planned_end_date", "Плановая дата окончания не может быть раньше даты начала.")
        inst = self.instance
        if inst.pk and inst.status != Project.DRAFT:
            changed = [f for f in ("name", "client", "start_date", "planned_end_date") if f in self.changed_data]
            if changed and not (data.get("change_reason") or "").strip():
                self.add_error("change_reason", "Проект уже в работе: укажите причину изменения названия, "
                                                "заказчика или сроков.")
        return data


class StageForm(StyledMixin, forms.ModelForm):
    dependencies = forms.ModelMultipleChoiceField(
        label="Зависит от этапов", queryset=Stage.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Этап откроется только после принятия выбранных этапов. Независимые этапы идут параллельно.",
    )
    change_reason = forms.CharField(label="Причина изменения срока", required=False,
                                    widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = Stage
        fields = ["name", "description", "expected_result", "executor_role", "start_date", "deadline", "labor_hours",
                  "file_required"]
        widgets = {"start_date": DateInput(), "deadline": DateInput(), "description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        qs = Stage.objects.filter(project=project)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
            self.fields["dependencies"].initial = list(self.instance.prerequisites().values_list("pk", flat=True))
        self.fields["dependencies"].queryset = qs.order_by("sequence_no")
        self.fields["executor_role"].queryset = Role.objects.filter(code__in=Role.EXECUTOR_ROLES)
        self.fields["executor_role"].empty_label = "Любая роль исполнителя"
        self.fields["start_date"].required = True
        self.fields["deadline"].required = True
        self._style()

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("deadline")
        if start and end and end < start:
            self.add_error("deadline", "Срок этапа не может быть раньше даты начала.")
        inst = self.instance
        if inst.pk and inst.status not in (Stage.NOT_STARTED,) and "deadline" in self.changed_data:
            if not (data.get("change_reason") or "").strip():
                self.add_error("change_reason", "Этап уже начат: укажите причину переноса срока.")
        return data


class TaskForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "executor", "deadline", "labor_hours", "priority", "description"]
        widgets = {"deadline": DateInput(), "description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["executor"].queryset = User.objects.filter(
            status=User.STATUS_ACTIVE, role__code__in=Role.EXECUTOR_ROLES)
        self.fields["executor"].empty_label = "Выберите исполнителя"
        self.fields["executor"].required = True
        self._style()


# ---------------------------------------------------------------------------
# Документы
# ---------------------------------------------------------------------------
class DocumentUploadForm(StyledMixin, forms.Form):
    project = forms.ModelChoiceField(label="Проект", queryset=Project.objects.none(), empty_label="Выберите проект")
    stage = forms.ModelChoiceField(label="Этап", queryset=Stage.objects.none(), required=False,
                                   empty_label="Без этапа (исходные материалы проекта)")
    doc_type = forms.ChoiceField(label="Тип документа", choices=DOC_TYPES)
    title = forms.CharField(label="Название документа", max_length=255)
    file = forms.FileField(label="Файл")
    comment = forms.CharField(label="Комментарий", widget=forms.Textarea(attrs={"rows": 2}),
                              help_text="Что содержит файл или что изменено.")

    def __init__(self, *args, projects=None, stages=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects if projects is not None else Project.objects.none()
        self.fields["stage"].queryset = stages if stages is not None else Stage.objects.none()
        self._style()

    def clean_file(self):
        f = self.cleaned_data["file"]
        self.extension = validate_upload(f)
        return f

    def clean(self):
        data = super().clean()
        project, stage = data.get("project"), data.get("stage")
        if project and stage and stage.project_id != project.pk:
            self.add_error("stage", "Этап не относится к выбранному проекту.")
        return data


class NewVersionForm(StyledMixin, forms.Form):
    file = forms.FileField(label="Файл новой версии")
    comment = forms.CharField(label="Комментарий к версии (что исправлено)", widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_file(self):
        f = self.cleaned_data["file"]
        self.extension = validate_upload(f)
        return f

    def clean_comment(self):
        value = self.cleaned_data["comment"].strip()
        if len(value) < 3:
            raise forms.ValidationError("Опишите изменения в новой версии.")
        return value


# ---------------------------------------------------------------------------
# Замечания и проверка
# ---------------------------------------------------------------------------
class ReturnForm(StyledMixin, forms.Form):
    version = forms.ModelChoiceField(label="Документ и версия", queryset=None, required=False,
                                     empty_label="Выберите версию")
    section = forms.CharField(label="Раздел или лист", max_length=150)
    text = forms.CharField(label="Текст замечания", widget=forms.Textarea(attrs={"rows": 4, "data-draft-target": ""}))
    severity = forms.ChoiceField(label="Критичность", choices=[("", "Выберите")] + SEVERITY_CHOICES)
    due_date = forms.DateField(label="Срок исправления", required=False, widget=DateInput())

    def __init__(self, *args, versions=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import DocumentVersion

        self.fields["version"].queryset = versions if versions is not None else DocumentVersion.objects.none()
        self.fields["version"].label_from_instance = lambda v: f"{v.document.title} — версия {v.version_no}"
        self._style()


class ExternalRemarkForm(StyledMixin, forms.Form):
    stage = forms.ModelChoiceField(label="Этап", queryset=Stage.objects.none(), empty_label="Выберите этап")
    document = forms.ModelChoiceField(label="Документ", queryset=Document.objects.none(), required=False,
                                      empty_label="Не указан")
    section = forms.CharField(label="Раздел / лист", max_length=150)
    text = forms.CharField(label="Текст замечания согласующей стороны", widget=forms.Textarea(attrs={"rows": 4}))
    severity = forms.ChoiceField(label="Критичность", choices=SEVERITY_CHOICES, initial="significant")
    due_date = forms.DateField(label="Срок ответа", required=False, widget=DateInput())

    def __init__(self, *args, stages=None, documents=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = stages if stages is not None else Stage.objects.none()
        self.fields["document"].queryset = documents if documents is not None else Document.objects.none()
        self._style()


class ApprovalPackageForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = ApprovalPackage
        fields = ["project", "title", "authority", "status", "documents", "sent_date", "response_date",
                  "response_note"]
        widgets = {"sent_date": DateInput(), "response_date": DateInput(),
                   "documents": forms.CheckboxSelectMultiple, "response_note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, projects=None, documents=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects if projects is not None else Project.objects.none()
        self.fields["project"].empty_label = "Выберите проект"
        self.fields["documents"].queryset = documents if documents is not None else Document.objects.none()
        self.fields["documents"].label_from_instance = lambda d: f"{d.project.number} · {d.title} (v{d.current_version_no})"
        self._style()


# ---------------------------------------------------------------------------
# ИИ-помощник
# ---------------------------------------------------------------------------
class AISearchForm(StyledMixin, forms.Form):
    query = forms.CharField(label="Опишите замечание или вставьте текст", widget=forms.Textarea(
        attrs={"rows": 5, "placeholder": "Опишите замечание или вставьте текст для поиска похожих случаев"}))
    stage_type = forms.CharField(label="Этап", required=False)
    doc_type = forms.ChoiceField(label="Тип документа", required=False, choices=[("", "Любой")] + DOC_TYPES)

    def __init__(self, *args, stage_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "Любой этап")] + [(s, s) for s in (stage_choices or [])]
        self.fields["stage_type"].widget = forms.Select(choices=choices)
        self._style()


class AIEntryForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = AIArchiveEntry
        fields = ["title", "text", "category", "stage_type", "doc_type", "resolution", "source_label", "record_date"]
        widgets = {"text": forms.Textarea(attrs={"rows": 4}), "resolution": forms.Textarea(attrs={"rows": 3}),
                   "record_date": DateInput()}
        help_texts = {"resolution": "Подтверждается специалистом. Не указывайте персональные и коммерческие данные."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doc_type"].choices = [("", "Не указан")] + DOC_TYPES
        self._style()
