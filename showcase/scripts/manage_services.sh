#!/usr/bin/env bash
# ==============================================================================
# showcase/scripts/manage_services.sh
# Zero-Daemon Rootless Microservice Orchestrator on Ephemeral tmpfs (/dev/shm).
# Manages: PostgreSQL 15, Redis, ClickHouse, Tansu (Kafka), Temporal, S3 (SeaweedFS)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
verify_enve

ACTION="${1:-status}"
shift || true

PID_DIR="${SHOWCASE_TMPFS}/pids"
LOG_DIR="${SHOWCASE_TMPFS}/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

# Helper: poll check command until success or timeout
wait_for_condition() {
    local name="$1"
    local check_cmd="$2"
    local log_file="$3"
    local max_attempts="${4:-60}"
    local interval="0.05"

    for ((i=1; i<=max_attempts; i++)); do
        if eval "$check_cmd" >/dev/null 2>&1; then
            return 0
        fi
        sleep "$interval"
    done

    echo "✗ FATAL: $name failed probe after $((max_attempts * 50 / 1000))s!" >&2
    if [[ -n "$log_file" && -f "$log_file" ]]; then
        echo "=== [LOG: $name ($log_file)] ===" >&2
        tail -n 30 "$log_file" >&2 || true
        echo "=================================" >&2
    fi
    return 1
}

# Measure RSS in MB for a PID
get_pid_rss_mb() {
    local pid="$1"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        local rss_kb
        rss_kb=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ' || echo "0")
        awk "BEGIN {printf \"%.1f\", ${rss_kb:-0} / 1024}"
    else
        echo "0.0"
    fi
}

