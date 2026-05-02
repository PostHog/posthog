#!/bin/sh
# Idempotent bootstrap: applies the llm-traces-v0_1 index template, creates the
# initial backing index, and attaches the rollover alias as the write index.
# Re-running is safe; all three operations are idempotent against an existing cluster.
set -eu

URL="${OPENSEARCH_URL:-http://opensearch:9200}"
TPL="${TEMPLATE_PATH:-/work/llm-traces-v0_1.template.json}"
TEMPLATE_NAME=llm-traces-v0_1
INDEX=llm-traces-v0_1-000001
ALIAS=llm-traces

echo "[opensearch-init] bootstrapping $TEMPLATE_NAME at $URL"

curl -fsS -X PUT "$URL/_index_template/$TEMPLATE_NAME" \
    -H 'Content-Type: application/json' \
    --data-binary "@$TPL" >/dev/null

code=$(curl -sS -o /tmp/r -w '%{http_code}' -X PUT "$URL/$INDEX")
if [ "$code" != "200" ] && ! grep -q resource_already_exists_exception /tmp/r 2>/dev/null; then
    echo "[opensearch-init] create $INDEX failed (HTTP $code):"
    cat /tmp/r
    exit 1
fi

curl -fsS -X POST "$URL/_aliases" \
    -H 'Content-Type: application/json' \
    -d "{\"actions\":[{\"add\":{\"index\":\"$INDEX\",\"alias\":\"$ALIAS\",\"is_write_index\":true}}]}" >/dev/null

echo "[opensearch-init] ok"
