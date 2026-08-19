"""Admin front end. Serves sources.localnewsimpact.org."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from directory.views import healthz

admin.site.site_header = "News Source Directory"
admin.site.site_title = "News Source Directory"
admin.site.index_title = "Registry"

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
    # The admin is the whole of this front end, so the root goes there rather
    # than mounting admin.site twice, which breaks URL reversing.
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
]
