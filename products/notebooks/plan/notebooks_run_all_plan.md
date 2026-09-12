# Run a whole markdown notebook

How to let a person, or an agent over MCP, run every SQL and Python cell of a revamped markdown notebook in one action.

## 1. Decisions

These decisions are fixed for this plan:

| Question                              | Decision                                                                                                                                      |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Where does orchestration live?        | In the backend. One `NotebookRun` record and one Temporal workflow drive the cells. The UI and the MCP call the same endpoints.               |
| Who writes results into the document? | The clients, as today. The UI node logic and the MCP tool write `runId` and `result` into the cell tag. The backend never edits the document. |
| Variables on the MCP run              | The run tool accepts a `variables` list. The backend saves it to the notebook first, then runs. The document then matches the results.        |
| Schedule                              | Out of scope. A future schedule reuses the run endpoint.                                                                                      |
| Failure rule                          | Stop on the first cell that fails or is interrupted. Cells after it do not run.                                                               |
| Which cells run                       | `SQLV2` and `PythonV2` cells with non-empty code, in document order. `Query`, widget, and legacy nodes do not run.                            |
| Flag                                  | Every surface checks `revamped-py-notebooks`: the button, the endpoints, and the MCP tools.                                                   |

## 2. Facts that shape the design

- The backend runs one cell at a time. `POST notebooks/{short_id}/sql_v2/run` in `products/notebooks/backend/presentation/views/notebook.py` resolves references, creates one `NotebookNodeRun`, and dispatches it. The dispatch logic sits inline in the view, about 130 lines.
- Document order is dependency order. A cell can only read exports of earlier cells. `frontend/src/scenes/notebooks/Notebook/notebookNodeStalenessLogic.ts` depends on this rule already.
- The backend can parse cells. `extract_cells` in `products/notebooks/backend/sql_v2_state.py` reads `SQLV2` and `PythonV2` tags from the markdown and computes `depends_on` and `dependents`. The MCP has the same parser in TypeScript in `services/mcp/src/tools/notebooks/cellTags.ts`.
- Two lanes finish a run in two ways. A kernel run (Python, DuckDB) finishes through the sandbox callback in `sql_v2_callback.py`. A direct run (pure HogQL) finishes only when a client polls `GET sql_v2/runs/{run_id}`, which calls `sync_direct_run`. Nobody polls in a headless run, so the orchestrator must poll.
- Kernel runs already have a Temporal workflow. `notebook-sandbox-cmd-run` in `products/notebooks/backend/temporal/sql_v2.py` dispatches one cell and expires it if the callback never arrives.
- A notebook allows one run at a time. `acquire_run_slots` in `sql_v2_concurrency.py` returns 409 `NotebookRunBusy` when a run is active. `MAX_NOTEBOOK_CELLS` is 50, so a whole-notebook run is bounded.
- The UI node logic recovers a run on mount. `notebookNodeSQLV2Logic` calls `startPolling(runId)` when a cell has a `runId` and no result. The poll path writes the result into the cell and reports `nodeRunFinished`.
- The MCP already has the pieces for one cell. `dispatchRun`, `awaitRun`, `shapeRunForModel`, and `buildResultProp` in `services/mcp/src/tools/notebooks/cellRuns.ts`, and `applyMarkdownEdit` in `markdownDoc.ts`. `notebooks-update-cell` waits 45 seconds at most, so a slow cell returns `running`.
- A Python cell starts a paid sandbox. Every dispatch response carries `starts_sandbox` and `sandbox_hourly_price`, and each client tells the user the price.

## 3. Design

### 3.1 Data model

Add `NotebookRun` to `products/notebooks/backend/models.py`. It inherits `TeamScopedRootMixin` and `UUIDModel`, the same as `NotebookNodeRun`.

| Field                                     | Type                                                | Purpose                                                                 |
| ----------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------- |
| `team`                                    | FK `posthog.Team`                                   | Tenant boundary.                                                        |
| `notebook`                                | FK `notebooks.Notebook`                             | The notebook that ran.                                                  |
| `user`                                    | FK `posthog.User`, null                             | Who started it. `None` for a token user, the same as `NotebookNodeRun`. |
| `trigger`                                 | choices `ui`, `mcp`                                 | Which surface started it. Drives metrics.                               |
| `status`                                  | choices `running`, `done`, `failed`, `interrupted`  | Whole-run state.                                                        |
| `variables`                               | JSON                                                | The variables the run bound. A snapshot, not a reference.               |
| `cell_plan`                               | JSON list of `{node_id, cell_type, dataframe_name}` | The cells in run order, frozen at start. Later edits do not change it.  |
| `current_index`                           | int                                                 | Position in `cell_plan`. The status endpoint reads it.                  |
| `failed_node_id`                          | text, null                                          | The cell that stopped the run.                                          |
| `error`                                   | text, null                                          | The stopping cell's error, or a run-level error.                        |
| `created_at`, `updated_at`, `finished_at` | datetime                                            | Timing for metrics and for the watchdog.                                |

