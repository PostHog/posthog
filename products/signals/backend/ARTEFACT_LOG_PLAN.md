# Signal report artefacts: an attributed, validated "log of work done"

> Status: design doc for the artefact-log work shipped in this PR. Folds into
> `products/signals/ARCHITECTURE.md` (and is removed) once shipped.

## Why

A `SignalReportArtefact` used to be a write-once snapshot owned by the pipeline. Artefacts are
now an **append-only log of the work done on a report** — so a signal report reads as a living
document: the evidence the research agent gathered, the commits it pushed, the task runs that
executed, and free-form notes, accumulating over time. Three properties hold for every new row:

1. **Validated** — content matches a per-type schema, enforced on the write path.
2. **Attributed** — every write declares who produced it: a user, a task, or (explicitly) the system.
3. **Unlabelled associations** — tasks are simply _associated_ with reports; a task's purpose is
   derived from the artefacts it produced, not stored on the link.

## Data model

`SignalReportArtefact` (`models.py`): `team`, `report`, `type`, `content` (JSON text),
`created_at`, `updated_at` (nullable, `auto_now`), and the attribution columns
`created_by` (FK `posthog.User`, `SET_NULL`) and `task` (FK `tasks.Task`, `SET_NULL`).
Legacy rows carry NULLs in both attribution columns.

### Two kinds of artefact: `status` and `log`

Everything is append-only; the sets classify what an entry _means_:

- **`status` artefacts** describe the report's current state — `safety_judgment`,
  `actionability_judgment`, `priority_judgment`, `repo_selection`, `suggested_reviewers`.
  Each (re)assessment appends a row; the current status is the latest row of that type.
- **`log` artefacts** record discrete work — `code_reference`, `line_reference`,
  `commit`, `task_run`, `note`. They accumulate and are addressable by UUID (update/delete).
- `signal_finding` is keyed by `(report, content.signal_id)` (latest per signal wins); `dismissal`
  entries stack. Both have dedicated appenders.

### Unified content schemas

`artefact_schemas.py` is the canonical, pydantic-only home of **every** content shape, collected
in `ARTEFACT_CONTENT_SCHEMAS` (one model per `ArtefactType`; a test asserts exact coverage). Raw
payloads become typed models once, at the boundaries — `parse_artefact_content(type, content)`
for API writes and reads that consume stored rows — and everything in between passes the model
around; the model helpers derive a row's type from the content model's class
(`artefact_type_for`) and store `model_dump_json()`, so a type can never mismatch its content.
Reads of legacy rows stay tolerant — parse failures are skipped or degraded, never raised.

The judgment models (`SignalFinding`, `ActionabilityAssessment`, `PriorityAssessment`) double as
LLM output schemas; `report_generation/research.py` re-exports them. `RepoSelection` mirrors the
tasks-product `RepoSelectionResult` (no cross-product import; a parity test guards drift).

### Attribution

`ArtefactAttribution` (`models.py`) is a required kw-only argument on every write helper
(`append_status` / `add_log` / `append_finding` / `append_dismissal`), with exactly three kinds:
`from_user(user_id)` | `from_task(task_id)` | `system()`. No write site can silently skip it.

| Writer                                                     | Attribution                                                                          |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| API writes (artefact CRUD, reviewers PUT, dismissals)      | the `X-PostHog-Task-Id` header's task when present, else `request.user`              |
| Agentic research pipeline (findings, judgments, reviewers) | the research sandbox task (`ReportResearchOutput.research_task_id`)                  |
| Repo selection                                             | the selection sandbox task when one ran (`RepoSelectionResult.task_id`), else system |
| Custom agents                                              | their `MultiTurnSession` task                                                        |
| Safety judge, Slack dismissals                             | system                                                                               |
| `task_run` artefacts                                       | always the task they record (derived in `task_run_artefacts.py`)                     |

**Deterministic task identity for agents:** sandbox provisioning bakes the agent's task id into
an `X-PostHog-Task-Id` header on its MCP config (`get_sandbox_ph_mcp_configs`); the MCP server
forwards it on every API call (`services/mcp/src/lib/request-properties.ts` → `api/client.ts`).
The LLM never handles its own task id. The header is attribution metadata, not an authorization
boundary — the token is team-scoped and the named task must belong to the same team.

### Commits, not branches

Agents push exclusively through the `git_signed_commit` tool (raw `git push` is blocked), so the
agent harness records one `commit` artefact (`{repository, branch, commit_sha, message, note?}`)
per pushed commit per associated report, automatically, after each successful signed-commit push.
The artefact viewset's `diff` action renders a commit's unified diff on demand via
`GitHubIntegration.get_commit_diff` (single-commit GitHub API, `diff` media type, 1 MB cap).

