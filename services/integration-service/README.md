# integration-service

Serves PostHog's **platform integration credentials** — the OAuth app client ids/secrets and API
keys PostHog itself owns, as opposed to a customer's — over HTTP, so they stop being injected as
environment variables into every pod that might need one. Today those keys are duplicated across
the Django stack and each temporal worker's chart values, and adding one means a `PostHog/charts`
PR plus knowing in advance which pods need which key.

This is phase 1. The per-team `Integration` model, the OAuth flows and token refresh come later;
nothing here touches them.

## What it does and does not buy

An attacker who has compromised a pod still holds that pod's JWT signing key, and can ask for any
credential in the manifest. Per-request key scoping contains a _leaked token_, not a _compromised
pod_. The wins are:

1. Environment dumps stop containing credentials — `/proc/self/environ`, crash reports, a stray
   `printenv` in a log, and environments inherited by subprocesses.
2. Every read is attributed, so rotating after a suspected exposure is scoped to what was actually
   accessed.
3. A compromised deployment is cut off by revoking one signing key, without disturbing any other
   deployment.
4. Rotation stops needing a charts PR and a rolling restart.

Nothing here stops a compromised pod reading credentials it is entitled to read, and no list is
maintained pretending otherwise.

## API

```text
GET  /_liveness          200 always
GET  /_readiness         200 once the pod holds a credential snapshot
GET  /metrics            prometheus text (bearer-gated when a token is configured)
POST /v1/secrets/resolve
```

**The request scope lives in the JWT and there is no request body.** The token _is_ the request,
so a body and a claim cannot diverge, and a token lifted from a log unlocks only the fields that
one call needed:

```jsonc
// Authorization: Bearer <token>
{
  "caller": "warehouse-sources", // the product that asked; recorded, not trusted
  "keys": ["GOOGLE_ADS_APP_CLIENT_ID", "GOOGLE_ADS_APP_CLIENT_SECRET"],
  "aud": "posthog:integration_service",
  "exp": 1786035932,
}
```

```jsonc
{
  "secrets": {
    "GOOGLE_ADS_APP_CLIENT_SECRET": {
      "state": "rotating",
      "value": "…",
      "previous": "…",
      "version_id": "…",
      "fetched_at": "…",
    },
  },
  "missing": [], // unknown key, or no value in this environment
}
```

An unresolvable field is reported per key in `missing` rather than as a 4xx over the whole batch,
so a mistyped name reads as one named field a human can act on while the rest still succeeds.

Callers do not cache, so there is no freshness hint to send. A rotation reaches every caller on
their next read.

## Auth

