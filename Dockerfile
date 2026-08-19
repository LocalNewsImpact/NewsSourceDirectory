# The application layer: nothing but our own code on top of the dependency image.
#
# BASE_IMAGE is supplied by the deploy, pinned to a hash of requirements.txt, so
# a deploy that changes only application code builds in seconds and pushes a few
# megabytes rather than reinstalling every library.

ARG BASE_IMAGE=sources-admin-base:local
FROM ${BASE_IMAGE}

WORKDIR /app

COPY manage.py ./
COPY config/ ./config/
COPY directory/ ./directory/
COPY checks/ ./checks/
COPY feed/ ./feed/
COPY templates/ ./templates/

# Static files are baked in and served by WhiteNoise; without this the admin
# renders unstyled on Cloud Run.
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgres://u:p@localhost/db \
    python manage.py collectstatic --noinput \
 && chown -R app:app /app

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
