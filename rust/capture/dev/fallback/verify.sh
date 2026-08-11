#!/bin/sh
set -eu

base_url="${CAPTURE_URL:-http://localhost:3308}"
proxy_url="${TOXIPROXY_URL:-http://localhost:8474}"
request_id="00000000-0000-4000-8000-$(printf '%012d' $$)"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
payload="{\"created_at\":\"${timestamp}\",\"batch\":[{\"uuid\":\"00000000-0000-4000-8000-$(printf '%012d' $$)\",\"event\":\"fallback harness event\",\"distinct_id\":\"fallback-harness\",\"timestamp\":\"${timestamp}\",\"options\":{},\"properties\":{}}]}"

capture() {
    curl --fail --silent --show-error \
        --header 'Authorization: Bearer phc_fallback_harness' \
        --header 'Content-Type: application/json' \
        --header 'PostHog-Sdk-Info: fallback-harness/1.0.0' \
        --header 'PostHog-Attempt: 1' \
        --header "PostHog-Request-Id: ${request_id}" \
        --header "PostHog-Request-Timestamp: ${timestamp}" \
        --header 'User-Agent: fallback-harness/1.0.0' \
        --data "$payload" \
        "${base_url}/i/v1/analytics/events"
}

set_proxy() {
    curl --fail --silent --show-error \
        --request POST \
        --header 'Content-Type: application/json' \
        --data "{\"enabled\":$1}" \
        "${proxy_url}/proxies/primary" >/dev/null
}

wait_for_metric() {
    deadline=$(($(date +%s) + 20))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if curl --fail --silent "${base_url}/metrics" | grep 'capture_v1_kafka_broker_connected.*cluster="msk"' | grep -q ' 0$'; then
            return 0
        fi
        sleep 1
    done
    echo "Capture did not report the primary Kafka broker as disconnected. Check ${base_url}/metrics." >&2
    return 1
}

trap 'set_proxy true' EXIT

healthy_response="$(capture)"
if ! echo "$healthy_response" | grep -q '"result":"ok"'; then
    echo "Capture did not publish the healthy event: ${healthy_response}" >&2
    exit 1
fi

set_proxy false
wait_for_metric

degraded_response="$(capture)"
if echo "$degraded_response" | grep -q '"result":"ok"'; then
    echo "Capture reported a successful publish while the primary Kafka proxy was disabled." >&2
    exit 1
fi

echo "Capture reported the primary Kafka degradation and rejected the affected event."
