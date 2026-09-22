#!/usr/bin/env bash
# Bring one hand-launched decision instance up in front of the gateway: Caddy serving the instance's certificate
# and checking the per-instance bearer, the serving container under systemd, both reading /etc/kev-vllm/env.
# Idempotent; run as root on an Ubuntu Lambda instance that already has Docker and the NVIDIA container runtime,
# with the checkpoint at MODEL_DIR and the certificate pair under /etc/kev-vllm/tls.
#
# Normally run through lambda-host.sh from an engineer's machine, which issues the certificate and fills
# /etc/kev-vllm/env first; by hand, the same variables can be exported before calling it.
#
# This is the phase 1 layout from the ML inference RFC: launched by hand, temporary by construction. Phase 2 renders
# the same files from cloud-init.
set -euo pipefail

# lambda-host.sh streams the values into /etc/kev-vllm/env before calling this, so they never sit on a command line.
if [ -f /etc/kev-vllm/env ]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/kev-vllm/env
  set +a
fi
INSTANCE_IP=${INSTANCE_IP:?the public IP the certificate was issued for}
KEV_BEARER=${KEV_BEARER:?per-instance bearer}
MODEL_DIR=${MODEL_DIR:?directory holding the exported checkpoint}
IMAGE=${IMAGE:?serving image reference}
CADDY_IMAGE=${CADDY_IMAGE:-caddy:2.10.2}
KEV_DATE_FACTS=${KEV_DATE_FACTS:-0}
HERE=$(cd "$(dirname "$0")" && pwd)

[ -f "$MODEL_DIR/manifest.json" ] || { echo "no checkpoint at $MODEL_DIR" >&2; exit 1; }
# The image serves as an unprivileged user (uid 10001), so the checkpoint must be readable by everyone.
chmod -R a+rX "$MODEL_DIR"
for f in instance.crt instance.key ca.pem; do
  [ -f "/etc/kev-vllm/tls/$f" ] || { echo "no /etc/kev-vllm/tls/$f; lambda-host.sh issues the certificate first" >&2; exit 1; }
done

install -d -m 0750 /etc/kev-vllm
umask 077
cat > /etc/kev-vllm/env <<ENV
INSTANCE_IP=$INSTANCE_IP
KEV_BEARER=$KEV_BEARER
IMAGE=$IMAGE
CADDY_IMAGE=$CADDY_IMAGE
MODEL_DIR=$MODEL_DIR
KEV_DATE_FACTS=$KEV_DATE_FACTS
ENV
umask 022

install -m 0644 "$HERE/Caddyfile" /etc/kev-vllm/Caddyfile
install -m 0644 "$HERE/kev-vllm.service" /etc/systemd/system/kev-vllm.service
install -m 0644 "$HERE/caddy.service" /etc/systemd/system/caddy.service

docker pull -q "$CADDY_IMAGE" >/dev/null
docker pull "$IMAGE"
systemctl daemon-reload
systemctl enable --now kev-vllm.service
systemctl enable --now caddy.service
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
# Verified the way the gateway verifies: against the CA, for the public IP in the certificate, connecting to loopback.
via_caddy=(--cacert /etc/kev-vllm/tls/ca.pem --connect-to "$INSTANCE_IP:443:127.0.0.1:443")
for _ in $(seq 1 12); do
  curl -fs -o /dev/null "${via_caddy[@]}" -H "Authorization: Bearer $KEV_BEARER" "https://$INSTANCE_IP/health" 2>/dev/null && break
  sleep 5
done
expect_status 200 "with the bearer" "${via_caddy[@]}" -H "Authorization: Bearer $KEV_BEARER" "https://$INSTANCE_IP/health"
expect_status 401 "without the bearer" "${via_caddy[@]}" "https://$INSTANCE_IP/health"
if curl -s -o /dev/null --connect-timeout 3 "http://127.0.0.1:80/"; then
  echo "something answers on port 80; the instance should have no plain HTTP listener" >&2
  exit 1
fi
