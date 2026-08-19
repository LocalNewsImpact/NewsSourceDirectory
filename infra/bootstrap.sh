#!/usr/bin/env bash
#
# Bootstrap the GCP project for the News Source Directory.
#
# Every stage is idempotent: it checks for the resource before creating it, so
# rerunning is safe and the script doubles as the description of what exists.
#
#   ./infra/bootstrap.sh            # everything except the database
#   ./infra/bootstrap.sh sql        # the one stage that starts real billing
#   ./infra/bootstrap.sh apis iam   # named stages, in order
#
# Requires an account with resourcemanager.projectCreator and billing.user on
# the org. See infra/README.md.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-lnic-source-directory}"
PROJECT_NAME="LNIC Source Directory"
ORG_ID="${ORG_ID:-293319414046}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-011142-05FA4C-0FCA10}"
REGION="${REGION:-us-central1}"

BUCKET="${BUCKET:-${PROJECT_ID}-feed}"
UPLOADS="${UPLOADS:-${PROJECT_ID}-uploads}"
SQL_INSTANCE="${SQL_INSTANCE:-directory}"
SQL_TIER="${SQL_TIER:-db-custom-1-3840}"
DB_NAME="${DB_NAME:-directory}"
DB_USER="${DB_USER:-directory}"
REPO="${REPO:-app}"

# Who may reach the admin through IAP. A Workspace group, so membership is
# managed in the admin console rather than in IAM.
EDITORS="${EDITORS:-group:lnic-directory-editors@localnewsimpact.org}"

# The GitHub repository allowed to deploy, via Workload Identity Federation.
GITHUB_REPO="${GITHUB_REPO:-LocalNewsImpact/NewsSourceDirectory}"

# The WordPress origin allowed to fetch the feed.
WEB_ORIGIN="${WEB_ORIGIN:-https://www.localnewsimpact.org}"

# Hostname for the Django admin. DNS is Route 53; a record for this exact name
# overrides the existing *.localnewsimpact.org wildcard.
ADMIN_HOST="${ADMIN_HOST:-directory.localnewsimpact.org}"
LB_IP_NAME="${LB_IP_NAME:-directory-admin-ip}"
SERVICE="${SERVICE:-directory-admin}"

RUN_SA="directory-run@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOY_SA="github-deploy@${PROJECT_ID}.iam.gserviceaccount.com"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
have() { gcloud "$@" >/dev/null 2>&1; }
gc() { gcloud --project="$PROJECT_ID" "$@"; }

# --------------------------------------------------------------------------

stage_project() {
  say "project ${PROJECT_ID}"
  if have projects describe "$PROJECT_ID"; then
    echo "  exists"
  else
    gcloud projects create "$PROJECT_ID" \
      --organization="$ORG_ID" --name="$PROJECT_NAME"
  fi

  local linked
  linked="$(gcloud billing projects describe "$PROJECT_ID" \
    --format='value(billingEnabled)' 2>/dev/null || echo False)"
  if [[ "$linked" == "True" ]]; then
    echo "  billing already linked"
  else
    gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
  fi
}

stage_apis() {
  say "APIs"
  gc services enable \
    run.googleapis.com \
    sqladmin.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    iap.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com \
    cloudscheduler.googleapis.com \
    iamcredentials.googleapis.com \
    compute.googleapis.com
}

stage_iam() {
  say "service accounts"
  for pair in "directory-run:Cloud Run runtime" "github-deploy:GitHub Actions deployer"; do
    local id="${pair%%:*}" desc="${pair#*:}"
    if have iam service-accounts describe "${id}@${PROJECT_ID}.iam.gserviceaccount.com" \
        --project="$PROJECT_ID"; then
      echo "  ${id} exists"
    else
      gc iam service-accounts create "$id" --display-name="$desc"
    fi
  done

  # Runtime: reach the database and publish the feed. Nothing else.
  for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
    gc projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${RUN_SA}" --role="$role" --condition=None >/dev/null
  done

  # Deployer: ship images and revisions, act as the runtime SA. No data access.
  for role in roles/run.developer roles/artifactregistry.writer roles/iam.serviceAccountUser; do
    gc projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${DEPLOY_SA}" --role="$role" --condition=None >/dev/null
  done
  echo "  roles bound"
}

