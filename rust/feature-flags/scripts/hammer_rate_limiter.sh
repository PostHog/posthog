#!/bin/bash
#
# Hammer the feature flags endpoint with many unique tokens to test rate limiter cleanup.
#
# This script generates many unique tokens and sends requests to populate the rate
# limiter's internal state. Use it to verify that the periodic cleanup task correctly
# removes stale entries and prevents unbounded memory growth.
#
# PREREQUISITES:
#   1. GeoIP database must exist at share/GeoLite2-City.mmdb
#      Download test DB: curl -sL "https://github.com/maxmind/MaxMind-DB/raw/main/test-data/GeoIP2-City-Test.mmdb" -o share/GeoLite2-City.mmdb
#
#   2. Rate limiting must be enabled (disabled by default):
#      FLAGS_RATE_LIMIT_ENABLED=true FLAGS_IP_RATE_LIMIT_ENABLED=true
#
# TESTING THE CLEANUP:
#
#   Terminal 1 - Start the server with a short cleanup interval for testing:
#     FLAGS_RATE_LIMIT_ENABLED=true FLAGS_IP_RATE_LIMIT_ENABLED=true \
#     RATE_LIMITER_CLEANUP_INTERVAL_SECS=5 \
#     RUST_LOG=debug cargo run 2>&1 | grep -E "(cleanup|entries|Rate limiter)"
#
#   Terminal 2 - Run this script:
#     ./scripts/hammer_rate_limiter.sh
#
#   Expected output in Terminal 1:
#     - token_entries increases during the hammer run (e.g., 20-100+ entries)
#     - ip_entries increases as random IPs are generated via X-Forwarded-For
#     - After requests stop, both counters drop to 0 on the next cleanup cycle
#
# OPTIONS:
#   -n NUM_TOKENS    Number of unique tokens to generate (default: 1000)
#   -r REQUESTS      Requests per token (default: 5)
#   -h HOST          Target host (default: http://localhost:3001)
#   -c CONCURRENCY   Concurrent requests (default: 50)

set -e

# Defaults
NUM_TOKENS=1000
REQUESTS_PER_TOKEN=5
HOST="http://localhost:3001"
CONCURRENCY=50

# Parse args
while getopts "n:r:h:c:" opt; do
    case $opt in
        n) NUM_TOKENS=$OPTARG ;;
        r) REQUESTS_PER_TOKEN=$OPTARG ;;
        h) HOST=$OPTARG ;;
        c) CONCURRENCY=$OPTARG ;;
        *) echo "Usage: $0 [-n num_tokens] [-r requests_per_token] [-h host] [-c concurrency]" && exit 1 ;;
    esac
done

ENDPOINT="$HOST/flags"

echo "=== Rate Limiter Hammer Test ==="
echo "Host:              $HOST"
echo "Endpoint:          $ENDPOINT"
echo "Unique tokens:     $NUM_TOKENS"
echo "Requests/token:    $REQUESTS_PER_TOKEN"
echo "Total requests:    $((NUM_TOKENS * REQUESTS_PER_TOKEN))"
echo "Concurrency:       $CONCURRENCY"
echo ""
echo "Starting in 3 seconds... (Ctrl+C to cancel)"
sleep 3

# Generate request function
make_request() {
    local token=$1
    local ip=$2
    curl -s -o /dev/null \
        -X POST "$ENDPOINT" \
        -H "Content-Type: application/json" \
        -H "X-Forwarded-For: $ip" \
        -d "{\"token\": \"$token\", \"distinct_id\": \"test-user\"}"
}

# Generate a random IP address
random_ip() {
    echo "$((RANDOM % 256)).$((RANDOM % 256)).$((RANDOM % 256)).$((RANDOM % 256))"
}

export -f make_request random_ip
export ENDPOINT

# Track progress
TOTAL=$((NUM_TOKENS * REQUESTS_PER_TOKEN))
COUNT=0
START_TIME=$(date +%s)

echo "Sending requests..."
echo ""

# Generate and send requests
for i in $(seq 1 $NUM_TOKENS); do
    # Generate unique token (using openssl for portability across Linux/macOS)
    TOKEN="phc_test_token_$(printf '%06d' $i)_$(openssl rand -hex 4)"

    for j in $(seq 1 $REQUESTS_PER_TOKEN); do
        # Run in background up to CONCURRENCY limit
        while [ $(jobs -r | wc -l) -ge $CONCURRENCY ]; do
            sleep 0.01
        done

        make_request "$TOKEN" "$(random_ip)" &

        COUNT=$((COUNT + 1))
        if [ $((COUNT % 100)) -eq 0 ]; then
            ELAPSED=$(($(date +%s) - START_TIME))
            RATE=$((COUNT / (ELAPSED + 1)))
            printf "\rProgress: %d/%d requests (%d req/s)" "$COUNT" "$TOTAL" "$RATE"
        fi
    done
done

# Wait for remaining requests
wait

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo ""
echo "=== Complete ==="
echo "Total requests:    $TOTAL"
echo "Time elapsed:      ${ELAPSED}s"
echo "Average rate:      $((TOTAL / (ELAPSED + 1))) req/s"
echo ""
echo "Now wait 60-70 seconds for cleanup to run, and check the logs for:"
echo "  - 'Rate limiter cleanup completed'"
echo "  - 'token_entries', 'ip_entries', 'definitions_entries'"
echo ""
echo "The entry counts should drop significantly after cleanup."
