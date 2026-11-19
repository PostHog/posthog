#!/usr/bin/env bash
set -euo pipefail

fixtures=$(mktemp -d)
containers=()
cleanup() {
    for container in "${containers[@]}"; do
        docker logs "$container"
        docker rm -f "$container" >/dev/null
    done
    rm -rf "$fixtures"
}
trap cleanup EXIT

test "$(docker image inspect agent-egress-proxy --format '{{.Config.User}}')" = '65532:65532'
docker run --rm -i --network none --read-only --tmpfs /run --cap-drop ALL --security-opt no-new-privileges agent-egress-relay python3 - <<'PY'
import fcntl
import os
import ssl
import subprocess
from pathlib import Path

os.umask(0o077)
os.chdir("/run")
with Path("identity.lock").open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", "key.pem"], check=True, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "req", "-new", "-key", "key.pem", "-out", "relay.csr", "-subj", "/CN=synthetic-relay"], check=True)
subprocess.run(["openssl", "req", "-in", "relay.csr", "-verify", "-noout"], check=True)
assert Path("key.pem").stat().st_mode & 0o777 == 0o600
assert ssl.create_default_context().get_ca_certs()
PY

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$fixtures/key.pem" 2>/dev/null
openssl req -x509 -key "$fixtures/key.pem" -days 1 -subj /CN=localhost \
    -addext subjectAltName=DNS:localhost -addext basicConstraints=critical,CA:TRUE \
    -out "$fixtures/cert.pem" 2>/dev/null
openssl pkey -in "$fixtures/key.pem" -pubout -out "$fixtures/public.pem"
python3 - "$fixtures" <<'PY'
import json
import secrets
import sys
from pathlib import Path

fixtures = Path(sys.argv[1])
common = {"certificate_file": "/run/egress/cert.pem", "private_key_file": "/run/egress/key.pem"}
(fixtures / "proxy.json").write_text(json.dumps(common | {
    "client_ca_file": "/run/egress/cert.pem",
    "verification_keys_file": "/run/egress/keys.json",
    "registry_url": "https://registry.example.com",
    "registry_region": "test-region",
    "registry_signing_key_file": "/run/egress/registry-key",
}))
(fixtures / "relay.json").write_text(json.dumps(common | {
    "endpoint": "https://localhost:8443",
    "admin_address": "127.0.0.1:9091",
    "server_ca_file": "/run/egress/cert.pem",
}))
(fixtures / "keys.json").write_text(json.dumps({"smoke": (fixtures / "public.pem").read_text()}))
(fixtures / "registry-key").write_text(secrets.token_urlsafe(48))
PY
chmod 755 "$fixtures"
chmod 444 "$fixtures"/*

options=(--read-only --cap-drop ALL --security-opt no-new-privileges --mount "type=bind,src=$fixtures,dst=/run/egress,readonly")
proxy=$(docker run -d --network none "${options[@]}" agent-egress-proxy -config /run/egress/proxy.json)
containers+=("$proxy")
relay=$(docker run -d --network "container:$proxy" "${options[@]}" agent-egress-relay /usr/local/bin/egress-relay -config /run/egress/relay.json)
containers+=("$relay")

docker exec -i "$relay" python3 - <<'PY'
import http.client
import time
import urllib.request

for port in (9090, 9091):
    deadline = time.monotonic() + 15
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1) as response:
                assert response.status == 204
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)

connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=5)
connection.request("GET", "/v1/probe")
response = connection.getresponse()
assert response.status == 401, (response.status, response.read())
connection.close()
print("Both services ready; relay mTLS request reached proxy and was denied without a capability")
PY

docker stop -t 10 "$relay" "$proxy" >/dev/null
for container in "${containers[@]}"; do
    test "$(docker inspect "$container" --format '{{.State.ExitCode}}')" = 0
done
