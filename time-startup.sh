#!/bin/bash
set -e

echo "=== Backend Startup Time Comparison ==="
echo ""

# Function to wait for server and return startup time
time_startup() {
    local name=$1
    local start_script=$2
    local url="http://127.0.0.1:8000/login"
    local max_wait=60  # 1 minute max

    # Kill everything before starting
    echo "[$name] Killing any existing servers..." >&2
    pkill -9 -f "granian|uvicorn|start-backend|debugpy" 2>/dev/null || true
    sleep 3
    echo "[$name] All processes killed, starting fresh..." >&2

    # Record start time
    local start_time=$(date +%s)
    echo "[$name] Start time: $start_time" >&2

    # Start server in background (DEBUG=1 like normal dev)
    env DEBUG=1 $start_script > /tmp/startup-${name}.log 2>&1 &
    local pid=$!
    echo "[$name] Server process started with PID $pid" >&2

    # Wait for server to respond
    local attempt=0
    while [ $attempt -lt $max_wait ]; do
        attempt=$((attempt + 1))

        # Try to curl and capture response
        http_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")

        if [ "$http_code" = "200" ] || [ "$http_code" = "302" ]; then
            local end_time=$(date +%s)
            local startup_time=$((end_time - start_time))
            echo "[$name] ✓ Server ready in ${startup_time}s (attempt #$attempt, HTTP $http_code)" >&2

            # Verify it's real by checking log for request
            echo "[$name] Verifying request in log..." >&2
            if grep -q "request_finished.*code=200" /tmp/startup-${name}.log 2>/dev/null; then
                echo "[$name] ✓ Confirmed: Found successful request in log" >&2
            else
                echo "[$name] ⚠ Warning: No request found in log, may be hitting stale server" >&2
            fi

            # Kill the server
            echo "[$name] Killing server..." >&2
            kill -9 $pid 2>/dev/null || true
            pkill -9 -f "$name|granian|uvicorn" 2>/dev/null || true
            wait $pid 2>/dev/null || true
            sleep 3

            echo "$startup_time"
            return 0
        else
            if [ $((attempt % 5)) -eq 0 ]; then
                local elapsed=$((attempt))
                echo "[$name] Still waiting... (attempt #$attempt, HTTP $http_code, ${elapsed}s elapsed)" >&2
            fi
        fi

        sleep 1
    done

    echo "[$name] ✗ Server failed to start within ${max_wait}s" >&2
    echo "[$name] Last 30 lines of log:" >&2
    tail -30 /tmp/startup-${name}.log >&2
    kill -9 $pid 2>/dev/null || true
    pkill -9 -f "$name|granian|uvicorn" 2>/dev/null || true
    wait $pid 2>/dev/null || true
    return 1
}

# Time Granian (current worktree)
echo "--- Testing Granian (this worktree) ---"
cd /Users/julian/workspace/django5
granian_time=$(time_startup "Granian" "./bin/start-backend")
echo ""

# Time Uvicorn (master)
echo "--- Testing Uvicorn (master worktree) ---"
cd ~/workspace/posthog
uvicorn_time=$(time_startup "Uvicorn" "./bin/start-backend")
echo ""

# Summary
echo "=== Results ==="
echo "Granian: ${granian_time}s"
echo "Uvicorn: ${uvicorn_time}s"
echo ""

# Calculate difference (simple integer arithmetic)
if [ -n "$granian_time" ] && [ -n "$uvicorn_time" ]; then
    diff=$((granian_time - uvicorn_time))

    if [ $granian_time -lt $uvicorn_time ]; then
        abs_diff=$((uvicorn_time - granian_time))
        percent=$(( (abs_diff * 100) / uvicorn_time ))
        echo "✓ Granian is faster by ${abs_diff}s (~${percent}% improvement)"
    elif [ $granian_time -gt $uvicorn_time ]; then
        abs_diff=$((granian_time - uvicorn_time))
        percent=$(( (abs_diff * 100) / granian_time ))
        echo "✗ Uvicorn is faster by ${abs_diff}s (~${percent}%)"
    else
        echo "Both servers have the same startup time"
    fi
fi
