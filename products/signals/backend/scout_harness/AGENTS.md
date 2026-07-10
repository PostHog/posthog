# Signals Agent Harness

This directory contains the headless **Signals agent** — a scheduled scout that explores
a project, writes durable scratchpad entries across runs, and emits findings into the
Signals inbox via `emit_signal()` using the `signals_scout` source variant.

It is the second agentic surface in Signals. The other one — `report_generation/` — runs
on demand when a `SignalReport` is promoted to `candidate` and produces a single research
output for one report. The harness here is the inverse: it runs on a schedule, decides
_what_ to investigate from scratch, and pushes new signals into the same pipeline rather
than acting on existing ones.

In production it is driven by `SignalsScoutCoordinatorWorkflow` (periodic tick every
`COORDINATOR_INTERVAL_MINUTES = 30` → fan out per-(team, skill) child workflows). Locally
it is exercised via the `run_signals_scout` management command (see `../management/AGENTS.md`).

## What lives here

- `runner.py`
  Per-run entrypoint (`arun_signals_scout` / `run_signals_scout`). Inserts the
  `SignalScoutRun` row, builds the prompt + toolset, spawns the sandbox session,
  pumps the agent loop until budget exhaustion or natural completion, finalizes the run,
  and returns a `RunResult`. The activity wrapper in `temporal/agentic/scout_scheduler.py`
  delegates straight to this.
- `prompt.py`
  Assembles the system prompt: persona + skill body + relevant scratchpad entries +
  project profile inventory + recent run summaries. Scratchpad and run history are
  filtered by skill so a specialist only sees its own past work. `build_run_prompt`
  forks on the run's channel via `skill_loader.skill_uses_report_channel`: a scout that
  opted into the report channel gets the report persona + report-authoring guidance
  (search the inbox first, edit before authoring a duplicate, set `suggested_reviewers`
  to route the report); every other scout gets the signal persona that fires weak
  `emit_signal` findings. The bootstrap, scratchpad, recency, and close-out sections
  are shared between both. The report persona is further gated per-tool: it names only
  the report tool(s) actually in `allowed_tools` (emit-only, edit-only, or both), and
  drops the author-time sections for an edit-only scout — the report endpoints fail
  closed on the exact tool, so the prompt must never steer a scout toward one it lacks.
  Orthogonal to the channel fork, the prompt also forks on the skill's origin
  (`LoadedSkill.origin`, resolved via `lazy_seed.scout_skill_row_origin`): a _custom_ scout —
  hand-authored, or a seeded canonical row the team has since edited in place (diverged) —
  gets a self-improvement section inviting evidence-backed `improve:<skill-name>:<topic>`
  scratchpad suggestions for its own skill body, which the owner reviews via the
  `exploring-scouts` / `authoring-scouts` meta skills. When such a scout also holds report
  tools, the section additionally invites escalating recurring or material suggestions as
  inbox reports about the scout itself (titled `Scout self-improvement: <skill-name> – <topic>`,
  `NO_REPO`, `requires_human_input`), authored/edited with the report tools it already holds
  and pointed to by the `report_id` stashed in the `improve:` entry — so self-improvement
  suggestions reach the owner through the inbox like any other report, with no extra scope or
  endpoint (the same per-tool fail-closed gating applies: an emit-only scout is never pointed
  at `edit_report`, and a signal-channel custom scout keeps the scratchpad-only path). A
  pristine canonical scout never sees
  it — applying such a suggestion would mark the seeded row diverged and cut it off from
  upstream sync; canonical-skill defects route upstream via the operational-friction
  (`agent-feedback`) section instead.
- `skill_loader.py`
  Resolves `signals-scout-*` skills from the team's `LLMSkill` rows. Defines
  `SIGNALS_SCOUT_SKILL_PREFIX` and `LoadedSkill` (body + version + allowed_tools + origin), plus
  `REPORT_CHANNEL_TOOLS` / `skill_uses_report_channel` — the shared report-channel opt-in
  predicate the runner (scope posture) and prompt builder (persona fork) both resolve from.
- `lazy_seed.py`
  Canonical skill sync. Reads `products/signals/skills/signals-scout-*/` from disk and
  reconciles them against the team's `LLMSkill` rows: creates missing rows, updates
  ones the team hasn't edited, leaves diverged / hand-authored rows alone, tombstones
  rows whose canonical skill was deleted. Only rows tagged
  `metadata.seeded_by="signals_scout_harness"` are ever updated. Called both lazily
  (coordinator tick, runner cold-start) and explicitly via the `sync_signals_scout_skills`
  management command.
