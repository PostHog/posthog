# Workflows agent guide

Repo-wide conventions live in [`../../AGENTS.md`](../../AGENTS.md) — read that first.
[`CONTRIBUTING.md`](./CONTRIBUTING.md) has the recipes for extending the builder UI
(trigger types, action nodes, Hog function templates, input types). This file covers
what isn't discoverable from types: how the product is split across runtimes, the
cross-language couplings that must move together, and the landmines that cost real
review cycles when missed.

## Orientation: workflows is a split-brain product

- **Django** (`products/workflows/backend/`) owns models, CRUD, validation, and the
  API (`api/hog_flow.py` is the center of gravity).
- **The Node plugin server** (`nodejs/src/cdp/services/hogflows/` and siblings under
  `nodejs/src/cdp/`) owns execution: trigger matching, the graph executor,
  cyclotron job queues, delays/waits, batch jobs, scheduling, email delivery.
- **The frontend** (`products/workflows/frontend/`) owns the builder and scenes.

Most features touch at least two of the three. When you change a definition on one
side, go looking for its mirror on the others — the couplings below are the known
ones.

## Execution pipeline: what rides Kafka vs cyclotron Postgres

Events reach CDP from the `clickhouse_events_json` Kafka topic;
`cdp-events.consumer.ts` evaluates them against enabled functions and flows, then
splits the resulting invocations by kind — the same split every re-enqueue path
(rerun worker, batch resolve) must preserve:

- **Hog functions → Kafka** (`hog` / `hogoverflow` queues): stateless
  fire-and-forget HTTP work, optimized for throughput.
- **Hog flows → cyclotron Postgres** (`hogflow` queue, `postgres-v2` source): flow
  runs are durable jobs with `queueScheduledAt`, because delay / wait-until /
  batch nodes park a job for hours or days — state that can't live in a Kafka
  offset. Workers: `cdp-cyclotron-worker-hogflow.consumer.ts`.
- **Email sends → the dedicated `email` cyclotron queue**
  (`cdp-cyclotron-worker-email`), which applies the SES rate limiter and
  suppression checks.
- Queue kinds and sources are the closed unions in `nodejs/src/cdp/types.ts`
  (`CYCLOTRON_INVOCATION_JOB_QUEUES`, `CYCLOTRON_JOB_QUEUE_SOURCES`) — extend
  there first or nothing routes.
- **Transformations never touch cyclotron** — they run inline in the ingestion
  pipeline before events reach ClickHouse. If you're adding "modify the event"
  behavior, it doesn't belong in this product's queue machinery at all.

