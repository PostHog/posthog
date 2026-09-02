#!/usr/bin/env bash
# Throwaway PG16 target for local testing: pg_stat_statements, auto_explain, file
# logging (bind-mounted to $LOG_DIR), Aurora stub functions, pg_proctab if the
# image has it built (see docs/telemetry-sources.md).
#
#   test/setup-local.sh [container-name] [port] [log-dir]
set -euo pipefail
NAME=${1:-pgcollector-test}
PORT=${2:-5499}
LOG_DIR=${3:-$PWD/.local/pglog}
IMAGE=${IMAGE:-postgres:16}
mkdir -p "$LOG_DIR"; chmod 777 "$LOG_DIR"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "$PORT:5432" -e POSTGRES_PASSWORD=test -v "$LOG_DIR:/var/log/pg" "$IMAGE" \
  -c shared_preload_libraries=pg_stat_statements,auto_explain -c compute_query_id=on -c track_io_timing=on \
  -c logging_collector=on -c log_directory=/var/log/pg -c log_filename=postgresql-%Y-%m-%d_%H%M%S.log \
  -c log_rotation_size=10MB -c log_rotation_age=1h \
  -c "log_line_prefix=%t:%r:%u@%d:[%p]:%Q:" \
  -c log_min_duration_statement=0 -c log_lock_waits=on -c deadlock_timeout=200ms \
  -c log_checkpoints=on -c log_autovacuum_min_duration=0 -c log_temp_files=0 -c log_connections=on -c log_disconnections=on \
  -c auto_explain.log_min_duration=0 -c auto_explain.log_format=json -c auto_explain.log_analyze=on -c auto_explain.sample_rate=1 \
  >/dev/null
for i in $(seq 1 30); do docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done

psql() { docker exec -i "$NAME" psql -U postgres -v ON_ERROR_STOP=1 "$@"; }
psql -qc "create extension if not exists pg_stat_statements"
psql -qc "create database app" || true
psql -qc "create database pgcollector" || true
psql -d app -qc "create extension if not exists pg_stat_statements; create table if not exists t(id int primary key, v text); insert into t select g, md5(g::text) from generate_series(1,10000) g on conflict do nothing;"
docker cp "$(dirname "$0")/aurora_stubs.sql" "$NAME:/tmp/aurora_stubs.sql"
psql -qf /tmp/aurora_stubs.sql
psql -qc "create extension if not exists pg_proctab" 2>/dev/null || echo "pg_proctab not available in image (optional)"
echo "ready: postgres://postgres:test@localhost:$PORT/postgres?sslmode=disable  (TLS is required unless sslmode=disable)  logs in $LOG_DIR"
