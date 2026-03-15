#!/bin/bash
# Build and run the Docker container locally for testing.
# Usage: ./scripts/docker-build.sh

set -euo pipefail

IMAGE_NAME="schedule-analyst:local"

echo ">>> Building Docker image..."
docker build -t "${IMAGE_NAME}" .

echo ">>> Running container on port 8080..."
echo "  Health check: curl http://localhost:8080/health"
echo "  Press Ctrl+C to stop."
echo ""

docker run --rm -p 8080:8080 \
  -e GOOGLE_API_KEY="${GOOGLE_API_KEY:-}" \
  -e GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-}" \
  "${IMAGE_NAME}"
