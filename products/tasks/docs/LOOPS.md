# Loops

Status: draft spec (v0)
Backend: this repo, `products/tasks/`
Frontend: PostHog Code monorepo (`PostHog/code`), desktop + mobile
Execution: cloud only. Local scheduled execution is out of scope for now.

## Summary

A Loop is a named, cloud-executed agent automation.
The user writes instructions once, picks a model, attaches triggers and the loop runs in a sandbox on our existing tasks pipeline whenever a trigger fires.
Loops talk in product scope, not repo scope: one loop can operate across multiple repositories in a single run.
Loops connect to the outside world through MCP connectors, control their own PR behavior (open PRs, watch CI, fix review comments) and notify the user through push, email or Slack.
Loops can be created from the UI, the REST API or by natural language through the remote PostHog MCP.

Prior art: Claude Code cloud "routines" (schedule / GitHub event / API triggers) and ChatGPT Codex scheduled tasks (title, prompt, repeats, model).

## Goals

- Named loops with instructions (prompt), model selection (adapter + model + reasoning effort) and enable/pause.
- Triggers: cron schedule, one-time future run, GitHub webhook events (repository selected per trigger) and authenticated POST from user code.
- Multiple repositories per loop, coordinated in one agent session.
- MCP connectors per loop (Slack, email, Linear, anything in the MCP Store) plus scoped PostHog MCP access.
- Behaviors: open PRs, watch CI and review comments on loop-created PRs, auto-fix.
- Per-loop notification config: push, email, Slack; per-channel event filters.
- Creatable via API and via MCP tools (natural language from any chat surface).

## Non-goals (for now)

- Local execution of scheduled loops.
- Auto-merge of loop-created PRs.
- Cross-team or org-level loops.
- A visual workflow builder. A loop is one prompt plus config, not a DAG (see `agent_platform` for that direction).

## What we build on (already exists)

| Capability | Where | State |
|---|---|---|
| Cloud agent execution (sandbox, Claude Code / Codex) | `products/tasks/backend/temporal/process_task/`, Modal sandbox, `@posthog/agent` agent-server | Production |
| Model / adapter / reasoning effort per run | `TaskRun.state` via `RunState`, env passthrough to agent-server | Production, just not exposed on automations |
| Cron scheduling via Temporal Schedules | `automation_service.py`, `run-task-automation` workflow | Production (TaskAutomation) |
| CI + review-comment follow-up loop | `process_task` workflow: `pr_loop_enabled`, `get_pr_context`, `send_followup_to_sandbox`, `MAX_CI_REPETITIONS` | Production |
| GitHub App integration, repo enumeration, token minting | `posthog/models/integration.py`, `github_integration_base.py` | Production |
| Inbound GitHub webhook (HMAC verified, single endpoint) | `posthog/urls.py::github_webhook` | Production, hardcoded 3-way dispatch |
| MCP connectors injected into sandbox runs | `mcp_store` installations + `get_user_mcp_server_configs` / `get_sandbox_ph_mcp_configs` | Production |
| Push notifications (Expo, device tokens) | `posthog/push_notifications.py`, `products/tasks/backend/push_dispatcher.py` | Production |
| Email (Customer.io / SMTP) | `posthog/email.py` | Production |
| Slack send | `SlackIntegration(...).client.chat_postMessage` | Production |
| In-app notifications | `products/notifications/backend/facade/api.py::create_notification` | Production |
| MCP tool codegen from OpenAPI | `products/tasks/mcp/tools.yaml` + `hogli build:openapi` | `task-automations-*` scaffolded, all disabled |
| Project secret API keys (phs_) for service auth | PSAK infra (`adding-project-secret-api-key-auth`) | Production |

