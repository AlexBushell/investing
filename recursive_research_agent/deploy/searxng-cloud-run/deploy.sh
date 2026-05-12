#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Deploy SearXNG to Cloud Run via Artifact Registry.

Required flags:
  --repository REPOSITORY
  --service SERVICE
  --searxng-secret SECRET

Optional flags:
  --project PROJECT_ID          Falls back to active gcloud project
  --region REGION              Falls back to active gcloud run/region
  --invoker-member MEMBER        Example: user:you@example.com
  --base-url URL
  --image-name NAME             Default: searxng
  --tag TAG                     Default: latest
  --create-repository           Create Artifact Registry repo if missing

Example:
  ./deploy.sh \
    --project my-project \
    --region us-central1 \
    --repository containers \
    --service searxng \
    --searxng-secret "$(openssl rand -hex 32)" \
    --invoker-member user:you@example.com \
    --create-repository
EOF
}

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Required command not found on PATH: $name" >&2
    exit 1
  fi
}

gcloud_config_value() {
  local key="$1"
  local value
  value="$(gcloud config get-value "$key" 2>/dev/null || true)"
  value="${value//$'\r'/}"
  if [[ -z "${value}" || "${value}" == "(unset)" ]]; then
    return 1
  fi
  printf '%s\n' "${value}"
}

project=""
region=""
repository=""
service=""
searxng_secret=""
invoker_member=""
base_url=""
image_name="searxng"
tag="latest"
create_repository="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      project="$2"
      shift 2
      ;;
    --region)
      region="$2"
      shift 2
      ;;
    --repository)
      repository="$2"
      shift 2
      ;;
    --service)
      service="$2"
      shift 2
      ;;
    --searxng-secret)
      searxng_secret="$2"
      shift 2
      ;;
    --invoker-member)
      invoker_member="$2"
      shift 2
      ;;
    --base-url)
      base_url="$2"
      shift 2
      ;;
    --image-name)
      image_name="$2"
      shift 2
      ;;
    --tag)
      tag="$2"
      shift 2
      ;;
    --create-repository)
      create_repository="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${project}" ]]; then
  project="$(gcloud_config_value project || true)"
fi
if [[ -z "${region}" ]]; then
  region="$(gcloud_config_value run/region || true)"
fi

for required in project region repository service searxng_secret; do
  if [[ -z "${!required}" ]]; then
    echo "Missing required flag for $required" >&2
    usage >&2
    exit 1
  fi
done

require_command gcloud
require_command docker

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
registry_host="${region}-docker.pkg.dev"
image_uri="${registry_host}/${project}/${repository}/${image_name}:${tag}"

echo "Configuring Docker authentication for Artifact Registry host ${registry_host}..."
gcloud auth configure-docker "${registry_host}" --quiet >/dev/null

if [[ "${create_repository}" == "true" ]]; then
  echo "Ensuring Artifact Registry repository exists: ${repository}"
  if ! gcloud artifacts repositories describe "${repository}" \
      --location "${region}" \
      --project "${project}" >/dev/null 2>&1; then
    gcloud artifacts repositories create "${repository}" \
      --repository-format docker \
      --location "${region}" \
      --project "${project}" \
      --description "SearXNG Cloud Run images"
  fi
fi

echo "Building image: ${image_uri}"
docker build -t "${image_uri}" "${script_dir}"

echo "Pushing image: ${image_uri}"
docker push "${image_uri}"

env_vars="SEARXNG_SECRET=${searxng_secret}"
if [[ -n "${base_url}" ]]; then
  env_vars="${env_vars},SEARXNG_BASE_URL=${base_url}"
fi

echo "Deploying Cloud Run service: ${service}"
gcloud run deploy "${service}" \
  --image "${image_uri}" \
  --project "${project}" \
  --region "${region}" \
  --platform managed \
  --port 8080 \
  --no-allow-unauthenticated \
  --set-env-vars "${env_vars}"

if [[ -n "${invoker_member}" ]]; then
  echo "Granting Cloud Run Invoker to: ${invoker_member}"
  gcloud run services add-iam-policy-binding "${service}" \
    --project "${project}" \
    --region "${region}" \
    --member "${invoker_member}" \
    --role roles/run.invoker
fi

echo
echo "Deployed image: ${image_uri}"
echo "Cloud Run service: ${service}"
echo "Authentication: required"
if [[ -n "${invoker_member}" ]]; then
  echo "Explicit invoker member: ${invoker_member}"
else
  echo "No explicit invoker member was granted by this script."
  echo "Grant roles/run.invoker to your user if needed."
fi
