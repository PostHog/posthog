#!/usr/bin/env bash
# Copy the prod inbox_report_state and inbox_report_labels partitions into local SeaweedFS so
# inbox_ranking_training_job can run from the local Dagster UI against real snapshots.
#
#   products/signals/dags/inbox_ranking/bin/sync_snapshots_local.sh
#
# Two hops: prod S3 -> a disk cache -> the local object-storage bucket. The disk copy is what
# makes a re-sync cheap (aws s3 sync only moves new partitions) and doubles as input for
# notebooks. Only the dt= partitions the training job reads are copied; latest/ is skipped.
# Both hops delete what the source no longer has, so a partition scrubbed from prod (see the
# README's retention section) leaves the cache and the local bucket on the next sync.
# S3 object metadata (snapshot-date, row-count) does not survive the download; the training
# job never reads it, so that is fine here.
#
# The prod read needs an active SSO session on the secrets profile and the id of the
# Secrets Manager secret that holds the reader credential (see the dag README):
#   aws sso login --profile prod-us-secrets
#   INBOX_RANKING_READER_SECRET_ID=... products/signals/dags/inbox_ranking/bin/sync_snapshots_local.sh
set -euo pipefail

SECRETS_PROFILE="${SECRETS_PROFILE:-prod-us-secrets}"
PROD_BUCKET="${INBOX_RANKING_PROD_BUCKET:-posthog-inbox-ranking-dataset-prod-us}"
PREFIX="${INBOX_RANKING_DATASET_S3_PREFIX:-inbox_ranking}"
LOCAL_ENDPOINT="${INBOX_RANKING_LOCAL_ENDPOINT:-${OBJECT_STORAGE_ENDPOINT:-http://localhost:19000}}"
LOCAL_BUCKET="${OBJECT_STORAGE_BUCKET:-posthog}"
LOCAL_KEY="${OBJECT_STORAGE_ACCESS_KEY_ID:-object_storage_root_user}"
LOCAL_SECRET="${OBJECT_STORAGE_SECRET_ACCESS_KEY:-object_storage_root_password}"
CACHE_DIR="${INBOX_RANKING_SYNC_DIR:-$HOME/.cache/posthog/inbox_ranking}"
TABLES=(inbox_report_state inbox_report_labels)

if [ -z "${INBOX_RANKING_READER_SECRET_ID:-}" ]; then
    echo "Set INBOX_RANKING_READER_SECRET_ID to the Secrets Manager id of the dataset reader credential." >&2
    exit 1
fi

if ! aws --profile "$SECRETS_PROFILE" sts get-caller-identity >/dev/null 2>&1; then
    echo "No active SSO session. Run: aws sso login --profile $SECRETS_PROFILE" >&2
    exit 1
fi

# Checked before the download so a stack that is not up fails in seconds, not after the pull.
# The objectstorage container registers its credentials in a bootstrap loop after it starts, so
# a fresh stack rejects signed requests for a short while; retry rather than fail on the first.
for attempt in 1 2 3 4 5 6; do
    if AWS_ACCESS_KEY_ID="$LOCAL_KEY" AWS_SECRET_ACCESS_KEY="$LOCAL_SECRET" AWS_SESSION_TOKEN= \
        aws --endpoint-url "$LOCAL_ENDPOINT" --region us-east-1 s3 ls "s3://$LOCAL_BUCKET/" >/dev/null 2>&1; then
        break
    fi
    if [ "$attempt" -eq 6 ]; then
        echo "Local object storage at $LOCAL_ENDPOINT is not accepting requests for bucket $LOCAL_BUCKET. Is the dev stack up (bin/start)?" >&2
        exit 1
    fi
    sleep 5
done

# An inherited xtrace (bash -x) would print the SecretString and every later expansion of the
# reader keys; force it off before the credential enters the shell.
{ set +x; } 2>/dev/null
secret_json=$(aws --profile "$SECRETS_PROFILE" secretsmanager get-secret-value \
    --secret-id "$INBOX_RANKING_READER_SECRET_ID" \
    --query SecretString --output text)
reader_key=$(printf '%s' "$secret_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_key_id"])')
reader_secret=$(printf '%s' "$secret_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["secret_access_key"])')

echo "==> prod -> $CACHE_DIR"
for table in "${TABLES[@]}"; do
    AWS_ACCESS_KEY_ID="$reader_key" AWS_SECRET_ACCESS_KEY="$reader_secret" AWS_SESSION_TOKEN= \
        aws s3 sync "s3://$PROD_BUCKET/$PREFIX/$table/v1/" "$CACHE_DIR/$table/v1/" --region us-east-1 \
        --delete --exclude "*" --include "dt=*/part-00000.parquet"
done

echo "==> $CACHE_DIR -> $LOCAL_ENDPOINT/$LOCAL_BUCKET/$PREFIX"
for table in "${TABLES[@]}"; do
    AWS_ACCESS_KEY_ID="$LOCAL_KEY" AWS_SECRET_ACCESS_KEY="$LOCAL_SECRET" AWS_SESSION_TOKEN= \
        aws s3 sync "$CACHE_DIR/$table/v1/" "s3://$LOCAL_BUCKET/$PREFIX/$table/v1/" \
        --endpoint-url "$LOCAL_ENDPOINT" --region us-east-1 --delete
done

echo "==> partitions present in both tables locally:"
# aws s3 sync --delete removes the parquet of a scrubbed partition but leaves its empty dt=
# directory, so enumerate the files, not the directories.
list_partitions() {
    local f
    for f in "$CACHE_DIR/$1/v1"/dt=*/part-00000.parquet; do
        [ -e "$f" ] || continue
        basename "$(dirname "$f")"
    done | sort
}
comm -12 <(list_partitions "${TABLES[0]}") <(list_partitions "${TABLES[1]}")
