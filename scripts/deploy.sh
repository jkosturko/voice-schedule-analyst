#!/bin/bash
# Deploy Voice Schedule Analyst to Google Cloud Run
# Usage: ./scripts/deploy.sh [PROJECT_ID] [REGION]

set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-us-east1}"
SERVICE_NAME="schedule-analyst"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

if [ -z "$PROJECT_ID" ]; then
  echo "Error: PROJECT_ID required."
  echo "Usage: ./scripts/deploy.sh PROJECT_ID [REGION]"
  echo "   or: export GOOGLE_CLOUD_PROJECT=your-project && ./scripts/deploy.sh"
  exit 1
fi

echo "=== Deploying ${SERVICE_NAME} to Cloud Run ==="
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo ""

# Step 1: Enable required APIs
echo ">>> Enabling required APIs..."
gcloud services enable run.googleapis.com containerregistry.googleapis.com calendar-json.googleapis.com \
  --project "${PROJECT_ID}" 2>/dev/null || true

# Step 2: Build container image via Cloud Build
echo ">>> Building container image..."
gcloud builds submit --tag "${IMAGE_NAME}" --project "${PROJECT_ID}"

# Step 3: Deploy to Cloud Run
echo ">>> Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_NAME}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --timeout 60

# Step 4: Get the service URL
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
