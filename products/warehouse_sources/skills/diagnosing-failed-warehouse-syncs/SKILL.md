---
name: diagnosing-failed-warehouse-syncs
description: >
  Diagnose why a data warehouse sync is failing and recommend the right recovery action. Use when the user asks "why
  isn't my Stripe/Postgres/Hubspot sync working?", "this table has been stuck for hours", "the data in the warehouse
  looks wrong", or wants to troubleshoot a specific source or schema. Covers source-level vs schema-level failures,
  stuck Running states, credential errors, plan-gated 403s, schema drift, incremental-field misconfig, CDC
  prerequisite failures, and the cancel / reload / resync / delete-data recovery actions.
---

# Diagnosing failed data warehouse syncs

Work top-down when a data warehouse source or table is failing, stuck, or producing bad data: source → schema →
recovery action. Do **not** jump straight to "resync from scratch" — that discards synced data and restarts from
zero, which is rarely the right first step.

## When to use this skill

- The user reports a specific sync is failing (e.g. "my Stripe source is red")
- A table has been in `Running` state far longer than expected
- Data in a warehouse table is stale, missing rows, or looks corrupt
- Latest rows aren't appearing despite the schema being marked `Completed`
- The user is choosing between cancel / reload / resync / delete-data and isn't sure which
- Another skill — typically `auditing-warehouse-source-health` — has surfaced a failing source or schema and the user
  wants to dig into it

Both entry points (user-reported and audit-handoff) use the same workflow; the audit just means you already know
which item to diagnose and can skip Step 1's discovery search.

## Available tools

| Tool                                                   | Purpose                                                                    |
| ------------------------------------------------------ | -------------------------------------------------------------------------- |
| `external-data-sources-list`                           | List all sources with connection status and latest error                   |
| `external-data-sources-retrieve`                       | Full details for one source including all its schemas                      |
| `external-data-schemas-list`                           | All table schemas across all sources, with per-table status + latest_error |
| `external-data-schemas-retrieve`                       | Full details for one schema including sync_type_config                     |
| `external-data-schemas-cancel`                         | Cancel a sync currently in `Running` state                                 |
| `external-data-schemas-reload`                         | Trigger a sync using the configured sync method (respects incremental)     |
| `external-data-schemas-resync`                         | Full resync — wipes synced data and restarts. Destructive                  |
| `external-data-schemas-delete-data`                    | Delete the synced table but keep the schema entry                          |
| `external-data-schemas-partial-update`                 | Change sync_type / incremental_field / cdc_table_mode                      |
| `external-data-sources-partial-update`                 | Update a source's credentials (`job_inputs`) after rotation                |
| `external-data-sources-reload`                         | Retrigger syncs for every enabled schema on a source                       |
| `external-data-sources-refresh-schemas`                | Re-fetch the source's table list to pick up new tables                     |
| `external-data-sources-check-cdc-prerequisites-create` | Verify Postgres CDC setup for a source                                     |
| `external-data-schemas-incremental-fields-create`      | Refresh candidate incremental fields when the source schema has changed    |
| `external-data-sources-webhook-info-retrieve`          | Check webhook registration state and external service status               |
| `external-data-sources-create-webhook-create`          | Re-register a webhook that was lost or never registered                    |
| `external-data-sources-update-webhook-inputs-create`   | Update the signing secret after rotation on the source side                |
| `external-data-sources-delete-webhook-create`          | Remove a broken webhook before re-registering                              |

## Workflow

### Step 1 — Locate the failing item

If the user named a source, go straight to `external-data-sources-retrieve`. Otherwise start with
`external-data-sources-list` and `external-data-schemas-list` to find what's red.

Two kinds of failure:

- **Source-level** (`ExternalDataSource.status = "Error"`): the connection itself is broken — credentials expired,
  host unreachable, account disabled. Affects every table.
- **Schema-level** — the source connects fine but one or more tables are failing. In the serialized API response
  from `external-data-schemas-list`, look for `status` values `"Failed"`, `"Billing limits"`, or `"Billing limits
too low"`. (The underlying model enum values are `BillingLimitReached` and `BillingLimitTooLow`, but the
  serializer rewrites them — match on both the human-readable and enum forms to be safe.)

