#!/usr/bin/env bash
#
# Day-to-day deploy: pull latest main, rebuild the Docker image and restart
# the container only if something changed, and verify it actually came back
# up.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="job-hunter"

cd "$REPO_DIR"

BEFORE_REV="$(git rev-parse HEAD)"

echo "Pulling latest changes..."
if ! git pull --ff-only; then
  echo "git pull failed. Resolve the issue (conflicts, diverged branch, network) and re-run deploy.sh." >&2
  exit 1
fi

AFTER_REV="$(git rev-parse HEAD)"

if [ "$BEFORE_REV" = "$AFTER_REV" ]; then
  echo "Nothing new to deploy."
  exit 0
fi

echo "Rebuilding and restarting ${CONTAINER_NAME}..."
docker compose up -d --build

# Give the container a moment to either settle into "running" or fail fast.
sleep 2

if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)" = "true" ]; then
  echo "Deploy finished, ${CONTAINER_NAME} is running."
else
  echo "ERROR: ${CONTAINER_NAME} did not come up after restart." >&2
  echo "Last logs:" >&2
  docker logs "$CONTAINER_NAME" --tail 20 >&2
  exit 1
fi