- `config_registry.py`
  `register_missing_configs(team_id)` — auto-creates an enabled, default-schedule
  `SignalScoutConfig` for any `signals-scout-*` skill lacking one ("author a skill, get a
  scout"). Called by the coordinator tick; the HTTP surface registers explicitly via the
  write-scoped config `create` endpoint instead (reads stay side-effect free).
- `tools/`
  Implementations of the four harness-internal tools the agent calls during a run.
  The effective toolset for a run is the intersection of the skill's `allowed_tools`
  list with what `tools/__init__.py` re-exports — there is no separate registry
  module today.
  - `emit.py` — `emit_signal_*` tools that push findings as `cross_source_issue`
    signals into the standard ingestion pipeline.
  - `scratchpad.py` — `remember`, `forget`, and `search_scratchpad` tools backed by
    the `SignalScratchpad` model.
  - `profile.py` — `project_profile_*` tools that read the deterministic
    `SignalProjectProfile` snapshot.
  - `runs.py` — `runs_*` tools that read past `SignalScoutRun` rows for dedupe and
    cross-skill awareness.
- `profile/`
  - `builders.py` — deterministic builders that compute the inventory payload for
    `SignalProjectProfile`. Sections fall into three layers: capability / configured
    (sticky — `products_in_use`, `integrations`, `external_data_sources`,
    `signal_source_configs`, …), aggregated recency (`recent_activity` — per-scope
    counts off the activity log, cross-cutting orientation across every entity type),
    and per-entity recent inventory (`recent_surveys`, `recent_feature_flags`,
    `recent_experiments`, `recent_alerts`, `recent_hog_functions`, `recent_hog_flows`,
    `recent_notebooks`, `recent_cohorts`, `recent_actions`, `recent_dashboards`,
    `business_knowledge`).
    Per-entity sections are deliberately light (counts + 5 most-recent items with
    name, status, timestamp); deep drilldowns go via the per-entity MCP list tools.
    See the module docstring at `profile/builders.py` for the authoritative section
    list — when adding or renaming a section, bump `INVENTORY_SOURCE_VERSION` so
    the cache invalidates cleanly.
- `limits.py`
  Runtime ceilings as module constants: `DEFAULT_MAX_RUNTIME_S` (per-run budget),
  `ACTIVITY_SLACK_S`, and `WORKFLOW_HARD_CEILING_S` (`= DEFAULT_MAX_RUNTIME_S +
ACTIVITY_SLACK_S`, the activity-level ceiling that gates the workflow's
  `start_to_close_timeout`).
- `team_limits.py`
  Single source of truth for a team's effective scout caps + metadata, resolved from the
  `signals-scout` flag payload in one read. The same three-layer cap resolution
  (`team_configs[team]` → `default_team_config` → code constant) the coordinator enforces at
  dispatch, plus enrollment (`_parse_enrollment` → `guaranteed_team_ids` / `skip_team_ids`, with a
  cloud/dev-gated fallback) and the editorial banner string. `guaranteed_team_ids` may contain the
  `"*"` wildcard (`ENROLL_ALL_TOKEN`): with it, enrollment inverts from an explicit allowlist to
  "every team that has enabled scout configs" — the self-serve gate, where the product-autonomy-
  gated UI creates the configs; explicit ids alongside `"*"` are still force-provisioned and
  `skip_team_ids` still hard-excludes. The global per-tick ceiling is flag-tunable too
  (`_resolve_global_max_runs_per_tick` ← `max_runs_per_tick_global`, default `MAX_RUNS_PER_TICK`).
  Kept free of the temporalio stack so it stays cheap to import on the API path; both the
  coordinator and the metadata endpoint import from here so the reported caps never drift from what
  dispatch allows. `resolve_team_metadata()` backs the metadata viewset;
  `seed_config_layers_for_team()` lets the on-demand `sync` endpoint seed the same launch posture.
- `serializers.py`
  DRF serializers for the harness HTTP surface (runs, scratchpad, project profile).
  Annotated for drf-spectacular so the generated MCP tools have informative schemas.
- `views.py`
  `SignalScoutRunViewSet`, `SignalScoutConfigViewSet`, `SignalScratchpadViewSet`,
  `SignalProjectProfileViewSet`, `SignalScoutMetadataViewSet`, `SignalScoutMembersViewSet`.
  Routed under `environment_signals_scout_*` basenames in `posthog/api/__init__.py`
  and exposed as `signals-scout-*` MCP tools via `products/signals/mcp/tools.yaml`.
  `SignalScoutMembersViewSet` (`signals-scout-members-list`) is the reviewer-routing roster:
  it returns the project's members (those with access to the team) with `user_uuid` / `email` /
  `github_login` so a report-channel scout can populate `suggested_reviewers` at cold start. The roster
  is member PII the scout needs to route, gated on the internal `signal_scout_internal` scope object
  (`scope_object = "signal_scout_internal"`, default `list` → `signal_scout_internal:read`, satisfied by
  the sandbox token's `…:write`) — so, like `emit-signal`, it is reachable only inside a scout run and
  never enters a customer's public MCP catalog. (The narrower `signal_scout_report` scope was considered
  but is transient — kept only while emit-signal and emit-report coexist — so the durable tool stays on
  `signal_scout_internal`.) Membership is resolved server-side via
  `report_generation/resolve_reviewers.list_project_members` (through `Team.all_users_with_access()`,
  so private-project access control is honored), the project-nested path that the org-nested
  `org-members-list` tool (stripped + 403'd for a scoped-team token) can't provide.
  The config viewset is the no-wait creation path: `create` registers (upserts) a
  config for an already-authored skill with its schedule/emit posture in one call.
  `list` is strictly read-only (its MCP tool is annotated `readOnly`) — it never
  mints config rows. The metadata viewset is the read-only `scout/metadata/current/`
  endpoint that reports enrollment + banner + enforced limits via
  `team_limits.resolve_team_metadata`.

## Mental model

`arun_signals_scout()` is the main entrypoint. One call → one `SignalScoutRun` row →
one sandbox session → zero or more emitted signals.

- The harness inserts the bridge row at the start of a run (inside `_spawn_and_run`).
  `SignalScoutRun` is now a thin bridge to a Tasks `TaskRun` — run status / timing / error
  live on `task_run`, not on the bridge row. Single-flight is a best-effort app-layer guard:
  `_has_running_run` skips dispatch when a prior run for the same `(team, skill_name)` has
  `task_run.status = IN_PROGRESS`. The old `WHERE status='running'` partial unique index was
  dropped in the bridge simplification; `_self_heal_stale_runs` now reaps the orphan case at
  the app layer (failing any `QUEUED`/`IN_PROGRESS` run older than `STALE_RUN_CUTOFF_S` before
  the guard), so a worker crash no longer wedges a lane permanently. A `task_run.status`-based
  DB constraint is still a possible follow-up for stronger single-flight guarantees.
- The sandbox is opened with the team's MCP token plus the harness-internal tools.
  The skill body is loaded into the system prompt; each scout has its own
  `SignalScoutConfig` row (keyed on `(team, skill_name)`) whose `enabled` flag and
  `run_interval_minutes` schedule the coordinator's per-scout due-check honors.
- `MultiTurnSession.start()` creates a Tasks `(Task, TaskRun)` pair to drive the
  sandbox. The bridge row links to its `TaskRun` via a `OneToOne` FK (`task_run`), created
  by the `on_task_run_created` hook before the agent's first turn — this powers the
  `task_url` deep-link on the run serializers
  (`/project/{team_id}/tasks/{task_id}?runId={task_run_id}`) and is the join key for the
  LLM-analytics token / cost roll-up. Failure context (status, error, full chat log via
  LLMA) lives on the `TaskRun`; the harness persists no run state on the bridge row.
- Each run emits scout-owned lifecycle analytics events (best-effort, keyed on the team):
  `signals_scout_run_started` (the run cleared the guards and a TaskRun exists),
  `signals_scout_run_finished` (terminal: `completed`/`failed`/`cancelled` + runtime + emit
  count), and `signals_scout_run_reaped` (a stranded orphan was reaped by
  `_self_heal_stale_runs`). They join on `run_id`/`task_run_id` and are the event-derived
  (no-warehouse-lag) basis for throughput, stall, and worker-death alerting — a `started`
  with no `finished` is a run that died before finalize; a reaped run emits no `finished`.
- Emit happens via the harness's `emit_signal_*` tools, which call `emit_signal()`
  with `source_product="signals_scout"` and `source_type="cross_source_issue"`.
  From there the signal flows through the same emitter → buffer → grouping v2 path
  as any other source.
- Scouts do not set a per-signal `weight`. The harness pins every emitted finding to
  `SCOUT_SIGNAL_WEIGHT = 1.0` (`tools/emit.py`), so a fresh report's `total_weight`
  meets `WEIGHT_THRESHOLD` (default 1.0) on the first signal and promotes immediately.
  `weight` is the pipeline's promotion knob, not a scout judgment — promotion is
  governed by the `confidence` emit-gate (≥ ~0.65), dedupe, and the safety filter.
  The scout-facing schema and skills carry no `weight` field.
- Findings can carry `tags` — lowercase kebab-case category slugs, normalized and
  capped by `normalize_tags` in `tools/emit.py`. Tags persist in the signal's
  `extra.tags` (queryable in the signal store) and on the `SignalScoutEmission` row.
  The vocabulary lives in the scout loop, not the harness: the base prompt's
  _Tagging your findings_ section instructs each scout to maintain a
  `tags:<domain>:taxonomy` scratchpad entry (read first-move like any memory, evolved
  as categories emerge), and the emission rows are the queryable ground truth a scout
  can audit its taxonomy against. The harness only normalizes, caps, and persists.
- Scratchpad entries and run history are read at prompt assembly time. The agent can
  also write scratchpad entries mid-run via `remember` / `forget` — that's how a
  specialist with no anomalies to chase records "no LLM activity here, close out
  fast" so future runs of the same skill short-circuit cold.

## Where the rest of the system meets this directory

- **Coordinator** — `temporal/agentic/scout_coordinator.py` and `scout_scheduler.py`.
  Polls every `COORDINATOR_INTERVAL_MINUTES = 30`; dispatches each scout whose
  per-scout schedule (`run_interval_minutes`, default every 24 hours) is due, most-overdue
  first, hard cap `MAX_RUNS_PER_TICK = 50` per tick, `ScheduleOverlapPolicy.SKIP` to
  drop ticks rather than queue them.
- **Models** — `SignalScoutConfig`, `SignalScoutRun`, `SignalScratchpad`,
  `SignalProjectProfile` in `../models.py`.
- **Source variant** — `SignalSourceConfig.SourceProduct.SIGNALS_SCOUT` paired with
  `SourceType.CROSS_SOURCE_ISSUE`.
- **Scout fleet** — the `signals-scout-*` skills live at
  `../../skills/signals-scout-*/` (generalist + 7 specialists). See
  `../../skills/AGENTS.md` for the fleet convention.
- **Local commands** — `run_signals_scout` (one-shot run) and
  `sync_signals_scout_skills` (force a canonical-skill sync). Both documented in
  `../management/AGENTS.md`.

## When editing this flow

- Keep the harness loop generic. Skill-specific logic belongs in the SKILL.md of the
  scout, not in `runner.py` or `prompt.py`.
- New harness-internal tools: add the implementation under `tools/`, re-export it
  from `tools/__init__.py`, and add a corresponding scope check on the viewset in
  `views.py` so the MCP surface and the sandbox surface stay aligned.
- If you change the canonical SKILL.md format or directory layout, update
  `lazy_seed.discover_canonical_skills()` and the parser tests — the coordinator
  call to `sync_canonical_skills()` runs on every tick and silently swallows parser
  errors (logs only), so a quiet schema break can leave canonical content stale on
  every team.
- Run lifecycle lives on the linked `TaskRun` (`task_run.status`), managed by
  `MultiTurnSession` — the `SignalScoutRun` bridge row carries no status of its own. A
  `TaskRun` stranded in `IN_PROGRESS` (worker SIGKILL before finalize) would block new runs
  for that `(team, skill)` via `_has_running_run` — so `_self_heal_stale_runs` fails any such
  run older than `STALE_RUN_CUTOFF_S` before the guard, letting the lane recover within a tick
  or two instead of wedging until manual intervention.
- Emit path goes through `emit_signal()` and only `emit_signal()` — **with one sanctioned
  carve-out**: a scout that opts into the report-authoring channel (`emit_report` / `edit_report`
  in its skill's `allowed_tools`) writes a full `SignalReport` directly. That write does NOT go
  through harness code touching `SignalReport` or the embeddings pipeline itself — it goes through
  the `scout_report/` service (`create_scout_report` / `update_scout_report`), which owns the report
  row + the bound `document_embeddings` signal write (the grouping substrate, minus the matcher).
  Harness/tool code calls that service; it still never touches `SignalReport` or the embeddings
  pipeline directly. See `../scout_report/persistence.py` and the `scouts-emit-reports` spec.
  Both report-channel actions are tracked on the run as queryable columns: `emit_report` appends to
  `SignalScoutRun.emitted_report_ids` (via `_record_report_emit`), and `edit_report` appends — deduped —
  to `edited_report_ids` (via `record_report_edit`), so "which reports did this run author vs. edit?"
  is a column lookup, not an event-stream or artefact-log join. Both writes are best-effort and
  post-commit (an edit/emit never fails because its tally write did).
- **If you add or rename a workflow/activity in `temporal/agentic/`, update
  `posthog/temporal/tests/ai/test_module_integrity.py` (`TestSignalsProductModuleIntegrity`)
  to match.**
- **If you change the harness layout or tool surface, update this file to match.**