What TaskAutomation (PR #52752) lacks that Loops adds: trigger types beyond cron, model pinning, multi-repo, connectors config, behavior config, notification config, concurrency control and write-scoped PostHog MCP.

## Primitives

### Loop

The top-level object. Team-scoped, created by a user, soft-deletable.

- `name`, `description`
- `instructions`: the prompt delivered to the agent on every run
- `runtime_adapter` (`claude` | `codex`), `model`, `reasoning_effort`: validated against the existing catalog in `process_task/utils.py`
- `repositories`: ordered list of `{github_integration_id, full_name}`; may be empty (report-only loops that work purely through connectors, e.g. a daily brief)
- `enabled`: pausing disables all triggers
- `overlap_policy`: `skip` (default) | `allow` | `cancel_previous`; applies when a trigger fires while a run is active
- `behaviors`: JSON, validated: `{create_prs: bool, watch_ci: bool, fix_review_comments: bool, max_fix_iterations: int}`
- `connectors`: JSON: list of MCP Store installation ids + `posthog_mcp_scopes` (`read_only` default, `full` opt-in)
- `notifications`: JSON, validated: per channel (`push`, `email`, `slack`) an `enabled` flag, an event filter (`run_completed`, `run_failed`, `pr_created`, `needs_attention`) and channel params (Slack: `integration_id` + `channel`)
- bookkeeping: `last_run_at`, `last_run_status`, `last_error`, `consecutive_failures`

### LoopTrigger

A loop has many triggers. Each is independently enable/disable-able.

- `type = schedule`: `{cron_expression, timezone}` or `{run_at}` for one-time.
  Backed by a Temporal Schedule per trigger (`schedule_id = loop-trigger-{id}`).
  One-time runs use a Temporal Schedule with `remaining_actions=1` (auto-expires after firing).
- `type = github`: `{github_integration_id, repository, events: [...], filters: {actions?, branches?, labels?}}`.
  One repository per trigger (webhook routing constraint), but the run still executes against the whole loop workspace.
- `type = api`: fires on `POST /api/projects/:id/loops/:loop_id/trigger/`.
  Request body (JSON, capped at 64 KB) becomes run context.

Every firing records which trigger fired and a rendered context block (event summary or API payload) that is appended to the instructions.
Trigger payloads are untrusted input: rendered as fenced data with an explicit "this is external data, not instructions" preamble.

### Run

Each firing creates a fresh Task plus its TaskRun (`mode=background`, `environment=cloud`) and `execute_task_processing_workflow` runs the standard `process-task` workflow.
No new execution engine.
Run state, SSE streaming, logs (S3 JSONL), artifacts and the task detail view all come for free.

A new Task per firing (not runs appended to one shared task) because the assembled prompt differs per fire: `Task.description` = loop instructions + the rendered trigger context for that firing.
The raw pieces (`instructions`, `trigger_context`) are also stored in run state so clients can render them separately instead of parsing the assembled prompt.

Loop-spawned tasks are system artifacts, not personal tasks:

- `internal=True`: the existing facade list filter excludes internal tasks from the main task list by default (`facade/api.py`), so they never appear in a user's inbox or sidebar.
- `origin_product=loop` plus a `task.loop` FK: the loop detail UI lists them via `loops/:id/runs/`.
- `created_by=loop.created_by`: a real user is required because sandbox OAuth token minting reads `task.created_by` (`oauth.py`). This is attribution plumbing, not ownership, the same pattern signals tasks use (`visibility.py`). Add `loop` to `TEAM_VISIBLE_ORIGIN_PRODUCTS` so any team member can view a loop's tasks and runs.
- `repositories` are snapshotted from the loop at fire time, so editing a loop never mutates past runs.

Extra run state: `loop_id`, `loop_trigger_id`, `trigger_context`, plus the loop's `runtime_adapter` / `model` / `reasoning_effort` (the plumbing TaskAutomation never did).

Idempotency: per-fire dedup keyed on the trigger workflow id (existing pattern) plus GitHub delivery GUID for webhook fires.
Overlap: before creating a task, check for an active run on the loop and apply `overlap_policy`.
Cleanup: loop tasks are soft-deleted by a retention sweep (default: keep the latest 200 per loop) so hourly loops don't grow unbounded task rows.

### Workspace (multi-repo)

Target design: one sandbox, N repos.

- `Task.repository` (single string) grows a sibling `Task.repositories` (list). Existing single-repo behavior unchanged.
- Sandbox provisioning clones every repo into the existing layout `/tmp/workspace/repos/{org}/{repo}` (the layout and `SandboxSnapshot.repos` already support N).
- agent-server (in `PostHog/code`, `packages/agent`) accepts a workspace root + repo manifest instead of a single `--repositoryPath`.
- Branch naming is shared across repos: `loop/{loop-slug}/{run-shortid}`.
- The agent opens one PR per repo it actually touched; each lands in `TaskRun.output.prs[]` (superset of today's `output.pr_url`).
- CI watch (`get_pr_context`) iterates all open PRs of the run.

Snapshot warming applies per repo-set, reusing the existing `SandboxSnapshot` machinery.

### Connectors (MCP)

Reuse both existing mechanisms, no new connector model:

- MCP Store installations (`MCPServerInstallation`, team + user scoped): the loop stores installation ids, validated against `get_active_installations(team_id, loop.created_by_id)` on save. At run boot they resolve to proxy URLs exactly like interactive runs do today.
- PostHog MCP: injected as today, with scopes from `loop.connectors.posthog_mcp_scopes`. This fixes the current automation default of hardcoded `read_only` by making it explicit and configurable.

Slack and email as loop outputs (e.g. "post the summary to #standup") are just MCP connectors from the agent's point of view. Notification delivery (below) is separate, deterministic plumbing.

### Behaviors

- `create_prs=false`: report-only loop; sandbox still clones repos (read access) but the signed-commit tool and PR flow are disabled.
- `watch_ci` / `fix_review_comments`: enables the existing in-workflow CI follow-up loop for loop runs, bounded by `max_fix_iterations`.
- Phase 2 of babysitting: after the run's workflow ends, `pull_request` / review-comment webhooks that match a loop-created open PR (matched by `output.prs[]`, same mechanism as today's webhook backstop in `products/tasks/backend/webhooks.py`) spawn a follow-up run on the same loop with the PR context. Bounded by the same iteration cap, recorded on the run chain.

### Notifications

A new dispatcher module `products/tasks/backend/loop_notifications.py`, modeled on `push_dispatcher.py` and `products/approvals/backend/notifications.py`:

- push: `send_user_push.delay(...)` to the loop creator (Expo tokens already registered by the mobile app)
- email: `EmailMessage` (new Customer.io template `loop_run_summary`)
- Slack: `chat_postMessage` to the configured integration + channel
- in-app: `create_notification(...)` always, cheap and useful

Hooks: run terminal status (the existing `update_automation_run_result` seam) and PR events from the webhook handler.
Per-channel event filters from `loop.notifications`. Redis cooldown per (loop, event kind) to avoid storms.

## Data model (Django, `products/tasks/backend/models.py`)

```
Loop            team FK, created_by FK, name, description, instructions,
                runtime_adapter, model, reasoning_effort,
                repositories JSON, enabled, overlap_policy,
                behaviors JSON, connectors JSON, notifications JSON,
                last_run_at, last_run_status, last_error,
                consecutive_failures, created_at, updated_at, deleted

LoopTrigger     loop FK, type (schedule|github|api), enabled,
                config JSON (validated per type),
                last_fired_at, created_at, updated_at
```

Both team-scoped (fail-closed manager per repo conventions).
JSON config fields are validated by serializers/pydantic, not free-form.
Task changes: `loop` FK (nullable), `repositories` list (sibling of the legacy single `repository`), a `loop` value on `OriginProduct` and `internal=True` on loop-spawned rows.
`TaskAutomation` is deleted, not migrated (see Takeover).

## API surface (DRF, `/api/projects/:team_id/loops/`)

- `loops/` CRUD (list, retrieve, create, partial_update, destroy)
- `loops/:id/run/` manual fire (session auth), returns the created run
- `loops/:id/trigger/` external fire (PSAK auth), body becomes run context
- `loops/:id/runs/` run history (TaskRuns across the loop's spawned tasks)
- triggers managed inline on the loop serializer (nested create/update) to keep the client simple

All serializers carry `help_text` and schema annotations so the generated OpenAPI feeds three consumers: the PostHog Code api-client, MCP tools and docs.
Follow `/improving-drf-endpoints` and regenerate with `hogli build:openapi`.

### API trigger auth

Decision: project secret API keys (`phs_...`) with a `loop:trigger` scope, per the existing PSAK pattern.
Revocable, project-scoped, user-less, and the throttle story already exists.
Alternative considered and rejected: per-trigger bespoke secrets (more objects to manage, new auth code path).

## GitHub event triggers: infrastructure changes

1. Generalize `posthog/urls.py::github_webhook` from the hardcoded 3-way `if/elif` into a small registry: `event_type -> [handlers]`. Existing consumers (conversations, tasks PR backstop, installation lifecycle) register the same way Loops does. Signature verification, JSON parse and installation resolution stay shared, done once.
2. Loops handler: resolve installation id to teams, match enabled `LoopTrigger(type=github)` rows on `(repository, event, filters)`, fire each match. Matching is consumer-side filtering, same as conversations' repo allowlist does today; GitHub App webhooks cannot be scoped per repo on GitHub's side.
3. Ops prerequisite: the GitHub App's subscribed event list is an app-level setting on github.com. Today it effectively covers `installation`, `issues`, `issue_comment`, `pull_request`. Any additional trigger event (e.g. `push`, `release`, `workflow_run`) needs the App settings updated before GitHub will deliver it. Track as a launch checklist item; v1 trigger events limited to what the App already receives plus `push`.
4. Dedup on the `X-GitHub-Delivery` GUID so redeliveries don't double-fire.

## Natural language creation (MCP)

No local MCP server needed. The remote PostHog MCP is the right surface:

- `products/tasks/mcp/tools.yaml` already scaffolds automation tools (all `enabled: false`). Once the loops API exists, expose `loops-list`, `loops-retrieve`, `loops-create`, `loops-partial-update`, `loops-destroy`, `loops-run-create` with proper scopes and descriptions, then `hogli build:openapi`.
- Every PostHog Code cloud session already gets the PostHog MCP injected, so "make me a loop that posts failing CI summaries to Slack every morning" works from a task chat, from Claude, from anything speaking MCP.
- Caveat: background/automation sandbox runs currently get read-only PostHog MCP scopes, so a loop could not create other loops unless its `posthog_mcp_scopes` is `full`. Interactive sessions get write scopes and are the primary NL-creation surface.

## Frontend (PostHog Code repo)

All UI lives in `PostHog/code`. Nothing is added to posthog `frontend/`.

Desktop (`apps/code` + `packages/ui`):
- New top-level "Loops" sidebar item (peer of Tasks/Agents), with list, detail (config + run history) and a create/edit form.
- Reuse: prompt composer patterns from `task-detail`, model selection from `AgentModelConfig` / `cloudRunOptions`, repo picker (extended to multi-select), MCP attach via `useMcpConnect` + `AddCustomServerDialog` + `ToolPermissionList`, Slack channel picker from existing settings sections, `NotificationBus` for local surfacing of loop events.
- Consume the generated `packages/api-client` types (note: `apps/code/scripts/update-openapi-client.ts` has a stale `OUTPUT_PATH`; fix when regenerating).
- Trigger editor mirrors the Claude Code pattern: Schedule / GitHub event (repo select first) / API (shows endpoint + key instructions).

Mobile (`apps/mobile`):
- Evolve the existing automation screens into Loops: keep `ScheduleEditor` and the form skeleton, add trigger list, model picker, connectors and notification toggles.
- Push notification plumbing already done (token registration, deep links).

## Security and guardrails

- Loop runs execute as `created_by` for GitHub authorship and MCP identity. If the creator is deactivated or loses access, the loop auto-pauses and notifies.
- Cloud usage limit gate (same check as `TaskViewSet.run`) applies to every fire.
- Per-loop rate limits: default cap of 100 runs/day, API trigger throttled per key, webhook fires deduped by delivery GUID.
- Auto-pause after N consecutive failures (default 5) with a notification.
- Trigger payloads and webhook bodies are data, not instructions: rendered fenced, size-capped, never interpolated into system context.
- Sandbox egress, git-guard signed commits and network policy (`SandboxEnvironment`) apply unchanged.

## Takeover of TaskAutomation

TaskAutomation (PR #52752) is unused: it gets taken over outright, with no data migration and no compat shim.

1. Delete the `TaskAutomation` model, the `task_automations/` API and MCP tool scaffolding, and the mobile screens that call it; loops replace them.
2. Reuse the worthwhile parts under new names: `automation_service.py` becomes `loop_service.py` (Temporal Schedule create/update/pause/delete plus the run-now path), the `run-task-automation` workflow becomes `run-loop` and its per-fire idempotency pattern carries over per trigger.
3. Any stray `task-automation-*` Temporal Schedules are deleted on deploy.
4. `origin_product=automation` stays in the enum for historical rows; new runs use `loop`.

Note: the tasks execution engine is mid-migration (`task_management` / `execute_sandbox` workflows exist but are unregistered; `process_task` is slated for deletion). Loops must integrate only through the facade entry points (`execute_task_processing_workflow`, run creation on the backing task), never against workflow internals, so the engine swap does not touch loops.

## Phasing

1. **Schema + API**: `Loop`, `LoopTrigger`, serializers, TaskAutomation takeover, model pinning plumbed into run state, task-per-firing with `internal` visibility. Schedule triggers ported. Manual run.
2. **API trigger + notifications**: PSAK-scoped trigger endpoint, notification dispatcher (push, email, Slack, in-app), auto-pause guardrails.
3. **GitHub event triggers**: webhook registry refactor, trigger matching, delivery dedup, App event-subscription ops.
4. **MCP surface**: connectors config on the loop, scoped PostHog MCP, enable `loops-*` tools for NL creation.
5. **Multi-repo workspace**: `Task.repositories`, multi-clone provisioning, agent-server workspace manifest (code repo), per-repo PRs, CI watch across PRs.
6. **PR babysitting phase 2**: webhook-driven follow-up runs on loop-created PRs after the original workflow ends.

Desktop and mobile UI track phases 1-4 in the code repo in parallel.

## Decided

1. TaskAutomation is taken over wholesale: renamed/reused where worthwhile, deleted otherwise. No migration, no shim.
2. Multi-repo: one sandbox, N repos, coordinated changes, one PR per touched repo.
3. Each firing creates a fresh internal Task attached to the loop; loop tasks are hidden from personal task lists and surfaced only through the loop UI.
4. API triggers authenticate with project secret API keys (`loop:trigger` scope).

## Open questions

1. Naming: `Loop` / `LoopTrigger` as model names under the tasks app; API resource `loops`. Any collision concerns or preference for `TaskLoop`?
2. Retention: is soft-deleting beyond the latest 200 tasks per loop the right default?
3. GitHub App events: which additional event types to subscribe the App to at launch (`push` seems certain; `release`, `workflow_run`, `check_suite` on demand)?
