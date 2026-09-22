# Offline evals for markdown notebooks over MCP

How to add agent evals for notebook creation and editing through the MCP tools, using the existing eval harness.

## 1. How evals work in this repo

Everything runs on the standalone harness in `products/posthog_ai/eval_harness/`, not pytest.
`hogli evals` boots shared infrastructure once (test DB, Django live server, LLM gateway, MCP server, Temporal, personhog), then runs every selected suite concurrently with Braintrust as the eval engine.

Two suite kinds:

| Kind                | Marker                            | Per case                                                           | Infra                         |
| ------------------- | --------------------------------- | ------------------------------------------------------------------ | ----------------------------- |
| sandboxed (default) | none                              | the real coding agent in a real sandbox, talking to the MCP server | everything                    |
| one-shot            | `SUITE_KIND = SuiteKind.ONE_SHOT` | one in-process model call                                          | test DB, personhog, demo data |

Notebook MCP evals are **sandboxed**: the thing under test is an agent driving real tools against real state, which a one-shot call cannot exercise.

Facts that shape the design:

- Suites are discovered by convention. Product-owned suites live in `products/<product>/evals/` (plural), so ours is `products/notebooks/evals/eval_*.py`, suite id `notebooks/<module>::<fn>`.
- A suite is one Braintrust experiment. `experiment_name` is the history key, so renaming it resets cross-run comparison.
- Every case gets its own org/team/user cloned from a master Hedgebox team. Cases never see each other's state. The seeded user is "Karen Smith".
- The Hedgebox dataset is byte-for-byte reproducible under a fixed seed, so assert shapes and relative date ranges, never absolute counts.
- Case fields: `name`, `prompt`, `expected` (keyed by scorer `_name()`), `metadata`, `setup` (the seeder).
- Whatever the seeder returns lands in `output["seed"]`, which is the only channel scorers have for seeded IDs.
- The harness adds `ExitCodeZero` to every experiment; suites must not declare it.
- Sandboxed evals are **not** in CI. `.github/workflows/ci-ai.yml` only runs the older `ee/hogai/eval/ci` pytest tree behind an `evals-ready` label. These run on demand, locally or on Modal.

## 2. The surface under test

Behind `revamped-py-notebooks`, the notebook tool set is:

| Tool                                                                                                                | Kind         | Notes                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `notebooks-create-markdown`                                                                                         | hand-written | title + optional prose. Explicitly refuses to carry cells                                                                                |
| `notebooks-add-cell`                                                                                                | hand-written | `sql` / `python` / `markdown` / `saved_insight` / `component`. sql and python dispatch a run and write the result back into the document |
| `notebooks-update-cell`                                                                                             | hand-written | edit code and re-run, or omit code to re-run as-is. Returns `stale_dependents`                                                           |
| `notebooks-delete-cell`                                                                                             | hand-written |                                                                                                                                          |
| `notebook-edit`                                                                                                     | hand-written | markdown string replacement (`old_markdown` / `new_markdown` / `replace_all`)                                                            |
| `notebooks-get`                                                                                                     | generated    | title, markdown, cells, `depends_on`/`dependents`, derived stale status                                                                  |
| `notebooks-list-frames`, `notebooks-configure-compute`, `notebooks-run-cell-result`, `notebooks-run-cell-interrupt` | generated    | kernel-side                                                                                                                              |

With the flag **off** the legacy set is registered instead (`notebooks-create`, `notebooks-retrieve`, `notebooks-partial-update`), and the markdown tools disappear.
The two sets are mutually exclusive, which matters for the harness change below.

## 3. Environment blockers, verified

**a. The markdown tools reach the eval MCP server through a flag override.**
Tool filtering gates the whole markdown set on `revamped-py-notebooks` (see `services/mcp/tests/unit/tool-filtering.test.ts`), and the eval MCP server sets that flag in `FEATURE_FLAG_OVERRIDES` (`harness/services.py`). Without it the tools are not registered at all.
Note the side effect: it also removes `notebooks-create` / `notebooks-retrieve` from the eval tool list, so a legacy-notebook eval needs a different lever.

