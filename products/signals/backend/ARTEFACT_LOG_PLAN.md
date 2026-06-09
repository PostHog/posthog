# Plan: report artefacts as a living "log of work done"

> Status: planning doc for the work that extends this PR. Folds into
> `products/signals/ARCHITECTURE.md` (and is removed) once shipped.

## Why

Today a `SignalReportArtefact` is a **write-once, replaced snapshot**: the agentic
pipeline deletes and re-creates its artefact types on every run, and nothing else
writes them. We want artefacts to become an **append-but-deletable, mutable log of
the work done on a report** — so a signal report reads as a living document: the
evidence the research agent gathered, the diffs and branches it produced, the task
runs that executed, and free-form notes, all accumulating over time.

This is a fairly routine data-modeling change plus some handling of legacy data.
**Simplicity is the guiding principle — do not over-engineer.** All of the work below
ships in a single PR (this one). The UI that renders the timeline lives in the
PostHog Code app and is a separate, later change.

## Where we are today

- `SignalReportArtefact` (`products/signals/backend/models.py`): `team`, `report`
  (FK, `related_name="artefacts"`), `type` (`CharField` choices), `content`
  (`TextField` holding JSON), `created_at`. No `updated_at` — write-once.
- The agentic pipeline (`temporal/agentic/report.py`) deletes + re-creates its five
  artefact types every run (`_replace_agentic_report_artefacts`); on re-promotion
  `_load_previous_research()` reconstructs prior research by reading those rows back.
- No agent writes artefacts directly — agents return structured output and orchestrator
  Python persists the rows afterward.
- API: `SignalReportArtefactViewSet` (`views.py`) is read-only except `PUT`, which is
  allow-listed to `suggested_reviewers` **only**. It declares `scope_object = "task"`,
  so the write requires `task:write` — and `task:write` is already in `INTERNAL_SCOPES`
  (`posthog/temporal/oauth.py`), so every agent token (research / implementation /
  custom, running the `read_only` preset) already carries it.
- `SignalReportTask` (`models.py`) joins a report to a `tasks.Task` and powers the
  implementation-PR-url annotation on the report serializer.

## Design

### Two kinds of artefact: `status` and `log`

- **`status` artefacts are singletons** — at most one per `(report, type)`. They
  represent the report's current state. Existing status types: `safety_judgment`,
  `actionability_judgment`, `priority_judgment`, `repo_selection`, `suggested_reviewers`.
- **`log` artefacts are a log** — many per report, time-ordered, append-but-deletable.
  New log types: `code_reference`, `code_diff`, `line_reference`, `pushed_branch`,
  `task_run`, `note`.
- `signal_finding` is N-per-report and stays owned by the existing pipeline replace
  logic. It predates this split and is **not** reclassified here.

The split is expressed as two sets on the model (`STATUS_ARTEFACT_TYPES`,
`LOG_ARTEFACT_TYPES`) with a comment stating the singleton-vs-log contract.

### Mutability and identity

- Add `updated_at` (`auto_now`, nullable). Artefacts are now mutable.
- Artefacts are deletable — by agents (via MCP) and deterministically in code.
- Artefacts are addressed by **UUID**: create returns the new UUID; update and delete
  address by UUID.
- Singleton-ness for `status` types is **maintained in the model class**, not via a DB
  unique constraint (a `signal_finding` is N-per-report, and the pipeline's
  delete-then-recreate would make a partial-failure unique-constraint state fragile).

### Business logic lives on the model

The model class is the home for artefact business logic; the viewset and deterministic
producers stay thin and call into it:

- `SignalReportArtefact.upsert_status(*, report, team, type, content)` — enforce the
  singleton: update the existing same-type row or create one.
- `SignalReportArtefact.add_log(*, report, team, type, content)` — append a log entry.
- `update_content(content)` and a delete helper as needed.

Helpers take already-serialized `content`; the caller that holds the typed object
serializes it. **No type→schema registry and no per-type validation dispatch** — that
would over-complicate a simple change.

### Write surface

