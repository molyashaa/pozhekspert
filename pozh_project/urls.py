from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "ПожЭксперт+ — администрирование"
admin.site.site_title = "ПожЭксперт+"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

handler403 = "core.views.errors.error_403"
handler404 = "core.views.errors.error_404"
handler500 = "core.views.errors.error_500"
