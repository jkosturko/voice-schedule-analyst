#!/bin/bash
# Deploy Voice Schedule Analyst to Google Cloud Run
#
# Prerequisites:
#   1. gcloud CLI installed and authenticated (gcloud auth login)
#   2. A GCP project with billing enabled
#   3. GOOGLE_API_KEY set (for Gemini API calls)
#   4. For Calendar access: a service account with domain-wide delegation,
#      or use GOOGLE_SERVICE_ACCOUNT_JSON env var with the JSON key contents
#
# Usage:
#   ./scripts/deploy.sh PROJECT_ID [REGION]
#   GOOGLE_CLOUD_PROJECT=my-proj ./scripts/deploy.sh

set -euo pipefail

# Check for gcloud
if ! command -v gcloud &> /dev/null; then
  echo "Error: gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
  exit 1
fi

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-us-east1}"
SERVICE_NAME="schedule-analyst"
REPO_NAME="schedule-analyst"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}"

if [ -z "$PROJECT_ID" ]; then
  echo "Error: PROJECT_ID required."
  echo ""
  echo "Usage: ./scripts/deploy.sh PROJECT_ID [REGION]"
  echo "   or: export GOOGLE_CLOUD_PROJECT=your-project && ./scripts/deploy.sh"
  echo ""
  echo "Example:"
  echo "   ./scripts/deploy.sh my-gcp-project us-east1"
  exit 1
fi

# Warn if GOOGLE_API_KEY is not set
if [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo "WARNING: GOOGLE_API_KEY is not set. Gemini API calls will fail at runtime."
  echo "  Set it with: export GOOGLE_API_KEY=your-key"
  echo "  Or pass it as a Cloud Run secret after deployment."
  echo ""
fi

echo "=== Deploying ${SERVICE_NAME} to Cloud Run ==="
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo "Image:   ${IMAGE_NAME}"
echo ""

# Step 1: Enable required APIs
echo ">>> Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  calendar-json.googleapis.com \
  --project "${PROJECT_ID}" 2>/dev/null || true

# Step 2: Create Artifact Registry repo (idempotent)
echo ">>> Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories describe "${REPO_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --description="Voice Schedule Analyst container images"

# Step 3: Build container image via Cloud Build
echo ">>> Building container image..."
gcloud builds submit \
  --tag "${IMAGE_NAME}" \
  --project "${PROJECT_ID}"

# Step 4: Deploy to Cloud Run
echo ">>> Deploying to Cloud Run..."
# Build env var string — always include project, conditionally add API key and service account
ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
if [ -n "${GOOGLE_API_KEY:-}" ]; then
  ENV_VARS="${ENV_VARS},GOOGLE_API_KEY=${GOOGLE_API_KEY}"
fi
if [ -n "${CALENDAR_OWNER_EMAIL:-}" ]; then
  ENV_VARS="${ENV_VARS},CALENDAR_OWNER_EMAIL=${CALENDAR_OWNER_EMAIL}"
fi

gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_NAME}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --allow-unauthenticated \
  --update-env-vars "${ENV_VARS}" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --timeout 120 \
  --concurrency 10

# Step 5: Get the service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format "value(status.url)")

echo ""
echo "=== Deployment Complete ==="
echo "Service URL: ${SERVICE_URL}"
echo ""
echo "Test with:"
echo "  curl ${SERVICE_URL}/health"
echo "  curl -X POST ${SERVICE_URL}/schedule-analyst/analyze -H 'Content-Type: application/json' -d '{\"time_range\": \"this week\"}'"
