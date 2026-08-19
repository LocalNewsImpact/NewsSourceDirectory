"""Admin front end. Serves sources.localnewsimpact.org."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from directory.views import healthz

admin.site.site_header = "News Source Directory"
admin.site.site_title = "News Source Directory"
admin.site.index_title = "Registry"

urlpatterns = [
    path("_health", healthz, name="healthz"),
    path("accounts/", include("allauth.urls")),
]

# Django's admin login form has no Google button — that lives on allauth's page.
# Left alone, /admin/login/ is a password box with no valid password behind it,
# which is exactly where the first person to try this ended up.
#
# The escape hatch is deliberate: blank the google-oauth-client-id secret and
# redeploy, and the ordinary form comes back. Nobody can be locked out by a
# broken OAuth client.
if settings.GOOGLE_SIGN_IN_CONFIGURED:
    urlpatterns += [
        path(
            "admin/login/",
            RedirectView.as_view(url="/accounts/login/", query_string=True),
        )
    ]

urlpatterns += [
    path("admin/", admin.site.urls),
    # The admin is the whole of this front end, so the root goes there rather
    # than mounting admin.site twice, which breaks URL reversing.
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
]
