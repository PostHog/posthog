# Agent egress

The regional proxy verifies run capabilities against the Tasks registry.
The relay forwards HTTP requests to one configured regional endpoint using mTLS.
The only regional operation is an authenticated `GET /v1/probe`, which returns 204 without contacting an upstream.
The probe rejects declared or streaming request bodies without waiting for their contents.
Tasks owns registration and capability issuance.
A development probe uses Tasks' Modal provisioning and an isolated relay sidecar. An opt-in observation mode runs the same probe on an existing Tasks VM. Agent traffic and upstream credentials still use their current paths.

## Probe a real development VM

`probe_agent_egress` runs synthetic requests for an active development TaskRun without repositories or an existing sandbox.
It requires `DEBUG=1` and `SANDBOX_PROVIDER=MODAL_DOCKER`. It does not start an agent or mint upstream credentials.

```text
Trusted controller -> Modal control API -> relay generates key and CSR
Trusted controller -> sign CSR -> register execution -> deliver guest capability
Guest -> private sidecar HTTP -> mTLS -> regional /v1/probe
Trusted controller -> renew lease / replace capability file -> revoke on exit
```

Build the relay image directly from this checkout using a development Modal app:

```bash
python products/tasks/services/egress-proxy/scripts/build_modal_relay.py --app agent-egress-dev --env <worker-environment>
```

Put the printed `im-...` ID in `relay_image_id` below. The build uses `Dockerfile.relay`; no local Go build or registry push is needed.
Use the Tasks worker's Modal workspace and environment. The script prints the selected environment before building; the worker's Modal credentials must be able to load the image ID.
Run the regional proxy and registry first, using development signing keys and an ephemeral client CA.
The CA key stays with the controller; the relay key stays in its sidecar.
The mounted verifier bundle must include the run's signing key.

Set `AGENT_EGRESS_PROBE_CONFIG_DIR` to a dedicated directory containing only probe configuration files, writable only by the worker operator. Keep certificate keys outside it.
Pass a JSON file from that directory to `python manage.py probe_agent_egress --config /path/to/probes/probe.json`:

```json
{
  "team_id": 1,
  "run_id": "00000000-0000-4000-8000-000000000001",
  "endpoint": "https://run-a.egress.example.com",
  "relay_image_id": "im-example",
  "server_ca_file": "/run/egress/server-ca.pem",
  "client_ca_file": "/run/egress/client-ca.pem",
  "client_ca_key_file": "/run/egress/client-ca-key.pem",
  "duration_seconds": 360,
  "concurrency": 16,
  "requests_per_round": 128
}
```

The main VM has an empty CIDR allowlist and can reach the sidecar over Modal's private bridge.
The sidecar allows the exact regional hostname on port 443; its admin listener stays on loopback.
The development-only `dev_proxy_ipv4` option instead allows one public `/32` and pins endpoint resolution to that address, for TCP test tunnels on other ports. This does not prove the production domain restriction.
Modal 1.6.4 supplies the VM sidecar memory-allocation API; the VM reserves 1 GiB for the relay.
This SDK defaults to the V2 backend unless configuration selects V1. The default also applies to ordinary Tasks sandboxes.

The controller renews the registration every ten seconds during requests and refreshes the capability every three minutes.
Each guest request reads the current capability file. Changing startup environment variables is unnecessary.
Authority or delivery failure stops renewal and revokes that execution. Process loss leaves the lease to expire; there is no direct-network fallback.
Replacement uses a fresh VM, relay key and execution. Expired executions cannot resume; old cleanup cannot revoke a replacement.
Snapshots and normal agent startup are refused in this profile. Filesystem restore and production certificate renewal need later integration.

DNS remains outside this route. The probe does not establish complete containment, production ingress, durable audit delivery or product-workflow compatibility.
Output contains status counts and sandbox/execution IDs. Proxy audit events still use the stdout contract below.

### Run the probe through Temporal

Start a development Tasks worker, then add `--temporal --task-queue <worker-queue>` to the probe command.
The worker needs the same configuration directory setting, file and certificate paths. Both command modes reject file access unless development probes are enabled, and reject paths or symlinks outside that directory. Configuration errors omit file contents. Private keys and capabilities never enter workflow history.
Ctrl+C cancels the workflow and requests cleanup. A rejected probe response fails the run without retrying it.

