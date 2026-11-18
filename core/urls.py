from django.urls import path

from .views import ai_views, auth, dashboard, documents, misc, people, projects, remarks, stages

urlpatterns = [
    # вход и профиль
    path("login/", auth.login_view, name="login"),
    path("login/help/", auth.login_help, name="login_help"),
    path("logout/", auth.logout_view, name="logout"),
    path("profile/", auth.profile, name="profile"),
    # главная
    path("", dashboard.home, name="home"),
    # проекты
    path("projects/", projects.project_list, name="projects"),
    path("projects/new/", projects.project_create, name="project_create"),
    path("projects/<int:pk>/", projects.project_detail, name="project_detail"),
    path("projects/<int:pk>/edit/", projects.project_edit, name="project_edit"),
    path("projects/<int:pk>/status/", projects.project_status, name="project_status"),
    path("projects/<int:pk>/stages/new/", stages.stage_create, name="stage_create"),
    # этапы, задачи, проверки
    path("stages/<int:pk>/", stages.stage_detail, name="stage_detail"),
    path("stages/<int:pk>/edit/", stages.stage_edit, name="stage_edit"),
    path("stages/<int:pk>/assign/", stages.stage_assign, name="stage_assign"),
    path("stages/<int:pk>/deadline/", stages.stage_deadline, name="stage_deadline"),
    path("stages/<int:pk>/submit/", stages.stage_submit, name="stage_submit"),
    path("stages/<int:pk>/review/", stages.review_detail, name="review_detail"),
    path("stages/<int:pk>/accept/", stages.stage_accept, name="stage_accept"),
    path("stages/<int:pk>/return/", stages.stage_return, name="stage_return"),
    path("stages/<int:pk>/cancel/", stages.stage_cancel, name="stage_cancel"),
    path("stages/<int:pk>/tasks/new/", stages.task_create, name="task_create"),
    path("stages/<int:pk>/hint/", ai_views.stage_hint, name="stage_hint"),
    path("tasks/", stages.task_list, name="tasks"),
    path("tasks/<int:pk>/status/", stages.task_status, name="task_status"),
    path("reviews/", dashboard.expert_dashboard, name="reviews"),
    # замечания
    path("remarks/", remarks.remark_list, name="remarks"),
    path("remarks/external/", remarks.remark_external, name="remark_external"),
    path("remarks/<int:pk>/", remarks.remark_detail, name="remark_detail"),
    path("remarks/<int:pk>/action/", remarks.remark_action, name="remark_action"),
    path("remarks/<int:pk>/review/", stages.remark_review, name="remark_review"),
    path("remarks/<int:pk>/comment/", remarks.remark_comment, name="remark_comment"),
    # документы
    path("documents/", documents.document_list, name="documents"),
    path("documents/upload/", documents.document_upload, name="document_upload"),
    path("documents/<int:pk>/", documents.document_detail, name="document_detail"),
    path("documents/<int:pk>/version/", documents.document_new_version, name="document_new_version"),
    path("files/<int:pk>/", documents.version_download, name="version_download"),
    # клиенты и сотрудники
    path("clients/", people.client_list, name="clients"),
    path("clients/new/", people.client_form, name="client_create"),
    path("clients/<int:pk>/edit/", people.client_form, name="client_edit"),
    path("clients/<int:pk>/archive/", people.client_archive, name="client_archive"),
    path("employees/", people.employee_list, name="employees"),
    path("employees/new/", people.employee_form, name="employee_create"),
    path("employees/<int:pk>/edit/", people.employee_form, name="employee_edit"),
    path("employees/<int:pk>/action/", people.employee_action, name="employee_action"),
    # согласование
    path("approvals/", misc.approval_list, name="approvals"),
    path("approvals/new/", misc.approval_form, name="approval_create"),
    path("approvals/<int:pk>/", misc.approval_form, name="approval_edit"),
    # уведомления, поиск, отчёты, аудит
    path("notifications/", misc.notification_list, name="notifications"),
    path("notifications/<int:pk>/read/", misc.notification_read, name="notification_read"),
    path("notifications/read-all/", misc.notification_read_all, name="notification_read_all"),
    path("search/", misc.search, name="search"),
    path("reports/", misc.reports, name="reports"),
    path("reports/export.csv", misc.reports_export, name="reports_export"),
    path("audit/", misc.audit_log, name="audit"),
    # ИИ-помощник
    path("ai/", ai_views.assistant, name="ai_assistant"),
    path("ai/archive/", ai_views.archive, name="ai_archive"),
    path("ai/archive/new/", ai_views.entry_form, name="ai_entry_create"),
    path("ai/archive/from-remark/<int:remark_pk>/", ai_views.entry_form, name="ai_entry_from_remark"),
    path("ai/archive/reject/<int:remark_pk>/", ai_views.candidate_reject, name="ai_candidate_reject"),
    path("ai/archive/<int:pk>/", ai_views.entry_detail, name="ai_entry"),
    path("ai/archive/<int:pk>/edit/", ai_views.entry_form, name="ai_entry_edit"),
    path("ai/archive/<int:pk>/action/", ai_views.entry_action, name="ai_entry_action"),
    path("ai/feedback/<int:pk>/", ai_views.feedback, name="ai_feedback"),
]
