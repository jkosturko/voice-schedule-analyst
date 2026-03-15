#!/bin/bash
# Build and run the Docker container locally for testing.
#
# Prerequisites:
#   - Docker installed and running
#   - GOOGLE_API_KEY set (for Gemini calls)
#   - For Calendar access, ONE of:
#     a) GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
#     b) token.json from running `python -m schedule_analyst.auth` (mount as volume)
#
# Usage:
#   ./scripts/docker-build.sh           # Build + run
#   ./scripts/docker-build.sh --build   # Build only

set -euo pipefail

IMAGE_NAME="schedule-analyst:local"

echo ">>> Building Docker image..."
docker build -t "${IMAGE_NAME}" .

if [ "${1:-}" = "--build" ]; then
  echo ">>> Build complete. Image: ${IMAGE_NAME}"
  exit 0
fi

echo ""
echo ">>> Running container on port 8080..."
echo "  Health:   curl http://localhost:8080/health"
echo "  Analyze:  curl -X POST http://localhost:8080/schedule-analyst/analyze -H 'Content-Type: application/json' -d '{\"time_range\":\"today\"}'"
echo "  Ctrl+C to stop."
echo ""

# Pass env vars for API access — service account JSON works inside container
# (file-based credentials don't, since the file isn't mounted)
docker run --rm -p 8080:8080 \
  -e GOOGLE_API_KEY="${GOOGLE_API_KEY:-}" \
  -e GOOGLE_SERVICE_ACCOUNT_JSON="${GOOGLE_SERVICE_ACCOUNT_JSON:-}" \
  -e CALENDAR_OWNER_EMAIL="${CALENDAR_OWNER_EMAIL:-}" \
  "${IMAGE_NAME}"
