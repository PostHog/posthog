# Phase 1 host

The hand-launched decision instance from the ML inference RFC (phase 1): one GPU box that the AI gateway reaches over the public internet, with a public certificate, a per-instance bearer, and a firewall that admits only the production cluster. Phase 2 renders the same layout from cloud-init and nothing is launched by hand after that.

What runs on the box:

- `kev-vllm.service` runs the serving image with the host network and the checkpoint mounted. vLLM binds loopback, so nothing of it faces the network directly.
- `caddy.service` runs Caddy, built with the Route53 DNS module (`caddy/Dockerfile`), on the host network. It obtains and renews the instance's certificate from Let's Encrypt through a DNS-01 challenge, refuses any request without the bearer with a 401, and forwards only `/pooling`, `/health` and `/metrics` to vLLM. Everything else is a 404. Nothing listens on port 80. The certificate and ACME account live in `/var/lib/kev-vllm/caddy`, so a restart is not a reissue.
- Both read `/etc/kev-vllm/env` (root-owned, mode 0600), written by `bootstrap.sh`.

Before running `bootstrap.sh`:

1. A DNS name for the instance, under the zone the gateway pins for decision hosts, pointing at the instance's public IP.
2. The Lambda firewall. It is one ruleset per region on the account and every instance inherits it: port 443 open only to the production cluster's egress addresses (listed in the RFC, not here), SSH on its own rule for engineers, and nothing else. No port 80: the certificate challenge is a DNS record, so Let's Encrypt never connects to the instance.
3. The instance in the `dns` unit's instance map in posthog-cloud-infra. That one entry gives it its A record and puts its exact `_acme-challenge` name into the ACME user's policy, so a compromised box can issue certificates for itself and for nothing else. The same unit keeps the ACME user's access key in Secrets Manager, where the host script reads it; nothing is minted by hand, and `terragrunt apply -replace=aws_iam_access_key.acme` rotates it.
4. The checkpoint on disk at `MODEL_DIR`, fetched with `aws s3 sync` from the published version (see the package README) and verified with `kev-vllm-checkpoint verify`. The container serves as an unprivileged user, so the directory has to be readable by everyone; the bootstrap script sets that, and a home directory on Ubuntu is not traversable by other users, so keep it outside `/home`.
5. The bearer, as `AI_GATEWAY_KEV_API_KEY` in the gateway's `ai-gateway-secrets` bag for that environment, created with the secrets tool (PostHog/secrets) and generated there. The gateway and the host script read the same key, so the two sides cannot drift.

Then, from your machine, with the environment's values in `envs/<environment>.env` copied from `envs/prod-us.env.example` (the box, the bucket, the AWS profiles, and the SSH key as an `op://` reference, so 1Password prompts once and nothing lands on disk; a new region is a new file):

```bash
deploy/phase1/lambda-host.sh prod-us all
```

`lambda-host.sh` loads the SSH key into a throwaway agent, copies this directory to the box, downloads the checkpoint through presigned URLs and verifies it with the serving image, reads the ACME key and the bearer from Secrets Manager, streams the env file over SSH into `/etc/kev-vllm/env`, and runs `bootstrap.sh` there. That script builds the Caddy image, pulls the serving image, starts both services, waits for the certificate, requires a 200 through Caddy with the bearer and a 401 without it, and fails if anything answers on port 80. `stage` and `bootstrap` also run as separate steps.

On the gateway side the host is a served host of kind `kev-vllm` with `base_url` `https://kev-1.<zone>/v1`, the bearer in `AI_GATEWAY_KEV_API_KEY`, and the enrolled teams in `AI_GATEWAY_SYSTEMONE_TEAM_IDS`.

To try the bearer check and the proxying without a DNS name, run the Caddy image with a Caddyfile that replaces the `tls` block by `tls internal` and `INSTANCE_HOST=localhost:8443`; the route block is what matters and is unchanged. `caddy validate` on the real Caddyfile with placeholder environment values checks the rest.
