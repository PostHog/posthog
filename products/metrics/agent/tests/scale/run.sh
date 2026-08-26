#!/bin/sh
# Sharded-fleet scale test: a farm of synthetic Prometheus targets is scraped
# by 4 agent shards, each delivering to its own sink file. Asserts the fleet
# partitions the target set: every series arrives (completeness) and no
# series arrives via two shards (disjointness). Also reports throughput and
# per-shard memory as evidence for capacity planning.
# Usage: products/metrics/agent/tests/scale/run.sh [--skip-build]
set -eu
cd "$(dirname "$0")"
AGENT_DIR=$(cd ../.. && pwd)

FARM_PORTS="${FARM_PORTS:-40}"
FARM_SERIES_PER_TARGET="${FARM_SERIES_PER_TARGET:-200}"
export FARM_PORTS FARM_SERIES_PER_TARGET

# The agents scrape the farm's ports; hashmod partitions this list.
SCRAPE_TARGETS=$(i=0; while [ "$i" -lt "$FARM_PORTS" ]; do
    printf '%sfarm:%s' "${SEP:-}" $((9500 + i))
    SEP=,
    i=$((i + 1))
done)
export SCRAPE_TARGETS

if [ "${1:-}" != "--skip-build" ]; then
    docker build -t posthog-metrics-agent:test "$AGENT_DIR"
fi

# The sharded render must be valid for the real collector, not just goldens.
docker run --rm --entrypoint /bin/sh \
    -e POSTHOG_API_KEY=phc_test -e SCRAPE_TARGETS=app:9090 \
    -e SHARD_COUNT=4 -e SHARD_INDEX=1 \
    posthog-metrics-agent:test \
    -c 'RENDER_ONLY=1 /entrypoint.sh > /tmp/validate.yaml && /usr/local/bin/otelcol-contrib validate --config /tmp/validate.yaml' \
    && echo "PASS sharded collector config validates"

rm -rf out && mkdir -p out && chmod 777 out

cleanup() {
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up -d
START=$(date +%s)

# Wait for every shard to deliver at least one payload (all four files
# non-empty), then a little longer so each target is scraped repeatedly.
for _ in $(seq 1 90); do
    nonempty=0
    for f in out/shard0.json out/shard1.json out/shard2.json out/shard3.json; do
        [ -s "$f" ] && nonempty=$((nonempty + 1))
    done
    [ "$nonempty" -eq 4 ] && break
    sleep 1
done
if [ "$nonempty" -ne 4 ]; then
    echo "FAIL: only $nonempty/4 shards delivered anything" >&2
    docker compose logs --tail 10
    exit 1
fi
sleep 10
ELAPSED=$(($(date +%s) - START))

# Per-shard memory while the fleet is under load, straight from the runtime.
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' \
    | grep -E 'shard[0-3]' | sed 's/^/mem /'

./assert.sh "$FARM_PORTS" "$FARM_SERIES_PER_TARGET" "$ELAPSED"
