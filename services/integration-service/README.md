# integration-service

Serves PostHog's **platform integration credentials** — the OAuth app client ids/secrets and API
keys PostHog itself owns, as opposed to a customer's — over HTTP, so they stop being injected as
environment variables into every pod that might need one.

Today adding one means a `PostHog/charts` PR touching `shared/posthog-django/common.yaml` (which
fans out to ~14 Django AppSets) plus each temporal worker's `values.yaml`, and knowing in advance
which pods need which key. 26 keys are currently duplicated between the Django stack and the data
warehouse temporal worker alone.

This is phase 1 of the shared integration service. The per-team `Integration` model, the OAuth
flows and token refresh come later; nothing here touches them.

## What it does and does not buy

Worth being precise, because it shapes what had to ship in phase 1 rather than after it.

An attacker who has compromised a pod still holds that pod's JWT signing key, and can ask for any
credential in the manifest. Per-request key scoping contains a _leaked token_, not a _compromised
pod_. The wins are:

1. Environment dumps stop containing credentials — `/proc/self/environ`, crash reports, a stray
   `printenv` in a log, and environments inherited by subprocesses.
2. Every read is attributed, so rotating after a suspected exposure is scoped to what was actually
   accessed rather than to everything.
3. A compromised deployment is cut off by revoking one signing key, without disturbing any other
   deployment.
4. Rotation stops needing a charts PR and a rolling restart.

Points 2 and 3 are where the value sits. Note what is _not_ claimed: nothing here stops a
compromised pod reading credentials it is entitled to read, and no list is maintained pretending
otherwise.

## API

```text
GET  /_liveness          200 always
GET  /_readiness         200 once the client registry is loaded and providers are warmed
GET  /metrics            prometheus text (bearer-gated when a token is configured)
POST /v1/secrets/resolve
```

**The request scope lives in the JWT and there is no request body.** The token _is_ the request, so
a body and a claim cannot diverge, and a token lifted from a log or a trace unlocks only the fields
that one call needed:

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

An unresolvable field is reported per key in `missing` rather than as a 4xx over the whole batch, so
a mistyped name or an unset value reads as one named field a human can act on while the rest of the
request still succeeds.

Callers do not cache, so there is no freshness hint to send. A rotation reaches every caller on
their next read.

## Auth

