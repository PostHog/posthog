#!/bin/bash

sudo apt-get install -y curl ca-certificates brotli
curl https://mmdbcdn.posthog.net/ | brotli -d > mmdb.db
./livestream