stage_storage() {
  # Two buckets, not one bucket with a public prefix. GCP rejects IAM conditions
  # on a binding to allUsers ("Conditions are not allowed on public resources"),
  # so a prefix cannot be a security boundary. Isolation is therefore by bucket:
  # everything in the feed bucket is public by construction, and nothing private
  # can be exposed there by mistake.
  say "buckets"

  if have storage buckets describe "gs://${BUCKET}"; then
    echo "  gs://${BUCKET} exists"
  else
    gc storage buckets create "gs://${BUCKET}" \
      --location="$REGION" --uniform-bucket-level-access
  fi

  # legacyObjectReader, not objectViewer: it grants get without list, so the
  # bucket cannot be enumerated. Readers reach files by the names the manifest
  # gives them, which is all the widget and the crawler ever need.
  # Domain Restricted Sharing is enforced org-wide and refuses allUsers, so this
  # needs a project-level exception on constraints/iam.allowedPolicyMemberDomains.
  # Left non-fatal: everything else in the project is usable without it, and the
  # exception is a deliberate decision about the org's posture, not a detail.
  if gc storage buckets add-iam-policy-binding "gs://${BUCKET}" \
      --member=allUsers --role=roles/storage.legacyObjectReader >/dev/null 2>&1; then
    echo "  public read (no listing)"
  else
    echo "  NOT public: blocked by Domain Restricted Sharing."
    echo "     see infra/README.md — needs a project-level org policy exception"
  fi

  gc storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${RUN_SA}" --role=roles/storage.objectAdmin \
    --condition=None >/dev/null
  echo "  runtime can publish"

  local cors; cors="$(mktemp)"
  cat > "$cors" <<JSON
[{"origin":["${WEB_ORIGIN}","https://localnewsimpact.org"],
  "method":["GET","HEAD"],
  "responseHeader":["Content-Type"],
  "maxAgeSeconds":3600}]
JSON
  gc storage buckets update "gs://${BUCKET}" --cors-file="$cors"
  rm -f "$cors"
  echo "  CORS set for ${WEB_ORIGIN}"

  # Private, for source spreadsheets handed to import_source. Never public.
  if have storage buckets describe "gs://${UPLOADS}"; then
    echo "  gs://${UPLOADS} exists"
  else
    gc storage buckets create "gs://${UPLOADS}" \
      --location="$REGION" --uniform-bucket-level-access
    gc storage buckets update "gs://${UPLOADS}" --versioning
  fi
  gc storage buckets add-iam-policy-binding "gs://${UPLOADS}" \
    --member="serviceAccount:${RUN_SA}" --role=roles/storage.objectAdmin \
    --condition=None >/dev/null
  echo "  gs://${UPLOADS} private, versioned, runtime can read"
}

stage_registry() {
  say "artifact registry"
  if have artifacts repositories describe "$REPO" \
      --location="$REGION" --project="$PROJECT_ID"; then
    echo "  exists"
  else
    gc artifacts repositories create "$REPO" \
      --repository-format=docker --location="$REGION" \
      --description="Directory admin images"
  fi
}

stage_wif() {
  say "workload identity federation for ${GITHUB_REPO}"
  local pool=github provider=github
  if have iam workload-identity-pools describe "$pool" \
      --location=global --project="$PROJECT_ID"; then
    echo "  pool exists"
  else
    gc iam workload-identity-pools create "$pool" \
      --location=global --display-name="GitHub Actions"
  fi

  if have iam workload-identity-pools providers describe "$provider" \
      --workload-identity-pool="$pool" --location=global --project="$PROJECT_ID"; then
    echo "  provider exists"
  else
    gc iam workload-identity-pools providers create-oidc "$provider" \
      --location=global --workload-identity-pool="$pool" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
      --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
  fi

  local num; num="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  gc iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
    --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/projects/${num}/locations/global/workloadIdentityPools/${pool}/attribute.repository/${GITHUB_REPO}" \
    >/dev/null
  echo "  repo may impersonate ${DEPLOY_SA}"
  echo
  echo "  GitHub Actions needs:"
  echo "    workload_identity_provider: projects/${num}/locations/global/workloadIdentityPools/${pool}/providers/${provider}"
  echo "    service_account: ${DEPLOY_SA}"
}

stage_secrets() {
  say "secrets"
  for name in django-secret-key db-password; do
    if have secrets describe "$name" --project="$PROJECT_ID"; then
      echo "  ${name} exists"
    else
      python3 -c "import secrets;print(secrets.token_urlsafe(48),end='')" \
        | gc secrets create "$name" --data-file=- --replication-policy=automatic
      echo "  ${name} created"
    fi
  done
}

# The only stage that starts meaningful billing: roughly $50/month.
stage_sql() {
  say "cloud sql ${SQL_INSTANCE} (${SQL_TIER})"
  if have sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID"; then
    echo "  exists"
  else
    gc sql instances create "$SQL_INSTANCE" \
      --database-version=POSTGRES_16 \
      --edition=enterprise \
      --tier="$SQL_TIER" \
      --region="$REGION" \
      --storage-size=10GB --storage-type=SSD --storage-auto-increase \
      --backup --backup-start-time=08:00 \
      --enable-point-in-time-recovery \
      --retained-backups-count=14 \
      --maintenance-window-day=SUN --maintenance-window-hour=9
  fi

  have sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" --project="$PROJECT_ID" \
    || gc sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"

  if ! gc sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
    gc secrets versions access latest --secret=db-password \
      | gc sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$(cat)"
    echo "  user ${DB_USER} created"
  fi
}

