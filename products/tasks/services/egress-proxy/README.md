# Agent egress

This module verifies run capabilities and relays HTTP requests to one configured endpoint.
Tasks owns registration and capability issuance.
The registry client and cache are available; the runnable service, sandbox wiring and credential injection are still to come.

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
Production callers must return HTTP 503 for unavailable authorization and count it separately from rejected identities, without token values or per-run metric labels. Only the test handler does this mapping today.

`LookupTimeout` must be positive. An earlier request deadline wins, and lookup code must honor cancellation.
The verifier rejects late results.
`ClockSkew` allows drift for issued-at and not-before times; zero allows none.
Tests allow three seconds. Capability, certificate-chain and lease expiry stay strict, even on reused TLS connections.

### Tasks registration

Trusted workers use `AgentEgressRegistry` in `backend/logic/services/agent_egress.py` to register, renew, revoke and issue capabilities.
Registration binds one execution to its team, actor, relay key, exact hostname and region, with a 30-second lease.
It keeps the run's exact team ID, including for child environments.
Reads and registration retries do not renew it. Renewal requires a live lease; an expired or revoked execution cannot be reused.
Replacement requires the previous execution ID and keeps the old registration revoked.
Workers recover that ID through `latest`, which includes expired and revoked registrations but cannot authorize requests.
The registry assigns actor epochs under the run lock: one for the first execution, increasing on each replacement and unchanged on retries.
Cancellation requests stop lookup, renewal and issuance even before the run reaches a terminal status.

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
Mounting and reloading this bundle belongs to the runnable-service deployment; it is not wired here yet.
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
