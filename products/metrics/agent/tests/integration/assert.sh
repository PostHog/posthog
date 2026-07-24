#!/bin/sh
# Asserts the sink received the scraped metrics with exemplars intact.
# Expects the compose stack from docker-compose.yml to be running.
set -eu
cd "$(dirname "$0")"
FILE=out/metrics.json

for _ in $(seq 1 60); do
    if [ -s "$FILE" ] && grep -q http_requests_total "$FILE" && grep -q exemplars "$FILE"; then
        break
    fi
    sleep 1
done

if [ ! -s "$FILE" ]; then
    echo "FAIL: sink never received metrics (out/metrics.json empty)" >&2
    exit 1
fi

fail=0
check() {
    name=$1
    expected=$2
    actual=$3
    if [ "$actual" = "$expected" ]; then
        echo "PASS $name"
    else
        echo "FAIL $name: expected '$expected', got '$actual'" >&2
        fail=1
    fi
}

metrics='[.[].resourceMetrics[].scopeMetrics[].metrics[]]'

names=$(jq -rs "$metrics | [.[].name] | unique | join(\",\")" "$FILE")
echo "metric names seen: $names"
for wanted in http_requests_total request_duration_seconds cpu_usage; do
    case ",$names," in
        *",$wanted,"*) echo "PASS metric $wanted present" ;;
        *)
            echo "FAIL metric $wanted missing" >&2
            fail=1
            ;;
    esac
done

check counter-value 42 "$(jq -rs "$metrics | [.[] | select(.name == \"http_requests_total\") | .sum.dataPoints[].asDouble] | first" "$FILE")"

check counter-exemplar-trace-id 4bf92f3577b34da6a3ce929d0e0e4736 \
    "$(jq -rs "$metrics | [.[] | select(.name == \"http_requests_total\") | .sum.dataPoints[].exemplars[]?.traceId] | first" "$FILE")"

check counter-exemplar-span-id 00f067aa0ba902b7 \
    "$(jq -rs "$metrics | [.[] | select(.name == \"http_requests_total\") | .sum.dataPoints[].exemplars[]?.spanId] | first" "$FILE")"

check histogram-exemplar-trace-id 4bf92f3577b34da6a3ce929d0e0e4736 \
    "$(jq -rs "$metrics | [.[] | select(.name == \"request_duration_seconds\") | .histogram.dataPoints[].exemplars[]?.traceId] | first" "$FILE")"

# job_name becomes the service.name resource attribute (and service_name in PostHog).
check service-name posthog-metrics-agent \
    "$(jq -rs '[.[].resourceMetrics[].resource.attributes[] | select(.key == "service.name") | .value.stringValue] | first' "$FILE")"

[ "$fail" -eq 0 ] && echo "integration assertions passed"
exit "$fail"
