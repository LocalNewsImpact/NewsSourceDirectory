"""Researcher portal front end.

Deliberately does not route the admin. Running it as a separate service means
the admin URLs do not exist here at all, rather than existing and returning 403.

The portal itself is not built yet — see docs/auth.md.
"""

from django.urls import include, path

from directory.views import healthz

urlpatterns = [
    path("_health", healthz, name="healthz"),
    path("accounts/", include("allauth.urls")),
]
