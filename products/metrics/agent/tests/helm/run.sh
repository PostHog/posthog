#!/bin/sh
# Behavior tests + golden diff for the posthog-metrics-agent Helm chart.
# Usage: products/metrics/agent/tests/helm/run.sh [--update-golden]
set -u
cd "$(dirname "$0")"
CHART=../../chart/posthog-metrics-agent
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
assert_contains default-health-probe '13133' "$out"
assert_contains default-ingest-route '/i/v1/metrics' "$out"
# The raw API key must appear only in the Secret (base64), never in the ConfigMap.
configmap_only=$(printf '%s' "$out" | awk '/^kind: Secret$/{skip=1} /^---$/{skip=0} !skip')
assert_not_contains default-key-not-in-configmap 'phc_test' "$configmap_only"

# --- existingSecret: chart must not create its own Secret ---
out=$(render --set posthog.existingSecret=my-secret)
assert_not_contains existing-secret-no-secret 'kind: Secret' "$out"
assert_contains existing-secret-referenced 'name: my-secret' "$out"

# --- static targets + extra scrape configs, discovery off ---
out=$(render --set posthog.apiKey=phc_test -f values/static-targets.yaml)
assert_not_contains static-no-discovery 'kubernetes_sd_configs' "$out"
assert_contains static-target-present "'static-svc:9090'" "$out"
assert_contains static-extra-job 'job_name: extra-job' "$out"

# --- rbac disabled ---
out=$(render --set posthog.apiKey=phc_test --set rbac.create=false --set serviceAccount.create=false)
assert_not_contains no-rbac-clusterrole 'kind: ClusterRole' "$out"
assert_not_contains no-rbac-serviceaccount 'kind: ServiceAccount' "$out"

# --- eu host flows into the rendered collector config ---
out=$(render --set posthog.apiKey=phc_test --set posthog.host=https://eu.i.posthog.com)
assert_contains eu-host 'https://eu.i.posthog.com/i/v1/metrics' "$out"

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