start_services() {
    local start_all_ts
    start_all_ts=$(date +%s%N)

    declare -A SERVICE_READY_MS
    declare -A SERVICE_RSS_MB
    declare -A SERVICE_STATUS

    # --------------------------------------------------------------------------
    # 1. PostgreSQL (tmpfs)
    # --------------------------------------------------------------------------
    local t0_pg
    t0_pg=$(date +%s%N)
    local pg_data="${SHOWCASE_TMPFS}/pg_${PG_PORT}"
    local pg_log="${LOG_DIR}/postgres.log"

    if pg_isready -h 127.0.0.1 -p "$PG_PORT" -U posthog >/dev/null 2>&1; then
        echo "ℹ PostgreSQL already running on port ${PG_PORT}"
        SERVICE_STATUS["postgres"]="running (reused)"
        SERVICE_READY_MS["postgres"]="0"
    else
        echo "▶ Starting rootless PostgreSQL cluster on tmpfs..."
        rm -rf "$pg_data"
        mkdir -p "$pg_data"
        initdb -D "$pg_data" --auth=trust --username=posthog --no-sync >/dev/null 2>&1
        setsid postgres -D "$pg_data" -h 127.0.0.1 -p "$PG_PORT" -k /tmp -c listen_addresses='127.0.0.1' -c fsync=off -c synchronous_commit=off -c max_locks_per_transaction=1024 > "$pg_log" 2>&1 &
        local pg_pid=$!
        disown "$pg_pid" 2>/dev/null || true
        echo "$pg_pid" > "$PID_DIR/postgres.pid"

        wait_for_condition "PostgreSQL Health" "pg_isready -h 127.0.0.1 -p $PG_PORT -U posthog" "$pg_log" 60
        createdb -h localhost -p "$PG_PORT" -U posthog posthog 2>/dev/null || true
        createdb -h localhost -p "$PG_PORT" -U posthog test_posthog 2>/dev/null || true
        createdb -h localhost -p "$PG_PORT" -U posthog test_posthog_persons 2>/dev/null || true

        if [ -f "$REPO_ROOT/.postgres-backups/schema-latest.sql.gz" ]; then
            gunzip -c "$REPO_ROOT/.postgres-backups/schema-latest.sql.gz" | psql -h localhost -p "$PG_PORT" -U posthog -q -d test_posthog >/dev/null 2>&1 || true
        fi
        wait_for_condition "PostgreSQL Query" "psql -h localhost -p $PG_PORT -U posthog -d postgres -c 'SELECT 1;'" "$pg_log" 30

        local t1_pg
        t1_pg=$(date +%s%N)
        SERVICE_READY_MS["postgres"]=$(( (t1_pg - t0_pg) / 1000000 ))
        SERVICE_STATUS["postgres"]="health: ok, readiness: ok"
        echo "✓ Live PostgreSQL running on port ${PG_PORT} (${SERVICE_STATUS["postgres"]})"
    fi
    local cur_pg_pid
    cur_pg_pid=$(cat "$PID_DIR/postgres.pid" 2>/dev/null || pgrep -f "postgres -D.*$PG_PORT" | head -n 1 || echo "")
    SERVICE_RSS_MB["postgres"]=$(get_pid_rss_mb "$cur_pg_pid")

    # --------------------------------------------------------------------------
    # 2. Redis (tmpfs)
    # --------------------------------------------------------------------------
    local t0_redis
    t0_redis=$(date +%s%N)
    local redis_dir="${SHOWCASE_TMPFS}/redis_${REDIS_PORT}"
    local redis_log="${LOG_DIR}/redis.log"

    if nc -z 127.0.0.1 "$REDIS_PORT" 2>/dev/null; then
        echo "ℹ Redis already running on port ${REDIS_PORT}"
        SERVICE_STATUS["redis"]="running (reused)"
        SERVICE_READY_MS["redis"]="0"
    else
        echo "▶ Starting rootless Redis server on tmpfs..."
        mkdir -p "$redis_dir"
        redis-server --port "$REDIS_PORT" --dir "$redis_dir" --save '' --appendonly no --daemonize yes --logfile "$redis_log" >/dev/null 2>&1
        wait_for_condition "Redis" "nc -z 127.0.0.1 $REDIS_PORT" "$redis_log" 40

        local t1_redis
        t1_redis=$(date +%s%N)
        SERVICE_READY_MS["redis"]=$(( (t1_redis - t0_redis) / 1000000 ))
        SERVICE_STATUS["redis"]="health: ok, readiness: ok"
        echo "✓ Live Redis running on port ${REDIS_PORT} (${SERVICE_STATUS["redis"]})"
    fi
    local cur_redis_pid
    cur_redis_pid=$(pgrep -f "redis-server.*$REDIS_PORT" | head -n 1 || echo "")
    if [[ -n "$cur_redis_pid" ]]; then echo "$cur_redis_pid" > "$PID_DIR/redis.pid"; fi
    SERVICE_RSS_MB["redis"]=$(get_pid_rss_mb "$cur_redis_pid")

    # --------------------------------------------------------------------------
    # 3. Tansu (Kafka broker) (tmpfs / in-memory)
    # --------------------------------------------------------------------------
    local t0_kafka
    t0_kafka=$(date +%s%N)
    local kafka_dir="${SHOWCASE_TMPFS}/kafka_${KAFKA_PORT}"
    local kafka_log="${LOG_DIR}/kafka.log"

    if nc -z 127.0.0.1 "$KAFKA_PORT" 2>/dev/null; then
        echo "ℹ Tansu Kafka broker already running on port ${KAFKA_PORT}"
        SERVICE_STATUS["kafka"]="running (reused)"
        SERVICE_READY_MS["kafka"]="0"
    else
        echo "▶ Starting rootless Tansu Kafka broker on 127.0.0.1:${KAFKA_PORT}..."
        mkdir -p "$kafka_dir"
        setsid tansu --listener-url "tcp://127.0.0.1:${KAFKA_PORT}" \
              --advertised-listener-url "tcp://127.0.0.1:${KAFKA_PORT}" \
              --storage-engine "memory://tansu/" \
              > "$kafka_log" 2>&1 &
        local kafka_pid=$!
        disown "$kafka_pid" 2>/dev/null || true
        echo "$kafka_pid" > "$PID_DIR/kafka.pid"

        wait_for_condition "Tansu Kafka" "nc -z 127.0.0.1 $KAFKA_PORT" "$kafka_log" 60
        # Provision common Kafka topics in background
        "$PYTHON_BIN" -c '
from kafka.admin import KafkaAdminClient, NewTopic
import re
try:
    with open("posthog/kafka_client/topics.py") as f:
        content = f.read()
    names = set(re.findall(r"\{KAFKA_PREFIX\}(.+?)\{SUFFIX\}", content))
    suffixes = ["_test"] + [f"_test_gw{i}" for i in range(16)]
    topics = [NewTopic(name=f"{n}{s}", num_partitions=1, replication_factor=1) for n in names for s in suffixes]
    admin = KafkaAdminClient(bootstrap_servers=["127.0.0.1:19092"])
    admin.create_topics(new_topics=topics)
except Exception:
    pass
' 2>/dev/null || true

        local t1_kafka
        t1_kafka=$(date +%s%N)
        SERVICE_READY_MS["kafka"]=$(( (t1_kafka - t0_kafka) / 1000000 ))
        SERVICE_STATUS["kafka"]="health: ok, readiness: ok"
        echo "✓ Live Tansu Kafka broker running on port ${KAFKA_PORT} (${SERVICE_STATUS["kafka"]})"
    fi
    local cur_kafka_pid
    cur_kafka_pid=$(cat "$PID_DIR/kafka.pid" 2>/dev/null || pgrep -f "tansu.*$KAFKA_PORT" | head -n 1 || echo "")
    SERVICE_RSS_MB["kafka"]=$(get_pid_rss_mb "$cur_kafka_pid")

    # --------------------------------------------------------------------------
    # 4. ClickHouse (tmpfs)
    # --------------------------------------------------------------------------
    local t0_ch
    t0_ch=$(date +%s%N)
    local ch_dir="${SHOWCASE_TMPFS}/ch_${CLICKHOUSE_HTTP_PORT}"
    local ch_log="${LOG_DIR}/clickhouse.log"

    if curl -s -f "http://127.0.0.1:${CLICKHOUSE_HTTP_PORT}/ping" 2>/dev/null | grep -q Ok; then
        echo "ℹ ClickHouse already running on port ${CLICKHOUSE_HTTP_PORT}"
        SERVICE_STATUS["clickhouse"]="running (reused)"
        SERVICE_READY_MS["clickhouse"]="0"
    else
        echo "▶ Starting rootless ClickHouse server on tmpfs..."
        rm -rf "$ch_dir"
        mkdir -p "$ch_dir/data" "$ch_dir/tmp" "$ch_dir/user_files" "$ch_dir/format_schemas" "$ch_dir/access" "$ch_dir/keeper/log" "$ch_dir/keeper/snapshots"
        ln -sf "$REPO_ROOT/posthog/user_scripts" "$ch_dir/data/user_scripts"
        mkdir -p /dev/shm/clickhouse/data && ln -sf "$REPO_ROOT/posthog/user_scripts" /dev/shm/clickhouse/data/user_scripts
        setsid env CLICKHOUSE_DATA_DIR="$ch_dir/data/" \
        CLICKHOUSE_TMP_DIR="$ch_dir/tmp/" \
        CLICKHOUSE_USER_FILES_DIR="$ch_dir/user_files/" \
        CLICKHOUSE_FORMAT_SCHEMA_DIR="$ch_dir/format_schemas/" \
        CLICKHOUSE_ACCESS_DIR="$ch_dir/access/" \
        CLICKHOUSE_KEEPER_LOG_DIR="$ch_dir/keeper/log" \
        CLICKHOUSE_KEEPER_SNAPSHOT_DIR="$ch_dir/keeper/snapshots" \
        KAFKA_HOSTS="127.0.0.1:$KAFKA_PORT" \
        clickhouse-server --config-file="$SHOWCASE_DIR/config/clickhouse.xml" > "$ch_log" 2>&1 &
        local ch_pid=$!
        disown "$ch_pid" 2>/dev/null || true
        echo "$ch_pid" > "$PID_DIR/clickhouse.pid"

        wait_for_condition "ClickHouse" "curl -s -f http://127.0.0.1:${CLICKHOUSE_HTTP_PORT}/ping | grep -q Ok" "$ch_log" 60
        curl -s --data-binary "CREATE DATABASE IF NOT EXISTS posthog_test" "http://127.0.0.1:${CLICKHOUSE_HTTP_PORT}/" >/dev/null 2>&1 || true

        local t1_ch
        t1_ch=$(date +%s%N)
        SERVICE_READY_MS["clickhouse"]=$(( (t1_ch - t0_ch) / 1000000 ))
        SERVICE_STATUS["clickhouse"]="health: ok, readiness: ok"
        echo "✓ Live ClickHouse running on ports ${CLICKHOUSE_HTTP_PORT} & ${CLICKHOUSE_TCP_PORT} (${SERVICE_STATUS["clickhouse"]})"
    fi
    local cur_ch_pid
    cur_ch_pid=$(cat "$PID_DIR/clickhouse.pid" 2>/dev/null || pgrep -f "clickhouse-server" | head -n 1 || echo "")
    SERVICE_RSS_MB["clickhouse"]=$(get_pid_rss_mb "$cur_ch_pid")

    # --------------------------------------------------------------------------
    # 5. Temporal Dev Server (tmpfs)
    # --------------------------------------------------------------------------
    local t0_temporal
    t0_temporal=$(date +%s%N)
    local temporal_dir="${SHOWCASE_TMPFS}/temporal_${TEMPORAL_PORT}"
    local temporal_log="${LOG_DIR}/temporal.log"

    if nc -z 127.0.0.1 "$TEMPORAL_PORT" 2>/dev/null; then
        echo "ℹ Temporal dev server already running on port ${TEMPORAL_PORT}"
        SERVICE_STATUS["temporal"]="running (reused)"
        SERVICE_READY_MS["temporal"]="0"
    else
        echo "▶ Starting rootless Temporal dev server on tmpfs..."
        mkdir -p "$temporal_dir"
        setsid temporal server start-dev --port "$TEMPORAL_PORT" --headless --db-filename "$temporal_dir/temporal.db" > "$temporal_log" 2>&1 &
        local temporal_pid=$!
        disown "$temporal_pid" 2>/dev/null || true
        echo "$temporal_pid" > "$PID_DIR/temporal.pid"

        wait_for_condition "Temporal" "nc -z 127.0.0.1 $TEMPORAL_PORT" "$temporal_log" 60

        local t1_temporal
        t1_temporal=$(date +%s%N)
        SERVICE_READY_MS["temporal"]=$(( (t1_temporal - t0_temporal) / 1000000 ))
        SERVICE_STATUS["temporal"]="health: ok, readiness: ok"
        echo "✓ Live Temporal dev server running on port ${TEMPORAL_PORT} (${SERVICE_STATUS["temporal"]})"
    fi
    local cur_temporal_pid
    cur_temporal_pid=$(cat "$PID_DIR/temporal.pid" 2>/dev/null || pgrep -f "temporal server.*$TEMPORAL_PORT" | head -n 1 || echo "")
    SERVICE_RSS_MB["temporal"]=$(get_pid_rss_mb "$cur_temporal_pid")

    # --------------------------------------------------------------------------
    # 6. S3 Object Storage: SeaweedFS (weed mini on tmpfs)
    # --------------------------------------------------------------------------
    local t0_s3
    t0_s3=$(date +%s%N)
    local s3_dir="${SHOWCASE_TMPFS}/s3_${OBJECT_STORAGE_PORT}"
    local s3_log="${LOG_DIR}/objectstorage.log"

    if nc -z 127.0.0.1 "$OBJECT_STORAGE_PORT" 2>/dev/null; then
        echo "ℹ SeaweedFS S3 object storage (weed mini) already running on port ${OBJECT_STORAGE_PORT}"
        SERVICE_STATUS["objectstorage"]="running (reused)"
        SERVICE_READY_MS["objectstorage"]="0"
    else
        echo "▶ Starting rootless SeaweedFS S3 object storage server (weed mini) on tmpfs..."
        mkdir -p "$s3_dir"
        setsid env AWS_ACCESS_KEY_ID="object_storage_root_user" AWS_SECRET_ACCESS_KEY="object_storage_root_password" S3_BUCKET="posthog,test-posthog,posthog-recordings,test-recordings" \
        weed mini -ip=127.0.0.1 -ip.bind=127.0.0.1 -dir="$s3_dir" -s3.port="$OBJECT_STORAGE_PORT" -bucket="posthog,test-posthog,posthog-recordings,test-recordings" > "$s3_log" 2>&1 &
        local s3_pid=$!
        disown "$s3_pid" 2>/dev/null || true
        echo "$s3_pid" > "$PID_DIR/objectstorage.pid"

        wait_for_condition "SeaweedFS S3 (weed mini)" "nc -z 127.0.0.1 $OBJECT_STORAGE_PORT" "$s3_log" 60

        local t1_s3
        t1_s3=$(date +%s%N)
        SERVICE_READY_MS["objectstorage"]=$(( (t1_s3 - t0_s3) / 1000000 ))
        SERVICE_STATUS["objectstorage"]="health: ok, readiness: ok"
        echo "✓ Live SeaweedFS S3 object storage running on port ${OBJECT_STORAGE_PORT} (${SERVICE_STATUS["objectstorage"]})"
    fi
    local cur_s3_pid
    cur_s3_pid=$(cat "$PID_DIR/objectstorage.pid" 2>/dev/null || pgrep -f "weed mini" | head -n 1 || echo "")
    SERVICE_RSS_MB["objectstorage"]=$(get_pid_rss_mb "$cur_s3_pid")

    # --------------------------------------------------------------------------
    # TELEMETRY & RESOURCE SUMMARY TABLE
    # --------------------------------------------------------------------------
    local end_all_ts
    end_all_ts=$(date +%s%N)
    local total_all_ms=$(( (end_all_ts - start_all_ts) / 1000000 ))
    local total_all_sec
    total_all_sec=$(awk "BEGIN {printf \"%.2f\", $total_all_ms / 1000}")

    local total_rss_mb=0
    for s in postgres redis kafka clickhouse temporal objectstorage; do
        total_rss_mb=$(awk "BEGIN {printf \"%.1f\", $total_rss_mb + ${SERVICE_RSS_MB[$s]:-0}}")
    done

    echo ""
    echo "========================================================================================================="
    echo "  📊 Service Resource Telemetry & Timings (tmpfs / user-space)"
    echo "========================================================================================================="
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "SERVICE" "PORT" "STARTUP" "RAM (RSS)" "HEALTH / READINESS"
    echo "  ───────────────────────────────────────────────────────────────────────────────────────────────────────"
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "postgres" "${PG_PORT}" "${SERVICE_READY_MS[postgres]}ms" "${SERVICE_RSS_MB[postgres]} MB" "pg_isready [ok]"
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "redis" "${REDIS_PORT}" "${SERVICE_READY_MS[redis]}ms" "${SERVICE_RSS_MB[redis]} MB" "tcp :${REDIS_PORT} [ok]"
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "kafka (tansu)" "${KAFKA_PORT}" "${SERVICE_READY_MS[kafka]}ms" "${SERVICE_RSS_MB[kafka]} MB" "tcp :${KAFKA_PORT} [ok]"
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "clickhouse" "${CLICKHOUSE_HTTP_PORT}" "${SERVICE_READY_MS[clickhouse]}ms" "${SERVICE_RSS_MB[clickhouse]} MB" "http /ping [ok]"
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "temporal" "${TEMPORAL_PORT}" "${SERVICE_READY_MS[temporal]}ms" "${SERVICE_RSS_MB[temporal]} MB" "tcp :${TEMPORAL_PORT} [ok]"
    printf "  %-16s %-8s %-14s %-12s %-30s\n" "s3 (seaweedfs)" "${OBJECT_STORAGE_PORT}" "${SERVICE_READY_MS[objectstorage]}ms" "${SERVICE_RSS_MB[objectstorage]} MB" "tcp :${OBJECT_STORAGE_PORT} [ok]"
    echo "  ───────────────────────────────────────────────────────────────────────────────────────────────────────"
    printf "  TOTAL (6)                       %-14s %-12s %-30s\n" "${total_all_ms}ms" "${total_rss_mb} MB" "6/6 Services Ready in ${total_all_sec}s"
    echo "========================================================================================================="
    echo ""
}