A source can look `Completed` at the top level while one of its schemas is `Failed` — always check both.

### Step 2 — Classify the schema status

From `external-data-schemas-list`, each schema has a `status`:

| Status                                                              | Meaning                                    | Usually means                          |
| ------------------------------------------------------------------- | ------------------------------------------ | -------------------------------------- |
| `Running`                                                           | Sync currently executing                   | Normal, unless stuck for hours         |
| `Completed`                                                         | Last sync finished successfully            | Healthy                                |
| `Failed`                                                            | Last sync errored — see `latest_error`     | Needs diagnosis                        |
| `Paused`                                                            | User disabled sync (`should_sync = false`) | Intentional                            |
| `Billing limits` (serializer) / `BillingLimitReached` (enum)        | Team hit its warehouse row quota           | Billing issue, not a technical failure |
| `Billing limits too low` (serializer) / `BillingLimitTooLow` (enum) | Team has insufficient credit               | Billing issue                          |

Read intent off the status, not off `should_sync`. A non-retryable error turns `should_sync` off on its own, and
such a schema stays `Failed` rather than moving to `Paused`.

Always check `last_synced_at` alongside status. A schema in `Running` with `last_synced_at` from 12 hours ago is
almost certainly stuck, even though the status isn't `Failed`.

### Step 3 — Interpret `latest_error`

Map the `latest_error` string to a root cause. Match on meaning, not on the status code. When the sync recognizes
a failure it stores the source's own wording in place of the raw HTTP error, so most 403s reach you as a phrase
like "refused access", "plan does not include", or "missing a scope", with no status code left in the text. The
rows below list the raw text; a reworded equivalent maps to the same row.

Common patterns:

| Error substring                                                                      | Root cause                                                 | Fix                                                                                   |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `authentication failed`, `401`, `invalid credentials`                                | Credentials expired or rotated                             | User rotates creds, then `external-data-sources-partial-update` with new `job_inputs` |
| `403`, `Forbidden`, or a refusal naming a plan, scope, or permission                 | Endpoint gate (plan or key scope), or a dead credential    | See B2. Prove the credential on a sibling before you rotate anything                  |
| `Could not establish session to SSH gateway`, `Could not connect to your SSH tunnel` | SSH tunnel misconfigured or remote host down               | User checks SSH host/key/bastion                                                      |
| `Primary key required for incremental syncs`                                         | Table has no PK and sync_type is `incremental`/`cdc`       | Either add PK in source, or switch schema to `full_refresh`                           |
| `primary keys for this table are not unique`                                         | Declared PK columns aren't actually unique                 | Pick different PK columns via `partial-update`                                        |
| `Integration matching query does not exist`                                          | Source's saved integration was deleted                     | Recreate the source                                                                   |
| `column "X" does not exist`, `does not have a column named`                          | Schema drift — incremental field or tracked column removed | Use `incremental-fields-create` to re-detect, then `partial-update`                   |
| `relation "..." does not exist`                                                      | Source table was dropped/renamed                           | Remove schema or rename source-side                                                   |
| `SSL`, `connection refused`, `timeout`, `unreachable`                                | Network / firewall / host reachability                     | User side — check host/port/allowlist                                                 |
| `replication slot`, `publication`, `wal_level`                                       | CDC prerequisites broken                                   | Run `check-cdc-prerequisites-create`; may need slot recreate                          |
| `Schema exceeds row limit`, `billing`                                                | Billing limit                                              | Upgrade plan or disable the schema                                                    |

If `latest_error` is null but the schema is `Failed`, retrieve the schema directly — the error may only be populated
on the detail view.

### Step 4 — Pick the recovery action

The recovery action depends on root cause, not just status. Match the user's situation to one of these:

**A. Transient failure (network blip, temporary API outage)**

- Data synced so far is still valid.
- Action: `external-data-schemas-reload` to retry using the configured sync method.
- Incremental/append syncs pick up where they left off.

**B. Credentials expired or rotated**

- Every schema under the source is failing, and the error names the credential.
- Action: user rotates creds → `external-data-sources-partial-update` with the new `job_inputs` → the reload happens
  automatically when the source status flips back to running, or trigger manually with `external-data-sources-reload`.