```text
Temporal workflow
  create or recover VM and relay -> enroll execution
  renew lease every 10s alongside probe requests
  on completion, cancellation or failure -> revoke execution -> destroy VM
```

Both command modes use the same lifecycle and persist an owner, execution, VM and sidecar IDs under `state.agent_egress_probe`.
Each activity reads that binding again. A restarted worker can renew a live lease; an expired execution needs a fresh VM and key.
Old cleanup targets its own execution and VM, leaving a replacement alone. An already-deleted VM counts as cleaned up; other cleanup failures remain retryable and do not replace the original workflow failure.
Revocation records its timestamp, initiating service and reason. Existing registrations have no invented audit history.

Enrollment retries within a fixed three-minute window. A stable provider name recovers the VM even if the worker died before saving its ID. Retries keep the relay key and running process; expired or revoked authority stays denied. Heartbeats let Temporal detect worker loss before the 30-second lease expires, though recovery still depends on a worker being available in time.
Retries reject changes to the registered configuration. They do not reload the running relay; changing certificates or settings requires a new execution.
The workflow or command runner owns terminal cleanup. A failed preparation attempt cannot tear down a successful retry.
Cleanup can find an unsaved VM by name. Cancellation markers expire after their enrollment deadline; requests past that deadline are rejected even after the marker is removed.
Workflow termination skips cleanup, so authority expires with the lease and the VM stops at its TTL.
The workflow sends synthetic probes and uses the same environment checks as the command.

### Probe the staging deployment

Run the same command from a trusted controller using the staging database, Modal credentials and sandbox signing key. A local database registration cannot authorize a request through a proxy reading the staging registry.

Staging requires `CLOUD_DEPLOYMENT=DEV`, `DEBUG=0`, `SANDBOX_PROVIDER=modal`, and `AGENT_EGRESS_STAGING_PROBE_RUN_ID` set to the one TaskRun being tested. Keep that setting on the probe controller only. Production deployments remain excluded, and normal Tasks launches do not enroll.

```text
Controller using staging DB -> existing enrollment / renewal / cleanup lifecycle
Synthetic VM -> isolated relay -> regional TCP ingress -> proxy -> staging registry
```

Use a dedicated active TaskRun with an eligible actor, no repositories and no sandbox. The configuration must name that run and its exact regional hostname. Staging rejects `sandbox_id` and `dev_proxy_ipv4`: each probe creates its own VM and uses the hostname's real network path. The existing ten-minute duration and request-concurrency limits still apply.

Mount the operator-owned configuration directory and CA material on the controller. The proxy must trust that client CA and the controller's public verification keys. Only the controller receives the client CA private key; only the relay holds its generated private key. Use an image visible in the controller's Modal environment.

```bash
AGENT_EGRESS_STAGING_PROBE_RUN_ID=<run-uuid> \
  python manage.py probe_agent_egress --config /run/egress/probes/probe.json
```

For `--temporal`, use a dedicated worker queue with the same run opt-in, configuration and mounted files. Workflow inputs still contain only IDs and a configuration path.

Before sending traffic, verify the deployed registry, network policy, log redaction, TLS material and load-balancer readiness. Start with the default 60-second probe, then run for 360 seconds to cross capability refresh. Check 204 counts alongside proxy admission/completion events and the registry's final revocation record. Clearing or changing the opt-in blocks enrollment and renewal; the owning workflow can still revoke and clean up its existing probe. A controller crash leaves authority bounded by the 30-second lease and the VM by its TTL.

This proves synthetic enrollment against deployed infrastructure. It does not establish general forwarding, upstream credential injection, DNS containment or production readiness. Denial tests, replica loss and certificate rotation still need separate deployment checks.

### Observe a development Tasks run

Set `AGENT_EGRESS_OBSERVATION_CONFIG` on the Tasks worker to a probe JSON file under `AGENT_EGRESS_PROBE_CONFIG_DIR`. Its `team_id` and `run_id` must match the run. Set it before the workflow loads its context; leave `sandbox_id` out of the file.

Observation is off by default. It requires `DEBUG=1`, `MODAL_DOCKER`, a noninteractive cloud run, full network access and an already-selected Modal VM runtime. Resumed VMs are excluded, and selected runs skip repository snapshots.
An invalid observation configuration logs a warning and disables observation for that launch. Fixing the file lets later launches try again.

```text
Tasks creates VM and starts agent using existing routing
  child workflow attaches isolated relay -> enrolls -> sends synthetic probes
  completion or cancellation -> revokes execution -> stops only that relay
Tasks retains ownership of the VM
```

