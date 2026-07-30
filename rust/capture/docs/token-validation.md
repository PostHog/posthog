# Validating project API keys at the capture edge

Capture used to answer `200 {"status":"Ok"}` for any *shape-valid* token (see
`src/token.rs`), so a mistyped project API key produced "events sent
successfully" in the SDK and no data anywhere: the batch was dropped much later
in ingestion as `team_not_found`, and because an unresolved token has no team,
not even an ingestion warning could be attributed to it. `/flags` and `/decide`
already return 401 for the same token, which is what makes the failure so
confusing to debug.

`src/token_validation.rs` resolves the token to a real team and lets capture
answer 401 for tokens no project owns, on every ingest surface (`/e`, `/batch`,
`/capture`, `/i/v0/e`, `/s`, `/i/v0/ai`, `/i/v0/ai/otel`, and the v1 analytics
handler).

## Reliability posture

Availability wins over catching typos. Only a *definitive* "no team owns this
token" rejects; everything else is accepted:

- Verdicts are cached in-process, positive and negative, so the hot path does at
  most one lookup per distinct token per TTL.
- Lookup order is in-process cache → `team_metadata` HyperCache (Redis → S3, the
  same entries Django writes and `/flags` reads) → Postgres.
- A HyperCache miss is not proof (Django may not have warmed that team yet), so
  only the Postgres tier can produce a rejection. With no Postgres configured,
  nothing is ever rejected.
- Any error — Redis, S3, or Postgres — fails open and is not cached, so
  validation self-heals as soon as the dependency returns.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `TOKEN_VALIDATION_MODE` | `off` | `off` (no lookups), `dry_run` (look up, report, still accept), `enforce` (401 for unknown tokens) |
| `TOKEN_VALIDATION_DATABASE_URL` | unset | Postgres read replica used to resolve tokens the cache doesn't hold. Required for any rejection to happen |
| `TOKEN_VALIDATION_CACHE_CAPACITY` | `100000` | Max cached verdicts, per verdict kind |
| `TOKEN_VALIDATION_CACHE_TTL_SECS` | `300` | TTL for "this token is valid" |
| `TOKEN_VALIDATION_NEGATIVE_CACHE_TTL_SECS` | `30` | TTL for "no team owns this token" — deliberately shorter so a newly created project recovers quickly |
| `OBJECT_STORAGE_BUCKET` / `OBJECT_STORAGE_REGION` / `OBJECT_STORAGE_ENDPOINT` | `posthog` / `us-east-1` / unset | The S3 tier behind Redis for the `team_metadata` HyperCache |

## Rolling it out

`capture_token_validation_total{tier,result}` carries everything needed to judge
a rollout. Run `dry_run` first and watch
`result="dry_run_would_reject"` — that is the exact 401 rate `enforce` would
produce. `result="unavailable"` / `"indeterminate"` show how often a tier could
not answer, and `tier="postgres"` shows the query volume the read replica is
actually taking.
