# credentials-service

Serves PostHog's **platform integration credentials** — the OAuth app client ids/secrets and API
keys PostHog itself owns, as opposed to a customer's — over HTTP, so they stop being injected as
environment variables into every pod that might need one. Today those keys are duplicated across
the Django stack and each temporal worker's chart values, and adding one means a `PostHog/charts`
PR plus knowing in advance which pods need which key.

This is phase 1. The per-team `Integration` model, the OAuth flows and token refresh come later;
nothing here touches them.

## What it does and does not buy

An attacker who has compromised a pod still holds that pod's JWT signing key, and can ask for any
credential on the mount. Per-request key scoping contains a _leaked token_, not a _compromised
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
GET  /_readiness         200 once the pod holds credentials (and, with a database, once it has reached it)
POST /v1/secrets/resolve
     /v1/integrations/*  customer integrations, with a database and a KMS only (see "Integrations API")

GET  /metrics            prometheus text, on its own port (CREDENTIALS_SERVICE_METRICS_PORT)
```

**The request scope lives in the JWT and there is no request body.** The token _is_ the request,
so a body and a claim cannot diverge, and a token lifted from a log unlocks only the fields that
one call needed:

```jsonc
// Authorization: Bearer <token>
{
  "caller": "warehouse-sources", // the product that asked; logged, not trusted
  "keys": ["GOOGLE_ADS_APP_CLIENT_ID", "GOOGLE_ADS_APP_CLIENT_SECRET"],
  "aud": "posthog:credentials_service",
  "exp": 1786035932,
}
```

```jsonc
{
  "secrets": {
    "GOOGLE_ADS_APP_CLIENT_SECRET": {
      "state": "rotating",
      "value": "…",
      "incoming": "…",
      "version_id": "…",
      "fetched_at": "…",
    },
  },
  "missing": [], // name not on the mount, or reserved
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
| **Deployment** | The pod set that signed the token (`posthog-web-django`, a temporal worker)                              | Yes. It is derived from _which key verified the token_, never from a claim, so there is nothing in the token to forge |
| **Caller**     | The code path that wanted the credential (`warehouse-sources`, `cdp`), from a code enum at the call site | No. Django holds one key and hosts many products, so a compromised Django pod could name any of them                  |

Authorization hangs off the deployment. The caller claim reaches the audit log so an incident can
ask "which product read this", and reaches nothing else — in particular it is never a metric
label, because prom-client keeps every series in process memory for the pod's lifetime.

**There is no per-deployment allowlist for platform secrets.** Every authenticated deployment may read any credential
on the mount: a list bounds nothing the signing key does not already bound, and a compromised
deployment is contained by revoking its key. What a deployment actually read is in the audit
log.

So one thing bounds a request: the `keys` claim, which _is_ the request, for as long as the token
has left to run — the verifier requires an `exp`.

Signing keys live in the same secret as the credentials, one flat entry per deployment
(`__CALLER_KEY_<DEPLOYMENT>`). Deployment names are derived from the entries present, not declared
in code, so onboarding a caller or revoking a compromised one is a secrets edit with no deploy.
The same value goes into that deployment's own secret as `CREDENTIALS_SERVICE_JWT_SECRET`.

### Integration tokens

The future `/v1/integrations/*` routes use the same signing keys with a different audience, `posthog:credentials_service:integrations`.
Each route accepts only its own audience, and `aud` must be a plain string, so one token never works on both.

```jsonc
{
  "aud": "posthog:credentials_service:integrations",
  "iat": 1786035872,
  "exp": 1786035932, // at most 60s after iat
  "jti": "<16-128 URL-safe chars>", // used once; a replay is rejected
  "owner": { "type": "team", "id": 2 }, // optional only when every op is cross-team
  "ops": ["read", "resolve"],
  "kinds": ["slack"], // optional; narrows the token to these kinds
  "refs": ["123"], // optional; narrows the token to these refs (decimal legacy id or lowercase UUID)
  "user_id": 7, // optional; audit only
  "caller": "integrations-sdk", // logged, not trusted
}
```

- Any other claim fails the token.
- Clocks may differ by 30s. A pod remembers each `jti` for 2 minutes.
- A request needs its op in the token **and** in the policy for its deployment (`src/auth/policy.ts`). A deployment that the policy does not name gets no op.
- The owner comes only from the token. A route never reads it from the path, query or body.
- A rejected token gets a bare 401. A valid token that does not allow the request gets a 403 with `forbidden_op`, `forbidden_kind` or `forbidden_ref`.

Deployments match by exact name. There is no prefix or family match.
The names come from the `__CALLER_KEY_<DEPLOYMENT>` entries in `PostHog/charts` (`apps/<name>`).
`src/auth/policy.ts` lists every name.

| Deployment                                                                                                                                  | Ops                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `posthog-web-django` (the web-two, frontdoor and streaming pools sign with its key)                                                         | all, including `revoke`, `delete`, `*_by_external_id`, `delete_owner`, `changes` |
| `temporal-worker-{batch-exports,data-warehouse,general-purpose,health-check,max-ai,stamphog,tasks-agent,video-export,wizard}`               | `read`, `resolve`, `write`, `refresh`, `list_across_teams`, `mint`               |
| `posthog-worker-django` (Celery), `posthog-query-django`, `posthog-admin-django`, `warehouse-sources-load`                                  | `read`, `resolve`, `write`, `refresh`, `list_across_teams`                       |
| `cdp-*` (the listed CDP API, cyclotron worker and events consumer deployments) and the listed `ingestion-*` lanes, including `cdp-api-push` | `resolve`                                                                        |

## Storage and rotation

**One secret holds everything**: `credentials-service-secrets`, a flat map of `KEY: value` pairs.
Flat and uppercase because the `PostHog/secrets` CLI and UI only manage `[A-Z0-9_]+` keys with
plain string values.

External Secrets Operator syncs that secret into a Kubernetes Secret.
The service reads it from one of two sources, set by `CREDENTIALS_SERVICE_SECRET_SOURCE` (`src/source.ts`):

- **`kubernetes`**: the service lists the Secret through the API server, then watches it (`src/kubernetes.ts`).
  Every replica gets an edit within about a second of ESO writing it.
- **`directory`** (the default): kubelet mounts the Secret as a directory of one file per key, and the service re-reads it on a timer.
  Kubelet refreshes the mount on each node on its own schedule, about 60-90s.
  So for a minute or more after an edit, different replicas can serve different versions.
  Use this source for local development and tests.

Each source yields the whole Secret at one version.
The service applies that one snapshot to the signing keys first and then to the credentials.
So a revocation and a rotation in one edit land together, and a revoked caller never reads the new values.

The kubernetes source:

- Lists with `fieldSelector=metadata.name=<name>` at boot, then watches from the listed `resourceVersion` with bookmarks.
- After a normal close, it watches again from the last `resourceVersion` it saw.
- After `410 Gone`, it lists again and watches from the new `resourceVersion`.
- After an error, it reconnects with capped exponential backoff.
- Every `CREDENTIALS_SERVICE_RELOAD_SECONDS`, it lists the Secret again as a safety check.
  If the list finds a change that the watch did not deliver, the service applies it and replaces the watch.
- Reads the service account token again for each request, because the projected token rotates.
- Connects straight to `KUBERNETES_SERVICE_HOST:KUBERNETES_SERVICE_PORT`.
  It ignores `HTTP_PROXY` and `HTTPS_PROXY`, so the egress proxy never sees API server traffic.

It needs a Role with `get`, `list` and `watch` on `secrets`, restricted by `resourceNames` to this one Secret.
With `resourceNames`, RBAC allows a list or watch only when it carries the field selector above.

A pod holding no credentials fails its readiness probe rather than exiting.
So an empty mount, or an API server it cannot reach at boot, recovers on its own instead of crash-looping.
A source that stops being readable keeps what is already held, with `credentials_service_serving_stale_seconds` as the only sign.
A deleted Secret also keeps what is held: an empty set would answer every resolve all-missing, which callers treat as deleted credentials.
`credentials_service_watch_restarts_total{reason}` counts watch restarts by why the previous watch ended.

```text
credentials-service-secrets
  STRIPE_APP_SECRET_KEY                 = "<credential>"
  STRIPE_APP_SECRET_KEY_FALLBACKS       = "<staged replacement, only while rotating>"
  CREDENTIALS_RECOVERY_KEYS             = "<comma-separated key names>"
  __CALLER_KEY_POSTHOG_DJANGO           = "<new>,<old>"
```

**Rotation rides an explicit `<KEY>_FALLBACKS` sibling, not AWS staging labels.** `AWSPREVIOUS`
applies to a whole secret version, so with everything in one secret, rotating Google — or adding
an unrelated key — would consume the slot Stripe's in-flight rotation was using and end its
overlap silently. A sibling key is unaffected by edits to anything else, and it is the convention
PostHog already uses for rotatable keys (`SECRET_KEY_FALLBACKS`), so the rotation guard in
`PostHog/secrets` grades these automatically.

Starting a rotation means writing the new value into the sibling, leaving the live one in place:
both are then served, so a caller can use the replacement before it goes live. Completing it means
moving the staged value into the key and dropping the sibling, in one write — so a sibling exists
if and only if a rotation is in flight, and the live value is never briefly absent. Two rotations
can be in flight at once without interfering.

The live value stops being served the moment a rotation completes. The overlap is the staging
window, not a grace period afterwards, so leave the new value staged long enough for callers to
pick it up before completing.

| State      | Condition                                        | Response                              |
| ---------- | ------------------------------------------------ | ------------------------------------- |
| `steady`   | no `_FALLBACKS` sibling, or it repeats the value | `value` only                          |
| `rotating` | the sibling holds a different, staged value      | `value` + `incoming` (the staged one) |
| `recovery` | field named in `CREDENTIALS_RECOVERY_KEYS`       | no value; caller raises a typed error |

`recovery` covers a credential that is known-burned with no valid replacement yet. These
credentials authenticate _PostHog_ to the third party, so there is no per-user "reconnect": the
integration is down for everyone until an engineer re-provisions the app. The state buys callers
an immediate, distinct error, so the outage is attributable instead of looking like a third-party
problem.

### What gets served

**Whatever is on the mount, except entries whose name starts with `__`.** There is no manifest in
code, so adding a credential is a secrets edit and needs no deploy.

The corollary is a rule on the secret: **only outbound credentials belong on it.** Every entry is
readable by every deployment holding a signing key. For an OAuth app secret we present to a third
party that is no expansion — the pod already had its own copy in its environment. For an
inbound-request authenticator such as a webhook signing secret it would be one, so those stay as
plain env vars on the deployment that checks them. `STRIPE_SIGNING_SECRET`, which authenticates
requests arriving at `ee/partners/stripe/api/provisioning/`, is the worked example: keep it off
this secret.

`__` is the one thing the mount will not serve, whatever a token asks for. The caller signing keys
carry that prefix, which is why they can share a secret with the credentials they protect.

## Metrics

No label value comes from a request. A key name becomes a label only once the mount is known to
carry it; anything else collapses to a constant, and the `caller` claim is not a label at all.

| Metric                                                                   | What it answers                                               |
| ------------------------------------------------------------------------ | ------------------------------------------------------------- |
| `credentials_service_resolve_total{deployment,key,result}`               | who read what, and whether it resolved                        |
| `credentials_service_last_resolved_timestamp{key}`                       | which credentials nothing reads any more                      |
| `credentials_service_previous_version_served_total{key}`                 | how much traffic is reading a key mid-rotation                |
| `credentials_service_serving_stale_seconds`                              | how long this pod has served credentials it could not refresh |
| `credentials_service_store_errors_total`                                 | source reads that returned nothing                            |
| `credentials_service_watch_restarts_total{reason}`                       | Kubernetes watch restarts, by why the previous watch ended    |
| `credentials_service_signing_keys_last_loaded_timestamp`                 | staleness means a revocation has not landed on this pod       |
| `credentials_service_signing_key_reload_failures_total`                  | reloads that kept the previous key set                        |
| `credentials_service_auth_failures_total{reason}`                        | rejected tokens, by why                                       |
| `credentials_service_integration_auth_total{deployment,outcome}`         | integration token decisions, by deployment and outcome        |
| `credentials_service_integration_replay_evictions_total`                 | live token ids dropped because the replay cache was full      |
| `credentials_service_http_requests_total{method,route,status}`           | request volume, with an unmatched path collapsed to `other`   |
| `credentials_service_http_request_duration_seconds{method,route,status}` | request latency                                               |
| `credentials_service_audit_dropped_total{reason}`                        | read audit rows lost: `queue_full` or `write_failed`          |
| `credentials_service_audit_written_total`                                | read audit rows written by the async queue                    |
| `credentials_service_shutting_down`                                      | 1 while draining                                              |

Two of these exist because a fail-open needs to be visible: the signing-key reload keeps the
previous keys when an edit is malformed, and an unreadable mount keeps what is already held. Alert
on the two staleness signals, or neither degradation is observable.

`/metrics` listens on its own port, which the chart keeps off the ingress; in-cluster Prometheus
scrapes it unauthenticated, the same shape as every other service.

## Database

The service has its own Postgres database for customer integrations. Platform secrets never use it.
When `CREDENTIALS_SERVICE_DATABASE_URL` is not set, the service starts as before and serves platform secrets only.
So the service can deploy before its database exists.

Tables:

| Table                 | Holds                                                                                                         |
| --------------------- | ------------------------------------------------------------------------------------------------------------- |
| `integrations`        | One row per credential, without secrets. Soft delete with `deleted_at`, and a `version` for optimistic writes |
| `integration_secrets` | The encrypted secret blob of one integration (1:1)                                                            |
| `audit_log`           | One row per access, partitioned by day on `occurred_at`                                                       |
| `idempotency_keys`    | Request keys for create and exchange, with `expires_at` 24 hours after the write                              |

`src/db/integrations.ts` holds the typed queries. Every query binds the owner, so no query reads or changes another team's row.

Readiness waits for the database until it answers once.
After that, a database outage does not make the pod unready, because platform secrets do not need the database.

### Migrations

Migrations are plain SQL files in `migrations/`, applied with `node-pg-migrate`.
Each file has a `-- Up Migration` and a `-- Down Migration` section.
To add one, create `migrations/<unix ms>_<name>.sql`. Never edit a migration that has run in production.

The migration runner is a separate bundle in the same image. Run it as a Kubernetes Job before each deploy, never from the server:

```bash
node credentials-service-migrate.mjs            # apply every pending migration
node credentials-service-migrate.mjs down 1     # revert the last migration
pnpm --filter @posthog/credentials-service migrate   # the same, from source, in local development
```

It reads `CREDENTIALS_SERVICE_DATABASE_URL` and the `migrations/` directory relative to the working directory.
An advisory lock makes two Jobs that start together run one after the other.

### Audit partitions

`audit_log` is partitioned by range on `occurred_at`, with one default partition, `audit_log_default`.
Infra runs pg_partman for the daily partitions: `create_parent('public.audit_log', 'occurred_at', '1 day', p_premake => 7, p_default_table => false)`, because the migration already made the default partition.
Set pg_partman up before the service writes audit rows.
Rows that land in the default partition stop pg_partman from making a partition for that day, until they are moved with `partition_data_proc`.

## Integrations API

The routes exist only when both `CREDENTIALS_SERVICE_DATABASE_URL` and `CREDENTIALS_SERVICE_KMS_PROVIDER` are set.
With one of them, the service logs `integrations:disabled` and serves platform secrets only.
Every route needs an integrations token (see "Integration tokens") that holds the route's op.
Every query binds the owner from the token.

| Route                                                       | Op                      | Does                                                                         |
| ----------------------------------------------------------- | ----------------------- | ---------------------------------------------------------------------------- |
| `GET /v1/integrations`                                      | `read`                  | Lists the owner's rows. Keyset pages                                         |
| `GET /v1/integrations/:ref`                                 | `read`                  | One row, by UUID or legacy id. Sends `ETag: "<version>"`                     |
| `POST /v1/integrations/batch-get`                           | `read`                  | `{refs}` (1 to 200) to `{records: {ref: record}, missing}`                   |
| `POST /v1/integrations`                                     | `write`                 | Creates a row. Takes `Idempotency-Key`                                       |
| `PUT /v1/integrations/upsert`                               | `write`                 | Creates the row, or replaces the config and secrets of the row with that key |
| `PATCH /v1/integrations/:ref`                               | `write`                 | An `IntegrationPatch` body. Takes `If-Match: <version>`                      |
| `DELETE /v1/integrations/:ref`                              | `delete`                | Soft-deletes the row and removes its secret. Takes `If-Match`                |
| `POST /v1/integrations/resolve`                             | `resolve`               | `{refs}` (1 to 200) to `{records: {ref: {record, credentials, expires_at}}}` |
| `POST /v1/integrations/list-across-teams`                   | `list_across_teams`     | Rows of every team that match a `CrossTeamFilter`-shaped body                |
| `GET /v1/integrations/by-external-id/:kind/:external_id`    | `read_by_external_id`   | Rows of every team with this kind and external id. Web only                  |
| `PATCH /v1/integrations/by-external-id/:kind/:external_id`  | `write_by_external_id`  | Applies an `IntegrationPatch` to those rows in one transaction. Web only     |
| `DELETE /v1/integrations/by-external-id/:kind/:external_id` | `delete_by_external_id` | Soft-deletes those rows and their secrets in one transaction. Web only       |
| `DELETE /v1/integrations?owner=<team id>`                   | `delete_owner`          | Soft-deletes every row and secret of the token's owner, in batches. Web only |
| `GET /v1/integrations/changes`                              | `changes`               | Rows of every team changed after a cursor, with secrets. Web only            |

- A record mirrors the Python `IntegrationRecord`, plus `reference`, `version`, `legacy_id` and `is_source_row`. No read returns a secret.
- `resolve` returns the decrypted secret blob without `refresh_token`, and without `client_secret` for an `oauth` row. `expires_at` is `refreshed_at + expires_in` from the config, or null.
  A ref with no live row is in `missing`. A ref whose secret cannot be read (a legacy unreadable key, or a ciphertext that fails to decrypt) is in `errors` with `unreadable_secret`.
- A write that changes secrets decrypts the blob, applies the change, and seals it again with a fresh data key, in the transaction of the row update.
- `GET /v1/integrations` takes `kind` and `auth_type` (both repeat), `external_id`, `where.<config key>=<JSON value>`, `source_rows` (`exclude`, `only` or `include`, default `exclude`), `limit` (1 to 1000, default 100), `newest_first` and `after`.
  Rows come oldest first by `created_at`. `next` in the response is the `after` of the next page.
- `list-across-teams` takes `kinds` (required), `auth_types`, `source_rows`, `team_ids`, `exclude_team_ids`, `created_by_ids`, `external_id`, `where`, `where_in`, `where_iexact`, `has_config_key`, `newest_first`, `limit` (default and maximum 1000) and `after`.
- A row of another team answers 404, the same as a row that does not exist, so a caller cannot probe ids.

Web-only routes (the web deployment is the only one whose policy holds these ops):

- The three `by-external-id` routes cross teams, so the token needs no owner, and an owner in the token does not narrow them.
  They take `source_rows` (`exclude` by default, the same as the SDK). `GET` also takes `team_id` (repeats), `limit` and `after`.
  `PATCH` answers `{matched, updated}`. A row that the patch does not change is not written. `DELETE` answers `{deleted}`.
  Both write one audit row per matched row with that row's own owner. A second `DELETE` finds no live row and answers `{deleted: 0}`.
  A token that names refs is refused, because these routes cannot name the refs they touch.
- `DELETE /v1/integrations?owner=` must name the token's own owner, and the token must not narrow by kind.
  It soft-deletes 500 rows per transaction until none are left, removes their secrets and the owner's idempotency keys, and audits each row.
  It is idempotent: after a failure, call it again.
- `GET /v1/integrations/changes` is the one read that returns secrets. It exists for the Django reverse sync during the migration.
  Each item has `record`, `deleted`, `updated_at`, `secret`, `secret_unreadable_keys` and `secret_error`.
  `secret` is the current decrypted blob, `refresh_token` and `client_secret` included, for every live row on the page.
  A secret that changed before `since` can sit on a row that changed again after it, so the feed never leaves it out.
  It is `{}` when the row has no secret or is deleted.
  A secret that cannot be opened gives `secret: null` and `secret_error: "unreadable_secret"` for that row and does not stop the page.
  The service writes the audit rows (with the secret key names) before it builds the response, and sends `Cache-Control: no-store`.
  Take `next` from each page as the `since` of the next call. `next` equals `since` when nothing changed.
  `kind` (repeats) and `limit` (1 to 500, default 100) also work. A token that names kinds sees only those kinds.
  Deleted rows appear once, with `deleted: true`.
- The feed orders by `(updated_at, id)` and uses the `integrations_updated_at_id` index.
  `updated_at` is the start time of the writing transaction, so a row can commit after a newer row.
  The feed therefore holds back changes younger than 30 seconds, so a reader never moves its cursor past a row that is not visible yet.
  This is safe while no write transaction lasts 30 seconds. The by-external-id writes roll back after 20 seconds to keep that true.

Errors are `{error: {code, message, details}}`:

| Code                    | Status | When                                                          |
| ----------------------- | ------ | ------------------------------------------------------------- |
| `validation`            | 400    | The body, query or a header is not valid                      |
| `unauthorized`          | 401    | The token is missing or not valid                             |
| `forbidden_op`          | 403    | The token or the deployment policy does not allow the op      |
| `forbidden_kind`        | 403    | The token does not allow the kind of the row                  |
| `forbidden_ref`         | 403    | The token does not allow the ref, or the route lists rows     |
| `not_found`             | 404    | No live row of the owner has the ref                          |
| `conflict`              | 409    | The external id is taken, or an `Idempotency-Key` is reused   |
| `version_mismatch`      | 412    | `If-Match` is not the current version                         |
| `unsupported_auth_type` | 422    | The auth type is not `oauth`, `token` or `credentials`        |
| `unreadable_secret`     | 422    | A write needs a stored secret that the service cannot decrypt |
| `kms_unavailable`       | 503    | The KMS did not answer. Retry later                           |

Audit: one `audit_log` row for each record that a request returns or changes.
A write stores its rows in its own transaction.
A read hands them to an in-process queue (10k rows) that writes batches every second.
When the queue is full, the service drops the rows and counts them on `credentials_service_audit_dropped_total`, so a read never waits.

## Isolation

This package must not depend on the rest of the monorepo. It shares the pnpm workspace only for
resolution — nothing from `nodejs/`, `frontend/` or `common/`. The package's own
`.oxlintrc.json` enforces that with a `no-restricted-imports` rule over static import specifiers
that name another part of the monorepo. It does not see `require()`, dynamic `import()`, or a new
npm dependency, so those still rest on review of `package.json` and the lockfile.

Installs run `--ignore-scripts`; nothing in the tree needs an install-time script, and that is
the npm-specific supply-chain path worth closing here.

## Local development

```bash
pnpm --filter @posthog/credentials-service dev                # tsx watch, pretty logs
pnpm --filter @posthog/credentials-service typecheck
pnpm --filter @posthog/credentials-service test:unit
pnpm --filter @posthog/credentials-service test:integration   # real server on a temp mount, Postgres in Docker
```

The integration suite boots a real `CredentialsServer` against a temp-dir mount and a real
socket, so it covers the wiring the unit suite fakes. The database tests start Postgres with
testcontainers, so the integration suite needs Docker. The unit suite needs neither.

Point `CREDENTIALS_SERVICE_SECRETS_DIR` at a directory of files, one per key, to stand in for the
mount.

## Envelope encryption

`src/crypto/` encrypts one integration's secret blob for storage. The integration routes use it for every secret they store.

- Each write gets a fresh 32-byte data key from the KMS, wrapped under one single-region key.
- The blob is canonical JSON (sorted keys, no whitespace), encrypted with AES-256-GCM and a random 12-byte nonce.
- The AAD and the KMS encryption context are the same three fields: `integration_id`, `owner_id` and `kind`.
  A ciphertext copied to another row, owner or kind does not decrypt.
- Stored per row: `key_id`, `wrapped_dek`, `ciphertext` (GCM output, then the 16-byte tag), `nonce` and `enc_version` (`1`).
- Unwrapped data keys stay in an in-process LRU cache: 50k entries, 10 minutes.
  The cache zeroes a key when it evicts it. A miss is one KMS `Decrypt`.
- `rewrap` wraps a data key under another KMS key. The ciphertext does not change.
  On AWS this is `ReEncrypt`, so the role needs `kms:ReEncryptFrom` and `kms:ReEncryptTo`.

The `aws` provider makes one attempt and two retries, each limited to 2s.
It connects to KMS directly and ignores `HTTP_PROXY` and `HTTPS_PROXY`, unless `CREDENTIALS_SERVICE_KMS_PROXY_URL` is set.
The `local` provider wraps data keys with AES-256-GCM under keys from config, for dev, CI and hobby.
Its wrapped keys go into the same columns. The service refuses it when `CREDENTIALS_SERVICE_ENV` starts with `prod`.

| Variable                             | Default | Notes                                                                      |
| ------------------------------------ | ------- | -------------------------------------------------------------------------- |
| `CREDENTIALS_SERVICE_KMS_PROVIDER`   | unset   | `aws` or `local`. Unset means no KMS                                       |
| `CREDENTIALS_SERVICE_KMS_KEY_ID`     |         | Alias, key id or ARN that wraps new data keys (`aws`, required)            |
| `CREDENTIALS_SERVICE_KMS_REGION`     | SDK     | Falls back to `AWS_REGION` (`aws`)                                         |
| `CREDENTIALS_SERVICE_KMS_ENDPOINT`   | SDK     | A VPC endpoint or an emulator (`aws`)                                      |
| `CREDENTIALS_SERVICE_KMS_PROXY_URL`  | unset   | Send KMS traffic through this proxy (`aws`)                                |
| `CREDENTIALS_SERVICE_KMS_LOCAL_KEYS` |         | Comma-separated base64 32-byte keys. The first wraps, all unwrap (`local`) |

| Metric                                            | What it answers                                           |
| ------------------------------------------------- | --------------------------------------------------------- |
| `credentials_service_kms_calls_total{op,outcome}` | KMS calls; `outcome` is `ok`, `unavailable` or `rejected` |
| `credentials_service_dek_cache_hits_total`        | decryptions served from the data key cache                |

## Configuration

| Variable                                 | Default                       | Notes                                                   |
| ---------------------------------------- | ----------------------------- | ------------------------------------------------------- |
| `CREDENTIALS_SERVICE_ENV`                | `dev`                         | Logical env, recorded on every startup log line         |
| `CREDENTIALS_SERVICE_SECRET_SOURCE`      | `directory`                   | `directory` or `kubernetes`; anything else fails boot   |
| `CREDENTIALS_SERVICE_SECRETS_DIR`        | `/etc/credentials-secrets`    | Where the Kubernetes Secret is mounted (`directory`)    |
| `CREDENTIALS_SERVICE_SECRET_NAME`        | `credentials-service-secrets` | The Secret to watch (`kubernetes`)                      |
| `CREDENTIALS_SERVICE_SECRET_NAMESPACE`   | the pod's namespace           | Read from the service account when unset (`kubernetes`) |
| `CREDENTIALS_SERVICE_RELOAD_SECONDS`     | `30`                          | Re-read interval; a safety re-list next to the watch    |
| `CREDENTIALS_SERVICE_METRICS_PORT`       | `9090`                        | Dedicated `/metrics` listener, kept off the ingress     |
| `CREDENTIALS_SERVICE_LOG_LEVEL`          | by `NODE_ENV`                 | `debug`, `info`, `warn` or `error`                      |
| `PORT`                                   | `8004`                        |                                                         |
| `HOST`                                   | `0.0.0.0`                     |                                                         |
| `SHUTDOWN_PRESTOP_DELAY_MS`              | `5000`                        | Wait before draining, for the Kubernetes prestop window |
| `CREDENTIALS_SERVICE_DATABASE_URL`       | unset                         | Postgres URL; unset means platform secrets only         |
| `CREDENTIALS_SERVICE_DATABASE_POOL_SIZE` | `20`                          | Connections per pod                                     |

The service exits at boot rather than starting degraded: a missing production variable, a
numeric variable that does not parse, or a `kubernetes` source without `KUBERNETES_SERVICE_HOST`
or a namespace. An empty secret mount does not exit; the pod fails its
readiness probe and recovers on its own once External Secrets Operator syncs.
