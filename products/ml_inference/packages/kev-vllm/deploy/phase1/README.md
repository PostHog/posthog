# Phase 1 host

The hand-launched decision instance from the ML inference RFC (phase 1): one GPU box that the AI gateway reaches over the public internet, with a public certificate, a per-instance bearer, and a firewall that admits only the production cluster. Phase 2 renders the same layout from cloud-init and nothing is launched by hand after that.

What runs on the box:

- `kev-vllm.service` runs the serving image with the host network and the checkpoint mounted. vLLM binds loopback, so nothing of it faces the network directly.
- `caddy.service` runs Caddy, built with the Route53 DNS module (`caddy/Dockerfile`), on the host network. It obtains and renews the instance's certificate from Let's Encrypt through a DNS-01 challenge, refuses any request without the bearer with a 401, and forwards only `/pooling`, `/health` and `/metrics` to vLLM. Everything else is a 404. Nothing listens on port 80. The certificate and ACME account live in `/var/lib/kev-vllm/caddy`, so a restart is not a reissue.
- Both read `/etc/kev-vllm/env` (root-owned, mode 0600), written by `bootstrap.sh`.

Before running `bootstrap.sh`:

1. A DNS name for the instance, under the zone the gateway pins for decision hosts, pointing at the instance's public IP.
2. The Lambda firewall. It is one ruleset per region on the account and every instance inherits it: port 443 open only to the production cluster's egress addresses (listed in the RFC, not here), SSH on its own rule for engineers, and nothing else. No port 80: the certificate challenge is a DNS record, so Let's Encrypt never connects to the instance.
3. An AWS access key for the ACME user that the zone's Terraform creates. Its policy can write only `_acme-challenge` TXT records in that zone, so what a compromised box gains is the ability to issue certificates for names in the zone, not access to anything else. Mint the key when the instance starts and delete it when the instance goes, the same lifecycle the ML training account uses for its rental keys:

   ```bash
   AWS_PROFILE=ml-prod-us-write aws iam create-access-key --user-name ml-inference-acme
   ```

4. The checkpoint on disk at `MODEL_DIR`, fetched with `aws s3 sync` from the published version (see the package README) and verified with `kev-vllm-checkpoint verify`. The container serves as an unprivileged user, so the directory has to be readable by everyone; the bootstrap script sets that, and a home directory on Ubuntu is not traversable by other users, so keep it outside `/home`.
5. A bearer: `openssl rand -hex 32`. The same value goes to the gateway as `AI_GATEWAY_KEV_API_KEY`.

Then, as root:

```bash
INSTANCE_HOST=kev-1.<zone> ACME_EMAIL=<contact> ROUTE53_ZONE_ID=<zone id> \
  AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> KEV_BEARER=<bearer> MODEL_DIR=/srv/models/kev-4b \
  IMAGE=ghcr.io/posthog/posthog-ml-inference-decision:sha-<commit>@sha256:<digest> ./bootstrap.sh
```

The script writes the env file and the units, builds the Caddy image, pulls the serving image, starts both services, waits for the certificate, requires a 200 through Caddy with the bearer and a 401 without it, and fails if anything answers on port 80.

On the gateway side the host is a served host of kind `kev-vllm` with `base_url` `https://kev-1.<zone>/v1`, the bearer in `AI_GATEWAY_KEV_API_KEY`, and the enrolled teams in `AI_GATEWAY_SYSTEMONE_TEAM_IDS`.

To try the bearer check and the proxying without a DNS name, run the Caddy image with a Caddyfile that replaces the `tls` block by `tls internal` and `INSTANCE_HOST=localhost:8443`; the route block is what matters and is unchanged. `caddy validate` on the real Caddyfile with placeholder environment values checks the rest.
