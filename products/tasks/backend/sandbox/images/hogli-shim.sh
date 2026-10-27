#!/bin/bash
set -euo pipefail

dir="$PWD"
while [ "$dir" != "/" ]; do
    if [ -x "$dir/bin/hogli" ]; then
        if [ -z "${VIRTUAL_ENV:-}" ] && [ ! -d "$dir/.venv" ]; then
            {
                printf '%s\n' "error: $dir has no .venv, so hogli cannot run yet." ""
                if [ -f /opt/posthog/dev-stack-bake.json ]; then
                    printf '%s\n' \
                        "Boot the prebaked dev stack from that checkout:" \
                        "    bootstrap-dev-stack" \
                        "    uv sync" \
                        "    source .venv/bin/activate" \
                        "" \
                        "This image already ships a migrated Postgres and ClickHouse, plus a seeded" \
                        "test_posthog database. When a test needs them and the task does not need the" \
                        "running app, start only the datastores:" \
                        "    docker compose -f docker-compose.dev.yml up -d --no-build db redis7 zookeeper kafka clickhouse objectstorage" \
                        "    bin/wait-for-docker objectstorage" \
                        "The full 'hogli start -y -d && hogli wait' stack takes about 12 GiB, too much" \
                        "for a 16 GiB VM. Never hand-roll a database container: it takes the ports the" \
                        "baked stack needs, and pytest then replays the whole migration history." \
                        "" \
                        "See docs/internal/cloud-task-sandbox.md."
                else
                    printf '%s\n' \
                        "Install it from that checkout:" \
                        "    uv sync" \
                        "    source .venv/bin/activate"
                fi
            } >&2
            exit 127
        fi
        exec "$dir/bin/hogli" "$@"
    fi
    dir="$(dirname "$dir")"
done

printf '%s\n' \
    "error: no posthog checkout found at or above $PWD." \
    "hogli runs from inside a posthog checkout; change into one and retry." >&2
exit 127
