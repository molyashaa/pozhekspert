"""
Модели (таблицы БД) системы «ПожЭксперт+».

Основа — девять сущностей ER-модели (roles, users, clients, projects, stages,
tasks, documents, remarks, ai_archive), дополненные таблицами, которых требует
ТЗ (п. 9): зависимости этапов, назначения, версии документов, проверки,
история статусов замечаний, уведомления, журнал аудита, пакеты согласования.
Физическое удаление истории не предусмотрено: используются статусы
«архивный» / «деактивирована» и версионирование.
"""
import os
import uuid
from datetime import date

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Справочники значений
# ---------------------------------------------------------------------------
DOC_TYPES = [
    ("source", "Исходные данные"),
    ("scheme", "Схема"),
    ("drawing", "Чертёж / план"),
    ("calculation", "Расчёт"),
    ("specification", "Спецификация"),
    ("explanatory", "Пояснительная записка"),
    ("estimate", "Смета"),
    ("letter", "Письмо / ответ"),
    ("other", "Прочее"),
]

SEVERITY_CHOICES = [
    ("minor", "Незначительное"),
    ("significant", "Существенное"),
    ("critical", "Критическое"),
]


# ---------------------------------------------------------------------------
# Роли и пользователи
# ---------------------------------------------------------------------------
class Role(models.Model):
    DIRECTOR = "director"
    GIP = "gip"
    DESIGNER = "designer"
    CALCULATOR = "calculator"
    EXPERT = "expert"
    ESTIMATOR = "estimator"
    APPROVAL = "approval"

    DEFAULTS = [
        (DIRECTOR, "Директор", "Контроль всех проектов, сроков, загрузки; учётные записи; справочник клиентов."),
        (GIP, "ГИП", "Создаёт проекты и этапы, назначает исполнителей и проверяющих, переносит сроки."),
        (DESIGNER, "Проектировщик", "Выполняет назначенные задачи, загружает результаты и версии."),
        (CALCULATOR, "Расчётчик", "Выполняет расчёты, загружает расчётные документы и версии."),
        (EXPERT, "Эксперт", "Проверяет результаты: принимает или возвращает на доработку с замечанием."),
        (ESTIMATOR, "Сметчик", "Готовит сметные материалы по назначенным задачам."),
        (APPROVAL, "Менеджер по согласованию", "Готовит пакеты, регистрирует внешние ответы и замечания."),
    ]
    EXECUTOR_ROLES = (DESIGNER, CALCULATOR, ESTIMATOR, APPROVAL)

    code = models.CharField("Код", max_length=30, unique=True)
    name = models.CharField("Название", max_length=80, unique=True)
    description = models.CharField("Описание полномочий", max_length=255, blank=True)

    class Meta:
        db_table = "roles"
        ordering = ["id"]
        verbose_name = "Роль"
        verbose_name_plural = "Роли"

    def __str__(self):
        return self.name


