---
name: consuming-endpoints-from-client-code
description: >
  Wire a PostHog endpoint into a client app or SDK. Covers fetching the OpenAPI spec, generating a
  typed client with openapi-generator or @hey-api/openapi-ts, sending the right auth header,
  shaping the variables payload (HogQL code_name vs insight breakdown property), handling
  rate-limit and materialised-endpoint error responses. Use when the user says "how do I call my
  endpoint", "generate a client for this", or "what auth header do I use".
---

# Consuming endpoints from client code

This skill is the **caller-side** counterpart to `creating-an-endpoint`. It helps integrate an
existing endpoint into a separate codebase — a mobile app, server backend, customer dashboard,
or downstream pipeline. No PostHog code is modified here.

## When to use this skill

- "How do I call my endpoint?" / "What does a request look like?"
- "Generate a typed TypeScript / Python / Go client for this endpoint"
- "I'm getting a 401 calling the endpoint" / auth questions
- "The endpoint rejects my call when I omit `user_id`" → materialised-endpoint variable
  questions
- "How do I handle rate limits?"

If the user is **creating** the endpoint, use `creating-an-endpoint` first.

## Available tools

| Tool                    | Purpose                                                                                                    |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- |
| `endpoint-get`          | Full config for a named endpoint, including the query shape and required variables                         |
| `endpoint-openapi-spec` | OpenAPI 3.0 spec for one endpoint, ready to feed to a code generator                                       |
| `endpoint-run`          | A live call against the endpoint — useful to confirm a payload works before sharing it with the user's app |

## The endpoint URL

```text
/api/projects/{team_id}/endpoints/{name}/run
```

- `team_id` is the project ID (numeric). Available in PostHog under project settings, or via
  `posthog-get-projects` if the user doesn't know it.
- `name` is the endpoint name — see `endpoints-get-all` if the user isn't sure.
- The trailing `/run` is required.

`POST` is the canonical method. `GET` also works for simple cases without a request body but
POST is preferred — variables go in the body.

## Auth

Endpoints are authenticated with a **personal API key**. The header is:

```http
Authorization: Bearer <key>
```

Keys are scoped — for endpoints, the key needs at least `endpoint:read`. If the user gets a 403,
they're usually missing the scope; if they get a 401, the key is missing or malformed.

Never put a personal API key in client-side code that's shipped to end users (mobile apps,
browser JS). Personal API keys grant scoped account access. For customer-facing apps, route
through the user's own backend, which holds the key.

## The request payload

```json
{
  "variables": { "code_name_1": value, "code_name_2": value },
  "limit": 100,
  "offset": 0,
  "refresh": "cache"
}
```

| Field       | Notes                                                                                                                                                                     |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `variables` | Keyed by `code_name` for HogQL endpoints; for insight endpoints with breakdowns, key is the **breakdown property name**                                                   |
| `limit`     | Max rows returned.                                                                                                                                                        |
| `offset`    | Skip rows. Only HogQL endpoints                                                                                                                                           |
| `refresh`   | `"cache"` (return cached results if fresh enough), `"force"` (always recalculate), `"direct"` (bypass materialisation, materialised endpoints only). Default is `"cache"` |

Call `endpoint-get` to see the exact variable shape. The response includes the query definition
with declared variables — each variable's `code_name` is what the client should send.

## Materialised endpoints: all variables are required

If `endpoint-get` shows `is_materialized: true` on the current version, the endpoint requires
**every declared variable** to be passed on each call. This is a security boundary — without
filters, a single call would return the entire pre-aggregated dataset.

Common symptom: the user's app worked when the endpoint was unmaterialised, then started
returning 400 errors after materialisation was enabled. The error message lists which variables
are missing.

Optional/partial variables on materialised endpoints are a known limitation the PostHog team plans
to lift. If requiring every variable is blocking the user's use case, send a note via the
`agent-feedback` tool — that demand signal is how the team prioritises it.

## Generating a typed client

The endpoint exposes its own OpenAPI 3.0 spec via `endpoint-openapi-spec`. Feed that into a code
generator:

| Language   | Tool                    | Command shape                                                                    |
| ---------- | ----------------------- | -------------------------------------------------------------------------------- |
| TypeScript | `@hey-api/openapi-ts`   | `openapi-ts -i spec.json -o ./generated`                                         |
| TypeScript | `openapi-generator-cli` | `openapi-generator-cli generate -i spec.json -g typescript-fetch -o ./generated` |
| Python     | `openapi-generator-cli` | `openapi-generator-cli generate -i spec.json -g python -o ./generated`           |
| Go         | `oapi-codegen`          | `oapi-codegen -package=client spec.json > client.go`                             |

The generated client gives the user types for the variables payload and the response shape. Re-
generate when the endpoint's query changes (each new version may have different variables).

If the user has multiple endpoints, generate a spec per endpoint and either combine them, or
generate one client per endpoint and use them side-by-side.

## Response shape

A typical successful response:

```json
{
  "results": [[...], [...]],
  "columns": ["col_a", "col_b"],
  "types": ["Int64", "String"],
  "hasMore": false,
  "name": "endpoint_name",
  "endpoint_version": 4,
  "endpoint_version_created_at": "2026-01-15T..."
}
```

- `results` is an array of rows; each row is an array of cell values in the order of `columns`.
- `endpoint_version` tells the client which version actually ran — useful for logging and for
  pinning to a known version with `?version=N`.

