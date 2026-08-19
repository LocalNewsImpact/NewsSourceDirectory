# One image, two services. The admin and the researcher portal differ by
# SERVICE_ROLE — which selects the URLconf — and by the database role they
# connect as. See docs/auth.md.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools for psycopg and friends, removed in the same layer so they leave
# nothing behind in the image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y

COPY manage.py ./
COPY config/ ./config/
COPY directory/ ./directory/
COPY checks/ ./checks/
COPY feed/ ./feed/

# Static files are baked in and served by WhiteNoise; without this the admin
# renders unstyled on Cloud Run. A placeholder key is enough to import settings.
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgres://u:p@localhost/db \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8080

# One worker because Cloud Run bills per instance and handles concurrency
# itself; threads because admin requests wait on the database; --timeout 0
# because Cloud Run enforces its own deadline and a second one only produces
# confusing 502s.
CMD exec gunicorn config.wsgi:application \
    --bind :${PORT:-8080} \
    --workers 1 \
    --threads 8 \
    --timeout 0 \
    --access-logfile - \
    --error-logfile -
