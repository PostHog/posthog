#!/bin/bash

if [[ ! -f mmdb.db ]]; then
    sudo apt-get install -y curl ca-certificates brotli
    curl https://mmdbcdn.posthog.net/ | brotli -d > mmdb.db
    git pull
    go build
    ./start.sh
fi