def ensure_roles():
    """Создаёт справочник ролей, если его ещё нет (вызывается после migrate)."""
    for code, name, description in Role.DEFAULTS:
        Role.objects.get_or_create(code=code, defaults={"name": name, "description": description})


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Укажите рабочую электронную почту")
        email = self.normalize_email(email).lower()
        if "role" not in extra and "role_id" not in extra:
            ensure_roles()
            extra["role"] = Role.objects.get(code=Role.DESIGNER)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        ensure_roles()
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("can_manage_users", True)
        extra.setdefault("can_manage_clients", True)
        extra.setdefault("full_name", "Администратор системы")
        if "role" not in extra and "role_id" not in extra:
            extra["role"] = Role.objects.get(code=Role.DIRECTOR)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    STATUS_ACTIVE = "active"
    STATUS_BLOCKED = "blocked"
    STATUS_DEACTIVATED = "deactivated"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Активна"),
        (STATUS_BLOCKED, "Заблокирована"),
        (STATUS_DEACTIVATED, "Деактивирована"),
    ]

    email = models.EmailField("Рабочая электронная почта", max_length=150, unique=True)
    full_name = models.CharField("ФИО", max_length=150)
    role = models.ForeignKey(Role, verbose_name="Роль", on_delete=models.PROTECT, related_name="users")
    department = models.CharField("Подразделение", max_length=120, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    status = models.CharField("Статус учётной записи", max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_active = models.BooleanField("Активна", default=True)
    is_staff = models.BooleanField("Доступ в админ-панель", default=False)
    can_manage_users = models.BooleanField("Право вести учётные записи", default=False)
    can_manage_clients = models.BooleanField("Право вести справочник клиентов", default=False)
    must_change_password = models.BooleanField("Требуется смена пароля", default=False)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField("Тестовая запись", default=False)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        ordering = ["full_name"]
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        self.is_active = self.status == self.STATUS_ACTIVE
        super().save(*args, **kwargs)

    def __str__(self):
        return self.short_name

    # --- удобные свойства для шаблонов ---
    @property
    def short_name(self):
        """«Соколов Олег Викторович» → «Соколов О. В.»"""
        parts = (self.full_name or "").split()
        if len(parts) >= 3:
            return f"{parts[0]} {parts[1][0]}. {parts[2][0]}."
        if len(parts) == 2:
            return f"{parts[0]} {parts[1][0]}."
        return self.full_name or self.email

    @property
    def initials(self):
        parts = (self.full_name or "?").split()
        if len(parts) >= 2:
            return (parts[1][0] + parts[0][0]).upper()
        return parts[0][:2].upper()

    @property
    def role_code(self):
        return self.role.code if self.role_id else ""

    @property
    def is_director(self):
        return self.role_code == Role.DIRECTOR

    @property
    def is_gip(self):
        return self.role_code == Role.GIP

    @property
    def is_expert(self):
        return self.role_code == Role.EXPERT

    @property
    def is_approval_manager(self):
        return self.role_code == Role.APPROVAL

    @property
    def is_executor_role(self):
        return self.role_code in Role.EXECUTOR_ROLES

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.short_name


# ---------------------------------------------------------------------------
# Клиенты
# ---------------------------------------------------------------------------
class Client(models.Model):
    TYPE_CHOICES = [("org", "Организация"), ("person", "Физическое лицо")]
    STATUS_CHOICES = [("active", "Активный"), ("archived", "Архивный")]

    name = models.CharField("Название организации или ФИО", max_length=200)
    client_type = models.CharField("Тип клиента", max_length=10, choices=TYPE_CHOICES, default="org")
    inn = models.CharField("ИНН / идентификатор", max_length=20, blank=True)
    contact_person = models.CharField("Контактное лицо", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Электронная почта", max_length=150, blank=True)
    address = models.CharField("Адрес", max_length=255, blank=True)
    note = models.TextField("Примечание", blank=True)
    source = models.CharField("Источник сведений", max_length=255, blank=True)
    status = models.CharField("Статус", max_length=10, choices=STATUS_CHOICES, default="active")
    is_demo = models.BooleanField("Тестовая запись", default=False)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField("Дата внесения", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)

    class Meta:
        db_table = "clients"
        ordering = ["name"]
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Проекты, этапы, зависимости, задачи
# ---------------------------------------------------------------------------
class Project(models.Model):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    APPROVAL = "approval"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    STATUS_CHOICES = [
        (DRAFT, "Черновик"),
        (IN_PROGRESS, "В работе"),
        (APPROVAL, "На согласовании"),
        (COMPLETED, "Завершён"),
        (ARCHIVED, "В архиве"),
    ]
    ACTIVE_STATUSES = (DRAFT, IN_PROGRESS, APPROVAL)

    number = models.CharField("Номер", max_length=30, unique=True)
    name = models.CharField("Название проекта", max_length=200)
    client = models.ForeignKey(Client, verbose_name="Заказчик", on_delete=models.PROTECT, related_name="projects")
    gip = models.ForeignKey(User, verbose_name="ГИП", on_delete=models.PROTECT, related_name="gip_projects")
    approval_manager = models.ForeignKey(
        User, verbose_name="Менеджер по согласованию", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="approval_projects",
    )
    object_address = models.CharField("Адрес / объект", max_length=255, blank=True)
    description = models.TextField("Описание (цель, состав работ, особые условия)", blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    start_date = models.DateField("Дата начала")
    planned_end_date = models.DateField("Плановая дата окончания")
    actual_end_date = models.DateField("Фактическое окончание", null=True, blank=True)
    is_demo = models.BooleanField("Тестовая запись", default=False)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects"
        ordering = ["-created_at"]
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"

    def __str__(self):
        return f"{self.name} ({self.number})"

    @classmethod
    def next_number(cls):
        year = date.today().year
        seq = cls.objects.filter(number__startswith=f"ПБ-{year}-").count() + 1
        while True:
            number = f"ПБ-{year}-{seq:03d}"
            if not cls.objects.filter(number=number).exists():
                return number
            seq += 1

    # --- расчётные показатели ---
    def stage_counts(self):
        counts = {"total": 0, "accepted": 0, "on_review": 0, "rework": 0, "blocked": 0, "in_progress": 0}
        for st in self.stages.all():
            counts["total"] += 1
            if st.status in counts:
                counts[st.status] += 1
        return counts

    @property
    def progress(self):
        c = self.stage_counts()
        return round(c["accepted"] * 100 / c["total"]) if c["total"] else 0

    @property
    def nearest_deadline(self):
        dates = [s.deadline for s in self.stages.all() if s.deadline and s.status != Stage.ACCEPTED]
        return min(dates) if dates else None

    @property
    def overdue_stages(self):
        today = date.today()
        return [s for s in self.stages.all() if s.deadline and s.deadline < today and s.status != Stage.ACCEPTED]

    @property
    def is_overdue(self):
        if self.status in (self.COMPLETED, self.ARCHIVED):
            return False
        return bool(self.overdue_stages) or self.planned_end_date < date.today()


class Stage(models.Model):
    NOT_STARTED = "not_started"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    ON_REVIEW = "on_review"
    REWORK = "rework"
    ACCEPTED = "accepted"
    STATUS_CHOICES = [
        (NOT_STARTED, "Не начат"),
        (BLOCKED, "Заблокирован"),
        (IN_PROGRESS, "В работе"),
        (ON_REVIEW, "Ожидает проверки"),
        (REWORK, "На доработке"),
        (ACCEPTED, "Принят"),
    ]
    ACTIVE = (NOT_STARTED, BLOCKED, IN_PROGRESS, ON_REVIEW, REWORK)

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="stages")
    sequence_no = models.PositiveIntegerField("Порядковый номер")
    name = models.CharField("Название этапа", max_length=150)
    description = models.TextField("Описание", blank=True)
    expected_result = models.CharField("Ожидаемый результат", max_length=255, blank=True)
    executor_role = models.ForeignKey(
        Role, verbose_name="Роль исполнителя", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    executor = models.ForeignKey(
        User, verbose_name="Исполнитель", null=True, blank=True, on_delete=models.PROTECT, related_name="executed_stages"
    )
    reviewer = models.ForeignKey(
        User, verbose_name="Проверяющий", null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_stages"
    )
    start_date = models.DateField("Плановое начало", null=True, blank=True)
    deadline = models.DateField("Плановое завершение (срок)", null=True, blank=True)
    actual_start = models.DateField("Фактическое начало", null=True, blank=True)
    actual_end = models.DateField("Фактическое завершение", null=True, blank=True)
    labor_hours = models.PositiveIntegerField("Плановая трудоёмкость, ч", null=True, blank=True)
    file_required = models.BooleanField("Обязательна загрузка файла", default=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=NOT_STARTED)
    submitted_at = models.DateTimeField("Передан на проверку", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stages"
        ordering = ["project_id", "sequence_no"]
        unique_together = [("project", "sequence_no")]
        verbose_name = "Этап"
        verbose_name_plural = "Этапы"

    def __str__(self):
        return f"Этап {self.sequence_no}: {self.name}"

    def prerequisites(self):
        return Stage.objects.filter(dependent_links__stage=self).order_by("sequence_no")

    def dependents(self):
        return Stage.objects.filter(dependency_links__depends_on=self).order_by("sequence_no")

    def unmet_prerequisites(self):
        return [s for s in self.prerequisites() if s.status != Stage.ACCEPTED]

    @property
    def days_left(self):
        if not self.deadline:
            return None
        return (self.deadline - date.today()).days

    @property
    def is_overdue(self):
        return self.status != self.ACCEPTED and self.deadline is not None and self.deadline < date.today()

    @property
    def block_reason(self):
        unmet = self.unmet_prerequisites()
        if not unmet:
            return ""
        nums = ", ".join(str(s.sequence_no) for s in unmet)
        word = "этапа" if len(unmet) == 1 else "этапов"
        return f"Ждёт принятия {word} {nums}"


class StageDependency(models.Model):
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="dependency_links")
    depends_on = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="dependent_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stage_dependencies"
        unique_together = [("stage", "depends_on")]
        verbose_name = "Зависимость этапов"
        verbose_name_plural = "Зависимости этапов"


class Task(models.Model):
    STATUS_CHOICES = [("todo", "Назначена"), ("in_progress", "В работе"), ("done", "Выполнена")]
    PRIORITY_CHOICES = [("low", "Низкий"), ("normal", "Обычный"), ("high", "Высокий")]

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField("Название задачи", max_length=200)
    description = models.TextField("Описание работы", blank=True)
    executor = models.ForeignKey(
        User, verbose_name="Исполнитель", null=True, blank=True, on_delete=models.PROTECT, related_name="tasks"
    )
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default="todo")
    priority = models.CharField("Приоритет", max_length=10, choices=PRIORITY_CHOICES, default="normal")
    deadline = models.DateField("Срок", null=True, blank=True)
    labor_hours = models.PositiveIntegerField("Трудоёмкость, ч", null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tasks"
        ordering = ["deadline", "id"]
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        return self.status != "done" and self.deadline is not None and self.deadline < date.today()


class Assignment(models.Model):
    ROLE_CHOICES = [("executor", "Исполнитель"), ("reviewer", "Проверяющий")]

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="assignments")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="assignments")
    previous_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    role_in_task = models.CharField(max_length=20, choices=ROLE_CHOICES)
    assigned_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.TextField("Причина (при перегрузке / переназначении)", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assignments"
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# Документы и версии
# ---------------------------------------------------------------------------
def version_upload_to(instance, filename):
    """Безопасное имя файла на диске; исходное имя хранится в original_name."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    project_id = instance.document.project_id
    return f"projects/{project_id}/{uuid.uuid4().hex}.{ext}"


class Document(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents")
    stage = models.ForeignKey(Stage, null=True, blank=True, on_delete=models.CASCADE, related_name="documents")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    doc_type = models.CharField("Тип документа", max_length=20, choices=DOC_TYPES, default="other")
    title = models.CharField("Название документа", max_length=255)
    current_version_no = models.PositiveIntegerField("Актуальная версия", default=0)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_documents")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "documents"
        ordering = ["-updated_at"]
        verbose_name = "Документ"
        verbose_name_plural = "Документы"

    def __str__(self):
        return self.title

    @property
    def latest_version(self):
        return self.versions.order_by("-version_no").first()


class DocumentVersion(models.Model):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    RETURNED = "returned"
    STATUS_CHOICES = [
        (DRAFT, "Не отправлена"),
        (SUBMITTED, "Ожидает проверки"),
        (ACCEPTED, "Принята"),
        (RETURNED, "Возвращена"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_no = models.PositiveIntegerField("Номер версии")
    file = models.FileField("Файл", upload_to=version_upload_to, max_length=500)
    original_name = models.CharField("Исходное имя файла", max_length=255)
    extension = models.CharField("Формат", max_length=10)
    size = models.BigIntegerField("Размер, байт", default=0)
    comment = models.TextField("Комментарий к версии", blank=True)
    review_status = models.CharField("Статус проверки", max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="uploaded_versions")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "document_versions"
        ordering = ["document_id", "-version_no"]
        unique_together = [("document", "version_no")]
        verbose_name = "Версия документа"
        verbose_name_plural = "Версии документов"

    def __str__(self):
        return f"{self.document.title} — версия {self.version_no}"

    @property
    def size_display(self):
        size = self.size or 0
        if size < 1024:
            return f"{size} Б"
        if size < 1024 * 1024:
            return f"{size / 1024:.0f} КБ"
        return f"{size / 1024 / 1024:.1f} МБ"

    @property
    def is_pdf(self):
        return self.extension == "pdf"


# ---------------------------------------------------------------------------
# Проверки и замечания
# ---------------------------------------------------------------------------
class Review(models.Model):
    DECISION_CHOICES = [
        ("accepted", "Результат принят"),
        ("returned", "Возвращено на доработку"),
        ("cancelled", "Приёмка отменена"),
    ]

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reviews")
    decision = models.CharField("Решение", max_length=20, choices=DECISION_CHOICES)
    comment = models.TextField("Комментарий", blank=True)
    versions = models.ManyToManyField(DocumentVersion, blank=True, related_name="reviews", db_table="review_versions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews"
        ordering = ["-created_at"]
        verbose_name = "Проверка"
        verbose_name_plural = "Проверки"


class Remark(models.Model):
    OPEN = "open"
    REWORK = "rework"
    FIXED = "fixed"
    ACCEPTED = "accepted"
    IRRELEVANT = "irrelevant"
    STATUS_CHOICES = [
        (OPEN, "Открыто"),
        (REWORK, "На доработке"),
        (FIXED, "Исправлено, ожидает проверки"),
        (ACCEPTED, "Принято"),
        (IRRELEVANT, "Неактуально"),
    ]
    UNRESOLVED = (OPEN, REWORK, FIXED)

    AI_CHOICES = [
        ("none", "—"),
        ("candidate", "Кандидат в архив ИИ"),
        ("included", "Включено в архив ИИ"),
        ("rejected", "Не включать"),
    ]
    SOURCE_CHOICES = [("internal", "Внутренняя проверка"), ("external", "Согласующая сторона")]

    number = models.CharField("Номер", max_length=20, unique=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="remarks")
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="remarks")
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.PROTECT, related_name="remarks")
    version = models.ForeignKey(
        DocumentVersion, verbose_name="Версия", null=True, blank=True, on_delete=models.PROTECT, related_name="remarks"
    )
    fixed_in_version = models.ForeignKey(
        DocumentVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="fixed_remarks"
    )
    review = models.ForeignKey(Review, null=True, blank=True, on_delete=models.SET_NULL, related_name="remarks")
    section = models.CharField("Раздел / лист / фрагмент", max_length=150)
    text = models.TextField("Текст замечания")
    category = models.CharField("Категория", max_length=100, blank=True)
    severity = models.CharField("Критичность", max_length=20, choices=SEVERITY_CHOICES, default="significant")
    source = models.CharField("Источник", max_length=10, choices=SOURCE_CHOICES, default="internal")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="authored_remarks")
    assignee = models.ForeignKey(User, on_delete=models.PROTECT, related_name="assigned_remarks")
    due_date = models.DateField("Срок исправления", null=True, blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=OPEN)
    ai_status = models.CharField("Архив ИИ", max_length=20, choices=AI_CHOICES, default="none")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "remarks"
        ordering = ["-created_at"]
        verbose_name = "Замечание"
        verbose_name_plural = "Замечания"

    def __str__(self):
        return self.number

    @classmethod
    def next_number(cls):
        last = cls.objects.order_by("-id").first()
        seq = (last.id + 1) if last else 1
        while True:
            number = f"Р-{seq:03d}"
            if not cls.objects.filter(number=number).exists():
                return number
            seq += 1

    @property
    def is_overdue(self):
        return self.status in self.UNRESOLVED and self.due_date is not None and self.due_date < date.today()


class RemarkHistory(models.Model):
    remark = models.ForeignKey(Remark, on_delete=models.CASCADE, related_name="history")
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "remark_status_history"
        ordering = ["created_at", "id"]

    def status_label(self, code):
        return dict(Remark.STATUS_CHOICES).get(code, code)

    @property
    def old_label(self):
        return self.status_label(self.old_status) if self.old_status else ""

    @property
    def new_label(self):
        return self.status_label(self.new_status)


class RemarkComment(models.Model):
    remark = models.ForeignKey(Remark, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    text = models.TextField("Сообщение")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "remark_comments"
        ordering = ["created_at"]


# ---------------------------------------------------------------------------
# Согласование (менеджер по согласованию)
# ---------------------------------------------------------------------------
class ApprovalPackage(models.Model):
    STATUS_CHOICES = [
        ("preparing", "Готовится"),
        ("sent", "Отправлен"),
        ("remarks", "Получены замечания"),
        ("approved", "Согласован"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="approval_packages")
    title = models.CharField("Название пакета", max_length=200)
    authority = models.CharField("Согласующая организация", max_length=200, default="Надзорный орган (МЧС)")
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default="preparing")
    documents = models.ManyToManyField(Document, blank=True, related_name="packages", db_table="approval_package_documents")
    sent_date = models.DateField("Дата отправки", null=True, blank=True)
    response_date = models.DateField("Дата ответа", null=True, blank=True)
    response_note = models.TextField("Ответ / примечание", blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_packages"
        ordering = ["-updated_at"]
        verbose_name = "Пакет согласования"
        verbose_name_plural = "Пакеты согласования"

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Уведомления и журнал аудита
# ---------------------------------------------------------------------------
class Notification(models.Model):
    TYPE_CHOICES = [
        ("assigned", "Назначение"),
        ("reassigned", "Изменение назначения"),
        ("deadline", "Приближается срок"),
        ("overdue", "Просрочка"),
        ("submitted", "Результат на проверке"),
        ("returned", "Возврат с замечаниями"),
        ("accepted", "Результат принят"),
        ("remark", "Замечание"),
        ("system", "Система"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    event_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="system")
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]


class AuditLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField("Действие", max_length=60)
    object_type = models.CharField("Тип объекта", max_length=60, blank=True)
    object_id = models.IntegerField(null=True, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit")
    description = models.CharField("Описание", max_length=500)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at", "-id"]
        verbose_name = "Запись журнала аудита"
        verbose_name_plural = "Журнал аудита"


# ---------------------------------------------------------------------------
# Архив ИИ
# ---------------------------------------------------------------------------
class AIArchiveEntry(models.Model):
    CANDIDATE = "candidate"
    CHECKED = "checked"
    INCLUDED = "included"
    EXCLUDED = "excluded"
    STATUS_CHOICES = [
        (CANDIDATE, "Кандидат"),
        (CHECKED, "Проверен"),
        (INCLUDED, "Включён в архив ИИ"),
        (EXCLUDED, "Исключён"),
    ]

    remark = models.OneToOneField(Remark, null=True, blank=True, on_delete=models.SET_NULL, related_name="ai_entry")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField("Краткое название", max_length=200)
    text = models.TextField("Текст примера")
    normalized_text = models.TextField("Подготовленный для поиска текст", blank=True)
    category = models.CharField("Категория", max_length=100)
    stage_type = models.CharField("Этап (тип работ)", max_length=150, blank=True)
    doc_type = models.CharField("Тип документа", max_length=20, choices=DOC_TYPES, blank=True)
    resolution = models.TextField("Способ устранения", blank=True)
    source_label = models.CharField("Источник", max_length=255, blank=True)
    record_date = models.DateField("Дата случая", null=True, blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=CANDIDATE)
    checked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    checked_at = models.DateTimeField(null=True, blank=True)
    indexed_at = models.DateTimeField("Включён в индекс", null=True, blank=True)
    is_demo = models.BooleanField("Демонстрационный пример", default=False)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_archive"
        ordering = ["-updated_at"]
        verbose_name = "Запись архива ИИ"
        verbose_name_plural = "Архив ИИ"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        from .ai import normalize

        self.normalized_text = normalize(" ".join(filter(None, [self.title, self.text, self.category, self.stage_type])))
        super().save(*args, **kwargs)


class AIFeedback(models.Model):
    entry = models.ForeignKey(AIArchiveEntry, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    useful = models.BooleanField()
    reason = models.CharField(max_length=255, blank=True)
    query = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_feedback"
        ordering = ["-created_at"]
