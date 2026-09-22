#!/usr/bin/env bash
# Bring one hand-launched decision instance up in front of the gateway: Caddy with a public certificate and the
# per-instance bearer, the serving container under systemd, both reading /etc/kev-vllm/env. Idempotent; run as root
# on an Ubuntu Lambda instance that already has Docker and the NVIDIA container runtime, with the checkpoint at
# MODEL_DIR and the DNS name in INSTANCE_HOST already resolving to this instance.
#
#   sudo INSTANCE_HOST=kev-1.example.com ACME_EMAIL=ops@example.com KEV_BEARER="$(openssl rand -hex 32)" \
#     MODEL_DIR=/srv/models/kev-4b IMAGE=ghcr.io/posthog/posthog-ml-inference-decision:latest deploy/phase1/bootstrap.sh
#
# This is the phase 1 layout from the ML inference RFC: launched by hand, temporary by construction. Phase 2 renders
# the same files from cloud-init.
set -euo pipefail

INSTANCE_HOST=${INSTANCE_HOST:?the instance's DNS name}
ACME_EMAIL=${ACME_EMAIL:?contact email for the ACME account}
KEV_BEARER=${KEV_BEARER:?per-instance bearer}
MODEL_DIR=${MODEL_DIR:?directory holding the exported checkpoint}
IMAGE=${IMAGE:?serving image reference}
KEV_DATE_FACTS=${KEV_DATE_FACTS:-0}
HERE=$(cd "$(dirname "$0")" && pwd)

[ -f "$MODEL_DIR/manifest.json" ] || { echo "no checkpoint at $MODEL_DIR" >&2; exit 1; }
# The image serves as an unprivileged user (uid 10001), so the checkpoint must be readable by everyone.
chmod -R a+rX "$MODEL_DIR"

if ! command -v caddy >/dev/null; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi

install -d -m 0750 /etc/kev-vllm
umask 077
cat > /etc/kev-vllm/env <<EOF
INSTANCE_HOST=$INSTANCE_HOST
ACME_EMAIL=$ACME_EMAIL
KEV_BEARER=$KEV_BEARER
IMAGE=$IMAGE
MODEL_DIR=$MODEL_DIR
KEV_DATE_FACTS=$KEV_DATE_FACTS
EOF
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
curl -fsS -o /dev/null -w "through caddy with the bearer: %{http_code}\n" -H "Authorization: Bearer $KEV_BEARER" "https://$INSTANCE_HOST/health"
curl -sS -o /dev/null -w "through caddy without the bearer: %{http_code}\n" "https://$INSTANCE_HOST/health"
