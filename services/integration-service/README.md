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

An attacker who has compromised a pod still holds that pod's JWT signing key, and can ask for
anything on that caller's allowlist. Per-request key scoping contains a _leaked token_, not a
_compromised caller_. The wins are:

1. Environment dumps stop containing credentials — `/proc/self/environ`, crash reports, a stray
   `printenv` in a log, and environments inherited by subprocesses.
2. Every read is attributed, so rotating after a suspected exposure is scoped to what was actually
   accessed rather than to everything.
3. Per-caller allowlists cap what any single compromised pod can obtain.
4. Rotation stops needing a charts PR and a rolling restart.

Point 3 is where most of the value sits, which is why the allowlist is in phase 1.

## API

```
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
  "caller": "temporal-worker-data-warehouse",
  "keys": ["GOOGLE_ADS_APP_CLIENT_ID", "GOOGLE_ADS_APP_CLIENT_SECRET"],
  "previous_used": [], // optional, see Rotation
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
  "denied": [], // in the token, but outside this caller's allowlist
  "missing": [], // unknown key, or no value in this environment
  "max_age_seconds": 60, // how long the caller may cache — server-controlled
}
```

Denials are per key rather than a 403 over the whole batch, so a policy mistake reads as one named
field a human can act on.

`max_age_seconds` being server-controlled is deliberate: dropping it to `0` fleet-wide during an
emergency rotation needs no caller redeploy.

## Auth

Per-caller HS256 JWT, following the `recording-api` scheme (PostHog/posthog#67476) — the pattern
`.agents/security.md` names as strongly preferred. Not `INTERNAL_API_SECRET`, which
`posthog/settings/data_stores.py` explicitly forbids extending.

**The signing key is per caller, not fleet-wide.** Same env var name, different value in
`posthog-django-shared-secrets` versus `temporal-worker-data-warehouse-secrets`. A fleet-wide key
would let a leak from the warehouse worker mint a token claiming to be Django and inherit Django's
wider allowlist, which would defeat the allowlist entirely.

Two layers, bounding different things:

| Layer                                      | Bounds                                                 |
| ------------------------------------------ | ------------------------------------------------------ |
| Caller allowlist (`integrations/_clients`) | a compromised caller — the standing ceiling            |
| `keys` claim                               | a leaked token — one request's scope, for five minutes |

The registry lives in Secrets Manager, so onboarding a caller or rotating a key is a secrets change
with no service deploy:

```jsonc
{
  "temporal-worker-data-warehouse": {
    "keys": ["<new>", "<old>"], // newest first; all accepted, so rotation is zero-downtime
    "providers": ["google-ads", "hubspot", "stripe"],
  },
}
```

`Verifier` is an interface so a Kubernetes projected-ServiceAccount-token verifier (TokenReview)
can drop in later without touching the routes or the policy layer.

## Storage and rotation

One AWS secret per provider (`integrations/<provider>`), holding that provider's fields as flat
JSON. Per-provider granularity matters because AWS staging labels apply to a whole secret version:
rotating Stripe must not disturb Google.

Rotation rides AWS's own staging labels rather than a bespoke format. `PutSecretValue` promotes the
new version to `AWSCURRENT` and demotes the old to `AWSPREVIOUS`; the service reads both and diffs
them **per field**, so a provider whose `client_id` did not change reports only the field that did.
Rollback is `secrets rollback`, which the `PostHog/secrets` CLI already implements.

| State      | Condition                         | Response                              |
| ---------- | --------------------------------- | ------------------------------------- |
| `steady`   | no `AWSPREVIOUS`, or equal values | `value` only                          |
| `rotating` | values differ                     | `value` + `previous`                  |
| `recovery` | `_state` entry in the secret JSON | no value; caller raises a typed error |

`recovery` covers a credential that is known-burned with no valid replacement yet. Callers fail
fast and surface "reconnect needed" rather than hammering a third party with a credential that
cannot work.

Only fields named in `src/providers.ts` are ever served. A field present in the secret but absent
from that manifest is ignored, so adding a credential is a reviewed code change and never just a
secrets edit.

### Knowing when the old value is safe to delete

We serve both values during a rotation and **cannot observe which one the caller's request to the
third party actually succeeded with**. So it is not inferred here — it is reported. A client that
fell back to the previous value lists that key in the signed `previous_used` claim on its next
resolve. Signed, so only an already-authorized caller can report; piggy-backed, so no extra round
trip.

`safeToRetirePrevious` then requires **both** conditions:

- nobody has needed the previous value across the quiet window, **and**
- at least one caller has successfully read the current value in it.

The second is not redundant. Zero previous-value use on its own is equally consistent with nothing
reading the credential at all — which is exactly the state in which retiring a value looks safe and
is not.

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
points at a local mock.

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

| Variable                                     | Default         | Notes                                                              |
| -------------------------------------------- | --------------- | ------------------------------------------------------------------ |
| `INTEGRATION_SERVICE_ENV`                    | `dev`           | Logical env; bound into cache keys, GCM AAD and the usage artifact |
| `INTEGRATION_SERVICE_REDIS_URL`              | —               | Unset disables L2. Required in production                          |
| `INTEGRATION_SERVICE_KMS_KEY_ID`             | —               | Required in production, and whenever Redis is configured           |
| `INTEGRATION_SERVICE_SECRET_PREFIX`          | `integrations/` | Prefix for the per-provider secrets and `_clients`                 |
| `INTEGRATION_SERVICE_CACHE_TTL_SECONDS`      | `300`           | Server-side snapshot TTL and refresh cadence                       |
| `INTEGRATION_SERVICE_CLIENT_MAX_AGE_SECONDS` | `60`            | The `max_age_seconds` hint sent to callers                         |
| `INTEGRATION_SERVICE_DEK_ROTATION_SECONDS`   | `3600`          | How often a new KMS data key is generated                          |
| `INTEGRATION_SERVICE_RETIRE_QUIET_HOURS`     | `24`            | Quiet window for `safeToRetirePrevious`                            |
| `INTEGRATION_SERVICE_USAGE_BUCKET`           | —               | Unset disables usage publishing                                    |
| `INTEGRATION_SERVICE_USAGE_KMS_KEY_ID`       | —               | SSE-KMS key for the usage artifact                                 |
| `INTEGRATION_SERVICE_METRICS_TOKEN`          | —               | Unset leaves `/metrics` open for in-cluster scrapes                |
| `PORT`                                       | `8004`          |                                                                    |

The service exits at boot rather than starting degraded when a production-required variable is
missing, or when Redis is configured without a KMS key.