Adjacent entry points that feed the same queues: the recurring-schedule poller
(`cdp-hogflow-scheduler`, driven by Django's `internal_process_due_schedules`),
batch broadcasts (`HogFlowBatchJob` rows → audience resolution in
`cdp-cyclotron-worker-batch-resolve`), and the subscription matcher. New
server-side entry points should enqueue through the existing `JobQueue`
abstractions rather than writing to topics or job tables directly.

## One flow definition, three schemas — change all of them together

The `HogFlow` shape exists in three places that nothing keeps in sync:

1. `products/workflows/backend/api/hog_flow.py` — DRF serializers, the **source of
   truth** (validation + generated API/MCP types flow from here)
2. `nodejs/src/cdp/schema/hogflow.ts` — zod schema the executor parses rows with
3. `products/workflows/frontend/Workflows/hogflows/types.ts` — the frontend zod/TS
   mirror

Adding an enum value (e.g. a new `status`), field, or action type in one place and
not the others fails at runtime or typecheck far from your change. Grep all three.

Other Django↔Node couplings enforced only by comments and runtime errors:

- `DELAY_DURATION_REGEX` in `hog_flow.py` must match the parser in
  `nodejs/src/cdp/services/hogflows/actions/delay.ts`.
- The `trigger` column is **derived** server-side from the actions array (exactly
  one `type: 'trigger'` action); `billable_action_types` is computed on save.
  Neither is client-writable — don't add API surface that pretends otherwise.

## Validation is deliberately two-tier: web drafts are lenient, everyone else is strict

`_should_validate_strictly` (hog_flow.py): drafts saved from the web builder pass
with incomplete/invalid configs (mid-edit saves), while programmatic callers (API,
MCP, agents) get full validation even on drafts. When adding validation, wire it
through this posture — a check that ignores it either blocks the builder's
incremental saves or lets agents store configs that only explode at activation.
Graph-structure validation (`graph_validation.py`) is enforced only on the `/graph`
endpoint and advisory elsewhere, because existing rows carry legacy corruption.

## Execution reads a cache — status changes need the reload signal

The plugin server loads **only `status='active'`** flows, cached via `LazyLoader`
(`hogflow-manager.service.ts`), invalidated by the `reload-hog-flows` pubsub
message. Django's `post_save` signal publishes it (`reload_hog_flows_on_workers`).
If you mutate flow rows any way that skips `save()` (queryset `.update()`, raw SQL
from Node), workers keep executing the stale definition until you publish the
reload yourself.

## The data layer: where workflow email metrics live

Delivery metrics are in ClickHouse `app_metrics2` with `app_source = 'hog_flow'`,
one row per (team, app_source_id, metric) per hour bucket. The metric names are not
what you'd guess — the SES-event mapping lives in
`nodejs/src/cdp/services/messaging/helpers/ses.ts`:

- `email_sent` / `email_failed` — send outcome (`email.service.ts`)
- `email_bounced` — every SES `Bounce` type: the catch-all rollup. Each bounce also
  emits exactly one sub-metric by `bounceType` — `email_bounced_hard` (Permanent),
  `email_bounced_transient` (Transient), `email_bounced_undetermined` — so
  hard + transient + undetermined = email_bounced. **Anything calibrated against
  AWS's account bounce rate must read `email_bounced_hard`**: AWS counts hard
  bounces only, so the rollup overcounts by the transient share.
- `email_blocked` — SES `Complaint`. **This is the spam-complaint metric**, despite
  the name; `email_spam` exists in the type union but SES complaints do NOT flow
  into it.
- `email_opened` / `email_link_clicked` — tracking pixel/redirect; publicly
  reachable and forgeable, so never use them for trust/reputation decisions.

Bounces and complaints arrive **hours after their send** via the SES webhook, into
whatever hour bucket they land in — a bucket can hold bounces with zero sends.
Windowed aggregations must not filter on `sent > 0` per bucket or late bounces
silently vanish.

**Batch broadcasts attribute metrics to the batch-job id** (`parentRunId`), not the
workflow id. To attribute per workflow, resolve unmatched source ids through
`workflows_hogflowbatchjob (id → hog_flow_id)`. Ids matching neither (deleted
flows, plain hog functions) are real traffic — decide explicitly whether they count
in team-level aggregates.

## Table names are mixed — check `db_table` before writing raw SQL

Older workflows models keep legacy names (`posthog_hogflow`,
`posthog_hogflowschedule`); newer ones use Django's app-prefixed default
(`workflows_hogflowbatchjob`). Node-side raw SQL against the wrong guess fails only
at runtime — a service test that inserts real rows is the cheapest guard.

## Rows written by Node, read by Django

Node services (evaluators, consumers) write rows keyed by the **raw** team id,
which in multi-environment projects can be a child environment id that
canonical-team resolution would rewrite. When Django reads such rows, use
`Model.objects.for_team(self.team_id, canonical=True)` — never plain ambient scope
(silently misses child-env rows) and never `unscoped()` (banned by root CLAUDE.md).

## New models: two registrations or CI fails

1. Team-scoped models must be added to
   `.semgrep/rules/security/idor-team-scoped-models.yaml` — **both** alternation
   blocks — or the repo-checks IDOR coverage job fails.
2. `ChoiceField`s named `scope`/`state`/`status` collide with existing enums; add
   `ENUM_NAME_OVERRIDES` entries in `posthog/settings/web.py`
   (`python manage.py find_enum_collisions` prints pastable entries).

## API endpoints on HogFlowViewSet

- **`hog_flow` is a registered access-control resource** (since #65314). Any
  `detail=False` action that returns per-workflow data must intersect with
  `self.user_access_control.filter_queryset_by_access_level(self.get_queryset())`
  — `metrics_global` is the reference pattern (ignore its stale "not a resource
  today" comment). Project-wide aggregates that can't be filtered per object should
  gate on `check_access_level_for_resource("hog_flow", "viewer")`: a member holding
  a single object-level grant otherwise reads every workflow's data, because
  `detail=False` actions never hit object-level permission checks.
- Custom `@action` methods must be listed in `scope_object_read_actions` /
  `scope_object_write_actions` or every personal API key / OAuth / MCP call 403s —
  see `products/ai_observability/AGENTS.md` for the full explanation.

## Node.js runtime patterns (nodejs/src/cdp)

- **New dedicated service** = a `PluginServerMode` entry
  (`nodejs/src/common/config.ts`) + a capability (`nodejs/src/capabilities.ts`,
  including the dev ride-along in `CAPABILITIES_CDP_WORKFLOWS`) + a loader block in
  `nodejs/src/server.ts`. In dev, degrade gracefully when optional deps (e.g. local
  Temporal) are down — and return a **healthy** stub, or the combined dev server's
  `/_health` 503s forever.
- **Temporal inside the plugin server**: follow
  `cdp/services/email-reputation/temporal/` (or the session-replay rasterizer) —
  TLS cert config, `EncryptionCodec`, and an idempotent ensure-schedule that
  **updates spec, policies, and action** when the schedule already exists (create-
  only ensures mean config changes are silently ignored forever). Activity results
  ride workflow history: page anything fleet-sized (root CLAUDE.md's ~256KB field
  rule).
- **Secure internal ClickHouse clients need the TLS-relaxed `http_agent`**
  (`rejectUnauthorized: false` + the nosemgrep annotation) — internal ClickHouse
  serves self-signed certs with a hostname mismatch. Copy the construction from
  `cdp-rerun-worker.consumer.ts`; without it every `CLICKHOUSE_SECURE=true` query
  fails in production while dev (insecure) stays green.
- **Deploying a new mode**: charts app copied from `apps/cdp-rerun-worker` or
  `apps/cdp-hogflow-scheduler` (shared/cdp provides `psql.cloud` + `temporalCloud`);
  Postgres credentials via `aurora_user_management/v3.0.0` per cloud stack in
  posthog-cloud-infra (NOT the legacy `posthog_app_db_users` list — it grants
  rds_superuser and provisions the persons cluster too); ClickHouse pod-auth
  namespace entry in `ansible/roles/clickhouse/ch-podauth`. Infra must apply before
  the charts app syncs or pods crash-loop on missing ExternalSecrets.

## Frontend: the workflows scene

Flag-gated tabs need three coordinated pieces in
`products/workflows/frontend/WorkflowsScene.tsx`: the `WORKFLOW_SCENE_TABS` entry,
the conditional tab in the tabs array, **and** a flag-off fallback in `urlToAction`
— without the fallback, a deep link to the hidden tab renders a tab bar with
nothing selected and empty content. The suppression-list tab is the reference.

## CI landmines that look unrelated to your change

- Adding any `FEATURE_FLAGS` constant grows toolbar-reachable `constants.tsx`; the
  toolbar graph budget (`frontend/bin/check-toolbar-graph.mjs`) rides within bytes
  of its ratchet. If file count and survivor closure match master, a small
  conscious budget bump is the intended fix.
- `ci-nodejs`'s fast path restores a schema snapshot **built from master** whenever
  the PR's own diff has no migration files. Node tests touching a table whose
  migration lives in another (stacked or unmerged) PR stay red until that migration
  reaches master — sequence stacked PRs accordingly instead of hunting a phantom
  bug.
