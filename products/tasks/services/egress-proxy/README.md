# Agent egress

This module verifies run capabilities and relays HTTP requests to one configured endpoint.
It does not yet include a runnable service, sandbox provisioning, credential injection, registry client or production metrics.

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

`Lookup` returns the current registration. It can use a local cache while the authorization lease is valid; reads cannot extend that lease.
The registration layer owns updates, invalidation and renewal.
A missing run returns `ErrUnauthorized`; lookup failures and timeouts return `ErrUnavailable`.
Production callers must return HTTP 503 for unavailable authorization and count it separately from rejected identities, without token values or per-run metric labels. Only the test handler does this mapping today.

`LookupTimeout` must be positive. An earlier request deadline wins, and lookup code must honor cancellation.
The verifier rejects late results.
`ClockSkew` allows drift for issued-at and not-before times; zero allows none.
Tests allow three seconds. Capability, certificate-chain and lease expiry stay strict, even on reused TLS connections.

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

Tests use generated keys and an in-memory registry. They cover identity binding, reused HTTP/2 connections, expiry, revocation, execution changes, lookup failures, clock skew and stalled uploads.
Guest-to-relay traffic uses plain HTTP on loopback; only relay-to-service TLS is tested. The deployed private bridge still needs isolation tests.
Tests use no Modal sandbox or upstream credentials. Task launches are unchanged.
