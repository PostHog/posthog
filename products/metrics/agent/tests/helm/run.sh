#!/bin/sh
# Behavior tests + golden diff for the posthog-metrics-agent Helm chart.
# Usage: products/metrics/agent/tests/helm/run.sh [--update-golden]
set -u
cd "$(dirname "$0")"
CHART=../../chart/posthog-metrics-agent
# Read from the chart so a version bump doesn't have to touch this file.
APP_VERSION=$(awk '/^appVersion:/{print $2}' "$CHART/Chart.yaml")
PASS=0
FAIL=0

render() {
    helm template test-release "$CHART" "$@" 2>&1
}

assert_contains() {
    name=$1
    needle=$2
    haystack=$3
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        echo "PASS $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL $name: output does not contain '$needle'"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    name=$1
    needle=$2
    haystack=$3
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        echo "FAIL $name: output unexpectedly contains '$needle'"
        FAIL=$((FAIL + 1))
    else
        echo "PASS $name"
        PASS=$((PASS + 1))
    fi
}

# --- defaults: annotation discovery on, chart-managed secret ---
out=$(render --set posthog.apiKey=phc_test)
assert_contains default-deployment 'kind: Deployment' "$out"
assert_contains default-configmap 'kind: ConfigMap' "$out"
assert_contains default-secret 'kind: Secret' "$out"
assert_contains default-clusterrole 'kind: ClusterRole' "$out"
assert_contains default-clusterrolebinding 'kind: ClusterRoleBinding' "$out"
assert_contains default-serviceaccount 'kind: ServiceAccount' "$out"
assert_contains default-single-replica 'replicas: 1' "$out"
assert_contains default-pod-discovery 'kubernetes_sd_configs' "$out"
assert_contains default-annotation-relabel '__meta_kubernetes_pod_annotation_prometheus_io_scrape' "$out"
assert_contains default-openmetrics-pinned 'scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]' "$out"
assert_contains default-key-via-env-reference '${env:POSTHOG_API_KEY}' "$out"
assert_contains default-key-in-secret 'posthog-api-key:' "$out"
assert_contains default-secret-env-ref 'secretKeyRef' "$out"
assert_contains default-config-checksum 'checksum/config:' "$out"
assert_contains default-secret-checksum 'checksum/secret:' "$out"
assert_contains default-health-probe '13133' "$out"
assert_contains default-ingest-route '/i/v1/metrics' "$out"
# The default image tag is the pinned appVersion, never a floating tag.
assert_contains default-pinned-image "image: 'posthog/metrics-agent:$APP_VERSION'" "$out"
assert_not_contains default-no-latest-tag ':latest' "$out"
# Restricted Pod Security Standard: these fields are required for admission.
assert_contains default-run-as-nonroot 'runAsNonRoot: true' "$out"
assert_contains default-no-priv-escalation 'allowPrivilegeEscalation: false' "$out"
assert_contains default-seccomp 'type: RuntimeDefault' "$out"
assert_contains default-drop-all-caps '- ALL' "$out"
# The raw API key must appear only in the Secret (base64), never in the ConfigMap.
configmap_only=$(printf '%s' "$out" | awk '/^kind: Secret$/{skip=1} /^---$/{skip=0} !skip')
assert_not_contains default-key-not-in-configmap 'phc_test' "$configmap_only"

# --- existingSecret: chart must not create its own Secret ---
out=$(render --set posthog.existingSecret=my-secret)
assert_not_contains existing-secret-no-secret 'kind: Secret' "$out"
assert_contains existing-secret-referenced 'name: my-secret' "$out"

# --- rotating the API key must change the pod spec so the pod restarts ---
sum_a=$(render --set posthog.apiKey=phc_a | grep 'checksum/secret:')
sum_b=$(render --set posthog.apiKey=phc_b | grep 'checksum/secret:')
if [ -n "$sum_a" ] && [ "$sum_a" != "$sum_b" ]; then
    echo "PASS secret-checksum-tracks-key"
    PASS=$((PASS + 1))
else
    echo "FAIL secret-checksum-tracks-key: checksum/secret did not change with the API key"
    FAIL=$((FAIL + 1))
fi

# --- static targets + extra scrape configs, discovery off ---
out=$(render --set posthog.apiKey=phc_test -f values/static-targets.yaml)
assert_not_contains static-no-discovery 'kubernetes_sd_configs' "$out"
assert_contains static-target-present "'static-svc:9090'" "$out"
assert_contains static-extra-job 'job_name: extra-job' "$out"

# --- rbac disabled ---
out=$(render --set posthog.apiKey=phc_test --set rbac.create=false --set serviceAccount.create=false --set serviceAccount.name=external-sa)
assert_not_contains no-rbac-clusterrole 'kind: ClusterRole' "$out"
assert_not_contains no-rbac-serviceaccount 'kind: ServiceAccount' "$out"
assert_contains no-rbac-sa-referenced 'serviceAccountName: external-sa' "$out"

# --- an unmanaged service account must be named explicitly, never 'default' ---
out=$(render --set posthog.apiKey=phc_test --set serviceAccount.create=false)
assert_contains sa-name-required 'serviceAccount.name is required' "$out"

