#!/bin/sh
# Asserts the sink received datapoints scraped before the agent restart.
set -eu
cd "$(dirname "$0")"

RESTART_NS=$1
FILE=out/metrics.json

datapoints='[.[].resourceMetrics[].scopeMetrics[].metrics[]
    | select(.name == "http_requests_total")
    | .sum.dataPoints[]]'

total=$(jq -rs "$datapoints | length" "$FILE")
pre_restart=$(jq -rs "$datapoints | [.[] | select((.timeUnixNano | tonumber) < $RESTART_NS)] | length" "$FILE")

echo "datapoints delivered: $total total, $pre_restart scraped before the restart"

fail=0
if [ "$total" -gt 0 ]; then
    echo "PASS delivery: queue drained into the recovered sink"
else
    echo "FAIL delivery: nothing arrived" >&2
    fail=1
fi

if [ "$pre_restart" -gt 0 ]; then
    echo "PASS durability: pre-restart samples survived the process death"
else
    echo "FAIL durability: only post-restart samples arrived (queue was not persistent)" >&2
    fail=1
fi

[ "$fail" -eq 0 ] && echo "durability assertions passed"
exit "$fail"
