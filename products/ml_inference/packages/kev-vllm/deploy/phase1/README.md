# Phase 1 host

The hand-launched decision instance from the ML inference RFC (phase 1): one GPU box that the AI gateway reaches over the public internet, with a public certificate, a per-instance bearer, and a firewall that admits only the production cluster. Phase 2 renders the same layout from cloud-init and nothing is launched by hand after that.

What runs on the box:

- `kev-vllm.service` runs the serving image with the host network and the checkpoint mounted. vLLM binds loopback, so nothing of it faces the network directly.
- Caddy terminates TLS with a certificate issued off the box (below), refuses any request without the bearer with a 401, and forwards only `/pooling`, `/health` and `/metrics` to vLLM. Everything else is a 404. Nothing listens on port 80.
- Both read `/etc/kev-vllm/env` (root-owned, mode 0600), written by `bootstrap.sh`.

Before running `bootstrap.sh`:

1. A DNS name for the instance, under the zone the gateway pins for decision hosts, pointing at the instance's public IP.
2. The Lambda firewall. It is one ruleset per region on the account and every instance inherits it: port 443 open only to the production cluster's egress addresses (listed in the RFC, not here), SSH on its own rule for engineers, and nothing else. No port 80: the certificate is issued with a DNS-01 challenge, so Let's Encrypt never connects to the instance.
3. A certificate for the name, issued from a machine that can write the zone, never from the instance, so no AWS credential lives on a rented host. With [lego](https://go-acme.github.io/lego/) and the ML account profile:

   ```bash
   AWS_PROFILE=ml-prod-us-write lego --email <contact> --dns route53 --domains kev-1.<zone> --accept-tos run
   ```

   That writes `.lego/certificates/kev-1.<zone>.crt` (the chain) and `.key`; copy both to the instance and pass their paths as `TLS_CERT` and `TLS_KEY`. Let's Encrypt certificates last 90 days, so run `lego ... renew` and copy again before then; phase 2 moves this into the apply job.

4. The checkpoint on disk at `MODEL_DIR`, fetched with `aws s3 sync` from the published version (see the package README) and verified with `kev-vllm-checkpoint verify`. The container serves as an unprivileged user, so the directory has to be readable by everyone; the bootstrap script sets that, and a home directory on Ubuntu is not traversable by other users, so keep it outside `/home`.
5. A bearer: `openssl rand -hex 32`. The same value goes to the gateway as `AI_GATEWAY_KEV_API_KEY`.

Then, as root:

```bash
INSTANCE_HOST=kev-1.<zone> TLS_CERT=/root/kev-1.crt TLS_KEY=/root/kev-1.key KEV_BEARER=<bearer> MODEL_DIR=/srv/models/kev-4b \
  IMAGE=ghcr.io/posthog/posthog-ml-inference-decision:sha-<commit>@sha256:<digest> ./bootstrap.sh
```

The script installs Caddy if missing, copies the certificate and key where only Caddy can read them, writes the env file and the units, pulls the image, starts both services, requires a 200 through Caddy with the bearer and a 401 without it, and fails if anything answers on port 80.

On the gateway side the host is a served host of kind `kev-vllm` with `base_url` `https://kev-1.<zone>/v1`, the bearer in `AI_GATEWAY_KEV_API_KEY`, and the enrolled teams in `AI_GATEWAY_SYSTEMONE_TEAM_IDS`.

To try the Caddyfile without a DNS name, set `INSTANCE_HOST=localhost:8443` and point `TLS_CERT` and `TLS_KEY` at a self-signed certificate for `localhost` with an unencrypted key, so a client that accepts that certificate can exercise the bearer check and the proxying on port 8443 against a vLLM already listening on 8000.