stop_services() {
    echo "🛑 Stopping running showcase microservices on tmpfs..."
    # Stop from PID files first
    if [[ -d "$PID_DIR" ]]; then
        for pid_file in "$PID_DIR"/*.pid; do
            if [[ -f "$pid_file" ]]; then
                local p
                p=$(cat "$pid_file" 2>/dev/null || true)
                if [[ -n "$p" ]] && kill -0 "$p" 2>/dev/null; then
                    kill "$p" 2>/dev/null || true
                fi
                rm -f "$pid_file"
            fi
        done
    fi

    # Terminate any remaining processes on our ports
    pkill -f "postgres -D.*$PG_PORT" 2>/dev/null || true
    pkill -f "redis-server.*$REDIS_PORT" 2>/dev/null || true
    pkill -f "tansu.*$KAFKA_PORT" 2>/dev/null || true
    pkill -f "clickhouse-server.*$CLICKHOUSE_HTTP_PORT" 2>/dev/null || true
    pkill -f "temporal server.*$TEMPORAL_PORT" 2>/dev/null || true
    pkill -f "weed mini.*$OBJECT_STORAGE_PORT" 2>/dev/null || true
    sleep 0.2
    echo "✓ All showcase microservices stopped and cleaned up."
}

status_services() {
    echo "======================================================================="
    echo "  📊 Showcase Data Tier Status & Memory Footprint"
    echo "======================================================================="
    (ps -eo pid,rss,comm,args 2>/dev/null || true) | { grep -E "(${PG_PORT}|${REDIS_PORT}|${KAFKA_PORT}|${CLICKHOUSE_HTTP_PORT}|${TEMPORAL_PORT}|${OBJECT_STORAGE_PORT}|weed mini|tansu|clickhouse-server)" || true; } | { grep -v grep || true; } | awk '
    BEGIN { total=0; printf "%-8s %-12s %-18s %s\n", "PID", "RSS (MB)", "COMMAND", "TARGET" }
    {
        rss_mb = $2 / 1024;
        total += rss_mb;
        printf "%-8s %-12.1f %-18s %s\n", $1, rss_mb, $3, $4
    }
    END {
        printf "-----------------------------------------------------------------------\n"
        printf "Total Active Service RSS: %.1f MB\n", total
    }'
    echo "======================================================================="
}

case "$ACTION" in
    start|up)
        start_services
        ;;
    stop|down)
        stop_services
        ;;
    status)
        status_services
        ;;
    *)
        echo "Usage: $0 {start|up|stop|down|status}"
        exit 1
        ;;
esac