Per-deployment HS256 JWT, following the `recording-api` scheme (PostHog/posthog#67476) — the
pattern `.agents/security.md` names as strongly preferred. Not `INTERNAL_API_SECRET`, which
`posthog/settings/data_stores.py` explicitly forbids extending.

Two identities, deliberately not conflated:

|                | What it is                                                                                               | Trusted?                                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Deployment** | The pod set that signed the token (`posthog-django`, a temporal worker)                                  | Yes. It is derived from _which key verified the token_, never from a claim, so there is nothing in the token to forge |
| **Product**    | The code path that wanted the credential (`warehouse-sources`, `cdp`), from a code enum at the call site | No. Django holds one key and hosts many products, so a compromised Django pod could name any of them                  |

Authorization hangs off the deployment. The product exists so an incident can ask "which product
read this", and is collapsed to a constant when the service does not recognise it, so it can never
become an unbounded metric label.

**There is no per-deployment provider allowlist.** Every authenticated deployment may read any
credential in the manifest.

A list would have to be kept current per deployment, which is the same friction this service exists
to remove, and it bounds nothing the signing key does not already bound: a compromised deployment
is contained by revoking its key, which leaves every other deployment working. What a deployment
actually read is in the audit log and the usage rollup, which is the more useful artifact after an
incident anyway.

So one thing bounds a request: the `keys` claim, which _is_ the request. A token lifted from a log
unlocks the fields of one call, for as long as it has left to run — the verifier requires an `exp`,
and the client mints for five minutes.

The corollary is a rule on the manifest: **only outbound credentials belong in it.** Anything in
`providers.ts` is readable by every deployment holding a signing key. For an OAuth app secret we
present to a third party that is no expansion — the pod already had its own copy in its
environment. For an inbound-request authenticator such as a webhook signing secret it would be one,
so those stay as plain env vars on the deployment that checks them.

Signing keys live in the same secret as the credentials, one flat entry per deployment
(`CALLER_KEY_<DEPLOYMENT>`). Deployment names are derived from the entries present, not declared in
code, so onboarding a caller or revoking a compromised one is a secrets edit with no deploy.

The same value goes into that deployment's own secret as `INTEGRATION_SERVICE_JWT_SECRET`.
Duplicating one value per deployment is inherent to shared-secret auth, and it replaces 26
duplicated credentials with one.

`Verifier` is an interface so a Kubernetes projected-ServiceAccount-token verifier (TokenReview)
can drop in later without touching the routes or the policy layer.

## Storage and rotation

**One secret holds everything**, the way every other PostHog service stores its configuration:
`integration-service-secrets`, a flat map of `KEY: value` pairs. Flat and uppercase is not a
preference — the `PostHog/secrets` CLI and UI only manage `[A-Z0-9_]+` keys with plain string
values, and a nested object would be invisible to the very tooling meant to operate this.

```text
integration-service-secrets
  STRIPE_APP_SECRET_KEY                 = "<credential>"
  STRIPE_APP_SECRET_KEY_FALLBACKS       = "<outgoing value, only while rotating>"
  INTEGRATION_RECOVERY_KEYS             = "<comma-separated key names>"
  CALLER_KEY_POSTHOG_DJANGO             = "<new>,<old>"
```

**Rotation rides an explicit `<KEY>_FALLBACKS` sibling, not AWS staging labels.** That is forced:
`AWSPREVIOUS` applies to a whole secret version, so with everything in one secret, rotating Google —
or simply adding an unrelated key — would consume the slot Stripe's in-flight rotation was using and
end its overlap silently. A sibling key is unaffected by edits to anything else.

It is also the convention PostHog already uses for rotatable keys (`SECRET_KEY_FALLBACKS`,
`JWT_SIGNING_KEY_FALLBACKS`), so the rotation guard in `PostHog/secrets` grades these automatically
and warns before an unsafe in-place edit.

Starting a rotation means writing the new value and moving the outgoing one into the sibling.
Completing it means deleting the sibling. Every other credential in the secret is untouched
throughout, so two rotations can be in flight at once without interfering.

| State      | Condition                                        | Response                              |
| ---------- | ------------------------------------------------ | ------------------------------------- |
| `steady`   | no `_FALLBACKS` sibling, or it repeats the value | `value` only                          |
| `rotating` | the sibling holds a different value              | `value` + `previous`                  |
| `recovery` | field named in `INTEGRATION_RECOVERY_KEYS`       | no value; caller raises a typed error |

`recovery` covers a credential that is known-burned with no valid replacement yet. These are the
client ids and secrets that authenticate _PostHog_ to the third party, so there is no per-user
"reconnect" to offer: the integration is down for everyone until an engineer re-provisions the app.
What the state buys is that callers fail immediately with a distinct error, so the outage is
attributable to a known cause instead of looking like a third-party problem.

`INTEGRATION_RECOVERY_KEYS` is a comma-separated list of key names in the same secret, which keeps
the whole layout flat.

Only fields named in `src/providers.ts` are ever served. A field present in the secret but absent
from that manifest is ignored, so adding a credential is a reviewed code change and never just a
secrets edit.

### Knowing when the old value is safe to delete

Nothing is reported to this service by a caller. Every metric and every verdict is measured here,
so none of it depends on a client being well behaved, current, or honest.

That rules out observing which value a caller's third-party call actually succeeded with, so the
verdict is built from something we can see instead:

> `safeToRetirePrevious` is true when **every deployment known to read this key has read it since
> the secret last changed**, and at least one such deployment exists.

The threshold is the secret's version timestamp rather than a per-field one. An unrelated edit moves
it forward and delays the verdict, which is the correct direction to be wrong in.

This is sound only because callers do not cache. A read after activation necessarily returned the
new value, so "has read since" means "is now on the new value". If a client-side cache is ever
reintroduced, this verdict stops holding and has to be rethought.

The "at least one" clause is not redundant. With nothing reading the key, "no reader is still on
the old value" is vacuously true, which is exactly the state where retiring looks safe and is not.

A deployment that reads a key rarely delays the verdict rather than rushing it. That is the correct
direction to be wrong in.

## Caching

L1 in-process → L2 Redis → L3 Secrets Manager.

Redis holds only sealed bytes. Values are AES-256-GCM encrypted under a data key that exists in
plaintext only inside the process; the copy travelling with the ciphertext is wrapped by a KMS CMK
that only this service's IRSA role can decrypt. Raw Redis access therefore yields ciphertext,
unwrapping needs a KMS permission the attacker does not have, and every unwrap is a CloudTrail
event.

Two bindings stop a sealed value being moved: the GCM AAD is `<env>|<cacheKey>`, and the KMS
`EncryptionContext` pins the wrapped key to this service and environment.

Availability shapes the rest more than performance does. Warehouse syncs now depend on this
service, so a Secrets Manager blip degrades rather than fails: an expired snapshot is still served
while `integration_secret_serving_stale_seconds` climbs. A Redis entry that cannot be opened is
treated as a miss, not an error, so a poisoned entry costs one store read instead of a failed
request.

For phase 1's working set (~50 values, a few KB) L2 is more machinery than the data justifies. It
is here because phase 2 puts per-team credentials on the same path at a different volume, and
retrofitting envelope encryption under live traffic is worse than building it now.

## Credentials

The service passes an explicit AWS credential provider and the build **aliases the SDK's default
chain to a stub that throws** (`src/aws/unreachable-provider.ts`). There are exactly two ways in:
the IRSA web identity token in cluster, and static throwaway credentials when `AWS_ENDPOINT_URL`
points at a local mock. The second is a dev-only path, enforced rather than documented:
`loadConfig()` exits if that variable is set under `NODE_ENV=production`.

This is a security control, not only a bundle-size one: a service whose entire job is holding
third-party credentials should not be able to silently authenticate as an EC2 instance role or as
whatever a developer last ran `aws sso login` against.

## Isolation

This package must not depend on the rest of the monorepo. It shares the pnpm workspace only for
resolution — nothing from `nodejs/`, `frontend/` or `common/`. Two checks hold that in place, and
both run in CI _and_ in the Docker build, against the built bundle rather than the source so a
re-export chain cannot smuggle a module past them:

```bash
pnpm build
pnpm check:boundary   # no first-party imports from outside this package
pnpm check:deps       # the bundled package set matches deps-allowlist.txt
```

`deps-allowlist.txt` is the committed list of every third-party package that actually ends up in
the artifact. A new transitive dependency is a reviewable line, not a lockfile diff nobody reads.
Accept a change with `pnpm build && pnpm check:deps --write` and review the result.

Installs run `--ignore-scripts`; nothing in the tree needs an install-time script, and that is the
npm-specific supply-chain path worth closing here.

## Local development

```bash
pnpm --filter @posthog/integration-service dev        # esbuild watch + respawn
pnpm --filter @posthog/integration-service test
pnpm --filter @posthog/integration-service typecheck
```

With `INTEGRATION_SERVICE_REDIS_URL` unset the service runs on L1 alone, which is enough for most
local work. Point `AWS_ENDPOINT_URL` at moto to exercise the store without real AWS.

## Configuration

| Variable                                   | Default                       | Notes                                                              |
| ------------------------------------------ | ----------------------------- | ------------------------------------------------------------------ |
| `INTEGRATION_SERVICE_ENV`                  | `dev`                         | Logical env; bound into cache keys, GCM AAD and the usage artifact |
| `INTEGRATION_SERVICE_REDIS_URL`            | —                             | Unset disables L2. Required in production                          |
| `INTEGRATION_SERVICE_KMS_KEY_ID`           | —                             | Required in production, and whenever Redis is configured           |
| `INTEGRATION_SERVICE_SECRET_ID`            | `integration-service-secrets` | The one secret holding credentials and signing keys                |
| `INTEGRATION_SERVICE_CACHE_TTL_SECONDS`    | `300`                         | Server-side snapshot TTL and refresh cadence                       |
| `INTEGRATION_SERVICE_DEK_ROTATION_SECONDS` | `3600`                        | How often a new KMS data key is generated                          |
| `INTEGRATION_SERVICE_RETIRE_QUIET_HOURS`   | `24`                          | Quiet window for `safeToRetirePrevious`                            |
| `INTEGRATION_SERVICE_USAGE_BUCKET`         | —                             | Unset disables usage publishing                                    |
| `INTEGRATION_SERVICE_USAGE_KMS_KEY_ID`     | —                             | SSE-KMS key for the usage artifact                                 |
| `INTEGRATION_SERVICE_METRICS_TOKEN`        | —                             | Bearer token for `/metrics`. Required in production                |
| `PORT`                                     | `8004`                        |                                                                    |

The service exits at boot rather than starting degraded when a production-required variable is
missing, when Redis is configured without a KMS key, or when `AWS_ENDPOINT_URL` is set under
`NODE_ENV=production` — that variable skips IRSA for static throwaway credentials and points every
AWS client at whatever it names, so it belongs to local dev only.

`/metrics` is bearer-gated whenever a token is set, and the token is production-required because the
endpoint exposes `integration_secret_resolve_total{deployment,product,provider,key}` — no credential
values, but a precise map of which deployment reads which credential.
