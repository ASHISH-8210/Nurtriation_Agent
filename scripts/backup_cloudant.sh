#!/usr/bin/env bash
# =============================================================================
# NutriMind — Cloudant Backup Script
# =============================================================================
# Downloads all Cloudant databases to local JSON files and uploads to COS.
# Run before each deployment as a safety net.
#
# Usage: ./scripts/backup_cloudant.sh
# =============================================================================

set -euo pipefail

BACKUP_DIR="/tmp/nutrimind-backup-$(date +%Y%m%d-%H%M%S)"
COS_BACKUP_PREFIX="backups/cloudant/$(date +%Y%m%d)"
DBS=("nutrimind-profiles" "nutrimind-feedback" "nutrimind-audit" "nutrimind-sessions")

echo "NutriMind Cloudant Backup → IBM COS"
echo "Backup dir: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

for db in "${DBS[@]}"; do
  echo "  Backing up: $db"
  curl -s \
    -H "Authorization: Bearer $(ibmcloud iam oauth-tokens --output json 2>/dev/null | \
        python3 -c 'import sys,json; print(json.load(sys.stdin)["iam_token"].split(" ")[1])')" \
    "${CLOUDANT_URL}/${db}/_all_docs?include_docs=true" \
    > "${BACKUP_DIR}/${db}.json"
  echo "  ✓ ${db}: $(python3 -c "import json; d=json.load(open('${BACKUP_DIR}/${db}.json')); print(d.get('total_rows',0),'docs')")"
done

# Upload to COS
python3 - <<PYEOF
import ibm_boto3, os
from ibm_botocore.client import Config
from pathlib import Path

cos = ibm_boto3.client(
    's3',
    ibm_api_key_id=os.environ['COS_APIKEY'],
    ibm_service_instance_id=os.environ['COS_INSTANCE_CRN'],
    config=Config(signature_version='oauth'),
    endpoint_url=os.environ['COS_ENDPOINT'],
)

backup_dir = Path("${BACKUP_DIR}")
for f in backup_dir.glob("*.json"):
    key = "${COS_BACKUP_PREFIX}/" + f.name
    cos.upload_file(str(f), 'nutrimind-rag', key)
    print(f"  ✓ Uploaded {f.name} → cos://nutrimind-rag/{key}")
PYEOF

echo "Backup complete: $BACKUP_DIR"
echo "COS path: cos://nutrimind-rag/$COS_BACKUP_PREFIX/"