**b. Django-side gating is already satisfied.**
`harness/lifecycle.py` patches `posthoganalytics.feature_enabled` to return `True` for the whole run, so the flag-gated SQLV2 endpoints answer normally.

**c. Both cell lanes run, docker only.**
A pure-HogQL run takes the direct lane (`enqueue_direct_run` in `presentation/views/notebook.py`), which rides the async query manager. The harness runs with `TEST=1`, where Celery is eager, so the query executes inline and no sandbox is involved.
Python and DuckDB runs call `start_sql_v2_run_workflow`, which needs the notebook Temporal workflows registered and a kernel sandbox. The harness now does both (see [Notebook kernel sandboxes](../../posthog_ai/eval_harness/README.md#notebook-kernel-sandboxes)); before that change the run sat at `running` until its poll window expired.

The kernel lane is docker-only: the notebook kernel reads its backend straight off `SANDBOX_PROVIDER`, and the modal provider sets that to `MODAL_EVALS`, which is not a `KernelRuntime.Backend` value. Run python or duckdb cases with `--provider docker`; SQL-only cases work on either provider.

**d. Scopes are fine.** The sandbox context defaults to `"full"` MCP scopes (`custom_prompt_internals.py`), which includes `notebook:write`.

**e. End-state scoring is possible but must be async.**
Braintrust's base `_run_eval_async` calls `_run_eval_sync` directly on the event loop, so a scorer doing sync ORM work trips Django's async guard. A DB-reading scorer subclasses `AsyncOnlyScorerMixin, Scorer` and does its work in `asyncio.to_thread`. The pattern already exists (`DuplicateUniqueFlagKey` in `products/posthog_ai/evals/experiments/scorers.py`).
The seeder must return `team_id` for this to work at all.

## 4. Use-case selection

Ground it in what the tools actually do in practice rather than what feels comprehensive.
Check the MCP analytics for the notebook tools before picking cases (`query-mcp-tool-stats` and `query-mcp-tool-failures` per tool, or the MCP analytics UI). What that showed when this plan was written:

- `notebook-edit` carries by far the highest error rate of the editing tools, and most of its failures are opaque `internal` — what a thrown `Error` looks like in telemetry, meaning `old_markdown` was not found or not unique. Highest-value target, and the one with a real failure signature to reproduce.
- `notebooks-add-cell` is barely used yet. Evals here lock behavior in before it scales, rather than fixing a fire.
- The legacy `notebooks-partial-update` fails mostly on HTTP 409 version conflicts.

Selection principles worth keeping:

- One case per behavior you could plausibly regress, not one case per tool.
- Prefer cases where a wrong answer is cheap to detect and expensive in production (clobbering a document, losing cell results, rebuilding an insight that already exists).
- Include at least one case where the correct behavior is _not_ calling a tool, and one where the tool rejects the first attempt and the agent must recover. Those catch prompt regressions that success-only cases miss.

### Proposed cases

**Suite 0: `eval_notebook_cells`** (shipped — the lane check)

Two cases, both creating a notebook from scratch: `sql_cell_report` proves the direct lane, `python_cell_from_dataframe` proves the kernel lane end to end (sandbox provisioned, code run, result written back). `CellRunsCompleted` grades the `NotebookNodeRun` rows rather than the transcript, because a dispatched run and a finished one look the same in the log.

**Suite A: `eval_notebook_authoring`** (create from an analysis request)

| Case                       | Prompt shape                                                                                               | What it grades                                                                          |
| -------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `create_signup_report`     | "Create a notebook called X showing weekly `signed_up` counts over the last 8 weeks, with a short summary" | uses `notebooks-create-markdown`, adds a SQL cell that completes, titles it, adds prose |
| `multi_cell_dependency`    | two related SQL steps where the second reads the first's dataframe                                         | dataframe naming, `refs`, dependency order                                              |
| `embed_saved_insight`      | "Put our 'Weekly signups' insight in a notebook"                                                           | reuses the seeded insight via a `saved_insight` cell instead of rewriting the SQL       |
| `component_hogql_rejected` | phrasing that tempts a `component` cell with a HogQL source                                                | the tool rejects it; agent recovers to `cell_type: sql`                                 |

**Suite B: `eval_notebook_editing`** (change an existing notebook without breaking it)

| Case                  | Prompt shape                                        | What it grades                                                                                            |
| --------------------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `local_prose_edit`    | "Reword the intro section of notebook X"            | edits only the target span; every other section and both cells survive with their `runId`/`result` intact |
| `insert_cell_after`   | "Add a breakdown cell right after the signups cell" | uses `after_node_id` rather than appending at the end                                                     |
| `delete_one_cell`     | "Drop the file-size cell"                           | deletes exactly one cell                                                                                  |
| `refresh_stale_cells` | seeded notebook where an upstream cell changed      | reads `notebooks-get`, re-runs stale cells in dependency order with `notebooks-update-cell` and no `code` |

Eight sandboxed cases is a sensible first suite. Each case is a full agent run, so cost scales linearly and a 20-case suite gets slow to iterate on.

## 5. Data generation

Hedgebox gives you events, insights, dashboards, and flags, but no notebooks. Editing and orientation cases therefore need a seeder.

Follow the synthesizer/seeder split that `data_warehouse` uses:

- `products/notebooks/evals/synthesizer.py` — pure, Django-free, deterministic. Builds the markdown document as frozen dataclasses: section anchors, cell tags with fixed `nodeId`s, dataframe names, and any planted "needle" the case must find. Unit-testable in `products/notebooks/backend/test/`, never inside the `evals/` tree.
- `products/notebooks/evals/seeders.py` — takes `CustomPromptSandboxContext`, creates the `Notebook` row in the case's team with `content = buildMarkdownNotebookContent(markdown)` equivalent, and (for staleness cases) `NotebookNodeRun` rows so `notebooks-get` reports realistic run state.
- `products/notebooks/evals/constants.py` — every literal shared by the prompt, the `expected` payload, and the scorers. Titles, anchor strings, node IDs, dataframe names. This is what stops prompt and scorer from drifting apart.

Seeder contract details that bite:

- Synchronous `def seed_x(context) -> dict[str, Any]`. The harness calls it via `asyncio.to_thread`; never make it async.
- No per-case parameters. Case-specific state means a dedicated seeder function, not a knob on a shared one.
- Return everything a scorer needs, including `team_id` and the notebook `short_id`. For editing cases also return `markdown_before` so a scorer can diff against it.
- A seeder exception marks the case an infra error, excluded from averages, so a broken seeder never reads as an agent regression.

For the authoring suite, the seeder is optional: Hedgebox already ships the "Weekly signups" insight that `embed_saved_insight` needs. A tiny seeder that just returns `{"team_id": ...}` is still worth it, because it unlocks end-state scoring.

## 6. Scoring

Stack three layers. Weight the deterministic ones as the backbone and use judges only where the question is genuinely qualitative.

### Layer 1: tool trajectory, from the agent log

Deterministic `Scorer` subclasses reading `LogParser.cached(output["raw_log"], ...)`. Reuse the generics first (`RequiredToolCall`, `NoToolCall`, `LastToolCallNot`, and `CalledTargetTool` from `cli_mcp/scorers.py`). Notebook-specific additions:

- `UsedMarkdownNotebookFlow` — created through `notebooks-create-markdown`, not by hand-assembling a document.
- `CellsTitled` — every successful sql/python `add-cell` carried a non-empty `title`. The tool description demands it and PR #75471 exists because agents skip it.
- `ReusedSavedInsight` — a `saved_insight` cell with the seeded short_id, and no SQL cell duplicating the same query.
- `RanCellsInDependencyOrder` — for update chains, each upstream re-run precedes its dependents' re-runs.
- `RecoveredFromToolRejection` — the rejected shape was attempted, then a correct call succeeded. Generalizes `RecoveredToCorrectTool`.

### Layer 2: end state, from the database

This is the layer that actually catches the production failure, and it is new for this repo. Async scorers (`AsyncOnlyScorerMixin, Scorer` + `asyncio.to_thread`) that read the notebook back from Postgres using `seed["team_id"]` and `seed["notebook_short_id"]`:

- `NotebookIsMarkdown` — content is still a single `ph-markdown-notebook` node, not clobbered into legacy rich text.
- `PreservedUnrelatedContent` — every anchor from `seed["markdown_before"]` except the edit target is still present, and every pre-existing cell tag still carries its `nodeId`, `runId`, and `result` props. Direct counter to the clobbering failure.
- `CellRunSucceeded` — the `NotebookNodeRun` rows for added cells are `DONE` with a non-empty envelope. Catches "wrote a cell that looks right and errors".

`system.notebooks` also exposes a `markdown` column via HogQL, but a direct ORM read from the scorer is simpler and avoids a query round trip.

### Layer 3: LLM judge, for quality

`JudgedScorer` subclasses implementing `_prepare` only:

- `NotebookAnswersQuestion` — given the final markdown, does the notebook actually answer the prompt: right metric, right window, a chart present, prose that a reader can skim.
- `CellTitlesAreDescriptive` — titles say what the cell shows, not that it is SQL.

Judges get the final markdown from the same DB read, so they are async by construction.

### Scoring discipline

- `score=None` means "this check does not apply to this case" and is dropped from the aggregate. `0.0` means the agent got it wrong, and also covers broken-judge and missing-input paths that must not vanish silently.
- Count only successful tool calls (`is_error=False`). The agent is allowed to attempt and fail.
- One implemented branch per scorer, never both `_run_eval_sync` and `_run_eval_async`.
- Keep `expected` payloads keyed by scorer name so one scorer list can span the whole suite.

## 7. Layout

```text
products/notebooks/evals/
    __init__.py
    constants.py            # shared literals: titles, anchors, node ids, dataframe names
    synthesizer.py          # pure deterministic markdown document builder
    seeders.py              # ORM installation into the per-case team          [shipped]
    scorers.py              # trajectory + end-state + judge scorers           [shipped]
    eval_notebook_cells.py  # both run lanes                                   [shipped]
    eval_notebook_authoring.py
    eval_notebook_editing.py
```

No `conftest.py` and no `pytest` import in that tree. Unit tests for the synthesizer go under `products/notebooks/backend/test/`.

Suite skeleton:

```python
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext


async def eval_notebook_editing(ctx: EvalContext) -> None:
    await SandboxedPublicEval(
        experiment_name="sandboxed-notebooks-editing-cli",
        cases=[...],
        scorers=[...],
        ctx=ctx,
    )
```

Use `SandboxedPublicEval` unless a prompt or seed should not leave the machine; public gets you a Braintrust URL and cross-run history. Keep the `-cli` suffix so the naming lines up with the other MCP suites.

## 8. Rollout order

1. ~~Enable `revamped-py-notebooks` in the eval MCP server, register the notebook Temporal workflows, and reclaim kernel sandboxes.~~ Done, with `eval_notebook_cells` as the case that proves it.
2. Add `eval_notebook_authoring` — the discrimination cases (reuse a saved insight, recover from the component+HogQL rejection) on trajectory scorers.
3. Add the document seeder plus `PreservedUnrelatedContent`, then `eval_notebook_editing`.
4. Add judges last. They are the noisiest layer and the easiest to over-fit.
5. Once stable, run with `--trials 3` to see variance before treating any score as a baseline.

Commands:

```bash
hogli evals --list | grep notebooks               # confirm discovery, import-checks the modules
hogli evals eval_notebook_cells --eval python_cell_from_dataframe --provider docker
hogli evals notebooks --provider docker           # whole domain; docker because of the kernel lane
```

Run from a flox shell. Read the transcript path printed on the final line, then the per-case `<case>.jsonl` and `<case>.summary.txt` in the experiment's agent-log directory. The score alone will not tell you why a case failed.

## 9. Open decisions

- **Kernel lane on modal.** Docker-only today, which caps python-cell cases at four concurrent sandboxes. Lifting it means teaching the notebook kernel that `MODAL_EVALS` is a modal backend, which is production code changed for an eval's benefit — worth it only if the python suite grows past what docker can hold.
- **Legacy notebook tools.** Enabling the flag hides them, so any eval of `notebooks-create` / `notebooks-partial-update` (the 409-conflict path, which has real error volume) needs a per-suite flag lever rather than a process-wide env var.
- **Judge model cost.** Judges run per case per scorer. Two judges across eight cases is fine; ten is not.
