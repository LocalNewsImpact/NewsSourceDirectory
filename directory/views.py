from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render


def healthz(request):
    """Liveness plus a database round trip.

    Served at /_health, not /healthz. Google's front end intercepts the exact
    path /healthz on Cloud Run and answers 404 itself — the request never
    reaches the container, and nothing in the logs explains why.

    It must fail when the database is unreachable: a service answering 200 while
    unable to read anything is worse than one that admits it is down, because
    the deploy would go green on a broken revision.
    """
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — report any failure, do not classify
        return JsonResponse({"status": "error", "database": str(exc)}, status=503)
    return JsonResponse({"status": "ok"})


def admin_login_gateway(request):
    """Stand in front of Django's admin login, which has no Google button.

    Three different people arrive here and they need three different answers:

    * Not signed in — send them to the page that can actually sign them in.
    * Signed in without access — say so. Redirecting them to the admin sends
      them straight back here, and Django and allauth will bounce a person
      between the two indefinitely. That loop is what this function exists to
      prevent.
    * Signed in with access — they were probably sent here by a stale
      bookmark; let them through.
    """
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(request.GET.get("next") or "/admin/")
        return render(
            request,
            "account/no_access.html",
            {"email": request.user.email, "domain": settings.ALLOWED_GOOGLE_DOMAIN},
            status=403,
        )

    # settings.LOGIN_URL is the provider handshake when Google is
    # configured and the sign-in page when it is not, so both cases are
    # this one line.
    target = settings.LOGIN_URL
    nxt = request.GET.get("next")
    return redirect(f"{target}?next={nxt}" if nxt else target)


def auth_context(request):
    """Make the permitted domain available to the sign-in templates, so the page
    can say which addresses will work instead of leaving people to guess."""
    return {"allowed_domain": settings.ALLOWED_GOOGLE_DOMAIN}