**B2. A 403 while the source's other tables are healthy**

- A `403` / `Forbidden`, or the source's reworded refusal, says an endpoint is closed. It does not say the credential
  is wrong. Sources return it both for an endpoint the account plan does not include and for one the key's scopes
  exclude.
- Do not try to date the failing attempt. `last_synced_at` moves only on success, so the failing schema's copy is its
  last good sync, and no tool here reports when the failed attempt ran.
- Prove the credential in the present instead. Pick a `Completed` schema on the same source, call
  `external-data-schemas-reload` on it, then poll `external-data-schemas-retrieve` until its `last_synced_at`
  advances. Reload is not destructive.
  - **Sibling completes.** The credential is live, so the source is gating this one endpoint. Do not rotate on the
    403 alone. A scope gate can still need a new key, so let the source's message decide.
  - **Sibling fails the same way.** Treat it as case B, or as a plan gate over the whole API. Read the source's
    message.
  - **No sibling to test**, because the source syncs one table or every table is failing. You cannot separate the two
    causes from here. Ask the user whether their plan covers the endpoint before you send them for a new key. A new
    key on the same plan fails the same way.
- Relay the source's own message to the user word for word, and do not compress it to "rotate your credentials".
  It carries what the status code cannot: the exact scopes a key needs, or which endpoint to ask for. Some messages
  only report the refusal and name the plan as the likely cause. When the message gives no concrete remedy, have the
  user ask the source which plan or scope covers the endpoint, rather than guess.
  - **Plan gate.** The user asks the source to enable the endpoint.
  - **Scope gate.** The user grants the missing scope on the key. Some sources cannot edit an existing key's scopes,
    so the user creates a correctly scoped key instead. That is a real credential change, so follow it with
    `external-data-sources-partial-update` and the new `job_inputs`.
- A reworded 403 means PostHog already turned the schema off, so every fix ends with
  `external-data-schemas-partial-update` and `should_sync: true`. If the user does not need the table, leave it off.

**C. Schema drift — column renamed, dropped, or type changed**

- Error mentions a specific column that no longer matches the source.
- Action: `external-data-schemas-incremental-fields-create` to get the current fields, then
  `external-data-schemas-partial-update` with the corrected `incremental_field` / `incremental_field_type` /
  `primary_key_columns`. Usually no need to wipe data.

**C2. Added / renamed tables in the source database**

- User mentions "I added a new table to Postgres but it isn't appearing", or a source table was renamed.
- Action: `external-data-sources-refresh-schemas` to pick up the new table list, then configure sync on any new
  schemas.

**D. Incremental state is wrong (duplicates, missing rows, data looks corrupt)**

- Schema status may be `Completed` — this isn't a "failure" per se, it's bad data.
- Action: `external-data-schemas-resync` to wipe synced data and re-import from source. Destructive but often the
  right call for data-quality issues.

**E. CDC pipeline broken on Postgres**

- Error mentions replication slot, publication, WAL.
- Action: `external-data-sources-check-cdc-prerequisites-create` to enumerate what's broken, fix on the Postgres
  side, then `external-data-schemas-reload`. If the WAL position was lost, a `resync` is sometimes unavoidable.

**F. Sync is stuck in `Running` for hours**

- Check `last_synced_at`. If it's hours old and still `Running`, the job is orphaned.
- Action: `external-data-schemas-cancel` to stop it, then `external-data-schemas-reload`.

**G. Table data is corrupt but you want to keep the schema config**

- Action: `external-data-schemas-delete-data` to drop the synced table but preserve the schema entry. Next reload
  re-imports from scratch without losing the configured sync_type/incremental_field.

**H. Billing limit**

- Action isn't technical. Explain the limit, recommend upgrading the plan or disabling lower-priority schemas so the
  important ones fit under quota.

**I. Webhook-backed schema isn't receiving events**

- Symptoms: schema has `sync_type: "webhook"`, initial bulk sync finished, but no new rows arrive despite activity on
  the source side. Status may still read `Completed` because the bulk sync (the safety-net cadence) is succeeding —
  the problem is the push path.
