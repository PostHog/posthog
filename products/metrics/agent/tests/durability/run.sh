#!/bin/sh
# Durability test: samples scraped while PostHog is unreachable must survive
# an agent restart and arrive once the destination comes back.
#
# Timeline: agent scrapes with the sink absent (outage) -> agent is killed and
# restarted -> sink starts -> assert the sink receives datapoints whose scrape
# timestamps predate the restart. Only the disk-backed queue can deliver
# those; an in-memory queue would have lost them with the first process.
# Usage: products/metrics/agent/tests/durability/run.sh [--skip-build]
set -eu
cd "$(dirname "$0")"
AGENT_DIR=$(cd ../.. && pwd)

if [ "${1:-}" != "--skip-build" ]; then
    docker build -t posthog-metrics-agent:test "$AGENT_DIR"
fi

# The persist-queue render must be valid for the real collector.
docker run --rm --entrypoint /bin/sh \
    -e POSTHOG_API_KEY=phc_test -e SCRAPE_TARGETS=app:9090 -e PERSIST_QUEUE=1 \
    posthog-metrics-agent:test \
    -c 'RENDER_ONLY=1 /entrypoint.sh > /tmp/validate.yaml && /usr/local/bin/otelcol-contrib validate --config /tmp/validate.yaml' \
    && echo "PASS persist-queue collector config validates"

rm -rf out && mkdir -p out && chmod 777 out

cleanup() {
    docker compose --profile recovery down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Phase 1: outage. The agent scrapes but has nowhere to deliver.
docker compose up -d fixture agent
echo "phase 1: scraping during outage (12s)"
sleep 12

# Phase 2: hard restart. In-memory state dies here; the disk queue must not.
RESTART_NS=$(date +%s)000000000
docker compose kill agent
docker compose up -d agent
echo "phase 2: agent hard-restarted at $RESTART_NS"

# Phase 3: recovery. The sink appears; the queue should drain into it.
docker compose --profile recovery up -d sink
echo "phase 3: sink up, waiting for delivery"

for _ in $(seq 1 60); do
    [ -s out/metrics.json ] && grep -q http_requests_total out/metrics.json && break
    sleep 1
done

if [ ! -s out/metrics.json ]; then
    echo "FAIL: sink never received metrics after recovery" >&2
    docker compose logs agent --tail 15
    exit 1
fi
sleep 5

./assert.sh "$RESTART_NS"