# Reserve the address early: the DNS record can then be created and propagate
# while the rest is built, and a Google-managed certificate will not issue until
# the hostname already resolves to this address.
stage_lb_ip() {
  say "static address for ${ADMIN_HOST}"
  if have compute addresses describe "$LB_IP_NAME" --global --project="$PROJECT_ID"; then
    echo "  exists"
  else
    gc compute addresses create "$LB_IP_NAME" --global --ip-version=IPV4
  fi
  local ip; ip="$(gc compute addresses describe "$LB_IP_NAME" --global --format='value(address)')"
  echo
  echo "  Route 53 record to create in localnewsimpact.org:"
  echo "    ${ADMIN_HOST}.   A   ${ip}"
  echo "  (a record for this exact name beats the *.localnewsimpact.org wildcard)"
}

# Everything from here needs the Cloud Run service to exist, so run this after
# the first deploy. A custom hostname with IAP requires a load balancer: IAP on
# the bare Cloud Run URL cannot serve directory.localnewsimpact.org.
stage_lb() {
  say "load balancer for ${ADMIN_HOST}"
  if ! have run services describe "$SERVICE" --region="$REGION" --project="$PROJECT_ID"; then
    echo "  Cloud Run service '${SERVICE}' does not exist yet — deploy first, then rerun."
    return 1
  fi

  have compute network-endpoint-groups describe "${SERVICE}-neg" \
      --region="$REGION" --project="$PROJECT_ID" \
    || gc compute network-endpoint-groups create "${SERVICE}-neg" \
         --region="$REGION" --network-endpoint-type=serverless --cloud-run-service="$SERVICE"

  if ! have compute backend-services describe "${SERVICE}-backend" --global --project="$PROJECT_ID"; then
    gc compute backend-services create "${SERVICE}-backend" \
      --global --load-balancing-scheme=EXTERNAL_MANAGED
    gc compute backend-services add-backend "${SERVICE}-backend" \
      --global --network-endpoint-group="${SERVICE}-neg" \
      --network-endpoint-group-region="$REGION"
  fi

  have compute url-maps describe "${SERVICE}-map" --global --project="$PROJECT_ID" \
    || gc compute url-maps create "${SERVICE}-map" --default-service="${SERVICE}-backend"

  have compute ssl-certificates describe "${SERVICE}-cert" --global --project="$PROJECT_ID" \
    || gc compute ssl-certificates create "${SERVICE}-cert" --domains="$ADMIN_HOST" --global

  have compute target-https-proxies describe "${SERVICE}-proxy" --global --project="$PROJECT_ID" \
    || gc compute target-https-proxies create "${SERVICE}-proxy" \
         --url-map="${SERVICE}-map" --ssl-certificates="${SERVICE}-cert" --global

  have compute forwarding-rules describe "${SERVICE}-fr" --global --project="$PROJECT_ID" \
    || gc compute forwarding-rules create "${SERVICE}-fr" \
         --global --target-https-proxy="${SERVICE}-proxy" \
         --address="$LB_IP_NAME" --ports=443 \
         --load-balancing-scheme=EXTERNAL_MANAGED

  echo
  echo "  Certificate provisioning takes 15-60 minutes once DNS resolves. Watch with:"
  echo "    gcloud compute ssl-certificates describe ${SERVICE}-cert --global \\"
  echo "      --project=${PROJECT_ID} --format='value(managed.status)'"
  echo
  echo "  Then lock the back door — without this the run.app URL bypasses IAP:"
  echo "    gcloud run services update ${SERVICE} --region=${REGION} \\"
  echo "      --project=${PROJECT_ID} --ingress=internal-and-cloud-load-balancing"
  echo
  echo "  And enable IAP on the backend service, granting ${EDITORS}."
}

STAGES=(project apis iam storage registry wif secrets lb_ip)

main() {
  local requested=("$@")
  [[ ${#requested[@]} -eq 0 ]] && requested=("${STAGES[@]}")
  [[ "${requested[0]:-}" == "all" ]] && requested=("${STAGES[@]}" sql lb)

  for s in "${requested[@]}"; do
    "stage_${s}"
  done

  say "done"
  echo "  project ${PROJECT_ID}  region ${REGION}"
  echo "  feed    https://storage.googleapis.com/${BUCKET}/feed/manifest.json"
  if [[ ! " ${requested[*]} " =~ " sql " ]]; then
    echo
    echo "  Cloud SQL not created. It is ~\$50/month; run './infra/bootstrap.sh sql' when ready."
  fi
}

main "$@"