Add `notebook_run` to `NotebookNodeRun`: a nullable FK to `NotebookRun`. This links the per-cell rows to the whole run. The status endpoint joins on it.

Add a partial unique constraint on `NotebookRun`: one row per notebook with `status = running`. The database then enforces "one whole-notebook run at a time" without a lock.

One migration, `0020`, adds the model, the FK, and the constraint. All new columns are nullable or have a default, so the migration is safe on a live table. Follow `/django-migrations`.

### 3.2 Shared dispatch function

Move the body of `sql_v2_run` from the view into `products/notebooks/backend/sql_v2_dispatch.py`:

```python
@frozen
class NodeRunRequest:
    node_id: str
    node_type: Literal["hogql", "python"]
    code: str
    output_name: str
    refs: dict[str, RefSpec]
    variables: list[NotebookVariable]
    connection_id: UUID | None
    send_raw_query: bool
    notebook_run_id: UUID | None = None

def dispatch_node_run(notebook: Notebook, user: User | None, team: Team, request: NodeRunRequest) -> NodeRunDispatch: ...
```

`NodeRunDispatch` carries `run_id`, `starts_sandbox`, and `sandbox_hourly_price`. The function raises typed errors that the view maps to 400, 409, 429, and 503 as it does today. The view becomes thin: validate, call, format. This is a behavior-preserving refactor, and the existing view tests must pass unchanged.

The orchestrator calls the same function. It builds `refs` from `cell_plan` the same way `collectRunRefs` does in TypeScript: every earlier `SQLV2` cell with a valid dataframe name is a `hogql` ref, every earlier `PythonV2` cell is a `local` ref. The backend `dispatch_node_run` then filters the refs to the names the code reads, as it does now.

### 3.3 Orchestrator

Add `products/notebooks/backend/temporal/notebook_run.py` with the workflow `notebook-run`, id `notebook-run-{notebook_run_id}`.

```mermaid
flowchart TD
    A[POST notebooks/{id}/runs] --> B[Save variables]
    B --> C[Create NotebookRun with cell_plan]
    C --> D[Start workflow notebook-run]
    D --> E{Next cell?}
    E -- no --> F[NotebookRun done]
    E -- yes --> G[Activity: dispatch_cell]
    G --> H[Activity: check_cell every 2 s]
    H -- running --> H
    H -- done --> I{NotebookRun still running?}
    I -- yes --> E
    I -- interrupted --> J[NotebookRun interrupted]
    H -- failed / interrupted --> K[NotebookRun failed, failed_node_id set]
```

Activities:

- `plan_notebook_run(notebook_run_id)`: loads the notebook, calls `extract_cells`, keeps `sql` and `python` cells with non-empty code, and writes `cell_plan`. The view can call this synchronously instead, so the response carries `cell_count`. Prefer the synchronous call. The workflow then starts with the plan in place.
- `dispatch_cell(notebook_run_id, index)`: builds `NodeRunRequest` from the plan and the snapshot variables, calls `dispatch_node_run`, and stores the new `NotebookNodeRun` id. A 409 `NotebookRunBusy` is retryable: a person may have clicked run on one cell. Retry with backoff for up to two minutes, then fail the run with a clear error. A 429 `TeamRunCapacityFull` is the same.
- `check_cell(node_run_id)`: loads the `NotebookNodeRun`, calls `sync_direct_run` and `expire_stale_kernel_run`, and returns the status. This is the poll the direct lane needs. It runs in a short activity, so no worker slot is held between polls. The workflow sleeps two seconds between calls.
- `finish_notebook_run(notebook_run_id, status, failed_node_id, error)`: status-guarded update, the same pattern as `finish_node_run`. Records the terminal metric.

Workflow rules:

- `run_timeout` of one hour. On timeout the workflow calls `finish_notebook_run` with `failed` and a timeout error. This is the watchdog for a run that hangs.
- Before each dispatch, the workflow reads `NotebookRun.status`. If it is `interrupted`, the workflow stops. This is how interrupt reaches the loop.
- The per-cell kernel workflow `notebook-sandbox-cmd-run` stays as it is. `dispatch_node_run` starts it the same way the view does today.

