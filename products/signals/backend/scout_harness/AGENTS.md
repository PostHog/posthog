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
  filtered by skill so a specialist only sees its own past work.
- `skill_loader.py`
  Resolves `signals-scout-*` skills from the team's `LLMSkill` rows. Defines
  `SIGNALS_SCOUT_SKILL_PREFIX` and `LoadedSkill` (body + version + allowed_tools).
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
- `serializers.py`
  DRF serializers for the harness HTTP surface (runs, scratchpad, project profile).
  Annotated for drf-spectacular so the generated MCP tools have informative schemas.
- `views.py`
  `SignalScoutRunViewSet`, `SignalScoutConfigViewSet`, `SignalScratchpadViewSet`,
  `SignalProjectProfileViewSet`.
  Routed under `environment_signals_scout_*` basenames in `posthog/api/__init__.py`
  and exposed as `signals-scout-*` MCP tools via `products/signals/mcp/tools.yaml`.
  The config viewset is the no-wait creation path: `create` registers (upserts) a
  config for an already-authored skill with its schedule/emit posture in one call.
  `list` is strictly read-only (its MCP tool is annotated `readOnly`) — it never
  mints config rows.

## Mental model

`arun_signals_scout()` is the main entrypoint. One call → one `SignalScoutRun` row →
one sandbox session → zero or more emitted signals.

- The harness inserts the bridge row at the start of a run (inside `_spawn_and_run`).
  `SignalScoutRun` is now a thin bridge to a Tasks `TaskRun` — run status / timing / error
  live on `task_run`, not on the bridge row. Single-flight is a best-effort app-layer guard:
  `_has_running_run` skips dispatch when a prior run for the same `(team, skill_name)` has
  `task_run.status = IN_PROGRESS`. The old `WHERE status='running'` partial unique index was
  dropped in the bridge simplification; a `task_run.status`-based constraint plus active
  stale-run recovery (`_self_heal_stale_runs` is a no-op today) is a tracked follow-up.
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
  per-scout schedule (`run_interval_minutes`, default hourly) is due, most-overdue
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
  `TaskRun` stranded in `IN_PROGRESS` (worker SIGKILL before finalize) blocks new runs for
  that `(team, skill)` via `_has_running_run` until it transitions out; active recovery of
  such rows is a deferred follow-up (`_self_heal_stale_runs` is currently a no-op).
- Emit path goes through `emit_signal()` and only `emit_signal()`. Do not write to
  the embeddings pipeline or `SignalReport` directly from harness code.
- **If you add or rename a workflow/activity in `temporal/agentic/`, update
  `posthog/temporal/tests/ai/test_module_integrity.py` (`TestSignalsProductModuleIntegrity`)
  to match.**
- **If you change the harness layout or tool surface, update this file to match.**
