#!/bin/sh
set -eu

until curl --fail --silent http://toxiproxy:8474/version >/dev/null; do
    sleep 1
done

create_proxy() {
    name="$1"
    listen="$2"
    upstream="$3"
    curl --fail --silent --show-error \
        --request POST \
        --header 'Content-Type: application/json' \
        --data "{\"name\":\"${name}\",\"listen\":\"${listen}\",\"upstream\":\"${upstream}\"}" \
        http://toxiproxy:8474/proxies >/dev/null
}

create_proxy primary 0.0.0.0:19092 kafka-primary:9092
create_proxy secondary 0.0.0.0:29092 kafka-secondary:9092