For insight endpoints, the response shape depends on the query kind (`TrendsQuery`,
`LifecycleQuery`, `RetentionQuery`) — the OpenAPI spec captures the right shape for the current
version. Insight kinds that can't be materialised (e.g. `FunnelsQuery`) still return their inline
result shape.

## Calling from the PostHog CLI

For local testing, scripts, or CI, the repo's `posthog-cli` calls endpoints without hand-rolling
HTTP:

- `posthog-cli exp endpoints run` — execute an endpoint (from a local YAML definition)
- `posthog-cli exp endpoints {list,get,pull,push,diff}` — inspect endpoints, or manage them as YAML
  files in version control (GitOps-style)

Auth uses the same personal API key, via `posthog-cli login` or the `POSTHOG_CLI_API_KEY` /
`POSTHOG_CLI_PROJECT_ID` / `POSTHOG_CLI_HOST` env vars. (These live under `exp` — experimental, may
change.)

## Error responses to handle

| Status | When                                                                           | Handling                                                                         |
| ------ | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| 400    | Missing required variable on a materialised endpoint, or invalid variable type | Surface the error message; fix the call                                          |
| 401    | Missing / wrong personal API key                                               | Check the Authorization header                                                   |
| 403    | Key lacks `endpoint:read` scope, or endpoint is in another project             | Adjust key scopes                                                                |
| 404    | Endpoint name typo, or endpoint not active                                     | Confirm name; check `is_active`                                                  |
| 429    | Rate limited — limits are per team, not per endpoint (see note below)          | Exponential backoff; cache responses client-side if possible                     |
| 5xx    | Query execution failure (ClickHouse error, timeout, etc.)                      | Retry with backoff. If persistent, hand off to `diagnosing-endpoint-performance` |

## Workflow

1. Confirm endpoint name. If unknown, list them with `execute-sql` on
   `system.data_modeling_endpoints` (or `endpoints-get-all`).
2. `endpoint-get` to see the full shape: variables, materialisation status, query kind.
3. Decide the auth posture: personal API key on a server, never client-side.
4. If the user wants generated types, call `endpoint-openapi-spec`, hand them the spec, and
   recommend a generator for their language.
5. Build a sample request payload from the variable declarations and walk through a test call.
6. Optionally call `endpoint-run` from this skill to confirm the payload works.
7. Wrap up with handling notes: the materialised-variables rule, the rate-limit shape, and
   pinning to a version with `?version=N`.

## Example interaction

```text
User: "I want to call monthly_active_users from my Node.js backend.
       Can you help me wire it up with types?"

Agent steps:
- endpoint-get monthly_active_users → HogQL, variables: lookback_days
  (int, default 30), org_id (string, no default), is_materialized: true
- "Two things to know upfront:
   1. This endpoint is materialised, so both lookback_days and org_id
      must be passed on every call. Calls without them will be rejected.
   2. You'll need a personal API key with endpoint:read scope. Set it
      as PH_API_KEY in your server env — never ship it in client code."

- endpoint-openapi-spec monthly_active_users → returns spec

- "Here's the spec. Drop it in your repo and run:
     pnpm dlx @hey-api/openapi-ts -i spec.json -o ./generated/posthog
   That gives you typed client functions.

   A minimum call looks like:
     POST /api/projects/12345/endpoints/monthly_active_users/run
     Authorization: Bearer <PH_API_KEY>
     Content-Type: application/json

     { 'variables': { 'org_id': 'acme', 'lookback_days': 30 } }

   The response includes columns and rows — your client will pick that
   up from the generated types.

   Want me to do a sample call to verify the payload works?"
```

## Important notes

- **Personal API keys are server-side only.** Never ship them in mobile apps or browser JS.
- **Re-generate the client when the query changes.** Each new endpoint version may add or
  remove variables — keep types in sync by re-fetching the spec.
- **Materialised endpoints reject calls missing variables.** This is intentional. If the user
  reports a 400 after materialisation was enabled, the fix is in the call, not in the endpoint.
- **Pin to a version — don't rely on "latest".** Always call with `?version=N`. Without it the
  latest active version runs, so a future query edit (which cuts a new version) can silently change
  a caller's results. Bump the pinned version deliberately once you've validated the new one.
- **Caching on the client side is fair game.** The endpoint already caches via
  `data_freshness_seconds`, but the client can layer another cache on top for hot paths. Be
  mindful of total staleness (endpoint cache + client cache).
- **Rate limits are per team, by category — not per endpoint.** Calls to non-materialised
  endpoints share the team-wide API-query budget (~240/min burst, ~2400/hour sustained) with all
  other query traffic; materialised endpoints draw on a separate, higher shared bucket
  (~1200/min, ~12000/hour). There is no per-endpoint-name limit, so hammering one endpoint can
  starve others on the same team. Heavy callers should batch where possible and back off on 429.
- **Pricing.** Calling endpoints isn't billed today, but it will be once endpoints ship alongside
  the [managed warehouse](https://posthog.com/data-stack/managed-warehouse). Flag this to the user
  if they're planning high-volume usage so the future cost isn't a surprise.
- **Tell PostHog what's missing.** If an error, a limit, or a missing capability gets in the way,
  use the `agent-feedback` tool — it's the main signal the team uses to improve endpoints and these
  tools.
