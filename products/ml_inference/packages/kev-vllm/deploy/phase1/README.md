# Phase 1 host

The hand-launched decision instance from the ML inference RFC (phase 1): one GPU box that the AI gateway reaches by IP over the public internet, with a certificate from our own CA, a per-instance bearer, and a firewall that admits only the production cluster. Phase 2 renders the same layout from cloud-init and nothing is launched by hand after that.

What runs on the box:

- `kev-vllm.service` runs the serving image with the host network and the checkpoint mounted. vLLM binds loopback, so nothing of it faces the network directly.
- `caddy.service` runs stock Caddy on the host network. It serves the instance's certificate from `/etc/kev-vllm/tls`, refuses any request without the bearer with a 401, and forwards only `/pooling`, `/health` and `/metrics` to vLLM. Everything else is a 404. Nothing listens on port 80 and nothing renews: the certificate is valid for five years.
- Both read `/etc/kev-vllm/env` (root-owned, mode 0600), written by `bootstrap.sh`.

Trust works like this. The ML inference CA (`ca.pem` here, key in the ML vault as "ML inference CA", expires 2036-09-21) signs each instance's certificate for its public IP. The gateway verifies `kev-vllm` hosts against that CA alone (`AI_GATEWAY_KEV_CA_PEM`), so the bearer only ever reaches a box holding one of its certificates, and no public CA, DNS name, ACME challenge or AWS credential is involved. The instance's private key is generated on the box and never leaves it; the host script signs its CSR.

Before running the host script:

1. The Lambda firewall. It is one ruleset per region on the account and every instance inherits it: port 443 open only to the production cluster's egress addresses (listed in the RFC, not here), SSH on its own rule for engineers, and nothing else.
2. The checkpoint published in the base-models bucket (see the package README). The host script stages it at `/srv/models/<model>`, readable by everyone because the container serves as an unprivileged user, and outside `/home`, which Ubuntu does not let other users traverse.
3. The bearer: a generated password item in the ML vault, one per environment, and the same value set as `AI_GATEWAY_KEV_API_KEY` in the gateway's `ai-gateway-secrets` bag for that environment by someone with the secrets-editor role there. The host script reads the vault item; the gateway reads the bag. Rotating it means changing both and re-running the bootstrap step, so it is the one value in this layout that lives in two places.

Then, from your machine, with the environment's values in `envs/<environment>.env` copied from `envs/prod-us.env.example` (the box, the bucket and its read profile, and the SSH key, CA key and bearer as `op://` references, so 1Password prompts once and nothing lands on disk; a new region is a new file). The script needs no access to a production account:

```bash
deploy/phase1/lambda-host.sh prod-us all
```

`lambda-host.sh` loads the SSH key into a throwaway agent, copies this directory to the box, downloads the checkpoint through presigned URLs and verifies it with the serving image, has the box generate its key and a CSR and signs it here with the CA key for five years, streams the env file over SSH into `/etc/kev-vllm/env`, and runs `bootstrap.sh` there. That script pulls the images, starts both services, requires a 200 through Caddy with the bearer and a 401 without it, verified against the CA for the public IP, and fails if anything answers on port 80. `stage`, `certificate` and `bootstrap` also run as separate steps; re-running `certificate` reuses the box's key and issues a fresh certificate.

On the gateway side the host is a served host of kind `kev-vllm` with `base_url` `https://<ip>/v1`, the CA in `AI_GATEWAY_KEV_CA_PEM`, the bearer in `AI_GATEWAY_KEV_API_KEY`, and the enrolled teams in `AI_GATEWAY_SYSTEMONE_TEAM_IDS`. When a box is released, remove it from the gateway's host list; its certificate is worthless to anyone else without the bearer, but the entry would keep the gateway trying it.

To try the bearer check and the proxying locally, run the Caddy image with the Caddyfile and any certificate pair under `/etc/kev-vllm/tls`; the route block is what matters. `caddy validate` on the Caddyfile with a placeholder bearer checks the rest.