### Task↔report association: `task_run` artefacts

There is no link table in use — a `task_run` artefact IS the association (its `task` attribution
FK is always the task it records). The built-in pipeline writes `product="signals"` with `type`
in `{research, implementation, repo_selection}` (`TASK_RUN_TYPE_*` constants); custom agents
supply their own `identifier()` pair; free-form associations default to `tasks/agent_run`.

- **Associate via the artefact endpoint**: POST a `task_run` artefact — `content.task_id`
  defaults to the `X-PostHog-Task-Id` header ("associate me"), `product`/`type` default to
  `tasks`/`agent_run`, the named task must belong to the team, attribution is always the
  recorded task, and re-associating an already-linked task is idempotent (returns the existing
  entry). The reports list accepts `?task_id=` (artefact-derived) so an agent or the commit hook
  can find the reports a task works against.
- **Auto-start idempotency** (`auto_start.py`): "implementation already started" :=
  `SignalReport.implementation_task` is set — a real gate column, checked and written inside the
  report-row `select_for_update` transaction so concurrent evaluations can't double-start. The
  gate deliberately does NOT key on the artefact log: task_run artefacts are freeform and
  API-mutable (any agent can append or delete them), so they can't carry a spend-controlling
  decision. Both writers (auto-start and the manual tasks-API path) go through
  `record_implementation_task`, which compare-and-sets the column and appends the `task_run`
  work-log artefact.
- **`implementation_pr_url`** is the newest PR produced by any associated task's runs
  (artefact-derived, both in the viewset annotation and `implementation_pr.py`).
- `SignalReportTask` is deprecated: no longer read or written; `backfill_task_run_artefacts`
  converts any remaining rows (labelled → `signals/<type>`, unlabelled without an artefact →
  `tasks/agent_run`); the table drop is a follow-up migration.

## Write surface

`SignalReportArtefactViewSet`: POST / PATCH / DELETE for artefacts of **any** type — no type is
writer-restricted ("status" vs "log" classifies semantics, not ownership). POST routes through
`SignalReportArtefact.append`, which dispatches to the type's append semantics (status →
latest-wins, finding → keyed by signal_id, dismissal → stacking, log → accumulate); PATCH edits
in place (an edit to the latest status row changes the canonical status); DELETE of the latest
status row reverts the canonical status to the previous version. Per-type schema validation
everywhere, plus the bespoke `suggested_reviewers` PUT (reviewer enrichment) and the commit
`diff` action. All gated by `scope_object = "task"` (`task:write`).

Custom agents queue artefacts of any type during a run via `CustomSignalAgent.register_artefact`
(`commit` and `task_run` never need registering — they're written by the signed-commit hook and
report persistence respectively). Queued entries are validated against their type's schema at the
call site and persisted in the same transaction as the report, attributed to the agent's task;
status types route through their latest-wins append semantics.

MCP tools (`products/signals/mcp/tools.yaml`): `inbox-report-artefacts-create` / `-update` /
`-delete`, `inbox-report-tasks-create`, plus the read tools. Implementation sandboxes
(auto-started tasks and signal-report runs started from the API) run with `full` scopes, so the
write tools are available for logging their work on the report. The research sandbox runs plain
`read_only`: it can list artefacts but never writes them via MCP — the pipeline persists its
artefacts deterministically from the session's structured outputs, and the harness records commit
artefacts via the direct API (the token's `task:write` scope is internal and preset-independent).

## Backfill

`backfill_task_run_artefacts` converts legacy `SignalReportTask` rows (which carry the old
relationship label) into `task_run` artefacts, attributed to their task and backdated to the
link's `created_at`; idempotent; rows without a legacy label are skipped (their artefact was
written at creation time).

## Guardrails

- `_AGENTIC_ARTEFACT_TYPES ∩ LOG_ARTEFACT_TYPES == ∅` (tested) — re-promotion never touches log entries.
- All writes funnel through `SignalReportArtefact._create_validated` — no unvalidated or
  unattributed row is constructible via the helpers.
- Reads stay generic (`json.loads`, tolerant parsing) for legacy rows.
- Attribution FKs are `SET_NULL`: deleting a user/task degrades attribution rather than
  destroying the report's work log.

## Out of scope (future work)

- Dropping the `relationship` column (and the redundant `signals_sig_report_type_idx`) once the
  rolling deploy completes.
- Commit artefacts for `git_signed_rewrite` (force-push rewrites).
- Tightening the implementation sandbox's `full` MCP scopes to a narrower write surface.
