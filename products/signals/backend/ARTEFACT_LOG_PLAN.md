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
- **`log` artefacts** record discrete work — `code_reference`, `code_diff`, `line_reference`,
  `commit`, `task_run`, `note`. They accumulate and are addressable by UUID (update/delete).
- `signal_finding` is keyed by `(report, content.signal_id)` (latest per signal wins); `dismissal`
  entries stack. Both have dedicated appenders.

### Unified content schemas

`artefact_schemas.py` is the canonical, pydantic-only home of **every** content shape, collected
in `ARTEFACT_CONTENT_SCHEMAS` (one schema per `ArtefactType`; a test asserts exact coverage).
`validate_artefact_content(type, content)` is the single write gate — called by the model helpers
and the API serializers. Validation is a gate, not a rewrite: forward-compatible extra keys are
preserved. Reads stay legacy-tolerant — old rows are never re-validated.

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

### Task↔report association (`SignalReportTask`)

A plain, unlabelled link (unique per `(report, task)`). The legacy `relationship` column is
nullable, no longer read or written; the column drop is a follow-up migration. Purpose is derived
from `task_run` artefacts: the built-in pipeline writes `product="signals"` with `type` in
`{research, implementation, repo_selection}` (`TASK_RUN_TYPE_*` constants); custom agents supply
their own `identifier()` pair.

- **Auto-start idempotency** (`auto_start.py`): "implementation already started" :=
  an implementation `task_run` artefact exists (`has_signals_task_run`), checked and written
  inside the report-row `select_for_update` transaction so concurrent evaluations can't double-start.
  The manual "start implementation" path (tasks API with a `signal_report`) writes the same artefact.
- **`implementation_pr_url`** is the newest PR produced by any associated task's runs.
- **Free-form association**: `POST /signals/reports/{id}/tasks/` associates a task (body `task_id`,
  defaulting to the header — "associate me"); idempotent. The reports list accepts `?task_id=` so an
  agent (or the commit hook) can find the reports a task works against.

## Write surface

`SignalReportArtefactViewSet`: POST / PATCH / DELETE for log artefacts (per-type schema
validation; status types 400), the bespoke `suggested_reviewers` PUT, and the commit `diff`
action. All gated by `scope_object = "task"` (`task:write`).

MCP tools (`products/signals/mcp/tools.yaml`): `inbox-report-artefacts-create` / `-update` /
`-delete`, `inbox-report-tasks-create`, plus the read tools. Sandbox agents reach the write tools
via the `signals_report` MCP preset (`posthog/temporal/oauth.py`) — scope-wise identical to
`read_only`, but `has_write_scopes` reports True so read-only mode doesn't strip the
`task:write`-gated tools. Used by auto-started implementation tasks, the research sandbox, and
signal-report runs started from the API.

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
- A tool-surface review of everything `task:write` exposes under the `signals_report` preset.
