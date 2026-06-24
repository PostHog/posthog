# Security: authentication and key rotation

How the live event plane authenticates callers, how it separates read from write
and how signing keys rotate without downtime.

## Token model

agent-proxy is **verify-only**. It never signs. Django holds the RS256 private key
(`SANDBOX_JWT_PRIVATE_KEY`) and is the only minter. agent-proxy holds only the public half
(`SANDBOX_JWT_PUBLIC_KEY`) and verifies statelessly, with no Django or database round-trip on
the hot path. A compromise of agent-proxy cannot forge a token for any run.

Every request to either leg must carry a valid, unexpired, Django-signed RS256 bearer token.
agent-proxy checks signature, expiry, audience and claim types. Invalid or missing means `401`.

## Read vs write is enforced by audience

Two token types, each a single capability for a single run. Neither carries user identity.

|           | Client (browser)                                              | Sandbox                                                       |
| --------- | ------------------------------------------------------------- | ------------------------------------------------------------- |
| `aud`     | `posthog:stream_read`                                         | `posthog:sandbox_event_ingest`                                |
| Leg       | `GET /v1/runs/:run/stream`                                    | `POST /v1/runs/:run/ingest`                                   |
| Minted by | `create_stream_read_token` (after Django authorizes the user) | `create_sandbox_event_ingest_token` (at sandbox provisioning) |
| Grants    | read this run's stream                                        | append events to this run's stream                            |
| TTL       | `SANDBOX_TTL + 1h` (~7h)                                      | `SANDBOX_TTL + 1h` (~7h)                                      |

Each leg validates only its own audience (`jwt.ts` `validateStreamReadToken` /
`validateSandboxEventIngestToken`). jose enforces `aud` as part of verification, so a read token
POSTed to the ingest leg fails (`401`) and an ingest token on the read leg fails. The split is
cryptographic, not a matter of which token each party happens to hold.

Beyond audience, both handlers bind the token to the URL: the `run_id`, `task_id` and `team_id`
claims must match the path, else `403`. A token for run A cannot touch run B.

Credential delivery:

- The browser gets its read token from Django's `stream_token` endpoint, which is
  session-authenticated and permission-checked first. It presents the token as
  `Authorization: Bearer` only — no `?token=` query fallback, since query strings
  leak into upstream infrastructure access logs.
- The sandbox gets its ingest token injected at provisioning, baked into its env for the run
  lifetime. Bearer only, no query fallback.

A third token type, `posthog:sandbox_connection`, carries identity for direct sandbox connections
and is not used by agent-proxy.

## Key rotation without downtime

### How it works

Both tokens agent-proxy verifies are signed with the key the run was provisioned under and carry a
`kid` header (`connection_token.py` `_encode_run_scoped_token`), reusing the same key registry the
`sandbox_connection` token already uses. agent-proxy trusts a **set** of public keys —
`SANDBOX_JWT_PUBLIC_KEY` plus the optional `SANDBOX_JWT_PUBLIC_KEY_SECONDARY` — and accepts a token
that verifies under **any** of them (`verifyWithKeys`); only a signature mismatch advances to the
next key. Django verifies the same way against its registry (`_decode_sandbox_token`). So rotating
the primary key is zero-downtime across all three token legs, not just `sandbox_connection`.

### The principle

JWTs are distributed, long-lived bearer credentials. A token lives ~7h, and a sandbox provisioned
just before a rotation holds an old-key token for its whole run. You cannot flip atomically.

> The verifier must trust the old key and the new key at the same time, for an overlap window at
> least as long as the longest token TTL in circulation (~7h).

### The choreography

1. **Expand trust.** Teach agent-proxy to accept both the current and the new public key. Deploy.
   Signing is unchanged, so nothing functionally changes yet.
2. **Switch signing.** Make the new key Django's primary. Now in-flight old-key tokens and fresh
   new-key tokens both verify. This is the zero-downtime moment.
3. **Wait** at least the max TTL (~7h) so every old-key token has expired.
4. **Contract trust.** Drop the old key from agent-proxy and Django. Deploy.

Step 1 must ship and bake before step 2. Step 4 must wait until the TTL drains, not just until
signing flips.

### Implementation options

**A. Static dual key.** Add `SANDBOX_JWT_PUBLIC_KEY_SECONDARY`, load both, try the second key on a
verify miss. Mirrors Django's existing `SANDBOX_JWT_PRIVATE_KEY` / `_SECONDARY` idiom. Smallest
change. Without a kid, agent-proxy verifies per key on the miss path (one extra RSA verify, so keep
the expected key first to keep the common path single-verify).

**B. Static dual key + `kid` (recommended).** Add a `kid` header to the two token minters (Django
already computes kids) and give jose a resolver `(header) => keymap[header.kid]`. O(1) selection, no
network dependency, clean support for N keys. The smallest change that is correct rather than
brute-forced.

**C. JWKS + `kid`.** Django serves a JWKS of trusted keys by kid. agent-proxy uses jose
`createRemoteJWKSet`, which caches and auto-refreshes on an unseen kid. Rotation becomes
near-automatic with no agent-proxy redeploy or coordinated config flip. Cost: a network dependency
(mitigated by caching plus a cached fallback) and a Django endpoint to maintain. The OIDC-standard
approach, worth it once rotations are frequent or automated.

### Operational notes

- The overlap window is set by `SANDBOX_EVENT_INGEST_TOKEN_TTL` and `STREAM_READ_TOKEN_TTL`
  (`SANDBOX_TTL_SECONDS + 1h`). Shorter token TTLs make rotation cheaper.
- Keep the old key trusted until every sandbox provisioned under it has aged out, which the ~7h
  TTL covers.
- Until one of the options above lands, a primary-key rotation has a brief failure window on the
  agent-proxy legs. Plan rotations accordingly, or build Option B first.
- Rolling deploys interact with rotation the same way: every verifier must trust the full key set
  before any minter signs with a non-primary key. A Django pod that only verifies against the
  primary key rejects (401) tokens that a newer pod minted under a run's stored secondary `kid`,
  so do not enable `SANDBOX_JWT_PRIVATE_KEY_SECONDARY` while pods without multi-key verification
  are still draining — and conversely, finish or roll back a rotation before such a deploy.
