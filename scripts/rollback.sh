#!/usr/bin/env bash
# =============================================================================
# NutriMind — Rollback Script
# =============================================================================
# Rolls back the Code Engine app to a specific previous image revision.
#
# Usage:
#   ./scripts/rollback.sh                          # list recent revisions
#   ./scripts/rollback.sh <image-tag>              # roll back to specific tag
#   ./scripts/rollback.sh 20240115-143022          # example with date tag
# =============================================================================

set -euo pipefail

APP_NAME="nutrimind-tools"
REGION="${IBM_REGION:-us-south}"
RESOURCE_GROUP="${IBM_RESOURCE_GROUP:-Default}"
CE_PROJECT="${CE_PROJECT_NAME:-nutrimind-ce-project}"
REGISTRY="us.icr.io"
NAMESPACE="${ICR_NAMESPACE:-nutrimind}"

TARGET_TAG="${1:-}"

echo "============================================================"
echo "NutriMind Rollback — IBM Code Engine"
echo "============================================================"

# Login
ibmcloud login --apikey "$WATSONX_APIKEY" -r "$REGION" -g "$RESOURCE_GROUP" --quiet
ibmcloud ce project select --name "$CE_PROJECT"

if [[ -z "$TARGET_TAG" ]]; then
  echo "Available image tags in IBM Container Registry:"
  echo "(showing last 10)"
  ibmcloud cr image-list --restrict "${NAMESPACE}/${APP_NAME}" \
    --format "table {{.Repository}}:{{.Tag}}  {{.Created}}" 2>/dev/null | tail -12
  echo ""
  echo "Usage: ./scripts/rollback.sh <image-tag>"
  echo "Example: ./scripts/rollback.sh 20240115-143022"
  exit 0
fi

TARGET_IMAGE="${REGISTRY}/${NAMESPACE}/${APP_NAME}:${TARGET_TAG}"
echo "Rolling back to: $TARGET_IMAGE"

# Verify image exists
if ! ibmcloud cr image-inspect "$TARGET_IMAGE" &>/dev/null; then
  echo "ERROR: Image not found in registry: $TARGET_IMAGE"
  echo "Run './scripts/rollback.sh' (no args) to list available tags."
  exit 1
fi

# Backup current config
CURRENT_IMAGE=$(ibmcloud ce app get --name "$APP_NAME" --output json | \
  python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[{}])[0].get('image','unknown'))")
echo "Current image: $CURRENT_IMAGE"
echo "Saving current revision to /tmp/nutrimind_pre_rollback.txt"
echo "$CURRENT_IMAGE" > /tmp/nutrimind_pre_rollback.txt

# Execute rollback
echo ""
echo "Updating app image..."
ibmcloud ce app update \
  --name "$APP_NAME" \
  --image "$TARGET_IMAGE" \
  --wait

echo ""
echo "Smoke test..."
sleep 5
MCP_URL=$(ibmcloud ce app get --name "$APP_NAME" --output json | \
  python3 -c "import sys,json; app=json.load(sys.stdin); print(app.get('status',{}).get('url','unknown'))")

if curl -s -f -H "X-NutriMind-Key: ${MCP_SERVER_API_KEY}" "${MCP_URL}/health" | grep -q '"status":"ok"'; then
  echo "  ✓ Rollback successful. App healthy at: $MCP_URL"
else
  echo "  ⚠  Health check failed after rollback."
  echo "  To re-rollback to previous: ./scripts/rollback.sh $CURRENT_IMAGE"
  exit 1
fi

echo ""
echo "Rollback complete. Now running: $TARGET_IMAGE"
echo "Previous image saved to /tmp/nutrimind_pre_rollback.txt"