The sidecar reserve takes 1 GiB from the main VM for its whole lifetime, even if observation never starts. A 2 GiB VM leaves the guest 1 GiB. Match guest memory allocations before comparing performance with an unobserved run. [Modal resource configuration](https://modal.com/docs/guide/sandbox-sidecars#resource-configuration).

Each execution has its own relay name and capability file, so delayed writes or cleanup cannot affect a replacement. Observation lasts at most the configured 600 seconds. Tasks stops it before teardown, VM rotation or workflow continuation; it does not restart on the replacement or continuation. Attached cleanup gets one attempt and a ten-second activity deadline, including queue time. Failure is logged so Tasks can continue; authority expires with its lease if revocation cannot finish.

Cleanup stops the relay and removes its guest capability file when Modal is reachable. The guest deliberately holds a bounded run capability; relay keys and upstream credentials belong outside it. This probe only authorizes `/v1/probe` and does not demonstrate an upstream credential adapter. An actor change invalidates its authorization through the registry.

Observation failures stop that probe and are logged. They do not change the agent's network path. This tests lifecycle integration; it does not enforce agent egress, remove guest credentials or remove agentsh. Named-VM recovery applies to standalone probes, not to ordinary Tasks VM creation. Production certificates, credential adapters and enforced routing remain separate work.

### Enroll selected normal runs

`tasks-agent-egress-enrollment` selects a bounded enrollment canary through the normal Tasks workflow. It is off by default and also requires `AGENT_EGRESS_ENROLLMENT_CONFIG` on the worker. The shared JSON file lives under `AGENT_EGRESS_PROBE_CONFIG_DIR`:

```json
{
  "endpoint_domain": "egress.example.com",
  "region": "test-us",
  "relay_image_id": "im-example",
  "server_ca_file": "/run/egress/server-ca.pem",
  "client_ca_file": "/run/egress/client-ca.pem",
  "client_ca_key_file": "/run/egress/client-ca-key.pem",
  "duration_seconds": 360
}
```

The region must match `AGENT_EGRESS_REGION`. Use separate regional material and a certificate covering `*.egress.example.com`. The worker derives `run-<run UUID without hyphens>.egress.example.com` and binds it to the run's team, actor, execution and provisioned sandbox. No per-run configuration file is needed. Keys stay in worker mounts and the isolated relay; workflow history carries IDs, the configuration path and the enrollment mode.

Set `renew_relay_certificate: true` in the enrollment or probe JSON only after selecting a relay image that supports certificate reload and `client_ca_file`. It defaults to false for existing images and executions. The worker installs the public enrollment CA in the sidecar and renews the same registered key halfway through the certificate's remaining lifetime. The renewal deadline is saved on the run so another worker can continue it.

```text
renew lease -> check registered key -> issue certificate
  publish atomically in sidecar -> SIGHUP identified process
  relay acknowledges reload -> save next renewal deadline
```

The relay retains its private key. The CA signing key stays with the worker. Renewal verifies the process identity before signalling, waits for the reload result and restores the previous file on failure. A failed delivery does not advance the saved deadline. The existing lease and run checks still apply before publication; certificate renewal does not extend the observation window or restore revoked authority. A 600-second observation can exercise the first renewal of a 15-minute certificate, but cannot prove continuity past its original expiry. Use an isolated test with short-lived certificates for that check until full-run enrollment is available. Enrollment-CA rotation remains separate.

```text
Selected TaskRun -> ordinary VM provision and agent launch
  attach relay -> register execution -> publish bounded capability
  renew lease and capability while synthetic requests run
  parent ends / replaces VM / continues as new -> revoke and close relay
```

Enrollment uses the existing probe lifecycle and authorizes only `/v1/probe`. It requires a fresh, noninteractive Modal VM with full network access. It skips snapshots and reserves 1 GiB for the sidecar. Existing agent routing, credentials and agentsh behavior remain unchanged.

Deploy the matching proxy image before enabling enrollment. Each proxy replica limits a relay's authenticated TLS key to 32 requests/second with a burst of 512, including requests with missing or invalid capabilities. This covers the configured 256-request probe rounds with room for startup. Changing tokens, connections or identity headers does not create another budget; certificate renewal with the same key and verifier reload preserve it. Budgets are replica-local and reset on process restart, so capacity scales with the replica count. The budget table is bounded by `cache_entries`; new keys are refused when all entries are live.

Excess requests receive 429 before registry lookup or normal audit reservation. Every refusal increments `egress_requests_total{outcome="rate_limited"}`. Audit records include the authenticated relay-key fingerprint; rate-limit records are coalesced to one admission/completion pair per key per ten seconds, subject to audit availability. The metric counts all refusals, while the audit marker identifies affected relay keys without letting rejected traffic fill the shared queue.

Rate-limit responses preserve HTTP/2 connections and bodyless HTTP/1.1 connections, so retrying does not require a new TLS handshake.
An unread HTTP/1.1 body still closes the connection promptly; HTTP/2 closes the rejected stream while other streams can continue.

The feature flag selects new enrollments; turning it off does not revoke running ones. Each activity rereads worker configuration and the run binding. Removing or changing configuration stops renewal; cleanup can revoke and remove its relay even if the configuration file is gone. An unavailable worker leaves authority bounded by the 30-second lease. Delayed cleanup cannot close a replacement relay or the agent VM.

This canary lasts at most 600 seconds and does not restart after sandbox replacement or workflow continuation. Its relay lifetime includes a three-minute provisioning allowance, and its client certificate lasts at most 15 minutes. Provision a client CA that remains valid for the whole window. Full-run enrollment needs certificate renewal and longer-lived relay management before removing these limits. A normal run may outlive its canary; enrollment failure is logged and does not fail the agent run.

## Run the processes

### Container images

From the repository root:

```bash
docker build -t agent-egress-proxy -f products/tasks/services/egress-proxy/Dockerfile products/tasks/services/egress-proxy
docker build -t agent-egress-relay -f products/tasks/services/egress-proxy/Dockerfile.relay products/tasks/services/egress-proxy
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:8443:8443 \
  --mount type=bind,src=/run/egress,dst=/run/egress,readonly \
  agent-egress-proxy -config /run/egress/proxy.json
```

The proxy runs as UID/GID 65532 with no shell. Give that user read access to its mounted configuration and keys. Its admin listener stays on loopback inside the container; do not publish it.
The relay image includes Python and OpenSSL for enrollment; the controller locks with Python's `fcntl.flock`. The image defaults to `sleep infinity` for manual runs. Modal's controller supplies its own sleep command, then starts `/usr/local/bin/egress-relay` after installing its configuration and certificate.
It runs as root inside the isolated sidecar because the controller writes `/run/egress` and may pin the development endpoint in `/etc/hosts`. Moving those writes to a user-owned directory and removing the hosts-file override must precede running the relay as UID/GID 65532.

Local Docker builds target the host architecture and are for smoke tests. Use the Modal builder above for the sandbox image.

Both builds cross-compile Go for the target architecture, use digest-pinned bases and copy only Go source and module files. Pass `--build-arg COMMIT_HASH=<revision>` when building a release; local builds default to `development`. No credentials or configuration are baked in.
CI starts both images with temporary TLS material, checks readiness and verifies that a request through the relay reaches the proxy and is rejected without a capability. Run the same check locally with `bash products/tasks/services/egress-proxy/scripts/smoke_images.sh` after building the images above.
After tests and image smoke checks pass, the `Agent Egress` workflow publishes multi-architecture images from GitHub-hosted Ubuntu runners on master in the repository with `CD_DEPLOY_ENABLED=true`:

- `posthog-agent-egress`: the regional service.
- `posthog-agent-egress-relay`: the Modal sidecar.

Each shared-services ECR image has an immutable full-commit tag and an ordered `r<position>-<short-sha>` alias for Kargo. The workflow verifies that the alias resolves to the published digest and prints the digest in its summary. Push and manual runs for the same commit serialize, and retries reuse an existing commit image. `ORDERED_IMAGE_ALIAS_PAUSED=true` pauses publication of both tags. Pull requests only build and test; manual publication also requires master.

The ECR repositories and their publisher permissions must exist before enabling publication. Consume images by digest; a release does not update the development probe's `relay_image_id` or deploy the service. Certificate delivery and regional deployment remain separate work.

### Local binaries

From the repository root:

```bash
go -C products/tasks/services/egress-proxy build -o /tmp/agent-egress/ ./cmd/...
/tmp/agent-egress/egress-proxy -config /run/egress/proxy.json
/tmp/agent-egress/egress-relay -config /run/egress/relay.json
```

Run each command in its own process.
The proxy configuration names its TLS material, verification bundle and regional registry:

```json
{
  "certificate_file": "/run/egress/server.pem",
  "private_key_file": "/run/egress/server-key.pem",
  "client_ca_file": "/run/egress/relay-ca.pem",
  "verification_keys_file": "/run/egress/verification-keys.json",
  "registry_url": "https://registry.example.com",
  "registry_region": "test-region",
  "registry_signing_key_file": "/run/egress/registry-key"
}
```

The relay configuration names the exact run authority and its own client certificate:

```json
{
  "endpoint": "https://run-a.egress.example.com",
  "admin_address": "127.0.0.1:9091",
  "certificate_file": "/run/egress/relay.pem",
  "private_key_file": "/run/egress/relay-key.pem",
  "client_ca_file": "/run/egress/enrollment-ca.pem"
}
```

Use `registry_ca_file` or `server_ca_file` for a private registry or regional CA, respectively.
Keep relay private-key files outside the guest's filesystem.
The relay receives the capability from the guest's `Authorization` header.
Neither process accepts CONNECT or general upstream destinations.

| Setting                    | Proxy default    | Relay default    |
| -------------------------- | ---------------- | ---------------- |
| `listen_address`           | `:8443`          | `127.0.0.1:8080` |
| `admin_address`            | `127.0.0.1:9090` | `127.0.0.1:9090` |
| `request_timeout_seconds`  | 30               | 300              |
| `shutdown_timeout_seconds` | 10               | 10               |

The relay's request budget includes connecting to the proxy and forwarding its response.
The proxy's budget covers its own request handling; its only operation is currently the probe.
The relay also waits at most 30 seconds for response headers.
Before adding streaming adapters, set and test these budgets together, leaving room in the relay's budget for connection and forwarding time.

Listener addresses must use IP literals. Administration must bind to loopback.
It exposes `GET /livez`, `/readyz` and `/metrics` on its own listener; those routes do not exist on the request listener.
Use `egress-proxy -config /run/egress/proxy.json -healthcheck ready` for a Kubernetes exec readiness probe, or `-healthcheck live` for liveness. The relay supports the same flags with its own configuration.
The check calls the configured loopback listener directly, refuses redirects and exits nonzero on failure within two seconds. It needs no shell, upstream credentials or access to the TLS key files.
Readiness checks local material and audit health, not registry or upstream availability.
Keep a relay's plaintext HTTP listener on a provider-isolated bridge if it must be reachable outside loopback.

Proxy limits default to `lookup_timeout_seconds=2`, `cache_entries=10000`, `cache_lookups=64` and `audit_capacity=4096`.
The limits are configurable; unknown configuration fields and invalid limits stop startup.

Send SIGHUP to the proxy after replacing its referenced TLS, CA, verification-key or registry-key files.
It loads them together and retains the active configuration if any file is invalid.
Failed reloads log the reason to stderr without exposing file contents.
Every request checks the current client CA, including requests on reused TLS connections.
The relay also reloads its certificate, key and server CA files on SIGHUP. Renewed certificates must use the same public key; a new key needs a new execution registration.
Set `client_ca_file` to the enrollment CA bundle trusted by the regional proxy. Reload verifies the candidate's client-authentication chain against this bundle. Existing configurations can start without it, but cannot reload certificates until it is configured and the relay restarted.
Successful relay reloads replace the upstream connection pool and close its idle connections. In-flight requests can finish, and new requests use the renewed certificate even on an existing guest connection.
Invalid material leaves the previous material active. Readiness and new requests fail once that certificate expires. Opted-in workers issue and publish renewed certificates through the existing renewal activity; SIGHUP does not extend enrollment or relay process lifetime.
Listener addresses, endpoints and limits require a restart.
SIGINT and SIGTERM drain requests, then audit output, each within the shutdown timeout.

### Audit output

The proxy writes versioned admission and completion events as JSON lines to stdout; lifecycle logs go to stderr.
Events include a generated request ID, trusted run identity when authorization succeeds, operation, outcome, status and duration.
They exclude tokens, raw URLs, headers and bodies.
Prometheus counters distinguish unavailable authorization, rejected identity, relay transport failures and reload failures.

Each request passing the rate limiter reserves room for both events before authorization.

| Failure                                 | Behavior                                                                                                                                  |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Output stalls and the queue fills       | New admissions receive 503 and increment `egress_audit_rejected_total`. Health checks stay healthy; admission resumes when output drains. |
| Output returns an error                 | New admissions receive 503, readiness and liveness fail, and `egress_audit_export_failed` becomes 1 until restart.                        |
| Collector or log storage is unavailable | Successful stdout writes do not acknowledge central delivery. Recovery and loss depend on collector buffering and node-log retention.     |

Configure the supervisor to restart on liveness failure and send SIGTERM for normal shutdown.
Queue pressure and planned draining do not fail liveness.
Shutdown attempts to drain accepted events; an output error, crash or drain timeout can lose buffered events.
This is bounded asynchronous output, not a durable audit guarantee. Deployment must connect stdout to the regional log collector.

## Adapter contract

Each run has a registered hostname, such as `run-a.egress.example.com`; many can share one regional load balancer.
On every request, the verifier checks TLS SNI, HTTP Host, signed run identity, actor, execution and relay certificate key against the registration.

The guest supplies its capability in `Authorization`.
The relay forwards it and uses mTLS to prove it holds the registered private key.
After verification, a future adapter must strip the capability and caller-supplied upstream auth before injecting managed credentials into a new upstream request.
The relay only connects to its configured endpoint. It rejects CONNECT, absolute request targets and protocol upgrades.

The relay does not retry writes after an upstream failure, even with an idempotency header.
This can return 502 when a stale connection fails before sending any bytes.
Safe retries need an operation that tolerates repetition, or transport support that proves the request was never sent.

`relay.Config.OnError` reports a failure category, never raw errors, URLs or credentials.
The callback must be safe for concurrent calls and must not block. Client errors stay generic.

`relay.Config.RequestTimeout` must be positive. It covers connection setup, upload and the full response; an earlier caller deadline wins.
Choose a budget that allows long streams to finish. Expiry cuts off an active stream.
The relay sets the same deadline on reads from and writes to the guest. Response wrappers must support `SetReadDeadline` and `SetWriteDeadline`, or expose the underlying writer through `Unwrap`.
If either deadline cannot be set, the relay reports the failure through `OnError` and aborts before sending anything upstream.

## Registration and time

`Lookup` receives the verified team, run and execution IDs and returns their current registration.
The registry cache serves entries within their authorization lease; reads cannot extend that lease.
A missing run returns `ErrUnauthorized`; lookup failures and timeouts return `ErrUnavailable`.
The regional handler returns HTTP 503 for unavailable authorization and counts it separately from rejected identities, without token values or per-run metric labels.

`LookupTimeout` must be positive. An earlier request deadline wins, and lookup code must honor cancellation.
The verifier rejects late results.
`ClockSkew` allows drift for issued-at and not-before times; zero allows none.
Tests allow three seconds. Capability, certificate-chain and lease expiry stay strict, even on reused TLS connections.

### Tasks registration

Trusted workers use `AgentEgressRegistry` in `backend/logic/services/agent_egress.py` to register, renew, revoke and issue capabilities.
Registration binds one execution to its team, actor, relay key, exact hostname and region, with a 30-second lease.
It also binds the execution to its sandbox. Lookup, renewal and capability issuance check that the run still owns that sandbox. Standalone development probes use their saved execution state; registrations without a sandbox binding are denied.
Workers must save the new sandbox binding before registering its execution. Registration rejects a sandbox that the run does not yet own. Saving the same binding again leaves the registration active.
It keeps the run's exact team ID, including for child environments.
Reads and registration retries do not renew it. Renewal requires a live lease; an expired or revoked execution cannot be reused.
Replacement requires the previous execution ID and keeps the old registration revoked.
Workers recover that ID through `latest`, which includes expired and revoked registrations but cannot authorize requests.
The registry assigns actor epochs under the run lock: one for the first execution, increasing on each replacement and unchanged on retries.
Cancellation requests stop lookup, renewal and issuance even before the run reaches a terminal status.
The Tasks workflow stops its egress child before writing a terminal status. Renewal and probe activities also recognize cancellation requests and terminal statuses, so a run ending during either operation retains its reason. Missing, revoked or expired authority on a live run still fails the child.
Failed probe rounds emit `agent_egress_probe_failed` with their status counts before checking whether the run ended. A normal child completion does not erase that failure evidence.

Changing or clearing the run's sandbox, or preparing a cloud resume, revokes its existing registration in the same transaction. If revocation fails, the state change fails too: otherwise restoring earlier run state could revive the old registration. Unrelated state updates do not access the egress table.

Sandbox cleanup revokes matching registrations before contacting the provider; delayed cleanup of an old sandbox leaves its replacement alone. A revocation failure is logged and provider teardown still runs. Connection metadata stays in run state until cleanup succeeds; strict cleanup reports the failure for retry. A later retry can revoke and clear that state even when the VM is already gone. The proxy can still use a cached lease until its existing deadline.

Registrations created before sandbox binding was added remain unbound and are denied, even if their stored `revoked` flag is false. In-flight development probes need a fresh execution after deployment. Replacement revokes the old row without inventing a historical revocation timestamp.

These checks apply to the current development enrollment path. Production enrollment still needs regional deployment, private registry access and managed certificate issuance and renewal. They do not route agent traffic through the proxy or remove agentsh.

Capabilities last five minutes, with `iss=posthog:tasks`, `aud=posthog:agent_egress`, `sub` set to the run ID and a separate `execution_id`.
Issuance checks current registration and pins the signing key in the run's existing `sandbox_jwt_kid` state.
A removed pinned key stops issuance instead of silently changing the signer.

The read-only route is:

```text
GET /api/projects/{team_id}/internal/agent_egress/runs/{run_id}/executions/{execution_id}
```

It uses a separate service JWT with audience `posthog:agent_egress_registry`, `operation=lookup`, and matching `team_id`, `sub`, `execution_id` and `region` claims.
Include integer `iat` and `exp`, at most 30 seconds apart.
Configure `AGENT_EGRESS_REGION` and dedicated `AGENT_EGRESS_REGISTRY_JWT_SECRETS` independently per region; keys are comma-separated, newest first. Both default to empty.
Guest capabilities cannot call this route. Missing or inactive registrations return 404; no write route is exposed.
Registry clients must treat 401/403 as service-authentication failures, not revoked guest authority, and report them as unavailable.
The `/internal/` route also needs private ingress when the service is deployed.

### Registry client and cache

`registry.New` takes a fixed HTTPS origin, region, active registry signing key and lookup timeout.

For a registry in the same Kubernetes cluster, `registry_allow_cluster_http: true` permits
HTTP to a fully qualified `<service>.<namespace>.svc.cluster.local` origin. It is off by
default. This sends lookup tokens and responses without transport encryption; the hostname
check is not a network boundary. Use it only with trusted cluster networking and an enforced
L7 policy that limits the destination pods, port, method and registry path. Keep HTTPS for
other origins. The registry must serve this internal endpoint over HTTP without an
HTTP-to-HTTPS redirect. Django's `SECURE_SSL_REDIRECT` can cause such a redirect; keep
HTTPS unless the internal route is configured to accept HTTP. The client refuses
redirects in both modes and reports them as unavailable.

It signs each lookup with a scoped 30-second service JWT and checks the response's team, run, execution and region.
It refuses redirects, limits response bodies to 16 KiB and honors cancellation through body reads.
It drains small error bodies within those same limits so HTTP/1.1 connections can be reused.
Only a 404 or an explicitly revoked registration returns `ErrUnauthorized`; transport, service-authentication and invalid-response failures return `ErrUnavailable`.
The default transport connects directly to the configured registry, without an environment proxy.

Wrap `client.Lookup` with `registry.NewCache` and pass `cache.Lookup` to the verifier.
Set both the maximum cached entries and concurrent registry lookups.
The cache uses team, run and execution as its key, evicts the least recently used entry at capacity, and shares concurrent lookups for one key.
Each cache belongs to one regional client.

Active entries refresh on the first request after 19–21 seconds.
That request waits for the lookup; other requests can use the still-valid entry.
An unavailable registry leaves the current lease usable and schedules the next refresh attempt at least one second later.
That retry delay survives lease expiry; requests then return unavailable until the retry is due.
Denials and failures share the cache's entry limit and eviction policy.
A 404 clears cached authority immediately and caches the denial for one second.
An unavailable result can preserve an existing live lease, but cannot create or extend one.
Cache misses fail with `ErrUnavailable` when lookup capacity is full.
The request that starts a lookup supplies its deadline; if it is cancelled, waiting callers must retry.

The cache stops using a lease three seconds before its absolute expiry and caps local validity at 27 seconds from lookup start.
An elapsed-time deadline prevents backward clock changes from extending that window.
Wall-clock drift beyond three seconds from the process's elapsed clock stops lookups until the clock recovers or the cache is recreated after clock synchronization.
Workers still renew the 30-second registration lease separately.
There is no push invalidation yet, so cached authorization can survive revocation for the remainder of its lease.

### Verification keys

Export the public `kid` → PEM bundle from the repository root:

```bash
python manage.py export_sandbox_jwt_public_keys > sandbox-jwt-public-keys.json
```

The export includes all configured signing keys' public halves and any explicit verification keys.
`identity.ParseKeyBundle` accepts RSA public keys only. Private signing keys stay with the issuer.
Publish the new public key before switching signing keys, and keep the old key while pinned runs still use it.
Mount the bundle through `verification_keys_file`; SIGHUP reloads it without restarting the proxy.
Launch integration must revoke the old registration before resume or restore, then register the new execution and relay key.

## General forwarding decision

The planned general forwarding path is a transparent TLS relay for eligible Modal cohorts. It is not implemented here.
A new sidecar binary will accept raw TLS on TCP/443 and run the adapter handler on a separate internal HTTP port.
Both use the same registered execution and relay key.

```text
Adapter client -> sidecar HTTP handler -> regional adapter -> managed upstream
HTTPS client   -> Modal TCP/443 route  -> sidecar TLS relay -> regional tunnel -> public upstream
```

The relay reads a size-limited ClientHello, takes the destination from SNI and forwards the original TLS bytes through a CONNECT tunnel to the regional service.
The outer TLS connection uses the run hostname and mTLS key. A worker supplies a renewable capability in `Proxy-Authorization`, bound to that key: raw TLS cannot carry the guest's capability header.
The sidecar holds this capability, but no managed upstream credentials.

CONNECT names the destination, not the run hostname.
The regional handler must verify the run and key, check the destination and public IPs, and match inner SNI to the CONNECT target before forwarding.
The adapter's Host-equals-run-hostname check needs a different form here.
Tunnels close on revocation or lease expiry, emit connection-level audit and never send proxy auth upstream.

Destinations that use managed credentials, including known aliases, must go through adapters and stay blocked on tunnels.
An encrypted tunnel cannot check HTTP Host, paths or bodies, or stop domain fronting through an allowed shared endpoint. Workloads needing those checks need a route that can inspect HTTP. See [Modal's inspection example](https://modal.com/docs/examples/sidecar_traffic_routing#block-domain-fronting).
Managed Git/GitHub operations still need adapters. Proxy-aware clients can also use explicit CONNECT for general forwarding, without an adapter per destination.

### Modal cohort configuration

Set `proxy_traffic_via_sidecar` to the relay sidecar name and `outbound_cidr_allowlist=[]` on the main sandbox.
Modal redirects TCP/443 despite the empty CIDR allowlist. Other public ports stay blocked, and traffic stops if the sidecar is absent.
This mode cannot also use `block_network`, a domain allowlist, Modal Proxy or Outbound Policy.
Restrict the sidecar's own egress to the regional endpoint; its default is open.
This needs a separate launch profile. See [Modal sidecar routing](https://modal.com/docs/guide/sandbox-sidecars#routing-https-traffic-through-a-sidecar).

Only TCP/443 is covered; the original destination IP is unavailable. Reject missing or encrypted SNI initially.
Git over SSH, plaintext HTTP, other ports and QUIC need separate support. DNS still bypasses this path. See [Modal networking](https://modal.com/docs/guide/sandbox-networking).

Before rollout, test provider isolation, sidecar loss/replacement, blocked direct access and sandbox restore.
Check Git HTTPS, npm, pip and browsers, including redirects and blocked managed destinations.
Local tests do not prove any of these provider or client behaviors.

## Local verification

From the repository root:

```bash
go -C products/tasks/services/egress-proxy test -race ./...
```

Go tests use generated keys and an in-memory registry. A shared synthetic fixture checks that Python issuance matches Go verification.
Tasks tests cover registration, renewal, replacement, revocation, scoped lookup and key rotation.
The transport tests cover identity binding, reused HTTP/2 connections, expiry, lookup failures, clock skew and stalled uploads.
Guest-to-relay traffic uses plain HTTP on loopback; only relay-to-service TLS is tested. The deployed private bridge still needs isolation tests.
Tests use no Modal sandbox or upstream credentials. Task launches are unchanged.