Per-deployment HS256 JWT, following the `recording-api` scheme (PostHog/posthog#67476) — the
pattern `.agents/security.md` names as strongly preferred, not `INTERNAL_API_SECRET`.

Two identities, deliberately not conflated:

|                | What it is                                                                                               | Trusted?                                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Deployment** | The pod set that signed the token (`posthog-django`, a temporal worker)                                  | Yes. It is derived from _which key verified the token_, never from a claim, so there is nothing in the token to forge |
| **Product**    | The code path that wanted the credential (`warehouse-sources`, `cdp`), from a code enum at the call site | No. Django holds one key and hosts many products, so a compromised Django pod could name any of them                  |

Authorization hangs off the deployment. The product exists so an incident can ask "which product
read this", and is collapsed to a constant when unrecognised, so it can never become an unbounded
metric label.

**There is no per-deployment provider allowlist.** Every authenticated deployment may read any
credential in the manifest: a list bounds nothing the signing key does not already bound, and a
compromised deployment is contained by revoking its key. What a deployment actually read is in
the audit log and the usage rollup.

So one thing bounds a request: the `keys` claim, which _is_ the request, for as long as the token
has left to run — the verifier requires an `exp`.

The corollary is a rule on the manifest: **only outbound credentials belong in it.** Anything in
`providers.ts` is readable by every deployment holding a signing key. For an OAuth app secret we
present to a third party that is no expansion — the pod already had its own copy in its
environment. For an inbound-request authenticator such as a webhook signing secret it would be
one, so those stay as plain env vars on the deployment that checks them.

Signing keys live in the same secret as the credentials, one flat entry per deployment
(`CALLER_KEY_<DEPLOYMENT>`). Deployment names are derived from the entries present, not declared
in code, so onboarding a caller or revoking a compromised one is a secrets edit with no deploy.
The same value goes into that deployment's own secret as `INTEGRATION_SERVICE_JWT_SECRET`.

`Verifier` is an interface so a Kubernetes projected-ServiceAccount-token verifier (TokenReview)
can drop in later without touching the routes or the policy layer.

## Storage and rotation

**One secret holds everything**: `integration-service-secrets`, a flat map of `KEY: value` pairs.
Flat and uppercase because the `PostHog/secrets` CLI and UI only manage `[A-Z0-9_]+` keys with
plain string values.

External Secrets Operator syncs that secret into a Kubernetes Secret, and kubelet mounts it as a
directory of one file per key. Kubelet rewrites the mount in place and swaps the `..data` symlink
atomically, so a rotation reaches the pod without a restart and a read never sees a half-written
set. The service re-reads on a jittered timer (`src/snapshot.ts`) and holds the parsed snapshot
in memory; each replica's period is drawn fresh per tick from [0.5×, 1×] of
`INTEGRATION_SERVICE_RELOAD_SECONDS`, so it never stretches past the configured value.

A pod with no snapshot fails its readiness probe rather than exiting, so an empty mount recovers
on its own once ESO syncs instead of crash-looping. A mount that stops being readable keeps the
previous snapshot, with `integration_secret_serving_stale_seconds` as the only sign.

```text
integration-service-secrets
  STRIPE_APP_SECRET_KEY                 = "<credential>"
  STRIPE_APP_SECRET_KEY_FALLBACKS       = "<outgoing value, only while rotating>"
  INTEGRATION_RECOVERY_KEYS             = "<comma-separated key names>"
  CALLER_KEY_POSTHOG_DJANGO             = "<new>,<old>"
```

**Rotation rides an explicit `<KEY>_FALLBACKS` sibling, not AWS staging labels.** `AWSPREVIOUS`
applies to a whole secret version, so with everything in one secret, rotating Google — or adding
an unrelated key — would consume the slot Stripe's in-flight rotation was using and end its
overlap silently. A sibling key is unaffected by edits to anything else, and it is the convention
PostHog already uses for rotatable keys (`SECRET_KEY_FALLBACKS`), so the rotation guard in
`PostHog/secrets` grades these automatically.

Starting a rotation means writing the new value and moving the outgoing one into the sibling.
Completing it means deleting the sibling. Two rotations can be in flight at once without
interfering.

| State      | Condition                                        | Response                              |
| ---------- | ------------------------------------------------ | ------------------------------------- |
| `steady`   | no `_FALLBACKS` sibling, or it repeats the value | `value` only                          |
| `rotating` | the sibling holds a different value              | `value` + `previous`                  |
| `recovery` | field named in `INTEGRATION_RECOVERY_KEYS`       | no value; caller raises a typed error |

`recovery` covers a credential that is known-burned with no valid replacement yet. These
credentials authenticate _PostHog_ to the third party, so there is no per-user "reconnect": the
integration is down for everyone until an engineer re-provisions the app. The state buys callers
an immediate, distinct error, so the outage is attributable instead of looking like a third-party
problem.

Only fields named in `src/providers.ts` are ever served. A field present in the secret but absent
from that manifest is ignored, so adding a credential is a reviewed code change and never just a
secrets edit.

### Knowing when the old value is safe to delete

Nothing is reported to this service by a caller: every metric and verdict is measured here
(`src/usage/verdict.ts`), so none of it depends on a client being well behaved, current, or
honest. That rules out observing which value a caller's third-party call succeeded with, so the
verdict is built from what we can see:

> `safeToRetirePrevious` is true when **every deployment known to read this key has read it since
> the secret last changed**, and at least one such deployment exists.

The threshold is the secret's version timestamp rather than a per-field one; an unrelated edit
moves it forward and only delays the verdict.

This is sound only because callers do not cache. A read after activation necessarily returned the
new value, so "has read since" means "is now on the new value". If a client-side cache is ever
reintroduced, this verdict stops holding and has to be rethought.

The "at least one" clause is not redundant: with nothing reading the key, "no reader is still on
the old value" is vacuously true, which is exactly the state where retiring looks safe and is
not. A deployment that reads a key rarely delays the verdict rather than rushing it, which is the
correct direction to be wrong in.

## Postgres

Postgres carries the usage counters and the version-observation log, and holds no credential.
Durability is the point: the counters decide whether an old credential is safe to retire, and
losing a stale reader's row flips that verdict to "safe" while the reader is still on the old
value. A store with an eviction policy cannot be trusted with an input to that decision.

Writes are batched in memory and flushed on a timer; an upsert per read would put a write on the
hot path for nothing. A crash loses at most one flush interval of counts — and only that much,
because shutdown (including `unhandledRejection` and `uncaughtException`) drains the server, then
flushes the recorder, then closes the pool.

Three tables, applied as idempotent DDL at boot (retried once, since replicas booting together
can race the `CREATE TABLE IF NOT EXISTS` statements):

| Table                          | Holds                                    | Pruned?                        |
| ------------------------------ | ---------------------------------------- | ------------------------------ |
| `integration_secret_usage`     | read counts per key, deployment and hour | yes, past the retention window |
| `integration_secret_last_seen` | when each deployment last read each key  | **never**                      |
| `integration_secret_version`   | when each content hash was first seen    | no                             |

`integration_secret_last_seen` is separate from the counts and never pruned on purpose: the
retirement verdict has to consider every deployment known to read a key, not only those active
inside the rolling window, or a consumer that reads rarely would drop out of the verdict.

A mounted secret carries no AWS version, so `integration_secret_version` is what "the value
changed at" means: the first time any replica saw this content hash, recorded centrally so
replicas agree and the answer survives a restart.

The DSN comes from the `psql:` harness in the `posthog-app` chart, so connections go through
PgBouncer in transaction mode. Nothing here may rely on session state: no `LISTEN`/`NOTIFY`, no
session-scoped settings, no server-side named prepared statements.

## Metrics

Every label value comes from fixed configuration, never from a request: a key the manifest does
not define and a product the service does not recognise both collapse to a constant.

| Metric                                                                     | What it answers                                                     |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `integration_secret_resolve_total{deployment,product,provider,key,result}` | who read what, and whether it resolved                              |
| `integration_secret_last_resolved_timestamp{provider,key}`                 | which credentials nothing reads any more                            |
| `integration_secret_previous_version_served_total{provider,key}`           | how much traffic is reading a key mid-rotation                      |
| `integration_secret_age_seconds`                                           | time since the secret last changed — drives "not rotated in N days" |
| `integration_secret_serving_stale_seconds`                                 | how long this pod has served a snapshot it could not refresh        |
| `integration_secret_store_errors_total`                                    | mount reads that returned nothing                                   |
| `integration_service_signing_keys_last_loaded_timestamp`                   | staleness means a revocation has not landed on this pod             |
| `integration_service_signing_key_reload_failures_total`                    | reloads that kept the previous key set                              |
| `integration_service_auth_failures_total{reason}`                          | rejected tokens, by why                                             |
| `integration_service_http_requests_total{method,route,status}`             | request volume, with an unmatched path collapsed to `other`         |
| `integration_service_http_request_duration_seconds{method,route,status}`   | request latency                                                     |
| `integration_service_shutting_down`                                        | 1 while draining                                                    |

Two of these exist because a fail-open needs to be visible: the signing-key reload keeps the
previous keys when an edit is malformed, and an unreadable mount keeps the last snapshot. Alert
on the two staleness signals, or neither degradation is observable.

`/metrics` is bearer-gated and the token is production-required: the resolve counter is a precise
map of which deployment reads which credential, even though it carries no values.

## Isolation

This package must not depend on the rest of the monorepo. It shares the pnpm workspace only for
resolution — nothing from `nodejs/`, `frontend/` or `common/`. The package's own
`.oxlintrc.json` enforces that with a `no-restricted-imports` rule, so `pnpm lint` fails on any
import that reaches outside.

Installs run `--ignore-scripts`; nothing in the tree needs an install-time script, and that is
the npm-specific supply-chain path worth closing here.

## Local development

```bash
pnpm --filter @posthog/integration-service dev                # tsx watch, pretty logs
pnpm --filter @posthog/integration-service typecheck
pnpm --filter @posthog/integration-service test:unit
pnpm --filter @posthog/integration-service test:integration   # needs Docker (testcontainers)
```

`pnpm vitest run` with no path runs both suites, so it needs Docker; without Docker, run
`test:unit`. The integration suite starts a disposable Postgres with testcontainers and boots a
real `IntegrationServer` against a temp-dir mount, so it covers the SQL and the HTTP wiring the
unit suite fakes.

Point `INTEGRATION_SERVICE_SECRETS_DIR` at a directory of files, one per key, to stand in for the
mount. With `INTEGRATION_SERVICE_DATABASE_URL` unset the service runs without usage recording,
which costs the rollup and nothing else.

## Configuration

| Variable                             | Default                    | Notes                                                    |
| ------------------------------------ | -------------------------- | -------------------------------------------------------- |
| `INTEGRATION_SERVICE_ENV`            | `dev`                      | Logical env; recorded on the usage rollup                |
| `INTEGRATION_SERVICE_SECRETS_DIR`    | `/etc/integration-secrets` | Where the Kubernetes Secret is mounted                   |
| `INTEGRATION_SERVICE_DATABASE_URL`   | —                          | From the chart's `psql:` harness. Required in production |
| `INTEGRATION_SERVICE_RELOAD_SECONDS` | `30`                       | How often to re-read the mount                           |
| `INTEGRATION_SERVICE_USAGE_FLUSH_MS` | `10000`                    | How often to flush batched usage counters                |
| `INTEGRATION_SERVICE_RETENTION_DAYS` | `9`                        | How long usage buckets are kept                          |
| `INTEGRATION_SERVICE_METRICS_TOKEN`  | —                          | Bearer token for `/metrics`. Required in production      |
| `INTEGRATION_SERVICE_LOG_LEVEL`      | by `NODE_ENV`              | `debug`, `info`, `warn` or `error`                       |
| `PORT`                               | `8004`                     |                                                          |
| `HOST`                               | `0.0.0.0`                  |                                                          |
| `SHUTDOWN_GRACE_MS`                  | `15000`                    | Drain budget before exit                                 |
| `SHUTDOWN_PRESTOP_DELAY_MS`          | `5000`                     | Wait before draining, for the Kubernetes prestop window  |

The service exits at boot rather than starting degraded: a missing production variable, or a
numeric variable that does not parse. An empty secret mount does not exit; the pod fails its
readiness probe and recovers on its own once External Secrets Operator syncs.
