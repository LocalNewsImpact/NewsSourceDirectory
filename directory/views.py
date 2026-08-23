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


#: How this console decides who may reach its admin.
#:
#: `is_staff` was the gate, and it cannot express what the suite needs: a
#: person is an editor in one application and a reviewer in another, and
#: one global boolean answers for both. ROADMAP item 1 replaces it with a
#: grant check rather than deriving `is_staff` from one, so the two
#: consoles cannot drift apart.
#:
#: A dotted path in settings rather than an import, because this package
#: installs into Datadesk's image but still has to run and be tested on
#: its own -- `accounts` is not a dependency of this repository. Datadesk
#: points this at its grant check; standalone it falls back to `is_staff`,
#: which is the right answer when there is no grant model to ask.
ADMIN_GATE_SETTING = "DIRECTORY_ADMIN_GATE"


def may_reach_admin(user):
    """Whether this person may reach the admin of this console."""
    from django.utils.module_loading import import_string

    path = getattr(settings, ADMIN_GATE_SETTING, "")
    if not path:
        return user.is_staff
    return import_string(path)(user)


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
        if may_reach_admin(request.user):
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
