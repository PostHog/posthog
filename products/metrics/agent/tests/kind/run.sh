#!/bin/sh
# Real-Kubernetes E2E for the agent chart on a kind cluster. Validates the
# legs compose cannot: restricted Pod Security admission, ClusterRole-backed
# annotation discovery, StatefulSet ordinal -> SHARD_INDEX derivation,
# volumeClaimTemplates binding, and exemplars surviving the in-cluster path.
# Usage: products/metrics/agent/tests/kind/run.sh [--skip-build]
# Requires: kind, kubectl, helm, jq, docker. Creates/reuses cluster
# kind-metrics-agent-test; cleans up namespaces but leaves the cluster.
set -eu
cd "$(dirname "$0")"
AGENT_DIR=$(cd ../.. && pwd)
CLUSTER=metrics-agent-test
CTX=kind-$CLUSTER
K="kubectl --context $CTX"

PASS=0
FAIL=0
check() {
    name=$1
    expected=$2
    actual=$3
    if [ "$actual" = "$expected" ]; then
        echo "PASS $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL $name: expected '$expected', got '$actual'" >&2
        FAIL=$((FAIL + 1))
    fi
}

if [ "${1:-}" != "--skip-build" ]; then
    docker build -t posthog-metrics-agent:test "$AGENT_DIR"
fi

kind get clusters 2>/dev/null | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --wait 120s
kind load docker-image posthog-metrics-agent:test --name "$CLUSTER"

cleanup() {
    helm --kube-context "$CTX" uninstall scrape -n agent >/dev/null 2>&1 || true
    $K delete namespace agent fixtures --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup
# Namespace deletion is async; wait for full teardown before recreating.
for _ in $(seq 1 60); do
    $K get namespace agent fixtures >/dev/null 2>&1 || break
    sleep 2
done

# The agent namespace enforces the restricted Pod Security Standard, so pod
# admission itself asserts the chart's security contexts.
$K create namespace agent
$K label namespace agent \
    pod-security.kubernetes.io/enforce=restricted \
    pod-security.kubernetes.io/warn=restricted
$K create namespace fixtures
$K -n fixtures create configmap fixture-server \
    --from-file=fixture_server.py=../integration/fixture_server.py
$K -n fixtures create configmap fixture-payload \
    --from-file=metrics.openmetrics.txt=../integration/fixtures/metrics.openmetrics.txt
$K apply -f manifests/fixtures.yaml >/dev/null
$K -n fixtures rollout status deployment/fixture deployment/fixture-decoy deployment/sink --timeout=180s

helm --kube-context "$CTX" install scrape "$AGENT_DIR/chart/posthog-metrics-agent" \
    -n agent \
    --set posthog.apiKey=phc_test \
    --set posthog.host=http://sink.fixtures.svc.cluster.local:4318 \
    --set posthog.ingestPath=/v1/metrics \
    --set shards=2 \
    --set persistence.enabled=true \
    --set persistence.size=1Gi \
    --set scrape.interval=3s \
    --set image.repository=posthog-metrics-agent \
    --set image.tag=test \
    --set image.pullPolicy=Never >/dev/null
echo "chart installed into restricted namespace"

# Read the sink's output file through its busybox sidecar (the collector
# image is distroless).
sink_json() {
    $K -n fixtures exec deploy/sink -c reader -- cat /out/metrics.json 2>/dev/null
}

STS=scrape-posthog-metrics-agent
$K -n agent rollout status "statefulset/$STS" --timeout=180s
check restricted-admission-ready-pods 2 "$($K -n agent get pods -l app.kubernetes.io/name=posthog-metrics-agent --field-selector=status.phase=Running --no-headers | wc -l | tr -d ' ')"

check pvcs-bound 2 "$($K -n agent get pvc --no-headers 2>/dev/null | grep -c Bound | tr -d ' ')"

# The entrypoint must derive each pod's shard index from its ordinal; read it
# back from the running collector's environment.
for i in 0 1; do
    derived=$($K -n agent exec "$STS-$i" -- sh -c "tr '\0' '\n' </proc/1/environ | sed -n 's/^SHARD_INDEX=//p'")
    check "shard-index-derived-pod-$i" "$i" "$derived"
done

# Discovery -> scrape -> OTLP -> sink: wait until series from every annotated
# fixture pod arrive (the relabel puts the pod name in the `pod` attribute).
expected_pods=$($K -n fixtures get pods -l app=fixture -o name | sed 's|pod/||' | sort)
seen=""
for _ in $(seq 1 60); do
    seen=$(sink_json | jq -rs '
        [.[].resourceMetrics[].scopeMetrics[].metrics[]
         | select(.name == "http_requests_total")
         | .sum.dataPoints[].attributes[]
         | select(.key == "pod") | .value.stringValue] | unique | .[]' 2>/dev/null | sort)
    [ "$seen" = "$expected_pods" ] && break
    sleep 3
done
check discovery-completeness "$expected_pods" "$seen"

decoy_seen=$(sink_json | jq -rs '
    [.[].resourceMetrics[].scopeMetrics[].metrics[].sum.dataPoints[]?.attributes[]?
     | select(.key == "pod") | .value.stringValue]
    | map(select(startswith("fixture-decoy"))) | length')
check decoy-not-scraped 0 "$decoy_seen"

exemplar=$(sink_json | jq -rs '
    [.[].resourceMetrics[].scopeMetrics[].metrics[]
     | select(.name == "http_requests_total")
     | .sum.dataPoints[].exemplars[]?.traceId] | unique | first')
check exemplar-survives-k8s-path 4bf92f3577b34da6a3ce929d0e0e4736 "$exemplar"

# Both shards must be doing work. Each collector's own telemetry (:8888,
# exposed by the chart) reports how many scraped points its prometheus
# receiver accepted; both > 0 proves the fleet isn't silently idle on one pod.
# Disjoint partitioning itself is proven exhaustively by the compose scale
# test (60k series); here we confirm both shards are live in-cluster.
shard_accepted() {
    $K -n agent exec "$STS-$1" -- wget -qO- http://127.0.0.1:8888/metrics 2>/dev/null \
        | awk '/^otelcol_receiver_accepted_metric_points/ {sum += $NF} END {printf "%d", sum}'
}
a0=$(shard_accepted 0)
a1=$(shard_accepted 1)
echo "accepted metric points: shard0=$a0 shard1=$a1"
[ "${a0:-0}" -gt 0 ] 2>/dev/null && { echo "PASS shard-0-active"; PASS=$((PASS + 1)); } || { echo "FAIL shard-0-active: accepted 0 points" >&2; FAIL=$((FAIL + 1)); }
[ "${a1:-0}" -gt 0 ] 2>/dev/null && { echo "PASS shard-1-active"; PASS=$((PASS + 1)); } || { echo "FAIL shard-1-active: accepted 0 points" >&2; FAIL=$((FAIL + 1)); }

echo
echo "kind tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
