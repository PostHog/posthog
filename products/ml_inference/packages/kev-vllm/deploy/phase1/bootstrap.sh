#!/usr/bin/env bash
# Bring one hand-launched decision instance up in front of the gateway: Caddy obtaining its own certificate through
# a DNS-01 challenge and checking the per-instance bearer, the serving container under systemd, both reading
# /etc/kev-vllm/env. Idempotent; run as root on an Ubuntu Lambda instance that already has Docker and the NVIDIA
# container runtime, with the checkpoint at MODEL_DIR and the DNS name in INSTANCE_HOST already resolving to this
# instance.
#
# Normally run through lambda-host.sh from an engineer's machine, which fills /etc/kev-vllm/env first; by hand, the
# same variables can be exported before calling it.
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
INSTANCE_HOST=${INSTANCE_HOST:?the DNS name of this instance}
ACME_EMAIL=${ACME_EMAIL:?contact email for the ACME account}
ROUTE53_ZONE_ID=${ROUTE53_ZONE_ID:?the zone the name lives in}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:?credential that can write the ACME challenge record}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:?credential that can write the ACME challenge record}
KEV_BEARER=${KEV_BEARER:?per-instance bearer}
MODEL_DIR=${MODEL_DIR:?directory holding the exported checkpoint}
IMAGE=${IMAGE:?serving image reference}
KEV_DATE_FACTS=${KEV_DATE_FACTS:-0}
HERE=$(cd "$(dirname "$0")" && pwd)

[ -f "$MODEL_DIR/manifest.json" ] || { echo "no checkpoint at $MODEL_DIR" >&2; exit 1; }
# The image serves as an unprivileged user (uid 10001), so the checkpoint must be readable by everyone.
chmod -R a+rX "$MODEL_DIR"

install -d -m 0750 /etc/kev-vllm /var/lib/kev-vllm/caddy
umask 077
cat > /etc/kev-vllm/env <<ENV
INSTANCE_HOST=$INSTANCE_HOST
ACME_EMAIL=$ACME_EMAIL
ROUTE53_ZONE_ID=$ROUTE53_ZONE_ID
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
AWS_REGION=us-east-1
KEV_BEARER=$KEV_BEARER
IMAGE=$IMAGE
MODEL_DIR=$MODEL_DIR
KEV_DATE_FACTS=$KEV_DATE_FACTS
ENV
umask 022

install -m 0644 "$HERE/Caddyfile" /etc/kev-vllm/Caddyfile
install -m 0644 "$HERE/kev-vllm.service" /etc/systemd/system/kev-vllm.service
install -m 0644 "$HERE/caddy.service" /etc/systemd/system/caddy.service

docker build -q -t kev-caddy:local "$HERE/caddy" >/dev/null
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
# The first request waits for the certificate; Caddy answers once the DNS-01 challenge has been validated.
for _ in $(seq 1 24); do
  curl -fs -o /dev/null -H "Authorization: Bearer $KEV_BEARER" "https://$INSTANCE_HOST/health" 2>/dev/null && break
  sleep 5
done
expect_status 200 "with the bearer" -H "Authorization: Bearer $KEV_BEARER" "https://$INSTANCE_HOST/health"
expect_status 401 "without the bearer" "https://$INSTANCE_HOST/health"
if curl -s -o /dev/null --connect-timeout 3 "http://127.0.0.1:80/"; then
  echo "something answers on port 80; the instance should have no plain HTTP listener" >&2
  exit 1
fi
