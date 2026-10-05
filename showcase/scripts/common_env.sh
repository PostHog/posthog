#!/usr/bin/env bash
# ==============================================================================
# showcase/scripts/common_env.sh
# Shared environment and portability configuration for PostHog DeveX Showcase.
# Handles Linux & macOS differences, enve environment configuration,
# ephemeral tmpfs directories, and loopback service ports.
# ==============================================================================

set -euo pipefail

SHOWCASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$SHOWCASE_DIR/.." && pwd)"

export SHOWCASE_DIR
export REPO_ROOT

# 1. Integrate enve toolchain and environment variables
if command -v enve >/dev/null 2>&1; then
    eval "$(cd "$SHOWCASE_DIR" && enve direnv 2>/dev/null | grep -E '^export ' || true)"
fi

# Add tools materialized in enve user store (e.g. Tansu Kafka)
if [ -d "${HOME}/.cache/enve/store" ]; then
    for store_bin in "${HOME}/.cache/enve/store"/*/bin; do
        if [ -d "$store_bin" ]; then
            export PATH="$store_bin:$PATH"
        fi
    done
fi

# Ensure repo virtualenv takes precedence for python/pytest
if [ -d "$REPO_ROOT/.venv/bin" ]; then
    export PATH="$REPO_ROOT/.venv/bin:$PATH"
    export VIRTUAL_ENV="$REPO_ROOT/.venv"
    export PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    export PYTHON_BIN="$(command -v python3 || command -v python)"
fi

# 3. Host Operating System and Architecture
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
export HOST_OS
export HOST_ARCH

# 4. CPU Core Discovery (Linux nproc vs macOS sysctl)
if command -v nproc >/dev/null 2>&1; then
    CPU_CORES="$(nproc)"
elif command -v sysctl >/dev/null 2>&1; then
    CPU_CORES="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
else
    CPU_CORES=4
fi
export CPU_CORES

# 5. Ephemeral Storage Path (Linux tmpfs /dev/shm vs macOS $TMPDIR)
if [ -d "/dev/shm" ] && [ -w "/dev/shm" ]; then
    SHOWCASE_TMPFS="/dev/shm/posthog_showcase_${UID:-$(id -u)}"
elif [ -n "${TMPDIR:-}" ] && [ -d "${TMPDIR}" ]; then
    SHOWCASE_TMPFS="${TMPDIR%/}/posthog_showcase_${UID:-$(id -u)}"
else
    SHOWCASE_TMPFS="/tmp/posthog_showcase_${UID:-$(id -u)}"
fi
mkdir -p "$SHOWCASE_TMPFS"
export SHOWCASE_TMPFS

# 6. Service Port Definitions (Loopback Networking)
export PG_PORT="${PGPORT:-15432}"
export REDIS_PORT="${REDIS_PORT:-16379}"
export CLICKHOUSE_HTTP_PORT="${CLICKHOUSE_HTTP_PORT:-8123}"
export CLICKHOUSE_TCP_PORT="${CLICKHOUSE_TCP_PORT:-9000}"
export TEMPORAL_PORT="${TEMPORAL_PORT:-7233}"
export OBJECT_STORAGE_PORT="${OBJECT_STORAGE_PORT:-19000}"
export OBJECT_STORAGE_CONSOLE_PORT="${OBJECT_STORAGE_CONSOLE_PORT:-19001}"
export KAFKA_PORT="${KAFKA_PORT:-19092}"
export KAFKA_HOSTS="127.0.0.1:${KAFKA_PORT}"
export KAFKA_URL="127.0.0.1:${KAFKA_PORT}"

# 7. Object Storage Credentials (MinIO & PostHog Parity)
export MINIO_ROOT_USER="object_storage_root_user"
export MINIO_ROOT_PASSWORD="object_storage_root_password"
export OBJECT_STORAGE_ENABLED="True"
export OBJECT_STORAGE_ENDPOINT="http://127.0.0.1:${OBJECT_STORAGE_PORT}"
export OBJECT_STORAGE_ACCESS_KEY_ID="object_storage_root_user"
export OBJECT_STORAGE_SECRET_ACCESS_KEY="object_storage_root_password"
export NOTEBOOKS_FRAME_STORE_S3_ENDPOINT="http://127.0.0.1:${OBJECT_STORAGE_PORT}"
export AWS_ACCESS_KEY_ID="object_storage_root_user"
export AWS_SECRET_ACCESS_KEY="object_storage_root_password"

# 8. Database URLs & Core Settings
export DATABASE_URL="postgres://posthog:posthog@127.0.0.1:${PG_PORT}/posthog"
export PGHOST="127.0.0.1"
export PGPORT="${PG_PORT}"
export PGUSER="posthog"
export REDIS_URL="redis://127.0.0.1:${REDIS_PORT}"
export CLICKHOUSE_HOST="127.0.0.1"
export CLICKHOUSE_HTTP_URL="http://127.0.0.1:${CLICKHOUSE_HTTP_PORT}"
export CLICKHOUSE_DATABASE="test_posthog"
export CLICKHOUSE_POSTGRES_HOST="127.0.0.1"
export CLICKHOUSE_POSTGRES_PORT="${PG_PORT}"
export TEMPORAL_HOST="127.0.0.1"
export DEBUG="true"
export TEST="true"
export SECRET_KEY="showcase_secret_key"
export DJANGO_SECRET_KEY="showcase_secret_key"
export INTERNAL_API_SECRET="ci-boot-test-dummy-secret"
export SKIP_SERVICE_VERSION_REQUIREMENTS="1"

# 8.1 Python & Linux Memory Scaling Optimizations
# glibc ptmalloc creates up to 8*cores arenas (128 on 16 cores) per worker process,
# causing severe memory fragmentation when C-extensions (Polars, PyArrow, PyTorch) run.
# MALLOC_ARENA_MAX=2 curbs glibc allocation fragmentation by 25-35% across pytest workers.
export MALLOC_ARENA_MAX=2

# Pytest parallelizes at the process level (5 workers). Prevent each worker from spawning
# 16-thread pools in Polars/NumPy/OpenBLAS/MKL/Rayon, which bloats RSS and causes cache thrashing.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export POLARS_MAX_THREADS=1
export RAYON_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# 9. Worker & CPU Allocation Helper
# Supports:
#   - Explicit: "4", "2", "8"
#   - Capped: "<=4", "<=8" -> min(N, available_cpus)
#   - Auto: "auto" -> derives from CPUS_PER_WORKER or defaults to min(available_cpus, 4)
resolve_worker_count() {
    local requested="${1:-${WORKERS:-auto}}"
    local cpus_per_worker="${CPUS_PER_WORKER:-}"
    local max_cpus="${MAX_CPUS:-}"
    local host_cpus="${CPU_CORES:-4}"

    # Cap total host cores if MAX_CPUS is defined
    if [[ -n "$max_cpus" && "$max_cpus" =~ ^[0-9]+$ ]]; then
        if (( max_cpus < host_cpus )); then
            host_cpus="$max_cpus"
        fi
    fi

    local resolved=1

    case "$requested" in
        "<="* )
            local cap="${requested#<=}"
            cap="$(echo "$cap" | tr -d ' ')"
            resolved=$(( host_cpus < cap ? host_cpus : cap ))
            if (( resolved < 1 )); then resolved=1; fi
            ;;
        [0-9]* )
            resolved="$requested"
            ;;
        "auto" )
            if [[ -n "$cpus_per_worker" && "$cpus_per_worker" =~ ^[0-9]+$ && "$cpus_per_worker" -gt 0 ]]; then
                resolved=$(( host_cpus / cpus_per_worker ))
                if (( resolved < 1 )); then resolved=1; fi
            else
                local default_max=4
                resolved=$(( host_cpus < default_max ? host_cpus : default_max ))
                if (( resolved < 1 )); then resolved=1; fi
            fi
            ;;
        * )
            resolved=4
            ;;
    esac

    echo "$resolved"
}

# 10. Thread Contention Prevention per Worker
# Prevent Python C-extensions (OpenBLAS, NumPy, MKL) from each spawning
# a full-machine threadpool, which causes extreme cache thrashing when running N workers.
export OMP_NUM_THREADS="${CPUS_PER_WORKER:-1}"
export OPENBLAS_NUM_THREADS="${CPUS_PER_WORKER:-1}"
export MKL_NUM_THREADS="${CPUS_PER_WORKER:-1}"
export NUMEXPR_NUM_THREADS="${CPUS_PER_WORKER:-1}"

# 11. Verify enve version 0.8.3
verify_enve() {
    if ! command -v enve >/dev/null 2>&1; then
        echo "❌ FATAL: enve command not found in PATH." >&2
        echo "   Please ensure enve 0.8.3 is installed or enter via 'enve dev'." >&2
        exit 1
    fi
    local ver_out
    ver_out="$(enve --version 2>&1 || true)"
    if ! echo "$ver_out" | grep -qE "0\.8\.3"; then
        echo "❌ FATAL: enve 0.8.3 required, but found: $ver_out" >&2
        exit 1
    fi
}

# 12. Suppress noisy third-party deprecation warnings across toolchains
export PYTHONWARNINGS="ignore:pkg_resources is deprecated as an API:UserWarning,ignore::UserWarning:infi.clickhouse_orm"
