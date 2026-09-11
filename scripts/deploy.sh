#!/usr/bin/env bash
# =============================================================================
# NutriMind — IBM Code Engine Deployment Script
# =============================================================================
# Deploys the NutriMind MCP tools server to IBM Code Engine (Lite plan).
# Requires: ibmcloud CLI + code-engine plugin + docker (or podman)
#
# Usage:
#   ./scripts/deploy.sh [--env staging|production] [--skip-build]
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_NAME="nutrimind-tools"
REGION="${IBM_REGION:-au-syd}"
RESOURCE_GROUP="${IBM_RESOURCE_GROUP:-Default}"
CE_PROJECT="${CE_PROJECT_NAME:-nutrimind-ce-project}"
REGISTRY="au.icr.io"                  # IBM Container Registry — Sydney region
NAMESPACE="${ICR_NAMESPACE:-nutrimind}"
ORCHESTRATE_HOST="https://au-syd.watson-orchestrate.cloud.ibm.com"
ORCHESTRATE_AGENT_ID="c7225708-c2da-45be-a606-2f9037b55bec"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"
IMAGE_NAME="${REGISTRY}/${NAMESPACE}/${APP_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGISTRY}/${NAMESPACE}/${APP_NAME}:latest"
ENV="${1:-production}"
SKIP_BUILD="${SKIP_BUILD:-false}"

# Code Engine Lite limits (stay within free tier)
CE_CPU="0.25"
CE_MEMORY="0.5G"
CE_MIN_SCALE="0"
CE_MAX_SCALE="3"
CE_TIMEOUT="300"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================================"
echo "NutriMind Deployment — IBM Code Engine"
echo "App:       $APP_NAME"
echo "Image:     $IMAGE_NAME"
echo "Env:       $ENV"
echo "Region:    $REGION"
echo "============================================================"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
echo ""
echo "[1/8] Pre-flight checks..."

required_vars=(
  WATSONX_APIKEY WATSONX_URL WATSONX_PROJECT_ID
  CLOUDANT_URL CLOUDANT_APIKEY
  COS_APIKEY COS_INSTANCE_CRN COS_ENDPOINT
  STT_APIKEY STT_URL
  MCP_SERVER_API_KEY
)

missing=()
for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    missing+=("$var")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: Missing required environment variables:"
  for v in "${missing[@]}"; do
    echo "  - $v"
  done
  echo ""
  echo "Create a .env file or export these variables before deploying."
  exit 1
fi
echo "  ✓ All required environment variables present"

for cmd in ibmcloud docker; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' not found. Please install it first."
    exit 1
  fi
done
echo "  ✓ ibmcloud and docker CLIs found"

# ---------------------------------------------------------------------------
# IBM Cloud login
# ---------------------------------------------------------------------------
echo ""
echo "[2/8] IBM Cloud login..."
ibmcloud login --apikey "$WATSONX_APIKEY" -r "$REGION" -g "$RESOURCE_GROUP" --quiet
ibmcloud cr login --client docker
echo "  ✓ Logged in to IBM Cloud and Container Registry"

# ---------------------------------------------------------------------------
# Cloudant database setup (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "[3/8] Setting up Cloudant databases (idempotent)..."

DB_NAMES=("nutrimind-profiles" "nutrimind-feedback" "nutrimind-audit" "nutrimind-sessions")
for db in "${DB_NAMES[@]}"; do
  echo "  Creating Cloudant DB: $db (ignoring if exists)..."
  curl -s -X PUT \
    -H "Authorization: Bearer $(ibmcloud iam oauth-tokens --output json | python3 -c 'import sys,json; print(json.load(sys.stdin)["iam_token"].split(" ")[1])')" \
    "${CLOUDANT_URL}/${db}" | python3 -c \
    "import sys,json; r=json.load(sys.stdin); print('  ✓', r.get('ok','already exists') and '$db OK')" 2>/dev/null || echo "  (may already exist — continuing)"
done

# ---------------------------------------------------------------------------
# COS bucket setup (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "[4/8] Setting up COS buckets..."
python3 -c "
import ibm_boto3
from ibm_botocore.client import Config
import os

cos = ibm_boto3.client(
    's3',
    ibm_api_key_id=os.environ['COS_APIKEY'],
    ibm_service_instance_id=os.environ['COS_INSTANCE_CRN'],
    config=Config(signature_version='oauth'),
    endpoint_url=os.environ['COS_ENDPOINT'],
)
for bucket in ['nutrimind-rag', 'nutrimind-images']:
    try:
        cos.create_bucket(Bucket=bucket)
        print(f'  ✓ Created bucket: {bucket}')
    except cos.exceptions.BucketAlreadyOwnedByYou:
        print(f'  ✓ Bucket exists: {bucket}')
    except Exception as e:
        print(f'  ! Warning for {bucket}: {e}')
" || echo "  (COS setup skipped — ibm-cos-sdk not installed locally)"

# ---------------------------------------------------------------------------
# RAG ingestion (if index doesn't exist in COS yet)
# ---------------------------------------------------------------------------
echo ""
echo "[5/8] Checking RAG index..."
if [[ -f "${PROJECT_ROOT}/rag/nutrition.index" ]]; then
  echo "  ✓ Local RAG index found — skipping ingestion"
else
  echo "  RAG index not found — running ingestion..."
  cd "$PROJECT_ROOT"
  python3 rag/ingest.py --sources-dir ./rag/sources --output-dir ./rag
  echo "  ✓ RAG ingestion complete"
fi