# --- eu host flows into the rendered collector config ---
out=$(render --set posthog.apiKey=phc_test --set posthog.host=https://eu.i.posthog.com)
assert_contains eu-host 'https://eu.i.posthog.com/i/v1/metrics' "$out"

# --- ingest path override (proxies, test sinks) ---
out=$(render --set posthog.apiKey=phc_test --set posthog.host=http://sink:4318 --set posthog.ingestPath=/v1/metrics)
assert_contains ingest-path-override 'http://sink:4318/v1/metrics' "$out"

# --- default: single instance, no sharding machinery ---
out=$(render --set posthog.apiKey=phc_test)
assert_contains default-is-deployment 'kind: Deployment' "$out"
assert_not_contains default-no-statefulset 'kind: StatefulSet' "$out"
assert_not_contains default-no-hashmod 'action: hashmod' "$out"

# --- shards > 1: StatefulSet fleet partitioning targets via hashmod ---
out=$(render --set posthog.apiKey=phc_test --set shards=3)
assert_contains sharded-statefulset 'kind: StatefulSet' "$out"
assert_not_contains sharded-no-deployment 'kind: Deployment' "$out"
assert_contains sharded-replicas 'replicas: 3' "$out"
assert_contains sharded-headless-service 'clusterIP: None' "$out"
assert_contains sharded-modulus 'modulus: 3' "$out"
assert_contains sharded-index-env "regex: '\${env:SHARD_INDEX}'" "$out"
assert_contains sharded-hashmod 'action: hashmod' "$out"
assert_contains sharded-count-env 'name: SHARD_COUNT' "$out"
# Every chart-generated scrape job must be sharded, or a job would be
# scraped by all shards (extraScrapeConfigs are verbatim: sharding those
# is the author's responsibility, called out in values.yaml).
static=$(render --set posthog.apiKey=phc_test --set shards=3 -f values/static-targets.yaml)
assert_contains sharded-static-job-hashmod 'action: hashmod' "$static"

# --- podEnv passthrough: extra agent env vars ---
out=$(render --set posthog.apiKey=phc_test --set podEnv.POSTHOG_DEBUG=1 --set podEnv.SCRAPE_JOB_NAME=custom)
assert_contains podenv-debug 'name: POSTHOG_DEBUG' "$out"
assert_contains podenv-jobname 'name: SCRAPE_JOB_NAME' "$out"
assert_contains podenv-jobname-value 'value: "custom"' "$out"

# --- persistence: disk-backed delivery queue ---
out=$(render --set posthog.apiKey=phc_test)
assert_not_contains default-no-persist-env 'PERSIST_QUEUE' "$out"
assert_not_contains default-no-pvc 'kind: PersistentVolumeClaim' "$out"

out=$(render --set posthog.apiKey=phc_test --set persistence.enabled=true)
assert_contains persist-env 'name: PERSIST_QUEUE' "$out"
assert_contains persist-pvc 'kind: PersistentVolumeClaim' "$out"
assert_contains persist-mount 'mountPath: /var/lib/posthog-agent' "$out"
assert_contains persist-fsgroup 'fsGroup: 10001' "$out"
assert_contains persist-size 'storage: 10Gi' "$out"
# The mounted config itself must wire the queue: the chart's full-config
# override means an unreferenced PERSIST_QUEUE env would silently do nothing.
assert_contains persist-config-queue 'storage: file_storage' "$out"
assert_contains persist-config-extension 'file_storage:' "$out"

# Default (no persistence) must not carry the queue wiring.
out=$(render --set posthog.apiKey=phc_test)
assert_not_contains default-no-queue 'sending_queue' "$out"
assert_not_contains default-no-file-storage 'file_storage' "$out"

# Self-telemetry endpoint is exposed for operator monitoring.
assert_contains telemetry-config 'port: 8888' "$out"
assert_contains telemetry-port 'containerPort: 8888' "$out"

# Sharded + persistent: each pod gets its own queue via claim templates.
out=$(render --set posthog.apiKey=phc_test --set persistence.enabled=true --set shards=3)
assert_contains persist-sharded-claim-template 'volumeClaimTemplates:' "$out"
assert_not_contains persist-sharded-no-standalone-pvc 'kind: PersistentVolumeClaim' "$out"

# --- golden drift guard for the fully default render ---
# Blank lines are stripped before comparing: helm 3 and 4 disagree on
# blank-line placement between documents, and that isn't drift we care about.
default=$(render --set posthog.apiKey=phc_test | grep -v '^[[:space:]]*$')
if [ "${1:-}" = "--update-golden" ]; then
    printf '%s\n' "$default" >golden/default.yaml
    echo "updated golden/default.yaml"
elif printf '%s\n' "$default" | diff -u golden/default.yaml -; then
    echo "PASS golden-default"
    PASS=$((PASS + 1))
else
    echo "FAIL golden-default: rendered output drifted (rerun with --update-golden if intentional)"
    FAIL=$((FAIL + 1))
fi

echo
echo "helm tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
