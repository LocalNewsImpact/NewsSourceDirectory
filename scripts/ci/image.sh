#!/usr/bin/env bash
# Both image stages build, and the container answers honestly with no database.
#
# Lifted verbatim from .github/workflows/ci.yml, where it could only ever
# run on a runner. CI now calls `make image`, so this is the same
# check in both places -- which is the whole point of the suite's shared
# pattern (lnic-contracts docs/shared-ci.md).
#
# The ::error:: lines are GitHub annotations. They are harmless echoes
# locally and worth keeping so a failure points at the same place.
set -euo pipefail

# The caller chooses the interpreter: `make` passes the venv's, so a
# local run uses the same dependencies CI installed.
PYTHON="${PYTHON:-python}"

# --- Build the deployment image ----------------------------------
# Both stages, so a change to either is checked before it can merge.
docker build -f Dockerfile.base -t nsd-base:ci .
docker build --build-arg BASE_IMAGE=nsd-base:ci -t news-source-directory .
echo "base: $(docker images nsd-base:ci --format '{{.Size}}')"
echo "app : $(docker images news-source-directory --format '{{.Size}}')"

# --- It starts and answers, without a database -------------------
docker run -d --name smoke -p 8080:8080 \
  -e DJANGO_SECRET_KEY=ci -e DJANGO_ALLOWED_HOSTS='*' \
  -e DATABASE_URL='postgres://nobody:nobody@127.0.0.1:1/none' \
  news-source-directory
for _ in $(seq 1 20); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/_health || true)"
  [ -n "$code" ] && [ "$code" != "000" ] && break
  sleep 2
done
echo "_health -> $code"
docker logs smoke | tail -20
# 503 is the correct answer with no database: the service is up and
# honest about being unable to serve. 200 here would mean the health
# check is not actually checking anything.
[ "$code" = "503" ] || { echo "::error::expected 503, got $code"; exit 1; }
docker rm -f smoke
