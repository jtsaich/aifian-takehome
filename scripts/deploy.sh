#!/usr/bin/env bash
# One-command deploy to Cloud Run (asia-east1) with Postgres on Neon.
#
#   GCP_PROJECT=my-project DATABASE_URL='postgresql://...?sslmode=require' scripts/deploy.sh
#
# Steps (each is idempotent, so rerunning is how you redeploy):
#   1. enable the APIs, create the Artifact Registry repo and the runtime service account;
#   2. store secrets in Secret Manager (values come from the environment, never from the repo);
#   3. build the image with Cloud Build (linux/amd64, no local Docker needed);
#   4. run `bakery-init` (Alembic upgrade + seed) as a Cloud Run job and wait for it;
#   5. deploy the service with min-instances 0 and secrets mounted as env vars;
#   6. print the public URL.
#
# Environment:
#   GCP_PROJECT     required. Google Cloud project ID (billing enabled).
#   DATABASE_URL    Neon connection string; must carry sslmode=require (or verify-ca/verify-full).
#                   Required on the first deploy; later deploys reuse the stored secret.
#   SESSION_SECRET  signed-session key. Generated on the first deploy if unset.
#   LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN
#                   Messaging API channel keys for the webhook. Optional: until they are
#                   stored once, the service runs without LINE (the webhook answers 503).
#   PUBLIC_BASE_URL absolute base for links in replies; default is the Cloud Run service URL.
#   REGION          default asia-east1.   SERVICE  default bakery-orders.
#   DRY_RUN=1       print the gcloud commands instead of running them (no secret values printed).
set -euo pipefail

: "${GCP_PROJECT:?set GCP_PROJECT to your Google Cloud project ID}"
REGION="${REGION:-asia-east1}"
SERVICE="${SERVICE:-bakery-orders}"
REPO="${REPO:-bakery}"
INIT_JOB="${SERVICE}-init"
RUNTIME_SA_NAME="${SERVICE}-run"
RUNTIME_SA="${RUNTIME_SA_NAME}@${GCP_PROJECT}.iam.gserviceaccount.com"
DRY_RUN="${DRY_RUN:-}"

# env var name -> Secret Manager secret name.
SECRETS=(
  "DATABASE_URL=bakery-database-url"
  "SESSION_SECRET=bakery-session-secret"
  "LINE_CHANNEL_SECRET=bakery-line-channel-secret"
  "LINE_CHANNEL_ACCESS_TOKEN=bakery-line-channel-access-token"
)
# Secrets the service can start without: skipped while they don't exist and aren't given.
OPTIONAL_SECRETS=" LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN "

cd "$(dirname "$0")/.."

run() {
  if [[ -n "$DRY_RUN" ]]; then
    printf '+ %s\n' "$*"
  else
    "$@"
  fi
}

# True if the resource exists; in a dry run nothing is assumed to exist.
exists() {
  [[ -z "$DRY_RUN" ]] && "$@" >/dev/null 2>&1
}

gc() { run gcloud --project "$GCP_PROJECT" --quiet "$@"; }

if [[ -n "${DATABASE_URL:-}" ]] && ! [[ "$DATABASE_URL" =~ [?\&]sslmode=(require|verify-ca|verify-full)(\&|$) ]]; then
  echo "DATABASE_URL must use TLS: add sslmode=require (Neon's connection string already has it)." >&2
  exit 1
fi

# --- 1. APIs, image repository, runtime identity -----------------------------------------
gc services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com

if ! exists gcloud --project "$GCP_PROJECT" artifacts repositories describe "$REPO" --location "$REGION"; then
  gc artifacts repositories create "$REPO" --location "$REGION" --repository-format docker
fi
# Keep the last 3 images so storage stays inside the 0.5 GB free tier.
gc artifacts repositories set-cleanup-policies "$REPO" --location "$REGION" \
  --policy scripts/artifact-cleanup-policy.json --no-dry-run --format none

if ! exists gcloud --project "$GCP_PROJECT" iam service-accounts describe "$RUNTIME_SA"; then
  gc iam service-accounts create "$RUNTIME_SA_NAME" --display-name "${SERVICE} runtime"