- The **viewset** gains programmatic create / update / delete actions. This is the
  surface the MCP tools wrap (and is independently useful for in-app and deterministic
  callers).
- **No new scope or preset.** Reuse `scope_object = "task"` (`task:write`) — the same
  authorization as the existing `suggested_reviewers` update, already held by agent
  tokens. The viewset's existing team-scoped `safely_get_queryset` is the access
  boundary (a foreign artefact UUID 404s; a deleted parent report is unreachable).
- The existing `suggested_reviewers` `PUT` path is **untouched** (it has bespoke
  reviewer enrichment); the new actions are additive.

### `task_run` artefacts and `SignalReportTask`

- For now, `task_run` artefacts **coexist** with `SignalReportTask`. A management
  command backfills a `task_run` artefact from each existing `SignalReportTask` row.
- The `task_run` content carries its **own** `relationship` enum
  (`signals_research`, `auto_implementation`, `repo_selection`, `custom_agent`, …) —
  intentionally distinct from `SignalReportTask.Relationship`.
- Removing `SignalReportTask` *creation* is deferred to a later PR (we keep reading it
  until the backfill has run everywhere).

## Artefact content shapes (new types)

| Type            | Content                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------ |
| `code_reference`| `{file_path, start_line, end_line, contents, relevance_note}` — a contiguous span (exists)        |
| `code_diff`     | `{file_path, diff, relevance_note}` — a unified diff for one file (exists)                         |
| `line_reference`| a single line of code (a point) for tour-style callouts — `{file_path, line, note}`               |
| `pushed_branch` | a pushed remote branch (no PR opened) used to render a full would-be PR diff in the UI            |
| `task_run`      | reference to a `tasks.Task` run with a `relationship` enum (`signals_research`, `auto_implementation`, …) |
| `note`          | free-form note authored by an agent or by code                                                    |

Schemas are simple Pydantic models, placed alongside `CodeReference` / `CodeDiff`.

## Implementation steps (this PR)

1. **Model + migration.** Add `updated_at` (nullable, `auto_now`); add the new
   `ArtefactType` values; add `STATUS_ARTEFACT_TYPES` / `LOG_ARTEFACT_TYPES` with the
   contract comment; add the `upsert_status` / `add_log` / update / delete helpers. One
   additive migration: `AddField(updated_at, null=True)` + a state-only
   `AlterField(type, choices=…)`.
2. **Content schemas.** Pydantic models for `LineReference`, `PushedBranch`,
   `TaskRunArtefact` (with the `relationship` enum), `NoteArtefact`.
3. **Viewset actions.** `create` (POST, returns UUID), `update` (PATCH by UUID),
   `delete` (DELETE by UUID) on `SignalReportArtefactViewSet`, reusing
   `scope_object = "task"`, delegating to the model helpers, with a log-type allow-list
   (non-allowed types → 400). The `suggested_reviewers` PUT stays as-is.
4. **MCP tools.** Create / update / delete tools in `products/signals/mcp/tools.yaml`
   (scopes `[task:write]`, `readOnly: false`), regenerated via the standard codegen.
5. **Backfill command.** `backfill_task_run_artefacts` converts every
   `SignalReportTask` into a `task_run` artefact; idempotent (skips a report that
   already has a `task_run` referencing that task), with `--dry-run` and `--team-id`.

## Guardrails

- `_replace_agentic_report_artefacts` must **never** widen its `type__in` to include
  `log` types — that would wipe agent work on re-promotion. A test asserts
  `_AGENTIC_ARTEFACT_TYPES ∩ LOG_ARTEFACT_TYPES == ∅`.
- No `(report, type)` DB unique constraint — singleton-ness lives in the model helper.
- Reads stay generic (`json.loads`) for back-compat; only the new write path is typed.
- `updated_at` is nullable to keep the migration a fast, rolling-deploy-safe
  `ADD COLUMN … NULL`.

## Out of scope (future work)

- Removing `SignalReportTask` creation once backfill is complete everywhere.
- Associating manually-started tasks with existing or new reports.
- The PostHog Code UI: timeline renderer, `pushed_branch` diff view, and `task_run`
  log viewer.
