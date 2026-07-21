# Workflows agent guide

Repo-wide conventions live in [`../../AGENTS.md`](../../AGENTS.md) — read that first.
[`CONTRIBUTING.md`](./CONTRIBUTING.md) has the recipes for extending the builder UI
(trigger types, action nodes, Hog function templates, input types). This file covers
the rules and landmines specific to workflows' data layer, its Node.js runtime, and
its API — the things that aren't discoverable from types and cost real review cycles
when missed.

## The data layer: where workflow email metrics actually live

Delivery metrics are in ClickHouse `app_metrics2` with `app_source = 'hog_flow'`,
one row per (team, app_source_id, metric) per hour bucket. The metric names are not
what you'd guess — the mapping from SES events lives in
`nodejs/src/cdp/services/messaging/helpers/ses.ts`:

- `email_sent` / `email_failed` — send outcome (`email.service.ts`)
- `email_bounced` — SES `Bounce`
- `email_blocked` — SES `Complaint`. **This is the spam-complaint metric**, despite
  the name. `email_spam` also exists in the type union but SES complaints do NOT
  flow into it.
- `email_opened` / `email_link_clicked` — tracking pixel/redirect; these arrive via
  publicly reachable endpoints and are forgeable, so never use them for
  trust/reputation decisions.

Bounces and complaints arrive **hours after their send** via the SES webhook, into
whatever hour bucket they land in — a bucket can hold bounces with zero sends.
Windowed aggregations must not filter on `sent > 0` per bucket or late bounces
silently vanish.

## Batch broadcasts attribute metrics to the batch-job id

Batch-triggered runs record `app_metrics2.app_source_id` as the **batch job id**
(`parentRunId`), not the workflow id. To attribute per workflow, resolve unmatched
source ids through `workflows_hogflowbatchjob (id → hog_flow_id)`. Source ids that
match neither a workflow nor a batch job (deleted flows, plain hog functions) are
real traffic — decide explicitly whether they count in team-level aggregates.

## Table names are mixed — check `db_table` before writing raw SQL

Older workflows models keep legacy names (`posthog_hogflow`,
`posthog_hogflowschedule`); newer ones use Django's app-prefixed default
(`workflows_hogflowbatchjob`). Node-side raw SQL against the wrong guess fails only
at runtime — a service test that inserts real rows is the cheapest guard.

## Rows written by Node, read by Django

Node services (evaluators, consumers) write rows keyed by the **raw** team id, which
in multi-environment projects can be a child environment id that canonical-team
resolution would rewrite. When Django reads such rows, use
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