fi

# Projects created since 2024 run Cloud Build as the Compute Engine default service
# account, which needs this role to read the uploaded source, push the image and log.
project_number="PROJECT_NUMBER"
if [[ -z "$DRY_RUN" ]]; then
  project_number="$(gcloud projects describe "$GCP_PROJECT" --format 'value(projectNumber)')"
fi
gc projects add-iam-policy-binding "$GCP_PROJECT" \
  --member "serviceAccount:${project_number}-compute@developer.gserviceaccount.com" \
  --role roles/cloudbuild.builds.builder --condition None --format none

# --- 2. Secrets ---------------------------------------------------------------------------
# A new version is added only when the value changed, so redeploys don't pile up versions.
set_secrets=()
for pair in "${SECRETS[@]}"; do
  var="${pair%%=*}"
  secret="${pair#*=}"
  value="${!var:-}"

  if ! exists gcloud --project "$GCP_PROJECT" secrets describe "$secret"; then
    if [[ -z "$value" && "$var" == "SESSION_SECRET" ]]; then
      value="$(openssl rand -hex 32)"
    fi
    if [[ -z "$value" && "$OPTIONAL_SECRETS" == *" $var "* ]]; then
      continue
    fi
    if [[ -z "$value" ]]; then
      echo "Secret $secret does not exist yet: set $var for the first deploy." >&2
      exit 1
    fi
    gc secrets create "$secret" --replication-policy automatic
  fi

  if [[ -n "$value" ]]; then
    current=""
    if [[ -z "$DRY_RUN" ]]; then
      current="$(gcloud --project "$GCP_PROJECT" secrets versions access latest --secret "$secret" 2>/dev/null || true)"
    fi
    if [[ "$value" != "$current" ]]; then
      printf '%s' "$value" | gc secrets versions add "$secret" --data-file=-
    fi
  fi

  gc secrets add-iam-policy-binding "$secret" \
    --member "serviceAccount:${RUNTIME_SA}" --role roles/secretmanager.secretAccessor --format none
  set_secrets+=("${var}=${secret}:latest")
done
SET_SECRETS="$(IFS=,; echo "${set_secrets[*]}")"

# --- 3. Build -----------------------------------------------------------------------------
tag="$(date -u +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
IMAGE="${REGION}-docker.pkg.dev/${GCP_PROJECT}/${REPO}/${SERVICE}:${tag}"
gc builds submit --tag "$IMAGE" .

# --- 4. Migrate + seed, once per deploy ---------------------------------------------------
gc run jobs deploy "$INIT_JOB" \
  --region "$REGION" \
  --image "$IMAGE" \
  --command bakery-init \
  --service-account "$RUNTIME_SA" \
  --set-secrets "$SET_SECRETS" \
  --set-env-vars BAKERY_ENV=production \
  --max-retries 0 \
  --task-timeout 300s \
  --execute-now --wait

# Cloud Run's service URL is deterministic, so links in LINE replies can be absolute
# from the first deploy on. Override PUBLIC_BASE_URL when using a custom domain.
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://${SERVICE}-${project_number}.${REGION}.run.app}"

# --- 5. Serve -----------------------------------------------------------------------------
# --cpu-throttling (request-based billing): CPU is only allocated while a request is in
# flight, so all work, including LINE webhook processing, must finish before the response.
gc run deploy "$SERVICE" \
  --region "$REGION" \
  --image "$IMAGE" \
  --service-account "$RUNTIME_SA" \
  --set-secrets "$SET_SECRETS" \
  --set-env-vars "BAKERY_ENV=production,PUBLIC_BASE_URL=${PUBLIC_BASE_URL}" \
  --min-instances 0 \
  --max-instances 2 \
  --cpu 1 --memory 512Mi \
  --cpu-throttling \
  --concurrency 20 \
  --timeout 60s \
  --allow-unauthenticated

# --- 6. Done ------------------------------------------------------------------------------
if [[ -z "$DRY_RUN" ]]; then
  url="$(gcloud --project "$GCP_PROJECT" run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
  echo "Deployed: ${url}  (模擬群組上傳: ${url}/demo/upload)"
fi
