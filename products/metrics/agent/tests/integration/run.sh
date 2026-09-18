#!/bin/sh
# End-to-end smoke test: fixture /metrics endpoint (OpenMetrics + exemplars)
# -> agent image -> OTLP sink -> JSON assertions.
# Usage: products/metrics/agent/tests/integration/run.sh [--skip-build]
set -eu
cd "$(dirname "$0")"
AGENT_DIR=$(cd ../.. && pwd)

if [ "${1:-}" != "--skip-build" ]; then
    docker build -t posthog-metrics-agent:test "$AGENT_DIR"
fi

# The sink container may run as a non-root user; make the output dir writable.
rm -rf out && mkdir -p out && chmod 777 out

cleanup() {
    docker compose logs agent 2>/dev/null | tail -20 || true
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up -d

# The rendered config must be valid for the real collector, not just our goldens.
docker run --rm --entrypoint /bin/sh \
    -e POSTHOG_API_KEY=phc_test -e SCRAPE_TARGETS=app:9090 \
    posthog-metrics-agent:test \
    -c 'RENDER_ONLY=1 /entrypoint.sh > /tmp/validate.yaml && /usr/local/bin/otelcol-contrib validate --config /tmp/validate.yaml' \
    && echo "PASS collector config validates"

# Google Cloud Monitoring: `validate` is a dry run that checks the receiver's
# config (factory present, interval, metrics_list) without credentials, which
# are only needed at Start(). This also proves the receiver ships in the image.
docker run --rm --entrypoint /bin/sh \
    -e POSTHOG_API_KEY=phc_test -e GCP_PROJECT_ID=test-project \
    -e GCP_METRICS=compute.googleapis.com/instance/cpu/utilization \
    posthog-metrics-agent:test \
    -c 'RENDER_ONLY=1 /entrypoint.sh > /tmp/validate.yaml && /usr/local/bin/otelcol-contrib validate --config /tmp/validate.yaml' \
    && echo "PASS collector validates gcp-only config"

docker run --rm --entrypoint /bin/sh \
    -e POSTHOG_API_KEY=phc_test -e SCRAPE_TARGETS=app:9090 -e GCP_PROJECT_ID=test-project \
    -e GCP_METRICS=compute.googleapis.com/instance/cpu/utilization \
    posthog-metrics-agent:test \
    -c 'RENDER_ONLY=1 /entrypoint.sh > /tmp/validate.yaml && /usr/local/bin/otelcol-contrib validate --config /tmp/validate.yaml' \
    && echo "PASS collector validates gcp-plus-scrape config"

# The receiver rejects intervals under 60s (Cloud Monitoring quota floor);
# pin the README claim to real collector behaviour.
if docker run --rm --entrypoint /bin/sh \
    -e POSTHOG_API_KEY=phc_test -e GCP_PROJECT_ID=test-project \
    -e GCP_METRICS=compute.googleapis.com/instance/cpu/utilization \
    -e GCP_COLLECTION_INTERVAL=30s \
    posthog-metrics-agent:test \
    -c 'RENDER_ONLY=1 /entrypoint.sh > /tmp/validate.yaml && /usr/local/bin/otelcol-contrib validate --config /tmp/validate.yaml' \
    >/dev/null 2>&1; then
    echo "FAIL gcp-interval-floor: collector accepted a 30s pull interval"
    exit 1
fi
echo "PASS gcp-interval-floor"

./assert.sh