- Action:
  1. `external-data-sources-webhook-info-retrieve({source_id})`.
  2. If `exists: false` → the webhook was never registered, or was deleted. Call `create-webhook-create` to
     register it.
  3. If `exists: true` but `external_status.error` is set → typically "API key doesn't have permission to read
     webhooks" or similar. The webhook may have been deleted on the source's dashboard. Re-create it.
  4. If `external_status.status` isn't `"enabled"` → the source disabled the webhook (usually after repeated
     delivery failures). Re-enable or re-register.
  5. If payloads are arriving but failing signature verification → the signing secret was rotated. Get the new
     one from the source's dashboard and call `update-webhook-inputs-create({source_id}, {inputs:
{signing_secret: "..."}})`.
- After any fix, check the source's webhook logs (on their side) to confirm PostHog is now responding 2xx.

### Step 5 — Confirm before destructive actions

Three recovery actions discard data and cannot be undone:

- `external-data-schemas-resync` — wipes synced rows, re-imports from scratch
- `external-data-schemas-delete-data` — drops the synced table
- `external-data-sources-destroy` — deletes the source and all its schemas

Always present the fix you're proposing and wait for explicit approval before calling any of these. "Just try
resync" is rarely the right default.

## Example interaction

```text
User: "Our Stripe sync is broken, can you check?"

Agent:
- external-data-sources-list → find Stripe source, status = Error
- external-data-sources-retrieve({id}) → latest_error: "authentication failed: 401 Unauthorized"
- Report: "Your Stripe source's API key is no longer authenticating.
   All 8 tables under it are failing with 401s. This usually means the key was rotated on the Stripe side.

   To fix:
   1. Grab a fresh restricted API key from the Stripe dashboard.
   2. I'll update the source with the new key.
   3. Syncs will resume automatically — no data loss.

   Paste the new key here when ready."

User: "sk_live_..."

Agent:
- external-data-sources-partial-update({id}, {job_inputs: {stripe_secret_key: "sk_live_..."}})
- external-data-sources-reload({id}) to trigger retry
- Report: "Updated and re-triggered. Check back in a few minutes — latest_error should clear."
```

## Important notes

- **Source status overrides schema status for diagnosis.** If the source is `Error`, nothing under it will work;
  fixing the source usually fixes all its schemas at once.
- **`Running` isn't always healthy.** Cross-check `last_synced_at`. A sync stuck in `Running` needs `cancel` then
  `reload`, not `resync`.
- **Resync is destructive.** It discards synced data. Only recommend it when the data itself is bad (duplicates,
  missing rows, corrupt) or when recovery genuinely requires a clean slate (lost WAL position on CDC). Never use it
  as a first-try for transient errors.
- **Delete-data preserves config.** When a user says "I just want to start this table over from scratch", prefer
  `delete-data` + `reload` over `resync` + new schema entry — it keeps the configured sync_type / incremental_field
  / PK setup.
- **A failure can belong to a destination, not the source.** Some projects sync a source to their own database as
  well as to PostHog. When they do, `latest_error` is prefixed with the destination's name, e.g.
  `customer postgres: connection refused`. That is the customer's database refusing the write, not the source failing
  to extract — check their database and its credentials rather than the source's. Every destination shares one
  lifecycle, so one unreachable destination holds up the whole sync, PostHog included.
- **A 403 is not proof of a bad key.** It says an endpoint is closed, not that the credential is wrong. Sources
  return it for an endpoint the plan does not include, and for one the key's scopes exclude, with a key that works
  everywhere else. Timestamps cannot settle it, because `last_synced_at` records only successes, so nothing here
  reports when the failing attempt ran. Settle it by making the credential work now: reload a healthy sibling and
  watch it complete. Rotate only when no sibling can succeed and the source's own message names the credential.
- **Billing limits aren't technical failures.** Don't try to retry or reconfigure your way out. Route to billing.
- **Webhook failures can hide behind a green status.** A webhook-type schema whose bulk fallback sync succeeded looks
  `Completed` even when the push channel is broken. When users say "my data is hours behind" on a webhook schema,
  call `webhook-info-retrieve` before looking at schema status. Webhook issues don't surface on
  `external-data-schemas-list`.
