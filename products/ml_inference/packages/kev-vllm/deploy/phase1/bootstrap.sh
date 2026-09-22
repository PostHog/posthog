#!/usr/bin/env bash
# Bring one hand-launched decision instance up in front of the gateway: Caddy with a certificate issued off the box and
# the per-instance bearer, the serving container under systemd, both reading /etc/kev-vllm/env. Idempotent; run as
# root on an Ubuntu Lambda instance that already has Docker and the NVIDIA container runtime, with the checkpoint at
# MODEL_DIR, the DNS name in INSTANCE_HOST already resolving to this instance, and the certificate chain and key
# copied to the paths in TLS_CERT and TLS_KEY (see README.md for the DNS-01 issuance).
#
#   sudo INSTANCE_HOST=kev-1.example.com TLS_CERT=/root/fullchain.pem TLS_KEY=/root/privkey.pem \
#     KEV_BEARER="$(openssl rand -hex 32)" MODEL_DIR=/srv/models/kev-4b \
#     IMAGE=ghcr.io/posthog/posthog-ml-inference-decision:sha-<commit>@sha256:<digest> deploy/phase1/bootstrap.sh
#
# This is the phase 1 layout from the ML inference RFC: launched by hand, temporary by construction. Phase 2 renders
# the same files from cloud-init.
set -euo pipefail

INSTANCE_HOST=${INSTANCE_HOST:?the DNS name of this instance}
TLS_CERT=${TLS_CERT:?path to the certificate chain issued for INSTANCE_HOST}
TLS_KEY=${TLS_KEY:?path to the matching private key}
KEV_BEARER=${KEV_BEARER:?per-instance bearer}
MODEL_DIR=${MODEL_DIR:?directory holding the exported checkpoint}
IMAGE=${IMAGE:?serving image reference}
KEV_DATE_FACTS=${KEV_DATE_FACTS:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
TLS_DIR=/etc/kev-vllm/tls

[ -f "$MODEL_DIR/manifest.json" ] || { echo "no checkpoint at $MODEL_DIR" >&2; exit 1; }
[ -f "$TLS_CERT" ] && [ -f "$TLS_KEY" ] || { echo "certificate or key missing" >&2; exit 1; }
# The image serves as an unprivileged user (uid 10001), so the checkpoint must be readable by everyone.
chmod -R a+rX "$MODEL_DIR"

if ! command -v caddy >/dev/null; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi

# Caddy runs as the caddy user; the copies are readable by that group and nothing else.
install -d -m 0750 -o root -g caddy /etc/kev-vllm "$TLS_DIR"
install -m 0640 -o root -g caddy "$TLS_CERT" "$TLS_DIR/fullchain.pem"
install -m 0640 -o root -g caddy "$TLS_KEY" "$TLS_DIR/privkey.pem"
umask 027
cat > /etc/kev-vllm/env <<ENV
INSTANCE_HOST=$INSTANCE_HOST
TLS_CERT=$TLS_DIR/fullchain.pem
TLS_KEY=$TLS_DIR/privkey.pem
KEV_BEARER=$KEV_BEARER
IMAGE=$IMAGE
MODEL_DIR=$MODEL_DIR
KEV_DATE_FACTS=$KEV_DATE_FACTS
ENV
chgrp caddy /etc/kev-vllm/env
umask 022

install -m 0644 "$HERE/Caddyfile" /etc/caddy/Caddyfile
install -d /etc/systemd/system/caddy.service.d
install -m 0644 "$HERE/caddy-env.conf" /etc/systemd/system/caddy.service.d/env.conf
install -m 0644 "$HERE/kev-vllm.service" /etc/systemd/system/kev-vllm.service

docker pull "$IMAGE"
systemctl daemon-reload
systemctl enable --now kev-vllm.service
systemctl restart caddy.service

for _ in $(seq 1 120); do
  curl -fs http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 5
done
curl -fs http://127.0.0.1:8000/health >/dev/null || { journalctl -u kev-vllm --no-pager -n 50; echo "server did not come up" >&2; exit 1; }
expect_status() {
  local expected=$1 label=$2; shift 2
  local status
  status=$(curl -sS -o /dev/null -w "%{http_code}" "$@")
  echo "through caddy $label: $status"
  [ "$status" = "$expected" ] || { echo "expected $expected $label" >&2; exit 1; }
}
expect_status 200 "with the bearer" -H "Authorization: Bearer $KEV_BEARER" "https://$INSTANCE_HOST/health"
expect_status 401 "without the bearer" "https://$INSTANCE_HOST/health"
if curl -s -o /dev/null --connect-timeout 3 "http://127.0.0.1:80/"; then
  echo "something answers on port 80; the instance should have no plain HTTP listener" >&2
  exit 1
fi
