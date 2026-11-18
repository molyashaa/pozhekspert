"""Админ-панель Django (для администратора данных; основная работа — в интерфейсе системы)."""
from django.contrib import admin

from . import models


@admin.register(models.User)
class UserAdmin(admin.ModelAdmin):
    """Учётные записи создаются в разделе «Сотрудники»; здесь — просмотр и правка служебных полей."""
    ordering = ("full_name",)
    list_display = ("full_name", "email", "role", "status", "last_login")
    list_filter = ("role", "status")
    search_fields = ("full_name", "email")
    exclude = ("password", "groups", "user_permissions")
    readonly_fields = ("last_login", "created_at", "updated_at", "is_active")


for model in (models.Role, models.Client, models.Project, models.Stage, models.StageDependency, models.Task,
              models.Assignment, models.Document, models.DocumentVersion, models.Review, models.Remark,
              models.RemarkHistory, models.Notification, models.ApprovalPackage, models.AIArchiveEntry,
              models.AIFeedback):
    admin.site.register(model)


@admin.register(models.AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "description")
    list_filter = ("action",)
    search_fields = ("description",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