# ---------------------------------------------------------------------------
# Docker build and push
# ---------------------------------------------------------------------------
echo ""
echo "[6/8] Building and pushing Docker image..."

if [[ "$SKIP_BUILD" == "false" ]]; then
  # Ensure ICR namespace exists
  ibmcloud cr namespace-add "$NAMESPACE" 2>/dev/null || true

  # Build
  cd "$PROJECT_ROOT"
  docker build \
    --platform linux/amd64 \
    -t "$IMAGE_NAME" \
    -t "$IMAGE_LATEST" \
    -f scripts/Dockerfile \
    .

  # Push both tags
  docker push "$IMAGE_NAME"
  docker push "$IMAGE_LATEST"
  echo "  ✓ Image pushed: $IMAGE_NAME"
else
  echo "  (build skipped — using existing image)"
fi

# ---------------------------------------------------------------------------
# Code Engine project + app deploy
# ---------------------------------------------------------------------------
echo ""
echo "[7/8] Deploying to IBM Code Engine..."

# Target CE project (create if first deploy)
if ! ibmcloud ce project select --name "$CE_PROJECT" 2>/dev/null; then
  echo "  Creating Code Engine project: $CE_PROJECT"
  ibmcloud ce project create --name "$CE_PROJECT"
  ibmcloud ce project select --name "$CE_PROJECT"
fi

# Build the secret values string
SECRET_VALS=(
  "WATSONX_APIKEY=${WATSONX_APIKEY}"
  "WATSONX_URL=${WATSONX_URL}"
  "WATSONX_PROJECT_ID=${WATSONX_PROJECT_ID}"
  "CLOUDANT_URL=${CLOUDANT_URL}"
  "CLOUDANT_APIKEY=${CLOUDANT_APIKEY}"
  "COS_APIKEY=${COS_APIKEY}"
  "COS_INSTANCE_CRN=${COS_INSTANCE_CRN}"
  "COS_ENDPOINT=${COS_ENDPOINT}"
  "STT_APIKEY=${STT_APIKEY}"
  "STT_URL=${STT_URL}"
  "MCP_SERVER_API_KEY=${MCP_SERVER_API_KEY}"
  "USDA_API_KEY=${USDA_API_KEY:-DEMO_KEY}"
)

# Create/update secret
SECRET_NAME="${APP_NAME}-secrets"
if ibmcloud ce secret get --name "$SECRET_NAME" &>/dev/null; then
  echo "  Updating existing secret: $SECRET_NAME"
  ibmcloud ce secret update --name "$SECRET_NAME" \
    $(for kv in "${SECRET_VALS[@]}"; do echo -n "--from-literal $kv "; done)
else
  echo "  Creating secret: $SECRET_NAME"
  ibmcloud ce secret create --name "$SECRET_NAME" \
    $(for kv in "${SECRET_VALS[@]}"; do echo -n "--from-literal $kv "; done)
fi

# Deploy / update app
if ibmcloud ce app get --name "$APP_NAME" &>/dev/null; then
  echo "  Updating existing app..."
  ibmcloud ce app update \
    --name "$APP_NAME" \
    --image "$IMAGE_NAME" \
    --cpu "$CE_CPU" \
    --memory "$CE_MEMORY" \
    --min-scale "$CE_MIN_SCALE" \
    --max-scale "$CE_MAX_SCALE" \
    --port 8080 \
    --env-from-secret "$SECRET_NAME" \
    --wait
else
  echo "  Creating new app..."
  ibmcloud ce app create \
    --name "$APP_NAME" \
    --image "$IMAGE_NAME" \
    --registry-secret nutrimind-icr-secret \
    --cpu "$CE_CPU" \
    --memory "$CE_MEMORY" \
    --min-scale "$CE_MIN_SCALE" \
    --max-scale "$CE_MAX_SCALE" \
    --port 8080 \
    --env-from-secret "$SECRET_NAME" \
    --wait
fi

# Get the deployed URL
MCP_URL=$(ibmcloud ce app get --name "$APP_NAME" --output json | python3 -c \
  "import sys,json; app=json.load(sys.stdin); print(app.get('status',{}).get('url','unknown'))")

echo "  ✓ App deployed: $MCP_URL"

# ---------------------------------------------------------------------------
# Register agent in watsonx Orchestrate
# ---------------------------------------------------------------------------
echo ""
echo "[8/8] Registering agent with watsonx Orchestrate..."
MCP_SERVER_URL="${MCP_URL}/mcp" \
  bash "${SCRIPT_DIR}/register_agent.sh" || echo "  (agent registration skipped — run register_agent.sh manually)"

# ---------------------------------------------------------------------------
# Post-deploy smoke test
# ---------------------------------------------------------------------------
echo ""
echo "Running post-deploy smoke test..."
sleep 5
if curl -s -f -H "X-NutriMind-Key: ${MCP_SERVER_API_KEY}" "${MCP_URL}/health" | grep -q '"status":"ok"'; then
  echo "  ✓ Health check passed"
else
  echo "  ⚠  Health check did not return expected response — check logs with:"
  echo "     ibmcloud ce app logs --name $APP_NAME"
fi

echo ""
echo "============================================================"
echo "Deployment complete!"
echo "  MCP Server URL: $MCP_URL"
echo "  Image:          $IMAGE_NAME"
echo ""
echo "Next steps:"
echo "  1. Update agent.yaml: MCP_SERVER_URL=$MCP_URL/mcp"
echo "  2. Run smoke tests: python tests/test_conversations.py --live"
echo "  3. Monitor logs:    ibmcloud ce app logs --name $APP_NAME --follow"
echo "============================================================"
