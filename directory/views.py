from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Liveness plus a database round trip.

    The deploy smoke test hits this, so it must fail when the database is
    unreachable — a service that answers 200 while unable to read anything is
    worse than one that admits it is down.
    """
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — report any failure, do not classify
        return JsonResponse({"status": "error", "database": str(exc)}, status=503)
    return JsonResponse({"status": "ok"})