### 3.4 API

Three actions on `NotebookViewSet`, all under the `revamped-py-notebooks` gate the same way `sql_v2_run` is gated (`settings.DEBUG or is_sql_v2_enabled(user)`), all with `_require_query_access`. Follow `/improving-drf-endpoints`.

| Method and path                                      | Scopes                         | Body                  | Response                                                                                                                                                              |
| ---------------------------------------------------- | ------------------------------ | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST notebooks/{short_id}/runs/`                    | `notebook:write`, `query:read` | `{variables?: [...]}` | `{run_id, cell_count, starts_sandbox, sandbox_hourly_price}`                                                                                                          |
| `GET notebooks/{short_id}/runs/{run_id}/`            | `notebook:read`, `query:read`  |                       | `{status, trigger, variables, current_node_id, failed_node_id, error, cells: [{node_id, cell_type, dataframe_name, run_id, status, error}], created_at, finished_at}` |
| `POST notebooks/{short_id}/runs/{run_id}/interrupt/` | `notebook:write`               |                       | `{interrupted: bool}`                                                                                                                                                 |

Behavior:

- `POST runs/` with `variables` validates them with the existing variables serializer and saves them through the existing variables save path, so the same limits and the `stale_cells` logic apply. Then it creates the `NotebookRun`, plans the cells, and starts the workflow. A notebook with zero runnable cells returns 400 with a message that says so.
- `POST runs/` returns 409 when a `NotebookRun` is already running for this notebook, with the same tone as `NotebookRunBusy`. The partial unique constraint is the backstop.
- `starts_sandbox` is true when the plan has a Python cell and no kernel is live for this user. Extract the live-kernel check from `sql_v2_run` into a helper so both endpoints share it. `sandbox_hourly_price` follows the same rule as today.
- `GET runs/{run_id}/` is cheap. It returns no envelopes. A client fetches a cell's envelope from the existing `GET sql_v2/runs/{run_id}` when it needs one.
- `POST interrupt/` marks the `NotebookRun` interrupted with a status-guarded update, then interrupts the current `NotebookNodeRun` through the existing interrupt path. The workflow sees the status before the next dispatch.

Serializers get `help_text` on every field. Run `hogli build:openapi` so the generated types reach `products/notebooks/frontend/generated/`, `frontend/src/generated/`, and `services/mcp/src/generated/notebooks/`. The scaffold adds the three new operations to `products/notebooks/mcp/tools.yaml` with `enabled: false`. The hand-written MCP tool wraps them, so the generated tools stay disabled.

### 3.5 UI

All UI is behind `FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS`. Follow `/writing-ui-components`, `/writing-kea-logics`, and `/writing-user-facing-copy`.

New kea logic `frontend/src/scenes/notebooks/Notebook/notebookRunLogic.ts`, keyed by `shortId`:

- Actions: `startRun`, `pollRun`, `interruptRun`, `setRun`, `runFinished`.
- `startRun` calls `POST runs/`, stores the run, and calls `announceSandboxStart` on the notebook when `starts_sandbox` is true, the same as a single cell does.
- `pollRun` calls `GET runs/{run_id}/` every two seconds. For each cell whose `run_id` the logic has not seen, it dispatches `adoptChainRun(nodeId, runId)` on `notebookNodeStalenessLogic`.
- The logic registers a `run` operation with `notebookOperationsLogic` for the duration of the run, so every per-cell run button shows the existing "another operation is running" reason.
- On a terminal status the logic clears the operation and shows one toast. A failure toast names the failed cell by its dataframe name or position.

Change to `notebookNodeSQLV2Logic`: add the `adoptChainRun` listener. Only the matching node acts. It sets `cache.activeRunId`, calls `props.updateAttributes({ nodeId, runId, result: null, runStatus: null })`, and calls `startPolling(runId)`. The existing poll path then writes the result into the cell and reports `nodeRunFinished`, so staleness marks and the result table work with no new code. A cell that is not mounted does not adopt. This is the same limit the stale-cell chain has today. The next mount recovers the run through the existing `afterMount` poll, once the cell has a `runId`, so the adopt step must also write the `runId` when the node mounts late. Verify this path in the first UI PR and record what you find.

New component `NotebookRunAllButton` in `frontend/src/scenes/notebooks/Notebook/NotebookMeta.tsx`, next to `NotebookVariablesButton` and `NotebookKernelInfoButton`, rendered from `NotebookScene.tsx`:

- Visible only for a markdown notebook with at least one `SQLV2` or `PythonV2` cell.
- `loading` while a run is active. `disabledReason` while the notebook is busy or in a shared view.
- While a run is active, the button becomes "Stop" and calls `interruptRun`.

Progress: a small banner above the document, the same style as `NotebookRunDownstreamBanner`, with the text "Running cell 3 of 8" and a stop action. The banner reads `current_node_id` from the run.

Analytics: two events through `notebookAnalytics.ts`, `notebook run all started` and `notebook run all finished`, with `cell_count`, `python_cell_count`, `outcome`, `duration_ms`, and `trigger: 'ui'`. No code or content in properties.

Tests: Jest tests for `notebookRunLogic` (start, poll adoption, interrupt, failure toast) and one test in `notebookNodeSQLV2Logic.test.ts` for `adoptChainRun`. A Storybook story for the button and banner states. Render the toolbar at a narrow width before calling the work done.

### 3.6 MCP

Two hand-written tools in `services/mcp/src/tools/notebooks/`, registered in `services/mcp/src/tools/index.ts` and described in `services/mcp/schema/tool-definitions.json` with `feature_flag: revamped-py-notebooks`.

`notebooks-run` (`runNotebook.ts`):

- Schema: `notebook_id` with the `notebookIdAliases` preprocessor, optional `variables` (move `NotebookVariableSchema` out of `setVariables.ts` into a shared module), optional `wait` default `true`.
- Handler: `POST runs/`. Then wait, with the same 45 second budget and poll delays as `awaitRun`. On each poll, for every cell that became `done` or `interrupted` since the last poll, fetch its envelope from `GET sql_v2/runs/{run_id}` and write `runId` and `result` into the cell tag with `applyMarkdownEdit` and `buildResultProp`. Write in batches, one `applyMarkdownEdit` per poll, so a ten-cell run does not save the document ten times per second.
- Result shape: `{run_id, status, cell_count, completed_count, failed_cell, cells: [{node_id, dataframe_name, status, run?: ShapedRunResult}], starts_sandbox, sandbox_hourly_price, hint}`. `run` for a cell uses `shapeRunForModel`, so rows stay previewed and media stays out of context. When the budget ends with `status: 'running'`, `hint` tells the agent to call `notebooks-run-status`.
- Scopes: `notebook:write`, `query:read`.

`notebooks-run-status` (`runNotebookStatus.ts`):

- Schema: `notebook_id`, `run_id`.
- Handler: the same wait and write-back loop, without the start. Idempotent: a cell whose result is already in the document is not written again.
- Scopes: `notebook:write`, `query:read`. Write, because it edits the document.

Description text for `notebooks-run` must state: cells run in document order and stop at the first failure; `variables` replaces the saved list and persists; a Python cell starts a paid sandbox and the agent must tell the user the hourly price; a long run returns `running` and the agent continues with `notebooks-run-status`.

Related edits:

- `notebooks-update-cell` and `notebooks-set-variables` descriptions say "Nothing re-runs automatically". Change them to point at `notebooks-run` for the whole notebook.
- `services/mcp/src/hono/instructions.ts`: add `notebooks-run` to the notebooks guidance.
- `services/mcp/tests/unit/notebook-cell-tools.test.ts`: add cases for start, partial completion at budget, failure stop, and write-back batching. Mock `context.api.request` the same way the existing cell tool tests do.
- `services/mcp/tests/unit/tool-filtering.test.ts`: the new tools disappear when the flag is off.
- Evals: one sandboxed case in `products/notebooks/evals/` per `notebooks_mcp_evals_plan.md`, where the agent must set a week window and run the notebook.

### 3.7 Observability

- Metrics in `sql_v2_metrics.py` style: `notebook_run_terminal` counter with labels `outcome` and `trigger`, and a duration histogram. Record them in `finish_notebook_run`.
- Structured logs at each workflow step with `notebook_short_id`, `notebook_run_id`, `index`, and `node_id`. Never log code.
- Product analytics from the backend with `ph_scoped_capture`: `notebook run completed` with `trigger`, `cell_count`, `outcome`, and `duration_ms`. This gives one event for both UI and MCP runs.
- Add a section to `products/notebooks/backend/sql_v2_observability.md` for the new metric and the log fields.

### 3.8 Docs

- Add `products/notebooks/backend/notebook_run.md` with the workflow diagram and the API table, next to the other SQL v2 design notes.
- The MCP tool description is the user-facing doc for agents. Keep it in `tool-definitions.json`.

## 4. Work plan

Four PRs in a shallow stack. Each is reviewable alone.

| PR                                                                        | Scope                                                                                                                                                        | Files                                                                                                                                             | Tests                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 `chore(notebooks): extract node run dispatch and add NotebookRun model` | `sql_v2_dispatch.py`, thin `sql_v2_run` view, `NotebookRun` model, FK on `NotebookNodeRun`, migration `0020`, partial unique constraint. No behavior change. | `models.py`, `sql_v2_dispatch.py`, `presentation/views/notebook.py`, `migrations/0020_*.py`, `max_migration.txt`                                  | Existing `test_sql_v2.py` view tests pass unchanged. One test that a second running `NotebookRun` for the same notebook raises `IntegrityError`.                                                                                                                                                                                       |
| 2 `feat(notebooks): run a whole notebook through one endpoint`            | Workflow and activities, three endpoints, serializers, sandbox-price helper, metrics, `notebook_run.md`, OpenAPI regen, `tools.yaml` sync.                   | `temporal/notebook_run.py`, `temporal/client.py`, `presentation/views/notebook.py`, `sql_v2_serializers.py`, `sql_v2_metrics.py`, generated types | Workflow test with the Temporal test environment: three cells run in order, a failing second cell stops the third, interrupt stops before the next dispatch, a direct-lane cell advances through `check_cell`. API tests: 404 when the flag is off, 409 on a second run, 400 on zero runnable cells, variables persist before the run. |
| 3 `feat(mcp): notebooks-run and notebooks-run-status tools`               | Two tools, shared variable schema, definitions, instructions, description edits on the two existing tools.                                                   | `services/mcp/src/tools/notebooks/runNotebook.ts`, `runNotebookStatus.ts`, `index.ts`, `schema/tool-definitions.json`, `hono/instructions.ts`     | Unit tests listed in 3.6. Flag filtering test.                                                                                                                                                                                                                                                                                         |
| 4 `feat(notebooks): run all cells button`                                 | `notebookRunLogic`, `adoptChainRun`, button, banner, analytics, story.                                                                                       | `Notebook/notebookRunLogic.ts`, `Nodes/notebookNodeSQLV2Logic.ts`, `Notebook/NotebookMeta.tsx`, `NotebookScene.tsx`, `notebookAnalytics.ts`       | Jest tests listed in 3.5. Storybook render at 520 px scene width.                                                                                                                                                                                                                                                                      |

PR 3 and PR 4 both depend on PR 2 and do not depend on each other. Land PR 2 before you extend the stack.

## 5. Risks and open items

- Late-mounting cells in the UI. The adopt step only reaches mounted cells. Confirm in PR 4 how the markdown renderer mounts V2 cells. If cells outside the viewport are not mounted, the run logic must write `runId` into the document for them so `afterMount` recovers the poll.
- A person edits the notebook during a run. `cell_plan` is frozen at start. A cell added during the run does not run. A cell deleted during the run still runs in the backend, and its result has no cell to land in. Both clients treat a missing cell as a no-op on write-back. Document this in the tool description.
- Kernel restart during a run. A compute change restarts the kernel and drops every dataframe. The next Python cell that reads a local frame fails, and the run stops there with the kernel's error. This is correct behavior and needs no new code.
- A run on a notebook that reads an external connection. `dispatch_node_run` already refuses a local frame ref on a connection run. The orchestrator inherits the same rule.
- Cost disclosure. A run with Python cells starts a sandbox. Both clients already announce the price for a single cell. Both must do the same for a whole run, from the `POST runs/` response.
- Widget data. `runWidgetDataChain` refreshes the cells a generated widget reads. A whole-notebook run covers those cells too, but it does not refresh the widget frame. Out of scope. Note it in the button tooltip if people ask.
- Concurrency with the per-cell path. During a run, a per-cell dispatch gets 409 from `acquire_run_slots`. The UI hides this behind the operation lock. The MCP `notebooks-update-cell` surfaces the 409 message, which already tells the agent to wait.

## 6. Success measures

- Adoption: count of `notebook run completed` by `trigger`. The MCP tool call events already exist through the MCP server's own analytics.
- Outcome: share of runs that end `done`, split by `trigger` and by whether the run had Python cells.
- Where runs fail: `failed_node_id` position and `cell_type`. A high failure rate at the first Python cell points at sandbox start.
- Duration: median and p95 `duration_ms` by `cell_count`. This tells us whether the 45 second MCP budget is enough for typical notebooks, or whether `notebooks-run-status` is the common path.
- Follow-up: if agents run the same notebook on a cadence, a native schedule becomes worth building. The `NotebookRun` record already holds the data a schedule needs.
