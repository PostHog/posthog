#!/bin/sh
# Completeness + disjointness assertions over the per-shard sink files.
set -eu
cd "$(dirname "$0")"

FARM_PORTS=$1
FARM_SERIES_PER_TARGET=$2
ELAPSED=$3
EXPECTED=$((FARM_PORTS * FARM_SERIES_PER_TARGET))

fail=0

# Every farm_series datapoint carries target+series labels; a shard's set is
# the unique (target, series) pairs it delivered.
shard_series() {
    jq -rs '
        [.[].resourceMetrics[].scopeMetrics[].metrics[]
         | select(.name == "farm_series")
         | .gauge.dataPoints[]
         | ([.attributes[] | select(.key == "target") | .value.stringValue][0])
           + ":" +
           ([.attributes[] | select(.key == "series") | .value.stringValue][0])]
        | unique | .[]
    ' "$1" 2>/dev/null
}

total_datapoints() {
    jq -rs '
        [.[].resourceMetrics[].scopeMetrics[].metrics[]
         | select(.name == "farm_series")
         | .gauge.dataPoints[]] | length
    ' "$1" 2>/dev/null
}

union_file=$(mktemp)
sum_unique=0
datapoints=0
for i in 0 1 2 3; do
    f="out/shard$i.json"
    shard_series "$f" >"/tmp/shard$i.series"
    count=$(wc -l <"/tmp/shard$i.series" | tr -d ' ')
    dp=$(total_datapoints "$f")
    datapoints=$((datapoints + dp))
    echo "shard$i: $count unique series, $dp datapoints"
    sum_unique=$((sum_unique + count))
    cat "/tmp/shard$i.series" >>"$union_file"
done

union=$(sort -u "$union_file" | wc -l | tr -d ' ')

if [ "$union" -eq "$EXPECTED" ]; then
    echo "PASS completeness: union covers all $EXPECTED series"
else
    echo "FAIL completeness: union $union != expected $EXPECTED" >&2
    fail=1
fi

# If any series were delivered by two shards, the per-shard sum exceeds the union.
if [ "$sum_unique" -eq "$union" ]; then
    echo "PASS disjointness: no series delivered by more than one shard"
else
    echo "FAIL disjointness: per-shard sum $sum_unique != union $union (overlap)" >&2
    fail=1
fi

# No shard may sit idle: hashmod should spread targets roughly evenly.
for i in 0 1 2 3; do
    count=$(wc -l <"/tmp/shard$i.series" | tr -d ' ')
    if [ "$count" -eq 0 ]; then
        echo "FAIL balance: shard$i delivered nothing" >&2
        fail=1
    fi
done
[ "$fail" -eq 0 ] && echo "PASS balance: every shard carried load"

echo "throughput: $datapoints datapoints across the fleet in ~${ELAPSED}s ($((datapoints / (ELAPSED > 0 ? ELAPSED : 1))) samples/sec aggregate)"

[ "$fail" -eq 0 ] && echo "scale assertions passed"
exit "$fail"
