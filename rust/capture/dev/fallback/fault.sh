#!/bin/sh
set -eu

action="${1:-}"
case "$action" in
    degrade)
        enabled=false
        ;;
    restore)
        enabled=true
        ;;
    *)
        echo "Usage: $0 degrade|restore" >&2
        exit 2
        ;;
esac

curl --fail --silent --show-error \
    --request POST \
    --header 'Content-Type: application/json' \
    --data "{\"enabled\":${enabled}}" \
    http://localhost:8474/proxies/primary >/dev/null

echo "Primary Kafka proxy enabled: ${enabled}"
