#!/usr/bin/env bash
# =============================================================================
# NutriMind — watsonx Orchestrate Agent Registration
# =============================================================================
# Registers the NutriMind agent definition with watsonx Orchestrate via ADK.
#
# Live deployment coordinates:
#   Host:       https://au-syd.watson-orchestrate.cloud.ibm.com
#   Agent ID:   c7225708-c2da-45be-a606-2f9037b55bec
#   CRN:        crn:v1:bluemix:public:watsonx-orchestrate:au-syd:a/aab8caee15fc49d6851636b85da74c1d:2cbd20fb-4e07-48e4-b81c-3902f34018fb::
#
# Usage:
#   MCP_SERVER_URL=https://... ./scripts/register_agent.sh
# =============================================================================

set -euo pipefail

AGENT_NAME="nutrimind"
AGENT_ID="c7225708-c2da-45be-a606-2f9037b55bec"
ORCHESTRATE_HOST="https://au-syd.watson-orchestrate.cloud.ibm.com"
ORCHESTRATE_URL="${ORCHESTRATE_URL:-${ORCHESTRATE_HOST}}"
AGENT_YAML="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd .. && pwd)/agent/agent.yaml"

echo "Registering NutriMind agent with watsonx Orchestrate..."

if [[ ! -f "$AGENT_YAML" ]]; then
  echo "ERROR: agent.yaml not found at $AGENT_YAML"
  exit 1
fi

# Replace env var placeholders in YAML before submitting
MCP_URL="${MCP_SERVER_URL:-}"
MCP_KEY="${MCP_SERVER_API_KEY:-}"

if [[ -z "$MCP_URL" ]]; then
  echo "WARNING: MCP_SERVER_URL not set — agent will not be able to call tools."
fi

TEMP_YAML="/tmp/nutrimind_agent_resolved.yaml"
sed \
  -e "s|\${MCP_SERVER_URL}|${MCP_URL}|g" \
  -e "s|\${MCP_SERVER_API_KEY}|${MCP_KEY}|g" \
  "$AGENT_YAML" > "$TEMP_YAML"

# watsonx Orchestrate ADK CLI registration
if command -v wxo &>/dev/null; then
  wxo agent import --file "$TEMP_YAML" --overwrite
  echo "  ✓ Agent registered via wxo CLI"
elif command -v python3 &>/dev/null; then
  # Fallback: direct REST API registration
  ORCHESTRATE_URL="${ORCHESTRATE_URL:-https://api.us-south.assistant.watson.cloud.ibm.com}"
  IAM_TOKEN=$(curl -s -X POST \
    "https://iam.cloud.ibm.com/identity/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey=${WATSONX_APIKEY}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

  python3 - <<'PYEOF'
import os, sys, json, yaml
import urllib.request

with open("/tmp/nutrimind_agent_resolved.yaml") as f:
    agent_def = yaml.safe_load(f)

payload = json.dumps(agent_def).encode()
req = urllib.request.Request(
    f"{os.environ.get('ORCHESTRATE_URL','https://api.us-south.assistant.watson.cloud.ibm.com')}"
    f"/v2/agents",
    data=payload,
    headers={
        "Authorization": f"Bearer {os.environ.get('IAM_TOKEN','')}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        print(f"  ✓ Agent registered: {result.get('agent_id', result)}")
except Exception as e:
    print(f"  ⚠  REST registration returned: {e}")
    print("  Please register agent.yaml manually via watsonx Orchestrate UI.")
PYEOF
else
  echo "  ⚠  Neither wxo CLI nor python3 found."
  echo "  Please register $AGENT_YAML manually via the watsonx Orchestrate UI."
fi

rm -f "$TEMP_YAML"
echo "Agent registration complete."
